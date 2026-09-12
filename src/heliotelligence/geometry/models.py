"""Canonical, source-independent site geometry.

Working geometry is immutable local right-handed East-North-Up (ENU), with
X east, Y north, Z up, and all distances in metres. External formats, physics
adapters, persistence, and visualisation schemas deliberately sit outside this
domain contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from numbers import Real
from typing import TypeVar

import numpy as np
import numpy.typing as npt

_UNIT_VECTOR_TOLERANCE = 1e-10
_AFFINE_TOLERANCE = 1e-12
_T = TypeVar("_T")


class ReceiverKind(StrEnum):
    """Supported physical PV receiver categories."""

    FIXED_TABLE = "fixed_table"
    TRACKER_TABLE = "tracker_table"
    MODULE = "module"
    UNKNOWN = "unknown"


class ShadowRole(StrEnum):
    """Explicit sunlight-blocking role for an arbitrary mesh."""

    OCCLUDER = "occluder"
    NON_OCCLUDER = "non_occluder"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceProvenance:
    """References to a source artifact without embedding its raw contents."""

    source_format: str | None = None
    source_version: str | None = None
    source_application: str | None = None
    source_application_version: str | None = None
    source_digest: str | None = None
    source_object_id: str | None = None
    geometry_revision: str | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _validate_optional_text(getattr(self, name), name)


@dataclass(frozen=True, eq=False)
class CoordinateReference:
    """Canonical ENU/metre invariants and optional source-coordinate metadata."""

    canonical_frame: str = field(default="ENU", init=False)
    canonical_unit: str = field(default="m", init=False)
    source_unit: str | None = None
    source_unit_to_m: float | None = None
    source_up_axis: str | None = None
    source_crs: str | None = None
    origin_latitude_deg: float | None = None
    origin_longitude_deg: float | None = None
    origin_altitude_m: float | None = None
    source_to_canonical_transform: npt.NDArray[np.float64] | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        for name in ("source_unit", "source_up_axis", "source_crs"):
            _validate_optional_text(getattr(self, name), name)

        if self.source_unit_to_m is not None:
            scale = _finite_real(self.source_unit_to_m, "source_unit_to_m")
            if scale <= 0.0:
                raise ValueError("source_unit_to_m must be greater than 0")
            object.__setattr__(self, "source_unit_to_m", scale)

        origin = (
            self.origin_latitude_deg,
            self.origin_longitude_deg,
            self.origin_altitude_m,
        )
        if any(value is not None for value in origin) and not all(
            value is not None for value in origin
        ):
            raise ValueError("geodetic origin latitude, longitude, and altitude are all required")
        if all(value is not None for value in origin):
            latitude = _finite_real(self.origin_latitude_deg, "origin_latitude_deg")
            longitude = _finite_real(self.origin_longitude_deg, "origin_longitude_deg")
            altitude = _finite_real(self.origin_altitude_m, "origin_altitude_m")
            if not -90.0 <= latitude <= 90.0:
                raise ValueError("origin_latitude_deg must be within [-90, 90]")
            if not -180.0 <= longitude <= 180.0:
                raise ValueError("origin_longitude_deg must be within [-180, 180]")
            object.__setattr__(self, "origin_latitude_deg", latitude)
            object.__setattr__(self, "origin_longitude_deg", longitude)
            object.__setattr__(self, "origin_altitude_m", altitude)

        transform = self.source_to_canonical_transform
        if transform is not None:
            transform_copy = _numeric_array(transform, "source_to_canonical_transform")
            if transform_copy.shape != (4, 4):
                raise ValueError("source_to_canonical_transform must have shape (4, 4)")
            if not np.allclose(
                transform_copy[3],
                np.array([0.0, 0.0, 0.0, 1.0]),
                rtol=0.0,
                atol=_AFFINE_TOLERANCE,
            ):
                raise ValueError("source_to_canonical_transform must be homogeneous affine")
            transform_copy.flags.writeable = False
            object.__setattr__(self, "source_to_canonical_transform", transform_copy)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CoordinateReference):
            return NotImplemented
        scalar_fields = (
            "canonical_frame",
            "canonical_unit",
            "source_unit",
            "source_unit_to_m",
            "source_up_axis",
            "source_crs",
            "origin_latitude_deg",
            "origin_longitude_deg",
            "origin_altitude_m",
        )
        if any(getattr(self, name) != getattr(other, name) for name in scalar_fields):
            return False
        left = self.source_to_canonical_transform
        right = other.source_to_canonical_transform
        return (left is None and right is None) or (
            left is not None and right is not None and np.array_equal(left, right)
        )


@dataclass(frozen=True, eq=False)
class TriangleMesh:
    """Immutable triangle mesh with finite float64 ENU vertices."""

    vertices_enu_m: npt.NDArray[np.float64] = field(repr=False)
    faces: npt.NDArray[np.int64] = field(repr=False)

    def __post_init__(self) -> None:
        vertices = _numeric_array(self.vertices_enu_m, "vertices_enu_m")
        if vertices.ndim != 2 or vertices.shape[1:] != (3,):
            raise ValueError("vertices_enu_m must have shape (N, 3)")

        faces_value = self.faces
        if not isinstance(faces_value, np.ndarray):
            raise ValueError("faces must be a NumPy array")
        if np.issubdtype(faces_value.dtype, np.bool_) or not np.issubdtype(
            faces_value.dtype, np.integer
        ):
            raise ValueError("faces must contain integers")
        faces = np.array(faces_value, dtype=np.int64, copy=True)
        if faces.ndim != 2 or faces.shape[1:] != (3,):
            raise ValueError("faces must have shape (M, 3)")

        vertex_count = vertices.shape[0]
        face_count = faces.shape[0]
        if (vertex_count == 0) != (face_count == 0):
            raise ValueError("vertices and faces must either both be empty or both be non-empty")
        if vertex_count and vertex_count < 3:
            raise ValueError("a non-empty mesh must contain at least 3 vertices")
        if face_count:
            if np.any(faces < 0):
                raise ValueError("faces must not contain negative indices")
            if np.any(faces >= vertex_count):
                raise ValueError("face index must be less than vertex count")
            if np.any(
                (faces[:, 0] == faces[:, 1])
                | (faces[:, 0] == faces[:, 2])
                | (faces[:, 1] == faces[:, 2])
            ):
                raise ValueError("each triangle must reference three distinct vertices")

        vertices.flags.writeable = False
        faces.flags.writeable = False
        object.__setattr__(self, "vertices_enu_m", vertices)
        object.__setattr__(self, "faces", faces)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TriangleMesh):
            return NotImplemented
        return np.array_equal(self.vertices_enu_m, other.vertices_enu_m) and np.array_equal(
            self.faces, other.faces
        )


@dataclass(frozen=True)
class PVReceiver:
    """Physical PV receiving geometry, independent of electrical topology."""

    id: str
    mesh: TriangleMesh
    centre_enu_m: tuple[float, float, float]
    normal_enu: tuple[float, float, float]
    receiver_kind: ReceiverKind
    provenance: SourceProvenance = field(default_factory=SourceProvenance)
    parent_id: str | None = None
    source_semantic_name: str | None = None

    def __post_init__(self) -> None:
        _validate_required_text(self.id, "receiver id")
        if not isinstance(self.mesh, TriangleMesh):
            raise ValueError("mesh must be a TriangleMesh")
        if not isinstance(self.provenance, SourceProvenance):
            raise ValueError("provenance must be SourceProvenance")
        if not isinstance(self.receiver_kind, ReceiverKind):
            raise ValueError("receiver_kind must be ReceiverKind")
        centre = _vector3(self.centre_enu_m, "centre_enu_m")
        normal = _vector3(self.normal_enu, "normal_enu")
        if not np.isclose(np.linalg.norm(normal), 1.0, rtol=0.0, atol=_UNIT_VECTOR_TOLERANCE):
            raise ValueError("normal_enu must be a unit vector")
        _validate_optional_text(self.parent_id, "parent_id")
        _validate_optional_text(self.source_semantic_name, "source_semantic_name")
        object.__setattr__(self, "centre_enu_m", centre)
        object.__setattr__(self, "normal_enu", normal)


@dataclass(frozen=True)
class TerrainSurface:
    """One canonical terrain triangle surface without derived terrain physics."""

    id: str
    mesh: TriangleMesh
    provenance: SourceProvenance = field(default_factory=SourceProvenance)
    source_semantic_name: str | None = None

    def __post_init__(self) -> None:
        _validate_geometry_object(self.id, self.mesh, self.provenance, "terrain")
        _validate_optional_text(self.source_semantic_name, "source_semantic_name")


@dataclass(frozen=True)
class ShadingObject:
    """Arbitrary geometry with an explicit, non-inferred shadow role."""

    id: str
    mesh: TriangleMesh
    shadow_role: ShadowRole
    provenance: SourceProvenance = field(default_factory=SourceProvenance)
    semantic_category: str | None = None
    source_semantic_name: str | None = None

    def __post_init__(self) -> None:
        _validate_geometry_object(self.id, self.mesh, self.provenance, "shading object")
        if not isinstance(self.shadow_role, ShadowRole):
            raise ValueError("shadow_role must be ShadowRole")
        _validate_optional_text(self.semantic_category, "semantic_category")
        _validate_optional_text(self.source_semantic_name, "source_semantic_name")


@dataclass(frozen=True)
class SiteGeometry:
    """Top-level canonical site geometry with deterministic importer ordering."""

    geometry_revision: str
    source_provenance: SourceProvenance
    coordinate_reference: CoordinateReference
    pv_receivers: tuple[PVReceiver, ...] = ()
    terrain_surfaces: tuple[TerrainSurface, ...] = ()
    shading_objects: tuple[ShadingObject, ...] = ()

    def __post_init__(self) -> None:
        _validate_required_text(self.geometry_revision, "geometry_revision")
        if not isinstance(self.source_provenance, SourceProvenance):
            raise ValueError("source_provenance must be SourceProvenance")
        if not isinstance(self.coordinate_reference, CoordinateReference):
            raise ValueError("coordinate_reference must be CoordinateReference")

        receivers = _typed_tuple(self.pv_receivers, PVReceiver, "pv_receivers")
        terrains = _typed_tuple(self.terrain_surfaces, TerrainSurface, "terrain_surfaces")
        shading = _typed_tuple(self.shading_objects, ShadingObject, "shading_objects")
        object.__setattr__(self, "pv_receivers", receivers)
        object.__setattr__(self, "terrain_surfaces", terrains)
        object.__setattr__(self, "shading_objects", shading)

        source_revision = self.source_provenance.geometry_revision
        if source_revision is not None and source_revision != self.geometry_revision:
            raise ValueError("source provenance geometry_revision must match SiteGeometry")

        all_ids = (
            [receiver.id for receiver in receivers]
            + [terrain.id for terrain in terrains]
            + [shading_object.id for shading_object in shading]
        )
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("canonical geometry IDs must be globally unique")


def _numeric_array(value: object, name: str) -> npt.NDArray[np.float64]:
    if not isinstance(value, np.ndarray):
        raise ValueError(f"{name} must be a NumPy array")
    if np.issubdtype(value.dtype, np.bool_) or not np.issubdtype(value.dtype, np.number):
        raise ValueError(f"{name} must contain real numeric values")
    if np.issubdtype(value.dtype, np.complexfloating):
        raise ValueError(f"{name} must contain real numeric values")
    result = np.array(value, dtype=np.float64, copy=True)
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite values")
    return result


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real non-Boolean value")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be a finite real non-Boolean value")
    return result


def _vector3(value: object, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list, np.ndarray)) or len(value) != 3:
        raise ValueError(f"{name} must be a length-3 vector")
    return tuple(_finite_real(component, name) for component in value)  # type: ignore[return-value]


def _validate_required_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value.isspace():
        raise ValueError(f"{name} must be a non-empty, non-whitespace string")


def _validate_optional_text(value: object, name: str) -> None:
    if value is not None:
        _validate_required_text(value, name)


def _validate_geometry_object(
    object_id: object,
    mesh: object,
    provenance: object,
    label: str,
) -> None:
    _validate_required_text(object_id, f"{label} id")
    if not isinstance(mesh, TriangleMesh):
        raise ValueError("mesh must be a TriangleMesh")
    if not isinstance(provenance, SourceProvenance):
        raise ValueError("provenance must be SourceProvenance")


def _typed_tuple(value: object, item_type: type[_T], name: str) -> tuple[_T, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} must be a tuple or list")
    result = tuple(value)
    if any(not isinstance(item, item_type) for item in result):
        raise ValueError(f"{name} contains an invalid object")
    return result
