"""Deterministic reference kernel for direct-beam geometric shading.

Geometry uses a right-handed local East-North-Up (ENU) Cartesian frame in
metres.  This module performs no geographic conversion, irradiance modelling,
or electrical calculation.  It samples receiving rectangles and tests rays
toward the sun against opaque, two-sided rectangular scene surfaces.

The NumPy implementation is intentionally a correctness reference with
approximately O(receivers * samples * surfaces) work.  A future BVH, batched,
Embree, or GPU backend must demonstrate equivalence to this behavior.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral

import numpy as np
import pandas as pd

_AXIS_TOLERANCE = 1e-10
_PARALLEL_TOLERANCE = 1e-12
_RAY_DISTANCE_EPSILON_M = 1e-9
_RECTANGLE_BOUNDS_TOLERANCE_M = 1e-10
_OUTPUT_COLUMNS = [
    "receiver_id",
    "visible_fraction",
    "shaded_fraction",
    "sample_count",
    "shaded_sample_count",
]


@dataclass(frozen=True)
class RectangularSurface3D:
    """Opaque two-sided rectangle in a local ENU coordinate system."""

    id: str
    center_enu_m: tuple[float, float, float]
    u_axis_enu: tuple[float, float, float]
    v_axis_enu: tuple[float, float, float]
    span_u_m: float
    span_v_m: float

    def __post_init__(self) -> None:
        """Reject malformed explicit geometry without normalizing it."""
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("surface id must be non-empty")

        center = _validated_tuple_vector(self.center_enu_m, "center_enu_m")
        u_axis = _validated_tuple_vector(self.u_axis_enu, "u_axis_enu")
        v_axis = _validated_tuple_vector(self.v_axis_enu, "v_axis_enu")

        if not np.isclose(
            np.linalg.norm(u_axis), 1.0, rtol=0.0, atol=_AXIS_TOLERANCE
        ):
            raise ValueError("u_axis_enu must be a unit vector")
        if not np.isclose(
            np.linalg.norm(v_axis), 1.0, rtol=0.0, atol=_AXIS_TOLERANCE
        ):
            raise ValueError("v_axis_enu must be a unit vector")
        if not np.isclose(
            np.dot(u_axis, v_axis), 0.0, rtol=0.0, atol=_AXIS_TOLERANCE
        ):
            raise ValueError("u_axis_enu and v_axis_enu must be orthogonal")

        for name, value in (
            ("span_u_m", self.span_u_m),
            ("span_v_m", self.span_v_m),
        ):
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and greater than 0")

        # Force evaluation of centre validation even though it is not otherwise
        # used in the orthonormality checks above.
        _ = center

    @property
    def normal_enu(self) -> tuple[float, float, float]:
        """Return the unit normal implied by the validated in-plane axes."""
        normal = np.cross(self.u_axis_enu, self.v_axis_enu)
        return tuple(float(component) for component in normal)


def make_fixed_tilt_rectangular_surface(
    *,
    surface_id: str,
    center_enu_m: tuple[float, float, float],
    span_u_m: float,
    span_v_m: float,
    tilt_deg: float,
    surface_azimuth_deg: float,
) -> RectangularSurface3D:
    """Build a rectangle from pvlib-style tilt and surface azimuth angles."""
    _validate_finite_angle(tilt_deg, "tilt_deg", lower=0.0, upper=90.0, closed=True)
    _validate_finite_angle(
        surface_azimuth_deg,
        "surface_azimuth_deg",
        lower=0.0,
        upper=360.0,
        closed=False,
    )

    tilt = np.radians(tilt_deg)
    azimuth = np.radians(surface_azimuth_deg)
    normal = np.array(
        [
            np.sin(tilt) * np.sin(azimuth),
            np.sin(tilt) * np.cos(azimuth),
            np.cos(tilt),
        ],
        dtype=float,
    )

    if tilt_deg == 0.0:
        u_axis = np.array([1.0, 0.0, 0.0])
        v_axis = np.array([0.0, 1.0, 0.0])
    else:
        u_axis = np.cross(np.array([0.0, 0.0, 1.0]), normal)
        u_axis /= np.linalg.norm(u_axis)
        v_axis = np.cross(normal, u_axis)

    return RectangularSurface3D(
        id=surface_id,
        center_enu_m=center_enu_m,
        u_axis_enu=tuple(float(component) for component in u_axis),
        v_axis_enu=tuple(float(component) for component in v_axis),
        span_u_m=span_u_m,
        span_v_m=span_v_m,
    )


def solar_direction_enu(
    solar_zenith_deg: float,
    solar_azimuth_deg: float,
) -> tuple[float, float, float]:
    """Return a unit ENU vector from a receiver toward the above-horizon sun."""
    _validate_finite_angle(
        solar_zenith_deg,
        "solar_zenith_deg",
        lower=0.0,
        upper=90.0,
        closed=False,
    )
    _validate_finite_angle(
        solar_azimuth_deg,
        "solar_azimuth_deg",
        lower=0.0,
        upper=360.0,
        closed=False,
    )

    zenith = np.radians(solar_zenith_deg)
    azimuth = np.radians(solar_azimuth_deg)
    direction = np.array(
        [
            np.sin(zenith) * np.sin(azimuth),
            np.sin(zenith) * np.cos(azimuth),
            np.cos(zenith),
        ],
        dtype=float,
    )
    direction /= np.linalg.norm(direction)
    return tuple(float(component) for component in direction)


def calculate_direct_beam_visibility(
    surfaces: Sequence[RectangularSurface3D],
    receiver_ids: Sequence[str],
    *,
    solar_zenith_deg: float,
    solar_azimuth_deg: float,
    samples_u: int = 5,
    samples_v: int = 5,
) -> pd.DataFrame:
    """Sample receiver rectangles and return direct-beam visibility fractions.

    Fractions are deterministic finite-sample approximations, not exact
    continuous-area integration.  Samples lie at grid-cell centres.
    """
    direction = np.asarray(
        solar_direction_enu(solar_zenith_deg, solar_azimuth_deg), dtype=float
    )
    _validate_sample_count(samples_u, "samples_u")
    _validate_sample_count(samples_v, "samples_v")

    surface_ids = [surface.id for surface in surfaces]
    duplicate_surface_ids = sorted(
        surface_id
        for surface_id, count in Counter(surface_ids).items()
        if count > 1
    )
    if duplicate_surface_ids:
        raise ValueError(
            "surfaces contains duplicate ids: " + ", ".join(duplicate_surface_ids)
        )

    duplicate_receiver_ids = sorted(
        receiver_id
        for receiver_id, count in Counter(receiver_ids).items()
        if count > 1
    )
    if duplicate_receiver_ids:
        raise ValueError(
            "receiver_ids contains duplicate ids: "
            + ", ".join(duplicate_receiver_ids)
        )

    surfaces_by_id = {surface.id: surface for surface in surfaces}
    missing_receiver_ids = sorted(set(receiver_ids) - set(surfaces_by_id))
    if missing_receiver_ids:
        raise ValueError(
            "receiver_ids are absent from surfaces: "
            + ", ".join(missing_receiver_ids)
        )

    sample_count = int(samples_u) * int(samples_v)
    rows: list[dict[str, str | float | int]] = []
    for receiver_id in receiver_ids:
        receiver = surfaces_by_id[receiver_id]
        shaded_sample_count = 0
        for origin in _receiver_sample_points(receiver, samples_u, samples_v):
            if any(
                occluder.id != receiver_id
                and _ray_intersects_rectangle(origin, direction, occluder)
                for occluder in surfaces
            ):
                shaded_sample_count += 1

        shaded_fraction = shaded_sample_count / sample_count
        rows.append(
            {
                "receiver_id": receiver_id,
                "visible_fraction": 1.0 - shaded_fraction,
                "shaded_fraction": shaded_fraction,
                "sample_count": sample_count,
                "shaded_sample_count": shaded_sample_count,
            }
        )

    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)


def _validated_tuple_vector(
    value: tuple[float, float, float],
    name: str,
) -> np.ndarray:
    """Validate one immutable three-component finite vector."""
    if not isinstance(value, tuple) or len(value) != 3:
        raise ValueError(f"{name} must be a three-component tuple")
    vector = np.asarray(value, dtype=float)
    if not np.isfinite(vector).all():
        raise ValueError(f"{name} must contain only finite values")
    return vector


def _validate_finite_angle(
    value: float,
    name: str,
    *,
    lower: float,
    upper: float,
    closed: bool,
) -> None:
    """Validate a finite angle against a fixed public interval."""
    valid_upper = value <= upper if closed else value < upper
    if not np.isfinite(value) or value < lower or not valid_upper:
        closing = "]" if closed else ")"
        raise ValueError(f"{name} must be finite and in [{lower}, {upper}{closing}")


def _validate_sample_count(value: int, name: str) -> None:
    """Require a positive integral deterministic grid dimension."""
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be an integer greater than or equal to 1")


def _receiver_sample_points(
    receiver: RectangularSurface3D,
    samples_u: int,
    samples_v: int,
) -> Sequence[np.ndarray]:
    """Yield deterministic rectangle cell-centre sample positions."""
    center = np.asarray(receiver.center_enu_m, dtype=float)
    u_axis = np.asarray(receiver.u_axis_enu, dtype=float)
    v_axis = np.asarray(receiver.v_axis_enu, dtype=float)
    u_positions = (
        (np.arange(samples_u, dtype=float) + 0.5) / samples_u - 0.5
    ) * receiver.span_u_m
    v_positions = (
        (np.arange(samples_v, dtype=float) + 0.5) / samples_v - 0.5
    ) * receiver.span_v_m
    return [
        center + u_position * u_axis + v_position * v_axis
        for u_position in u_positions
        for v_position in v_positions
    ]


def _ray_intersects_rectangle(
    origin: np.ndarray,
    direction: np.ndarray,
    surface: RectangularSurface3D,
) -> bool:
    """Test a positive-distance ray against one opaque two-sided rectangle."""
    center = np.asarray(surface.center_enu_m, dtype=float)
    u_axis = np.asarray(surface.u_axis_enu, dtype=float)
    v_axis = np.asarray(surface.v_axis_enu, dtype=float)
    normal = np.cross(u_axis, v_axis)
    denominator = float(np.dot(direction, normal))
    if abs(denominator) <= _PARALLEL_TOLERANCE:
        return False

    ray_distance = float(np.dot(center - origin, normal) / denominator)
    if ray_distance <= _RAY_DISTANCE_EPSILON_M:
        return False

    delta = origin + ray_distance * direction - center
    du = float(np.dot(delta, u_axis))
    dv = float(np.dot(delta, v_axis))
    return (
        abs(du) <= surface.span_u_m / 2.0 + _RECTANGLE_BOUNDS_TOLERANCE_M
        and abs(dv) <= surface.span_v_m / 2.0 + _RECTANGLE_BOUNDS_TOLERANCE_M
    )
