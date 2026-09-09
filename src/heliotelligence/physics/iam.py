"""Front-surface direct-beam incidence-angle modifiers from pvlib.

This dormant optical primitive consumes AOI from R2 and delegates to one
explicitly selected pvlib beam-IAM model.  It does not apply the factor to
irradiance or model diffuse light, shading, bifacial response, temperature, or
electrical conversion.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd
import pvlib.iam

BeamIAMModel = Literal["physical", "martin-ruiz", "ashrae"]

_OUTPUT_COLUMNS = [
    "aoi_deg",
    "beam_iam_factor",
    "beam_iam_resolved",
    "beam_iam_state",
    "beam_iam_model",
]
_PARAMETER_KEYS = {
    "physical": frozenset({"n", "K", "L", "n_ar"}),
    "martin-ruiz": frozenset({"a_r"}),
    "ashrae": frozenset({"b"}),
}


def calculate_beam_iam(
    aoi_deg: pd.Series,
    *,
    model: BeamIAMModel,
    model_parameters: Mapping[str, object],
) -> pd.DataFrame:
    """Calculate a front-surface direct-beam IAM factor for each AOI."""
    _validate_aoi(aoi_deg)
    parameters = _validate_model_parameters(model, model_parameters)

    index = aoi_deg.index
    if index.empty:
        return _empty_result(index)

    aoi = aoi_deg.astype(float).copy()
    if model == "physical":
        iam = pvlib.iam.physical(
            aoi,
            n=parameters["n"],
            K=parameters["K"],
            L=parameters["L"],
            n_ar=parameters["n_ar"],
        )
    elif model == "martin-ruiz":
        iam = pvlib.iam.martin_ruiz(aoi, a_r=parameters["a_r"])
    else:
        iam = pvlib.iam.ashrae(aoi, b=parameters["b"])

    factor = pd.Series(iam, index=index, dtype=float)
    resolved = pd.Series(np.isfinite(factor), index=index, dtype=bool)
    state = pd.Series("model_output_unresolved", index=index, dtype=str)
    state.loc[resolved] = "resolved"

    return pd.DataFrame(
        {
            "aoi_deg": aoi,
            "beam_iam_factor": factor,
            "beam_iam_resolved": resolved,
            "beam_iam_state": state,
            "beam_iam_model": pd.Series(model, index=index, dtype=str),
        },
        index=index,
        columns=_OUTPUT_COLUMNS,
    )


def _validate_aoi(aoi_deg: object) -> None:
    if not isinstance(aoi_deg, pd.Series):
        raise ValueError("aoi_deg must be a pandas Series")
    index = aoi_deg.index
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("aoi_deg index must be a pandas DatetimeIndex")
    if index.tz is None:
        raise ValueError("aoi_deg index must be timezone-aware")
    if index.hasnans:
        raise ValueError("aoi_deg index must not contain NaT")
    if index.has_duplicates:
        raise ValueError("aoi_deg index must not contain duplicate timestamps")

    for value in aoi_deg.array:
        if (
            pd.isna(value)
            or isinstance(value, (bool, np.bool_))
            or not isinstance(value, Real)
            or not np.isfinite(value)
        ):
            raise ValueError("aoi_deg values must be finite real numbers")
        if value < 0.0 or value > 180.0:
            raise ValueError("aoi_deg values must be between 0 and 180")


def _validate_model_parameters(
    model: object,
    model_parameters: object,
) -> dict[str, object]:
    if not isinstance(model, str) or model not in _PARAMETER_KEYS:
        raise ValueError("model must be 'physical', 'martin-ruiz', or 'ashrae'")
    if not isinstance(model_parameters, Mapping):
        raise ValueError("model_parameters must be a mapping")

    expected = _PARAMETER_KEYS[model]
    actual = set(model_parameters)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing keys: " + ", ".join(missing))
        if extra:
            details.append("extra keys: " + ", ".join(extra))
        raise ValueError(
            f"model_parameters for {model} must contain exactly "
            f"{sorted(expected)} ({'; '.join(details)})"
        )

    parameters = dict(model_parameters)
    if model == "physical":
        _validate_parameter(parameters["n"], "n", allow_zero=False)
        _validate_parameter(parameters["K"], "K", allow_zero=True)
        _validate_parameter(parameters["L"], "L", allow_zero=True)
        if parameters["n_ar"] is not None:
            _validate_parameter(parameters["n_ar"], "n_ar", allow_zero=False)
    elif model == "martin-ruiz":
        _validate_parameter(parameters["a_r"], "a_r", allow_zero=False)
    else:
        _validate_parameter(parameters["b"], "b", allow_zero=True)
    return parameters


def _validate_parameter(value: object, name: str, *, allow_zero: bool) -> None:
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, Real)
        or not np.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite real number")
    if value < 0.0 or (not allow_zero and value == 0.0):
        comparison = "non-negative" if allow_zero else "greater than 0"
        raise ValueError(f"{name} must be {comparison}")


def _empty_result(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "aoi_deg": pd.Series(index=index, dtype=float),
            "beam_iam_factor": pd.Series(index=index, dtype=float),
            "beam_iam_resolved": pd.Series(index=index, dtype=bool),
            "beam_iam_state": pd.Series(index=index, dtype=str),
            "beam_iam_model": pd.Series(index=index, dtype=str),
        },
        index=index,
        columns=_OUTPUT_COLUMNS,
    )
