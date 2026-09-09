"""Resolve horizontal irradiance components without fabricating missing data.

GHI-only rows are decomposed by pvlib's Erbs implementation using true solar
zenith. Complete supplied triplets are preserved, while every other incomplete
combination remains explicitly unresolved. This primitive is dormant from the
production irradiance and weather-query paths.
"""

from __future__ import annotations

from numbers import Real

import numpy as np
import pandas as pd
import pvlib.irradiance

_OUTPUT_COLUMNS = [
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "solar_zenith_deg",
    "direct_horizontal_wm2",
    "closure_residual_wm2",
    "irradiance_components_resolved",
    "decomposition_applied",
    "component_resolution_state",
    "decomposition_model",
    "ghi_provenance",
    "dhi_provenance",
    "dni_provenance",
]


def resolve_horizontal_irradiance_components(
    ghi_wm2: pd.Series,
    dhi_wm2: pd.Series,
    dni_wm2: pd.Series,
    solar_zenith_deg: pd.Series,
) -> pd.DataFrame:
    """Resolve supplied horizontal irradiance or apply Erbs to GHI-only rows."""
    inputs = (ghi_wm2, dhi_wm2, dni_wm2, solar_zenith_deg)
    _validate_inputs(inputs)
    index = ghi_wm2.index
    if len(index) == 0:
        return _empty_result(index)

    ghi = _numeric_irradiance(ghi_wm2)
    dhi = _numeric_irradiance(dhi_wm2)
    dni = _numeric_irradiance(dni_wm2)
    zenith = solar_zenith_deg.astype(float).copy()

    ghi_present = ghi.notna()
    dhi_present = dhi.notna()
    dni_present = dni.notna()
    complete = ghi_present & dhi_present & dni_present
    ghi_only = ghi_present & ~dhi_present & ~dni_present
    all_missing = ~ghi_present & ~dhi_present & ~dni_present

    if ghi_only.any():
        erbs = pvlib.irradiance.erbs(
            ghi.loc[ghi_only],
            zenith.loc[ghi_only],
            index[ghi_only],
        )
        dhi.loc[ghi_only] = erbs["dhi"]
        dni.loc[ghi_only] = erbs["dni"]

    resolved = complete | ghi_only
    direct_horizontal = pd.Series(np.nan, index=index, dtype=float)
    closure_residual = pd.Series(np.nan, index=index, dtype=float)
    projection = np.maximum(np.cos(np.deg2rad(zenith.loc[resolved])), 0.0)
    direct_horizontal.loc[resolved] = dni.loc[resolved] * projection
    closure_residual.loc[resolved] = (
        ghi.loc[resolved] - dhi.loc[resolved] - direct_horizontal.loc[resolved]
    )

    state = pd.Series("unresolved_partial_input", index=index, dtype=str)
    state.loc[complete] = "supplied_complete"
    state.loc[ghi_only] = "erbs_decomposed"
    state.loc[all_missing] = "unresolved_all_missing"

    model = pd.Series("not_applied", index=index, dtype=str)
    model.loc[ghi_only] = "erbs"
    supplied_or_missing = lambda present: pd.Series(  # noqa: E731
        np.where(present, "supplied", "missing"), index=index, dtype=str
    )
    ghi_provenance = supplied_or_missing(ghi_present)
    dhi_provenance = supplied_or_missing(dhi_present)
    dni_provenance = supplied_or_missing(dni_present)
    dhi_provenance.loc[ghi_only] = "erbs_from_ghi"
    dni_provenance.loc[ghi_only] = "erbs_from_ghi"

    return pd.DataFrame(
        {
            "ghi_wm2": ghi,
            "dhi_wm2": dhi,
            "dni_wm2": dni,
            "solar_zenith_deg": zenith,
            "direct_horizontal_wm2": direct_horizontal,
            "closure_residual_wm2": closure_residual,
            "irradiance_components_resolved": resolved.astype(bool),
            "decomposition_applied": ghi_only.astype(bool),
            "component_resolution_state": state,
            "decomposition_model": model,
            "ghi_provenance": ghi_provenance,
            "dhi_provenance": dhi_provenance,
            "dni_provenance": dni_provenance,
        },
        index=index,
        columns=_OUTPUT_COLUMNS,
    )


def _validate_inputs(inputs: tuple[object, object, object, object]) -> None:
    names = ("ghi_wm2", "dhi_wm2", "dni_wm2", "solar_zenith_deg")
    for value, name in zip(inputs, names, strict=True):
        if not isinstance(value, pd.Series):
            raise ValueError(f"{name} must be a pandas Series")

    series = inputs
    for value, name in zip(series, names, strict=True):
        _validate_index(value.index, name)  # type: ignore[union-attr]

    index = series[0].index  # type: ignore[union-attr]
    if any(
        not value.index.equals(index) or value.index.name != index.name
        for value in series[1:]  # type: ignore[union-attr]
    ):
        raise ValueError(
            "input Series indexes must match exactly; index names must match exactly"
        )

    for value, name in zip(series[:3], names[:3], strict=True):
        _validate_irradiance(value, name)  # type: ignore[arg-type]
    _validate_zenith(series[3])  # type: ignore[arg-type]


def _validate_index(index: pd.Index, series_name: str) -> None:
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError(f"{series_name} index must be a pandas DatetimeIndex")
    if index.tz is None:
        raise ValueError(f"{series_name} index must be timezone-aware")
    if index.hasnans:
        raise ValueError(f"{series_name} index must not contain NaT")
    if index.has_duplicates:
        raise ValueError(f"{series_name} index must not contain duplicate timestamps")


def _validate_irradiance(series: pd.Series, name: str) -> None:
    for value in series.array:
        if pd.isna(value):
            continue
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise ValueError(f"{name} present values must be finite real numbers")
        if not np.isfinite(value):
            raise ValueError(f"{name} present values must be finite real numbers")
        if value < 0:
            raise ValueError(f"{name} present values must be non-negative")


def _validate_zenith(series: pd.Series) -> None:
    for value in series.array:
        if (
            pd.isna(value)
            or isinstance(value, (bool, np.bool_))
            or not isinstance(value, Real)
            or not np.isfinite(value)
        ):
            raise ValueError("solar_zenith_deg values must be finite real numbers")
        if value < 0 or value > 180:
            raise ValueError("solar_zenith_deg values must be between 0 and 180")


def _numeric_irradiance(series: pd.Series) -> pd.Series:
    return pd.Series(
        (np.nan if pd.isna(value) else float(value) for value in series.array),
        index=series.index,
        dtype=float,
    )


def _empty_result(index: pd.DatetimeIndex) -> pd.DataFrame:
    float_columns = _OUTPUT_COLUMNS[:6]
    bool_columns = _OUTPUT_COLUMNS[6:8]
    string_columns = _OUTPUT_COLUMNS[8:]
    values = {
        **{name: pd.Series(index=index, dtype=float) for name in float_columns},
        **{name: pd.Series(index=index, dtype=bool) for name in bool_columns},
        **{name: pd.Series(index=index, dtype=str) for name in string_columns},
    }
    return pd.DataFrame(values, index=index, columns=_OUTPUT_COLUMNS)
