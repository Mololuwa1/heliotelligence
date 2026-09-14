"""Objective acceptance checks for privately supplied PVCollada geometry.

This module consumes S3 import results; it does not parse PVCollada. Reports
contain bounded engineering facts and never contain source XML or mesh arrays.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real
from typing import TypeAlias, cast

import numpy as np
import numpy.typing as npt

from heliotelligence.geometry import ReceiverKind, SiteGeometry
from heliotelligence.ingest.pvcollada.importer import PVColladaImportResult

CheckValue: TypeAlias = str | int | float | tuple[float, ...] | None
_ORIENTATION_TOLERANCE = 1e-12


class AcceptanceStatus(StrEnum):
    """Outcome of one check or the complete acceptance evaluation."""

    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounds in canonical ENU metres."""

    min_east_m: float
    max_east_m: float
    min_north_m: float
    max_north_m: float
    min_elevation_m: float
    max_elevation_m: float

    def values(self) -> tuple[float, ...]:
        """Return values in deterministic field order."""
        return (
            self.min_east_m,
            self.max_east_m,
            self.min_north_m,
            self.max_north_m,
            self.min_elevation_m,
            self.max_elevation_m,
        )


@dataclass(frozen=True)
class BoundingBoxExpectation:
    """Optional exact site-bound facts sharing one metre tolerance."""

    min_east_m: float | None = None
    max_east_m: float | None = None
    min_north_m: float | None = None
    max_north_m: float | None = None
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    tolerance_m: float = 0.0

    def __post_init__(self) -> None:
        bounds = (
            self.min_east_m,
            self.max_east_m,
            self.min_north_m,
            self.max_north_m,
            self.min_elevation_m,
            self.max_elevation_m,
        )
        for value in bounds:
            if value is not None:
                _finite_real(value, "bbox bound")
        _validate_tolerance(self.tolerance_m, "bbox tolerance_m")
        if all(value is None for value in bounds):
            raise ValueError("bbox expectation must supply at least one bound")


@dataclass(frozen=True)
class GeolocationExpectation:
    """Expected explicit source geolocation and independent tolerances."""

    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    latitude_tolerance_deg: float = 0.0
    longitude_tolerance_deg: float = 0.0
    altitude_tolerance_m: float = 0.0

    def __post_init__(self) -> None:
        latitude = _finite_real(self.latitude_deg, "latitude_deg")
        longitude = _finite_real(self.longitude_deg, "longitude_deg")
        _finite_real(self.altitude_m, "altitude_m")
        if not -90.0 <= latitude <= 90.0:
            raise ValueError("latitude_deg must be within [-90, 90]")
        if not -180.0 <= longitude <= 180.0:
            raise ValueError("longitude_deg must be within [-180, 180]")
        for name in (
            "latitude_tolerance_deg",
            "longitude_tolerance_deg",
            "altitude_tolerance_m",
        ):
            _validate_tolerance(getattr(self, name), name)


@dataclass(frozen=True)
class ReceiverExpectation:
    """Checks for one receiver selected by canonical or exact source ID."""

    receiver_id: str | None = None
    source_object_id: str | None = None
    centre_enu_m: tuple[float, float, float] | None = None
    centre_tolerance_m: float = 0.0
    receiver_kind: ReceiverKind | None = None
    tilt_deg: float | None = None
    tilt_tolerance_deg: float = 0.0
    azimuth_deg: float | None = None
    azimuth_tolerance_deg: float = 0.0

    def __post_init__(self) -> None:
        if (self.receiver_id is None) == (self.source_object_id is None):
            raise ValueError("receiver expectation requires exactly one receiver identity")
        _validate_optional_text(self.receiver_id, "receiver_id")
        _validate_optional_text(self.source_object_id, "source_object_id")
        if self.centre_enu_m is not None:
            object.__setattr__(self, "centre_enu_m", _vector3(self.centre_enu_m, "centre_enu_m"))
        if self.receiver_kind is not None and not isinstance(self.receiver_kind, ReceiverKind):
            raise ValueError("receiver_kind must be ReceiverKind")
        if self.tilt_deg is not None and not 0.0 <= _finite_real(self.tilt_deg, "tilt_deg") <= 90.0:
            raise ValueError("tilt_deg must be within [0, 90]")
        if (
            self.azimuth_deg is not None
            and not 0.0 <= _finite_real(self.azimuth_deg, "azimuth_deg") < 360.0
        ):
            raise ValueError("azimuth_deg must be within [0, 360)")
        for name in ("centre_tolerance_m", "tilt_tolerance_deg", "azimuth_tolerance_deg"):
            _validate_tolerance(getattr(self, name), name)

    @property
    def identity(self) -> str:
        """Return a deterministic namespace-qualified selector."""
        if self.receiver_id is not None:
            return f"canonical:{self.receiver_id}"
        return f"source:{self.source_object_id}"


@dataclass(frozen=True)
class TerrainElevationExpectation:
    """Elevation bounds for one explicitly identified terrain surface."""

    terrain_id: str | None = None
    source_object_id: str | None = None
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    tolerance_m: float = 0.0

    def __post_init__(self) -> None:
        if (self.terrain_id is None) == (self.source_object_id is None):
            raise ValueError("terrain expectation requires exactly one terrain identity")
        _validate_optional_text(self.terrain_id, "terrain_id")
        _validate_optional_text(self.source_object_id, "source_object_id")
        if self.min_elevation_m is None and self.max_elevation_m is None:
            raise ValueError("terrain expectation requires an elevation bound")
        for name in ("min_elevation_m", "max_elevation_m"):
            if getattr(self, name) is not None:
                _finite_real(getattr(self, name), name)
        _validate_tolerance(self.tolerance_m, "terrain tolerance_m")

    @property
    def identity(self) -> str:
        """Return a deterministic namespace-qualified selector."""
        if self.terrain_id is not None:
            return f"canonical:{self.terrain_id}"
        return f"source:{self.source_object_id}"


@dataclass(frozen=True)
class PVColladaAcceptanceExpectations:
    """Optional engineering facts required for one private acceptance run."""

    expected_source_application: str | None = None
    expected_source_digest: str | None = None
    expected_geometry_revision: str | None = None
    expected_receiver_count: int | None = None
    expected_fixed_receiver_count: int | None = None
    expected_tracker_receiver_count: int | None = None
    expected_terrain_surface_count: int | None = None
    expected_shading_object_count: int | None = None
    expected_semantic_category_counts: tuple[tuple[str, int], ...] = ()
    bbox: BoundingBoxExpectation | None = None
    geolocation: GeolocationExpectation | None = None
    receivers: tuple[ReceiverExpectation, ...] = ()
    terrain_surfaces: tuple[TerrainElevationExpectation, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "expected_source_application",
            "expected_source_digest",
            "expected_geometry_revision",
        ):
            _validate_optional_text(getattr(self, name), name)
        for name in (
            "expected_receiver_count",
            "expected_fixed_receiver_count",
            "expected_tracker_receiver_count",
            "expected_terrain_surface_count",
            "expected_shading_object_count",
        ):
            value = getattr(self, name)
            if value is not None:
                _nonnegative_int(value, name)
        categories = tuple(self.expected_semantic_category_counts)
        if len({item[0] for item in categories}) != len(categories):
            raise ValueError("semantic category expectations must be unique")
        for category, count in categories:
            _validate_required_text(category, "semantic category")
            _nonnegative_int(count, "semantic category count")
        receivers = tuple(self.receivers)
        terrains = tuple(self.terrain_surfaces)
        if any(not isinstance(item, ReceiverExpectation) for item in receivers):
            raise ValueError("receivers must contain ReceiverExpectation values")
        if any(not isinstance(item, TerrainElevationExpectation) for item in terrains):
            raise ValueError("terrain_surfaces must contain TerrainElevationExpectation values")
        if len({item.identity for item in receivers}) != len(receivers):
            raise ValueError("selected receiver expectation identities must be unique")
        if len({item.identity for item in terrains}) != len(terrains):
            raise ValueError("selected terrain expectation identities must be unique")
        object.__setattr__(self, "expected_semantic_category_counts", categories)
        object.__setattr__(self, "receivers", receivers)
        object.__setattr__(self, "terrain_surfaces", terrains)


@dataclass(frozen=True)
class ReceiverOrientation:
    """Orientation derived from an ENU receiver normal."""

    tilt_deg: float | None
    azimuth_deg: float | None
    state: str


@dataclass(frozen=True)
class ReceiverSummary:
    """Deterministic in-memory receiver facts; no mesh data."""

    receiver_id: str
    source_object_id: str | None
    centre_enu_m: tuple[float, float, float]
    normal_enu: tuple[float, float, float]
    receiver_kind: ReceiverKind
    orientation: ReceiverOrientation


@dataclass(frozen=True)
class PVColladaCanonicalSummary:
    """Bounded canonical facts used by acceptance checks."""

    source_digest: str | None
    source_application: str | None
    source_application_version: str | None
    source_version: str | None
    geometry_revision: str
    canonical_frame: str
    canonical_unit: str
    source_unit: str | None
    source_unit_to_m: float | None
    geolocation: tuple[float, float, float] | None
    receiver_count: int
    fixed_receiver_count: int
    tracker_receiver_count: int
    unknown_receiver_count: int
    terrain_surface_count: int
    shading_object_count: int
    semantic_category_counts: tuple[tuple[str, int], ...]
    shadow_role_counts: tuple[tuple[str, int], ...]
    bounding_box: BoundingBox | None
    receiver_bounding_box: BoundingBox | None
    terrain_bounding_box: BoundingBox | None
    receivers: tuple[ReceiverSummary, ...]


@dataclass(frozen=True)
class AcceptanceCheck:
    """One required supplied expectation and its objective result."""

    name: str
    status: AcceptanceStatus
    expected: CheckValue
    actual: CheckValue
    tolerance: float | None = None
    message: str = ""


@dataclass(frozen=True)
class PVColladaAcceptanceReport:
    """Immutable overall report; PASS requires every emitted check to pass."""

    status: AcceptanceStatus
    summary: PVColladaCanonicalSummary
    checks: tuple[AcceptanceCheck, ...]


def derive_receiver_orientation(
    normal_enu: tuple[float, float, float],
) -> ReceiverOrientation:
    """Derive tilt and meteorological azimuth from an upward ENU unit normal.

    Azimuth is 0° north and increases clockwise through 90° east. For a
    horizontal surface the horizontal normal component is zero, so azimuth is
    explicitly undefined. Downward normals are diagnosed, never reinterpreted.
    """
    east, north, up = _vector3(normal_enu, "normal_enu")
    if up < -_ORIENTATION_TOLERANCE:
        return ReceiverOrientation(None, None, "downward_normal")
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, up))))
    if math.hypot(east, north) <= _ORIENTATION_TOLERANCE:
        return ReceiverOrientation(tilt, None, "azimuth_undefined")
    azimuth = math.degrees(math.atan2(east, north)) % 360.0
    return ReceiverOrientation(tilt, azimuth, "resolved")


def summarize_site_geometry(site: SiteGeometry) -> PVColladaCanonicalSummary:
    """Create deterministic acceptance facts from canonical geometry."""
    if not isinstance(site, SiteGeometry):
        raise ValueError("site must be SiteGeometry")
    receivers = tuple(
        ReceiverSummary(
            receiver_id=item.id,
            source_object_id=item.provenance.source_object_id,
            centre_enu_m=item.centre_enu_m,
            normal_enu=item.normal_enu,
            receiver_kind=item.receiver_kind,
            orientation=derive_receiver_orientation(item.normal_enu),
        )
        for item in site.pv_receivers
    )
    categories = _count_values(
        item.semantic_category
        for item in site.shading_objects
        if item.semantic_category is not None
    )
    roles = _count_values(item.shadow_role.value for item in site.shading_objects)
    reference = site.coordinate_reference
    origin_values = (
        reference.origin_latitude_deg,
        reference.origin_longitude_deg,
        reference.origin_altitude_m,
    )
    origin: tuple[float, float, float] | None = None
    if all(value is not None for value in origin_values):
        latitude, longitude, altitude = origin_values
        assert latitude is not None and longitude is not None and altitude is not None
        origin = (float(latitude), float(longitude), float(altitude))
    receiver_meshes = tuple(item.mesh.vertices_enu_m for item in site.pv_receivers)
    terrain_meshes = tuple(item.mesh.vertices_enu_m for item in site.terrain_surfaces)
    all_meshes = (
        receiver_meshes
        + terrain_meshes
        + tuple(item.mesh.vertices_enu_m for item in site.shading_objects)
    )
    return PVColladaCanonicalSummary(
        source_digest=site.source_provenance.source_digest,
        source_application=site.source_provenance.source_application,
        source_application_version=site.source_provenance.source_application_version,
        source_version=site.source_provenance.source_version,
        geometry_revision=site.geometry_revision,
        canonical_frame=reference.canonical_frame,
        canonical_unit=reference.canonical_unit,
        source_unit=reference.source_unit,
        source_unit_to_m=reference.source_unit_to_m,
        geolocation=origin,
        receiver_count=len(receivers),
        fixed_receiver_count=sum(
            item.receiver_kind is ReceiverKind.FIXED_TABLE for item in receivers
        ),
        tracker_receiver_count=sum(
            item.receiver_kind is ReceiverKind.TRACKER_TABLE for item in receivers
        ),
        unknown_receiver_count=sum(
            item.receiver_kind is ReceiverKind.UNKNOWN for item in receivers
        ),
        terrain_surface_count=len(site.terrain_surfaces),
        shading_object_count=len(site.shading_objects),
        semantic_category_counts=categories,
        shadow_role_counts=roles,
        bounding_box=_bounding_box(all_meshes),
        receiver_bounding_box=_bounding_box(receiver_meshes),
        terrain_bounding_box=_bounding_box(terrain_meshes),
        receivers=receivers,
    )


def evaluate_pvcollada_acceptance(
    result: PVColladaImportResult,
    expectations: PVColladaAcceptanceExpectations,
) -> PVColladaAcceptanceReport:
    """Evaluate only explicitly supplied engineering expectations."""
    if not isinstance(result, PVColladaImportResult):
        raise ValueError("result must be PVColladaImportResult")
    if not isinstance(expectations, PVColladaAcceptanceExpectations):
        raise ValueError("expectations must be PVColladaAcceptanceExpectations")
    summary = summarize_site_geometry(result.site_geometry)
    checks: list[AcceptanceCheck] = []
    scalar_checks = (
        (
            "source_application",
            expectations.expected_source_application,
            summary.source_application,
        ),
        ("source_digest", expectations.expected_source_digest, summary.source_digest),
        ("geometry_revision", expectations.expected_geometry_revision, summary.geometry_revision),
        ("receiver_count", expectations.expected_receiver_count, summary.receiver_count),
        (
            "fixed_receiver_count",
            expectations.expected_fixed_receiver_count,
            summary.fixed_receiver_count,
        ),
        (
            "tracker_receiver_count",
            expectations.expected_tracker_receiver_count,
            summary.tracker_receiver_count,
        ),
        (
            "terrain_surface_count",
            expectations.expected_terrain_surface_count,
            summary.terrain_surface_count,
        ),
        (
            "shading_object_count",
            expectations.expected_shading_object_count,
            summary.shading_object_count,
        ),
    )
    for name, expected, actual in scalar_checks:
        if expected is not None:
            checks.append(_exact_check(name, expected, actual))
    actual_categories = dict(summary.semantic_category_counts)
    for category, expected in expectations.expected_semantic_category_counts:
        checks.append(
            _exact_check(
                f"semantic_category_count:{category}", expected, actual_categories.get(category, 0)
            )
        )
    if expectations.bbox is not None:
        _append_bbox_checks(checks, summary.bounding_box, expectations.bbox)
    if expectations.geolocation is not None:
        _append_geolocation_checks(checks, summary.geolocation, expectations.geolocation)
    for selected in expectations.receivers:
        _append_receiver_checks(checks, summary.receivers, selected)
    for terrain_selected in expectations.terrain_surfaces:
        _append_terrain_checks(checks, result.site_geometry, terrain_selected)
    status = (
        AcceptanceStatus.PASS
        if all(check.status is AcceptanceStatus.PASS for check in checks)
        else AcceptanceStatus.FAIL
    )
    return PVColladaAcceptanceReport(status=status, summary=summary, checks=tuple(checks))


def parse_acceptance_expectations(data: str | bytes) -> PVColladaAcceptanceExpectations:
    """Parse a strict JSON expectations document without accepting NaN/Infinity."""
    try:
        value = json.loads(data, parse_constant=lambda item: _reject_json_constant(item))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("expectations must be valid JSON") from exc
    root = _object(value, "expectations")
    allowed = {
        "expected_source_application",
        "expected_source_digest",
        "expected_geometry_revision",
        "expected_receiver_count",
        "expected_fixed_receiver_count",
        "expected_tracker_receiver_count",
        "expected_terrain_surface_count",
        "expected_shading_object_count",
        "expected_semantic_category_counts",
        "bbox",
        "geolocation",
        "receivers",
        "terrain_surfaces",
    }
    _reject_unknown_keys(root, allowed, "expectations")
    categories_value = root.get("expected_semantic_category_counts", {})
    categories = _object(categories_value, "expected_semantic_category_counts")
    receivers = _array(root.get("receivers", []), "receivers")
    terrains = _array(root.get("terrain_surfaces", []), "terrain_surfaces")
    return PVColladaAcceptanceExpectations(
        expected_source_application=_optional_string(
            root.get("expected_source_application"), "expected_source_application"
        ),
        expected_source_digest=_optional_string(
            root.get("expected_source_digest"), "expected_source_digest"
        ),
        expected_geometry_revision=_optional_string(
            root.get("expected_geometry_revision"), "expected_geometry_revision"
        ),
        expected_receiver_count=_optional_integer(
            root.get("expected_receiver_count"), "expected_receiver_count"
        ),
        expected_fixed_receiver_count=_optional_integer(
            root.get("expected_fixed_receiver_count"), "expected_fixed_receiver_count"
        ),
        expected_tracker_receiver_count=_optional_integer(
            root.get("expected_tracker_receiver_count"), "expected_tracker_receiver_count"
        ),
        expected_terrain_surface_count=_optional_integer(
            root.get("expected_terrain_surface_count"), "expected_terrain_surface_count"
        ),
        expected_shading_object_count=_optional_integer(
            root.get("expected_shading_object_count"), "expected_shading_object_count"
        ),
        expected_semantic_category_counts=tuple(
            sorted(
                (name, _nonnegative_int(count, f"category {name}"))
                for name, count in categories.items()
            )
        ),
        bbox=_parse_bbox(root["bbox"]) if "bbox" in root else None,
        geolocation=_parse_geolocation(root["geolocation"]) if "geolocation" in root else None,
        receivers=tuple(_parse_receiver(item) for item in receivers),
        terrain_surfaces=tuple(_parse_terrain(item) for item in terrains),
    )


def acceptance_report_dict(
    report: PVColladaAcceptanceReport,
    expectations: PVColladaAcceptanceExpectations,
    *,
    input_label: str | None = None,
    supplied_as: str | None = None,
) -> dict[str, object]:
    """Serialize a bounded private report without XML, meshes, or full model state."""
    summary = report.summary
    output_summary: dict[str, object] = {
        "source_digest": summary.source_digest,
        "source_application": summary.source_application,
        "source_application_version": summary.source_application_version,
        "source_version": summary.source_version,
        "geometry_revision": summary.geometry_revision,
        "canonical_frame": summary.canonical_frame,
        "canonical_unit": summary.canonical_unit,
        "source_unit": summary.source_unit,
        "source_unit_to_m": summary.source_unit_to_m,
        "receiver_count": summary.receiver_count,
        "fixed_receiver_count": summary.fixed_receiver_count,
        "tracker_receiver_count": summary.tracker_receiver_count,
        "unknown_receiver_count": summary.unknown_receiver_count,
        "terrain_surface_count": summary.terrain_surface_count,
        "shading_object_count": summary.shading_object_count,
        "semantic_category_counts": dict(summary.semantic_category_counts),
        "shadow_role_counts": dict(summary.shadow_role_counts),
    }
    if expectations.bbox is not None and summary.bounding_box is not None:
        output_summary["bounding_box"] = _bbox_dict(summary.bounding_box)
    if expectations.geolocation is not None:
        output_summary["geolocation"] = summary.geolocation
    output: dict[str, object] = {
        "status": report.status.value,
        "summary": output_summary,
        "checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "expected": check.expected,
                "actual": check.actual,
                "tolerance": check.tolerance,
                "message": check.message,
            }
            for check in report.checks
        ],
    }
    if input_label is not None:
        output["input_label"] = input_label
    if supplied_as is not None:
        output["supplied_as"] = supplied_as
    return output


def _bounding_box(arrays: tuple[npt.NDArray[np.float64], ...]) -> BoundingBox | None:
    nonempty = tuple(array for array in arrays if array.size)
    if not nonempty:
        return None
    vertices = np.vstack(nonempty)
    if not np.isfinite(vertices).all():
        raise ValueError("canonical geometry contains non-finite vertices")
    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)
    return BoundingBox(
        float(minimum[0]),
        float(maximum[0]),
        float(minimum[1]),
        float(maximum[1]),
        float(minimum[2]),
        float(maximum[2]),
    )


def _count_values(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return tuple(sorted(counts.items()))


def _exact_check(name: str, expected: CheckValue, actual: CheckValue) -> AcceptanceCheck:
    passed = actual == expected
    return AcceptanceCheck(
        name,
        AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
        expected,
        actual,
        message="matched" if passed else "expected value did not match",
    )


def _tolerance_check(
    name: str, expected: float, actual: float | None, tolerance: float
) -> AcceptanceCheck:
    passed = actual is not None and math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)
    return AcceptanceCheck(
        name,
        AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
        expected,
        actual,
        tolerance,
        "within tolerance" if passed else "value missing or outside tolerance",
    )


def _append_bbox_checks(
    checks: list[AcceptanceCheck], actual: BoundingBox | None, expected: BoundingBoxExpectation
) -> None:
    for name in expected.__dataclass_fields__:
        if name == "tolerance_m" or (expected_value := getattr(expected, name)) is None:
            continue
        actual_value = getattr(actual, name) if actual is not None else None
        checks.append(
            _tolerance_check(f"bbox:{name}", expected_value, actual_value, expected.tolerance_m)
        )


def _append_geolocation_checks(
    checks: list[AcceptanceCheck],
    actual: tuple[float, float, float] | None,
    expected: GeolocationExpectation,
) -> None:
    expected_values = (expected.latitude_deg, expected.longitude_deg, expected.altitude_m)
    tolerances = (
        expected.latitude_tolerance_deg,
        expected.longitude_tolerance_deg,
        expected.altitude_tolerance_m,
    )
    for index, name in enumerate(("latitude_deg", "longitude_deg", "altitude_m")):
        checks.append(
            _tolerance_check(
                f"geolocation:{name}",
                expected_values[index],
                actual[index] if actual is not None else None,
                tolerances[index],
            )
        )


def _append_receiver_checks(
    checks: list[AcceptanceCheck],
    receivers: tuple[ReceiverSummary, ...],
    expected: ReceiverExpectation,
) -> None:
    matches = [
        item
        for item in receivers
        if (expected.receiver_id is not None and item.receiver_id == expected.receiver_id)
        or (
            expected.source_object_id is not None
            and item.source_object_id == expected.source_object_id
        )
    ]
    selector = expected.identity
    if len(matches) != 1:
        checks.append(
            AcceptanceCheck(
                f"receiver:{selector}:identity",
                AcceptanceStatus.FAIL,
                selector,
                len(matches),
                message="receiver identity did not resolve exactly once",
            )
        )
        return
    receiver = matches[0]
    checks.append(_exact_check(f"receiver:{selector}:identity", selector, selector))
    if expected.centre_enu_m is not None:
        distance = math.dist(expected.centre_enu_m, receiver.centre_enu_m)
        passed = distance <= expected.centre_tolerance_m
        checks.append(
            AcceptanceCheck(
                f"receiver:{selector}:centre_enu_m",
                AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
                expected.centre_enu_m,
                receiver.centre_enu_m,
                expected.centre_tolerance_m,
                "within Euclidean tolerance" if passed else "centre outside tolerance",
            )
        )
    if expected.receiver_kind is not None:
        checks.append(
            _exact_check(
                f"receiver:{selector}:kind",
                expected.receiver_kind.value,
                receiver.receiver_kind.value,
            )
        )
    if expected.tilt_deg is not None:
        checks.append(
            _tolerance_check(
                f"receiver:{selector}:tilt_deg",
                expected.tilt_deg,
                receiver.orientation.tilt_deg,
                expected.tilt_tolerance_deg,
            )
        )
    if expected.azimuth_deg is not None:
        actual = receiver.orientation.azimuth_deg
        difference = (
            None
            if actual is None
            else min(abs(actual - expected.azimuth_deg), 360.0 - abs(actual - expected.azimuth_deg))
        )
        passed = difference is not None and difference <= expected.azimuth_tolerance_deg
        checks.append(
            AcceptanceCheck(
                f"receiver:{selector}:azimuth_deg",
                AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
                expected.azimuth_deg,
                actual,
                expected.azimuth_tolerance_deg,
                "within circular tolerance" if passed else "azimuth missing or outside tolerance",
            )
        )


def _append_terrain_checks(
    checks: list[AcceptanceCheck], site: SiteGeometry, expected: TerrainElevationExpectation
) -> None:
    matches = [
        item
        for item in site.terrain_surfaces
        if (expected.terrain_id is not None and item.id == expected.terrain_id)
        or (
            expected.source_object_id is not None
            and item.provenance.source_object_id == expected.source_object_id
        )
    ]
    selector = expected.identity
    if len(matches) != 1:
        checks.append(
            AcceptanceCheck(
                f"terrain:{selector}:identity",
                AcceptanceStatus.FAIL,
                selector,
                len(matches),
                message="terrain identity did not resolve exactly once",
            )
        )
        return
    elevations = matches[0].mesh.vertices_enu_m[:, 2]
    if expected.min_elevation_m is not None:
        checks.append(
            _tolerance_check(
                f"terrain:{selector}:min_elevation_m",
                expected.min_elevation_m,
                float(elevations.min()),
                expected.tolerance_m,
            )
        )
    if expected.max_elevation_m is not None:
        checks.append(
            _tolerance_check(
                f"terrain:{selector}:max_elevation_m",
                expected.max_elevation_m,
                float(elevations.max()),
                expected.tolerance_m,
            )
        )


def _parse_bbox(value: object) -> BoundingBoxExpectation:
    item = _object(value, "bbox")
    _reject_unknown_keys(item, set(BoundingBoxExpectation.__dataclass_fields__), "bbox")
    return BoundingBoxExpectation(
        min_east_m=_optional_number(item.get("min_east_m"), "min_east_m"),
        max_east_m=_optional_number(item.get("max_east_m"), "max_east_m"),
        min_north_m=_optional_number(item.get("min_north_m"), "min_north_m"),
        max_north_m=_optional_number(item.get("max_north_m"), "max_north_m"),
        min_elevation_m=_optional_number(item.get("min_elevation_m"), "min_elevation_m"),
        max_elevation_m=_optional_number(item.get("max_elevation_m"), "max_elevation_m"),
        tolerance_m=_number(item.get("tolerance_m", 0.0), "tolerance_m"),
    )


def _parse_geolocation(value: object) -> GeolocationExpectation:
    item = _object(value, "geolocation")
    _reject_unknown_keys(item, set(GeolocationExpectation.__dataclass_fields__), "geolocation")
    return GeolocationExpectation(
        latitude_deg=_required_number(item, "latitude_deg", "geolocation"),
        longitude_deg=_required_number(item, "longitude_deg", "geolocation"),
        altitude_m=_required_number(item, "altitude_m", "geolocation"),
        latitude_tolerance_deg=_number(
            item.get("latitude_tolerance_deg", 0.0), "latitude_tolerance_deg"
        ),
        longitude_tolerance_deg=_number(
            item.get("longitude_tolerance_deg", 0.0), "longitude_tolerance_deg"
        ),
        altitude_tolerance_m=_number(item.get("altitude_tolerance_m", 0.0), "altitude_tolerance_m"),
    )


def _parse_receiver(value: object) -> ReceiverExpectation:
    item = _object(value, "receiver")
    _reject_unknown_keys(item, set(ReceiverExpectation.__dataclass_fields__), "receiver")
    receiver_kind: ReceiverKind | None = None
    if "receiver_kind" in item:
        try:
            receiver_kind = ReceiverKind(_required_string(item, "receiver_kind", "receiver"))
        except (ValueError, TypeError) as exc:
            raise ValueError("receiver_kind is unsupported") from exc
    return ReceiverExpectation(
        receiver_id=_optional_string(item.get("receiver_id"), "receiver_id"),
        source_object_id=_optional_string(item.get("source_object_id"), "source_object_id"),
        centre_enu_m=(
            _vector3(item["centre_enu_m"], "centre_enu_m") if "centre_enu_m" in item else None
        ),
        centre_tolerance_m=_number(item.get("centre_tolerance_m", 0.0), "centre_tolerance_m"),
        receiver_kind=receiver_kind,
        tilt_deg=_optional_number(item.get("tilt_deg"), "tilt_deg"),
        tilt_tolerance_deg=_number(item.get("tilt_tolerance_deg", 0.0), "tilt_tolerance_deg"),
        azimuth_deg=_optional_number(item.get("azimuth_deg"), "azimuth_deg"),
        azimuth_tolerance_deg=_number(
            item.get("azimuth_tolerance_deg", 0.0), "azimuth_tolerance_deg"
        ),
    )


def _parse_terrain(value: object) -> TerrainElevationExpectation:
    item = _object(value, "terrain")
    _reject_unknown_keys(item, set(TerrainElevationExpectation.__dataclass_fields__), "terrain")
    return TerrainElevationExpectation(
        terrain_id=_optional_string(item.get("terrain_id"), "terrain_id"),
        source_object_id=_optional_string(item.get("source_object_id"), "source_object_id"),
        min_elevation_m=_optional_number(item.get("min_elevation_m"), "min_elevation_m"),
        max_elevation_m=_optional_number(item.get("max_elevation_m"), "max_elevation_m"),
        tolerance_m=_number(item.get("tolerance_m", 0.0), "tolerance_m"),
    )


def _bbox_dict(value: BoundingBox) -> dict[str, float]:
    return {
        "min_east_m": value.min_east_m,
        "max_east_m": value.max_east_m,
        "min_north_m": value.min_north_m,
        "max_north_m": value.max_north_m,
        "min_elevation_m": value.min_elevation_m,
        "max_elevation_m": value.max_elevation_m,
    }


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return value


def _reject_unknown_keys(value: dict[str, object], allowed: set[str], name: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ValueError(f"{name} contains unexpected fields: {', '.join(unexpected)}")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is prohibited: {value}")


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    _validate_required_text(value, name)
    return cast(str, value)


def _required_string(value: dict[str, object], key: str, parent: str) -> str:
    if key not in value:
        raise ValueError(f"{parent} requires {key}")
    result = value[key]
    _validate_required_text(result, key)
    return cast(str, result)


def _optional_integer(value: object, name: str) -> int | None:
    return None if value is None else _nonnegative_int(value, name)


def _number(value: object, name: str) -> float:
    return _finite_real(value, name)


def _optional_number(value: object, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _required_number(value: dict[str, object], key: str, parent: str) -> float:
    if key not in value:
        raise ValueError(f"{parent} requires {key}")
    return _number(value[key], key)


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real non-Boolean value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _validate_tolerance(value: object, name: str) -> None:
    if _finite_real(value, name) < 0.0:
        raise ValueError(f"{name} must be non-negative")


def _validate_required_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validate_optional_text(value: object, name: str) -> None:
    if value is not None:
        _validate_required_text(value, name)


def _vector3(value: object, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError(f"{name} must be a three-value array")
    first, second, third = value
    return (
        _finite_real(first, name),
        _finite_real(second, name),
        _finite_real(third, name),
    )


__all__ = [
    "AcceptanceCheck",
    "AcceptanceStatus",
    "BoundingBox",
    "BoundingBoxExpectation",
    "GeolocationExpectation",
    "PVColladaAcceptanceExpectations",
    "PVColladaAcceptanceReport",
    "PVColladaCanonicalSummary",
    "ReceiverExpectation",
    "ReceiverOrientation",
    "ReceiverSummary",
    "TerrainElevationExpectation",
    "acceptance_report_dict",
    "derive_receiver_orientation",
    "evaluate_pvcollada_acceptance",
    "parse_acceptance_expectations",
    "summarize_site_geometry",
]
