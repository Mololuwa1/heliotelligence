"""Canonical PVsyst far-horizon profile and point-sun visibility evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from numpy.typing import NDArray

from heliotelligence.physics.pvsyst_linear_shading import (
    PVsystHemisphere,
    convert_pvlib_azimuth_to_pvsyst,
)

PVSYST_FAR_HORIZON_CONTRACT_ID = "pvsyst_far_horizon_profile_v1"
PVSYST_FAR_HORIZON_MODEL_ID = (
    "pvsyst_circular_piecewise_linear_horizon_visibility_v1"
)
PVSYST_FAR_HORIZON_SCOPE = "far_horizon_direct_beam_geometry_only"
PVSYST_FAR_HORIZON_COVERAGE_SCOPE = "site_global_full_azimuth_periodic_profile"
PVSYST_FAR_HORIZON_AZIMUTH_REFERENCE = (
    "pvsyst_signed_equator_facing_west_positive"
)

PVsystHorizonCoverageSemantics = Literal["full_azimuth_periodic"]

_TOLERANCE = 1e-12
_OUTPUT_COLUMNS = (
    "solar_elevation_deg",
    "solar_azimuth_deg",
    "pvsyst_solar_azimuth_deg",
    "pvsyst_horizon_elevation_deg",
    "pvsyst_horizon_clearance_deg",
    "pvsyst_horizon_beam_visible_factor",
    "pvsyst_horizon_visibility_resolved",
    "pvsyst_horizon_state",
    "pvsyst_horizon_profile_id",
    "pvsyst_version",
    "pvsyst_source_label",
    "pvsyst_source_reference",
    "pvsyst_far_horizon_azimuth_reference",
    "pvsyst_far_horizon_contract",
    "pvsyst_far_horizon_model",
    "pvsyst_far_horizon_coverage_scope",
    "pvsyst_far_horizon_scope",
)


@dataclass(frozen=True)
class PVsystFarHorizonProfile:
    """Normalized, weather-independent, full-periodic far-horizon geometry."""

    profile_id: str
    pvsyst_solar_azimuth_deg: tuple[float, ...]
    horizon_elevation_deg: tuple[float, ...]
    coverage_semantics: PVsystHorizonCoverageSemantics
    source_label: str
    source_reference: str | None = None
    pvsyst_version: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.profile_id, "profile_id")
        _required_text(self.source_label, "source_label")
        _optional_text(self.source_reference, "source_reference")
        _optional_text(self.pvsyst_version, "pvsyst_version")
        if self.coverage_semantics != "full_azimuth_periodic":
            raise ValueError(
                "coverage_semantics must explicitly be 'full_azimuth_periodic'"
            )
        azimuths = _grid(
            self.pvsyst_solar_azimuth_deg,
            "pvsyst_solar_azimuth_deg",
            -180.0,
            180.0,
            minimum_length=3,
        )
        if not isinstance(self.horizon_elevation_deg, tuple) or len(
            self.horizon_elevation_deg
        ) != len(azimuths):
            raise ValueError("horizon_elevation_deg must be a matching tuple")
        elevations = tuple(
            _bounded_real(value, "horizon_elevation_deg", -90.0, 90.0)
            for value in self.horizon_elevation_deg
        )
        if np.isclose(azimuths[0], -180.0, atol=_TOLERANCE, rtol=0.0) and np.isclose(
            azimuths[-1], 180.0, atol=_TOLERANCE, rtol=0.0
        ) and not np.isclose(elevations[0], elevations[-1], atol=_TOLERANCE, rtol=0.0):
            raise ValueError("PVsyst -180/+180 horizon seam elevations must agree")


@dataclass(frozen=True)
class PVsystFarHorizonDiagnostics:
    timestamp_count: int
    resolved_count: int
    visible_count: int
    blocked_count: int
    not_applicable_count: int
    profile_id: str
    model: str


@dataclass(frozen=True)
class PVsystFarHorizonResult:
    horizon: pd.DataFrame
    diagnostics: PVsystFarHorizonDiagnostics


def evaluate_pvsyst_far_horizon(
    profile: PVsystFarHorizonProfile,
    solar_elevation_deg: pd.Series,
    solar_azimuth_deg: pd.Series,
    *,
    hemisphere: PVsystHemisphere,
) -> PVsystFarHorizonResult:
    """Interpolate skyline height and classify binary point-sun visibility."""
    if not isinstance(profile, PVsystFarHorizonProfile):
        raise ValueError("profile must be PVsystFarHorizonProfile")
    _angle_series(solar_elevation_deg, "solar_elevation_deg", -90.0, 90.0)
    _angle_series(
        solar_azimuth_deg,
        "solar_azimuth_deg",
        0.0,
        360.0,
        upper_open=True,
    )
    if (
        not solar_elevation_deg.index.equals(solar_azimuth_deg.index)
        or solar_elevation_deg.index.name != solar_azimuth_deg.index.name
        or solar_elevation_deg.index.tz != solar_azimuth_deg.index.tz
    ):
        raise ValueError("solar elevation and azimuth indexes must match exactly")

    pvsyst_azimuth = convert_pvlib_azimuth_to_pvsyst(
        solar_azimuth_deg, hemisphere=hemisphere
    )
    periodic_azimuths, periodic_elevations = _periodic_profile(profile)
    rows: list[dict[str, object]] = []
    visible_count = 0
    blocked_count = 0
    not_applicable_count = 0
    for timestamp in solar_elevation_deg.index:
        elevation = float(solar_elevation_deg.loc[timestamp])
        azimuth = float(solar_azimuth_deg.loc[timestamp])
        pvsyst_angle = float(pvsyst_azimuth.loc[timestamp])
        horizon_elevation = _interpolate_horizon(
            pvsyst_angle, periodic_azimuths, periodic_elevations
        )
        clearance = elevation - horizon_elevation
        if elevation <= 0.0:
            factor = np.nan
            resolved = False
            state = "not_applicable_no_above_horizon_beam"
            not_applicable_count += 1
        elif clearance > _TOLERANCE:
            factor = 1.0
            resolved = True
            state = "resolved_visible_above_far_horizon"
            visible_count += 1
        else:
            factor = 0.0
            resolved = True
            state = "resolved_blocked_by_far_horizon"
            blocked_count += 1
        rows.append(
            {
                "solar_elevation_deg": elevation,
                "solar_azimuth_deg": azimuth,
                "pvsyst_solar_azimuth_deg": pvsyst_angle,
                "pvsyst_horizon_elevation_deg": horizon_elevation,
                "pvsyst_horizon_clearance_deg": clearance,
                "pvsyst_horizon_beam_visible_factor": factor,
                "pvsyst_horizon_visibility_resolved": resolved,
                "pvsyst_horizon_state": state,
                "pvsyst_horizon_profile_id": profile.profile_id,
                "pvsyst_version": profile.pvsyst_version,
                "pvsyst_source_label": profile.source_label,
                "pvsyst_source_reference": profile.source_reference,
                "pvsyst_far_horizon_azimuth_reference": (
                    PVSYST_FAR_HORIZON_AZIMUTH_REFERENCE
                ),
                "pvsyst_far_horizon_contract": PVSYST_FAR_HORIZON_CONTRACT_ID,
                "pvsyst_far_horizon_model": PVSYST_FAR_HORIZON_MODEL_ID,
                "pvsyst_far_horizon_coverage_scope": (
                    PVSYST_FAR_HORIZON_COVERAGE_SCOPE
                ),
                "pvsyst_far_horizon_scope": PVSYST_FAR_HORIZON_SCOPE,
            }
        )

    frame = pd.DataFrame(rows, index=solar_elevation_deg.index, columns=_OUTPUT_COLUMNS)
    frame = _typed(frame)
    if tuple(frame.columns) != _OUTPUT_COLUMNS:
        raise RuntimeError("PVsyst far-horizon output schema changed unexpectedly")
    resolved_count = (
        int(frame["pvsyst_horizon_visibility_resolved"].sum()) if len(frame) else 0
    )
    if resolved_count != visible_count + blocked_count or len(frame) != (
        resolved_count + not_applicable_count
    ):
        raise RuntimeError("PVsyst far-horizon diagnostic counts do not close")
    return PVsystFarHorizonResult(
        frame,
        PVsystFarHorizonDiagnostics(
            timestamp_count=len(frame),
            resolved_count=resolved_count,
            visible_count=visible_count,
            blocked_count=blocked_count,
            not_applicable_count=not_applicable_count,
            profile_id=profile.profile_id,
            model=PVSYST_FAR_HORIZON_MODEL_ID,
        ),
    )


def _periodic_profile(
    profile: PVsystFarHorizonProfile,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    azimuths = np.asarray(profile.pvsyst_solar_azimuth_deg, dtype=float)
    elevations = np.asarray(profile.horizon_elevation_deg, dtype=float)
    if np.isclose(azimuths[0], -180.0, atol=_TOLERANCE, rtol=0.0) and np.isclose(
        azimuths[-1], 180.0, atol=_TOLERANCE, rtol=0.0
    ):
        azimuths = azimuths[:-1]
        elevations = elevations[:-1]
    return (
        np.concatenate((azimuths, (azimuths[0] + 360.0,))),
        np.concatenate((elevations, elevations[:1])),
    )


def _interpolate_horizon(
    azimuth: float,
    azimuths: NDArray[np.float64],
    elevations: NDArray[np.float64],
) -> float:
    wrapped = azimuth
    while wrapped < azimuths[0]:
        wrapped += 360.0
    while wrapped > azimuths[-1]:
        wrapped -= 360.0
    upper = int(np.searchsorted(azimuths, wrapped, side="right"))
    upper = min(max(upper, 1), len(azimuths) - 1)
    lower = upper - 1
    span = azimuths[upper] - azimuths[lower]
    weight = (wrapped - azimuths[lower]) / span
    return float(elevations[lower] * (1.0 - weight) + elevations[upper] * weight)


def _grid(
    value: object,
    name: str,
    lower: float,
    upper: float,
    *,
    minimum_length: int,
) -> tuple[float, ...]:
    if not isinstance(value, tuple) or len(value) < minimum_length:
        raise ValueError(f"{name} must be a tuple with at least {minimum_length} entries")
    result = tuple(_bounded_real(item, name, lower, upper) for item in value)
    if any(right <= left for left, right in zip(result, result[1:], strict=False)):
        raise ValueError(f"{name} must be strictly increasing and unique")
    return result


def _angle_series(
    value: object,
    name: str,
    lower: float,
    upper: float,
    *,
    upper_open: bool = False,
) -> None:
    if not isinstance(value, pd.Series) or not isinstance(value.index, pd.DatetimeIndex):
        raise ValueError(f"{name} must be a Series with DatetimeIndex")
    if value.index.tz is None or value.index.hasnans or value.index.has_duplicates:
        raise ValueError(f"{name} index must be timezone-aware, unique, and contain no NaT")
    for item in value.array:
        number = _bounded_real(item, name, lower, upper)
        if upper_open and number >= upper:
            raise ValueError(f"{name} must be within [{lower}, {upper})")


def _bounded_real(value: object, name: str, lower: float, upper: float) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must contain finite non-Boolean real values")
    number = float(value)
    if not np.isfinite(number) or number < lower or number > upper:
        raise ValueError(f"{name} values must be within [{lower}, {upper}]")
    return number


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    for column in _OUTPUT_COLUMNS[:6]:
        frame[column] = frame[column].astype(float)
    frame["pvsyst_horizon_visibility_resolved"] = frame[
        "pvsyst_horizon_visibility_resolved"
    ].astype(bool)
    for column in _OUTPUT_COLUMNS[7:]:
        frame[column] = frame[column].astype("string")
    return frame
