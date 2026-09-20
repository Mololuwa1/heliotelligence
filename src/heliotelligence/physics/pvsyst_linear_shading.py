"""Canonical PVsyst linear beam-shading table and interpolator."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from numpy.typing import NDArray

PVSYST_LINEAR_SHADING_CONTRACT_ID = "pvsyst_linear_beam_shading_table_v1"
PVSYST_LINEAR_SHADING_MODEL_ID = "pvsyst_solar_position_bilinear_interpolation_v1"
PVSYST_LINEAR_SHADING_SCOPE = "near_shading_linear_beam_geometry_only"
PVSYST_LINEAR_SHADING_COVERAGE_SCOPE = "fixed_table_pvsyst_orientation_or_zone"

PVsystShadingValueSemantics = Literal["shaded_fraction", "transmission_fraction"]
PVsystHemisphere = Literal["north", "south"]

_TOLERANCE = 1e-12
_OUTPUT_COLUMNS = (
    "solar_elevation_deg",
    "solar_azimuth_deg",
    "pvsyst_solar_azimuth_deg",
    "pvsyst_beam_transmission_fraction",
    "pvsyst_beam_shaded_fraction",
    "pvsyst_linear_shading_resolved",
    "pvsyst_linear_shading_state",
    "pvsyst_table_id",
    "pvsyst_orientation_id",
    "pvsyst_zone_id",
    "pvsyst_input_value_semantics",
    "pvsyst_version",
    "pvsyst_source_label",
    "pvsyst_source_reference",
    "pvsyst_linear_shading_contract",
    "pvsyst_linear_shading_model",
    "pvsyst_linear_shading_coverage_scope",
    "pvsyst_linear_shading_scope",
)


@dataclass(frozen=True)
class PVsystLinearShadingTable:
    """A weather-independent, normalized PVsyst linear near-shading artifact."""

    table_id: str
    orientation_id: str
    zone_id: str | None
    sun_height_deg: tuple[float, ...]
    pvsyst_solar_azimuth_deg: tuple[float, ...]
    values: tuple[tuple[float, ...], ...]
    value_semantics: PVsystShadingValueSemantics
    source_label: str
    source_reference: str | None = None
    pvsyst_version: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.table_id, "table_id")
        _required_text(self.orientation_id, "orientation_id")
        _optional_text(self.zone_id, "zone_id")
        _required_text(self.source_label, "source_label")
        _optional_text(self.source_reference, "source_reference")
        _optional_text(self.pvsyst_version, "pvsyst_version")
        if self.value_semantics not in ("shaded_fraction", "transmission_fraction"):
            raise ValueError("value_semantics must explicitly identify shaded or transmission")
        heights = _grid(self.sun_height_deg, "sun_height_deg", 0.0, 90.0)
        azimuths = _grid(
            self.pvsyst_solar_azimuth_deg,
            "pvsyst_solar_azimuth_deg",
            -180.0,
            180.0,
        )
        if not isinstance(self.values, tuple) or len(self.values) != len(heights):
            raise ValueError("values must have one tuple row per sun height")
        normalized_rows: list[tuple[float, ...]] = []
        for row in self.values:
            if not isinstance(row, tuple) or len(row) != len(azimuths):
                raise ValueError("values must be a rectangular tuple matrix matching the grids")
            normalized_rows.append(tuple(_fraction(value, "table value") for value in row))
        if np.isclose(azimuths[0], -180.0, atol=_TOLERANCE, rtol=0.0) and np.isclose(
            azimuths[-1], 180.0, atol=_TOLERANCE, rtol=0.0
        ):
            for row in normalized_rows:
                if not np.isclose(row[0], row[-1], atol=_TOLERANCE, rtol=0.0):
                    raise ValueError("PVsyst -180/+180 seam values must agree")

    @property
    def beam_transmission_values(self) -> tuple[tuple[float, ...], ...]:
        """Return canonical beam transmission without mutating supplied values."""
        if self.value_semantics == "transmission_fraction":
            return tuple(tuple(float(value) for value in row) for row in self.values)
        return tuple(tuple(1.0 - float(value) for value in row) for row in self.values)


@dataclass(frozen=True)
class PVsystLinearShadingDiagnostics:
    timestamp_count: int
    resolved_count: int
    not_applicable_count: int
    table_id: str
    model: str


@dataclass(frozen=True)
class PVsystLinearShadingResult:
    shading: pd.DataFrame
    diagnostics: PVsystLinearShadingDiagnostics


def convert_pvlib_azimuth_to_pvsyst(
    solar_azimuth_deg: pd.Series, *, hemisphere: PVsystHemisphere
) -> pd.Series:
    """Convert meteorological pvlib azimuth to PVsyst's signed convention."""
    _angle_series(solar_azimuth_deg, "solar_azimuth_deg", 0.0, 360.0, upper_open=True)
    if hemisphere not in ("north", "south"):
        raise ValueError("hemisphere must be 'north' or 'south'")
    values = solar_azimuth_deg.to_numpy(dtype=float)
    relative = values - 180.0 if hemisphere == "north" else -values
    wrapped = (relative + 180.0) % 360.0 - 180.0
    return pd.Series(wrapped, index=solar_azimuth_deg.index, name="pvsyst_solar_azimuth_deg")


def evaluate_pvsyst_linear_beam_shading(
    table: PVsystLinearShadingTable,
    solar_elevation_deg: pd.Series,
    solar_azimuth_deg: pd.Series,
    *,
    hemisphere: PVsystHemisphere,
) -> PVsystLinearShadingResult:
    """Evaluate canonical beam transmission by circular bilinear interpolation."""
    if not isinstance(table, PVsystLinearShadingTable):
        raise ValueError("table must be PVsystLinearShadingTable")
    _angle_series(solar_elevation_deg, "solar_elevation_deg", -90.0, 90.0)
    _angle_series(solar_azimuth_deg, "solar_azimuth_deg", 0.0, 360.0, upper_open=True)
    if not solar_elevation_deg.index.equals(solar_azimuth_deg.index) or (
        solar_elevation_deg.index.name != solar_azimuth_deg.index.name
    ):
        raise ValueError("solar elevation and azimuth indexes must match exactly")
    pvsyst_azimuth = convert_pvlib_azimuth_to_pvsyst(
        solar_azimuth_deg, hemisphere=hemisphere
    )
    rows: list[dict[str, object]] = []
    not_applicable = 0
    heights = np.asarray(table.sun_height_deg, dtype=float)
    azimuths, transmissions = _periodic_table(table)
    for timestamp in solar_elevation_deg.index:
        elevation = float(solar_elevation_deg.loc[timestamp])
        azimuth = float(solar_azimuth_deg.loc[timestamp])
        pvsyst_angle = float(pvsyst_azimuth.loc[timestamp])
        resolved = False
        transmission = np.nan
        if elevation <= 0.0:
            state = "not_applicable_no_above_horizon_beam"
            not_applicable += 1
        elif elevation < heights[0] - _TOLERANCE or elevation > heights[-1] + _TOLERANCE:
            state = "unresolved_outside_table_height_domain"
        else:
            clipped_height = float(np.clip(elevation, heights[0], heights[-1]))
            transmission = _bilinear(
                clipped_height, pvsyst_angle, heights, azimuths, transmissions
            )
            if transmission < -_TOLERANCE or transmission > 1.0 + _TOLERANCE:
                raise RuntimeError("interpolated transmission is outside physical bounds")
            transmission = float(np.clip(transmission, 0.0, 1.0))
            resolved = True
            state = "resolved"
        rows.append(
            {
                "solar_elevation_deg": elevation,
                "solar_azimuth_deg": azimuth,
                "pvsyst_solar_azimuth_deg": pvsyst_angle,
                "pvsyst_beam_transmission_fraction": transmission,
                "pvsyst_beam_shaded_fraction": 1.0 - transmission if resolved else np.nan,
                "pvsyst_linear_shading_resolved": resolved,
                "pvsyst_linear_shading_state": state,
                "pvsyst_table_id": table.table_id,
                "pvsyst_orientation_id": table.orientation_id,
                "pvsyst_zone_id": table.zone_id,
                "pvsyst_input_value_semantics": table.value_semantics,
                "pvsyst_version": table.pvsyst_version,
                "pvsyst_source_label": table.source_label,
                "pvsyst_source_reference": table.source_reference,
                "pvsyst_linear_shading_contract": PVSYST_LINEAR_SHADING_CONTRACT_ID,
                "pvsyst_linear_shading_model": PVSYST_LINEAR_SHADING_MODEL_ID,
                "pvsyst_linear_shading_coverage_scope": PVSYST_LINEAR_SHADING_COVERAGE_SCOPE,
                "pvsyst_linear_shading_scope": PVSYST_LINEAR_SHADING_SCOPE,
            }
        )
    frame = pd.DataFrame(rows, index=solar_elevation_deg.index, columns=_OUTPUT_COLUMNS)
    frame = _typed(frame)
    if tuple(frame.columns) != _OUTPUT_COLUMNS:
        raise RuntimeError("PVsyst shading output schema changed unexpectedly")
    resolved_count = int(frame["pvsyst_linear_shading_resolved"].sum()) if len(frame) else 0
    return PVsystLinearShadingResult(
        frame,
        PVsystLinearShadingDiagnostics(
            len(frame),
            resolved_count,
            not_applicable,
            table.table_id,
            PVSYST_LINEAR_SHADING_MODEL_ID,
        ),
    )


def _grid(value: object, name: str, lower: float, upper: float) -> tuple[float, ...]:
    if not isinstance(value, tuple) or len(value) < 2:
        raise ValueError(f"{name} must be a tuple with at least two entries")
    result = tuple(_bounded_real(item, name, lower, upper) for item in value)
    if any(right <= left for left, right in zip(result, result[1:], strict=False)):
        raise ValueError(f"{name} must be strictly increasing and unique")
    return result


def _periodic_table(
    table: PVsystLinearShadingTable,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    azimuths = np.asarray(table.pvsyst_solar_azimuth_deg, dtype=float)
    values = np.asarray(table.beam_transmission_values, dtype=float)
    if np.isclose(azimuths[0], -180.0, atol=_TOLERANCE, rtol=0.0) and np.isclose(
        azimuths[-1], 180.0, atol=_TOLERANCE, rtol=0.0
    ):
        azimuths = azimuths[:-1]
        values = values[:, :-1]
    periodic_azimuths = np.concatenate((azimuths, (azimuths[0] + 360.0,)))
    periodic_values = np.concatenate((values, values[:, :1]), axis=1)
    return periodic_azimuths, periodic_values


def _bilinear(
    height: float,
    azimuth: float,
    heights: NDArray[np.float64],
    azimuths: NDArray[np.float64],
    values: NDArray[np.float64],
) -> float:
    wrapped = azimuth
    while wrapped < azimuths[0]:
        wrapped += 360.0
    while wrapped > azimuths[-1]:
        wrapped -= 360.0
    height_upper = int(np.searchsorted(heights, height, side="right"))
    height_upper = min(max(height_upper, 1), len(heights) - 1)
    height_lower = height_upper - 1
    azimuth_upper = int(np.searchsorted(azimuths, wrapped, side="right"))
    azimuth_upper = min(max(azimuth_upper, 1), len(azimuths) - 1)
    azimuth_lower = azimuth_upper - 1
    height_span = heights[height_upper] - heights[height_lower]
    azimuth_span = azimuths[azimuth_upper] - azimuths[azimuth_lower]
    height_weight = (height - heights[height_lower]) / height_span
    azimuth_weight = (wrapped - azimuths[azimuth_lower]) / azimuth_span
    lower = values[height_lower, azimuth_lower] * (1.0 - azimuth_weight) + values[
        height_lower, azimuth_upper
    ] * azimuth_weight
    upper = values[height_upper, azimuth_lower] * (1.0 - azimuth_weight) + values[
        height_upper, azimuth_upper
    ] * azimuth_weight
    return float(lower * (1.0 - height_weight) + upper * height_weight)


def _angle_series(
    value: object, name: str, lower: float, upper: float, *, upper_open: bool = False
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


def _fraction(value: object, name: str) -> float:
    return _bounded_real(value, name, 0.0, 1.0)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = _OUTPUT_COLUMNS[:5]
    for column in numeric:
        frame[column] = frame[column].astype(float)
    frame["pvsyst_linear_shading_resolved"] = frame[
        "pvsyst_linear_shading_resolved"
    ].astype(bool)
    for column in _OUTPUT_COLUMNS[6:]:
        frame[column] = frame[column].astype("string")
    return frame
