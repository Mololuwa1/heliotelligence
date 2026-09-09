"""Beam-IAM parameter derivation and provenance without source selection.

This dormant primitive validates caller-selected native or fallback parameters,
or delegates measured-profile fitting to :func:`pvlib.iam.fit`.  It does not
rank parameter sources, infer optical properties from electrical data, convert
IAM model families, or evaluate IAM against a time-series AOI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd
import pvlib.iam

BeamIAMModel = Literal["physical", "martin-ruiz", "ashrae"]
ResolutionMethod = Literal["direct", "measured_fit", "explicit_fallback"]

_MODEL_PARAMETER_KEYS = {
    "physical": frozenset({"n", "K", "L", "n_ar"}),
    "martin-ruiz": frozenset({"a_r"}),
    "ashrae": frozenset({"b"}),
}
_FIT_PARAMETER_KEYS = {
    "physical": frozenset({"n", "K", "L"}),
    "martin-ruiz": frozenset({"a_r"}),
    "ashrae": frozenset({"b"}),
}
_PVLIB_FIT_MODEL = {
    "physical": "physical",
    "martin-ruiz": "martin_ruiz",
    "ashrae": "ashrae",
}
_PHYSICAL_FIT_NOTE = "pvlib_physical_fit_does_not_fit_n_ar; n_ar set to None"


def resolve_beam_iam_parameters(
    *,
    model: BeamIAMModel,
    method: ResolutionMethod,
    source_label: str,
    source_reference: str | None = None,
    model_parameters: Mapping[str, object] | None = None,
    measured_aoi_deg: Sequence[object] | np.ndarray | pd.Series | None = None,
    measured_iam: Sequence[object] | np.ndarray | pd.Series | None = None,
) -> dict[str, object]:
    """Resolve R3A-compatible beam-IAM parameters with explicit provenance."""
    _validate_model(model)
    _validate_method(method)
    _validate_provenance(source_label, source_reference)

    if method in ("direct", "explicit_fallback"):
        if measured_aoi_deg is not None or measured_iam is not None:
            raise ValueError(f"{method} does not accept measured profile inputs")
        parameters = _validated_model_parameters(model, model_parameters)
        return _result(
            model=model,
            parameters=parameters,
            method=method,
            source_label=source_label,
            source_reference=source_reference,
            is_fallback=method == "explicit_fallback",
        )

    if model_parameters is not None:
        raise ValueError("measured_fit does not accept model_parameters")
    if measured_aoi_deg is None or measured_iam is None:
        raise ValueError("measured_fit requires measured_aoi_deg and measured_iam")

    measured_aoi = _validated_measurements(
        measured_aoi_deg, "measured_aoi_deg", minimum=0.0, maximum=90.0
    )
    measured_values = _validated_measurements(
        measured_iam, "measured_iam", minimum=0.0, maximum=None
    )
    if measured_aoi.size != measured_values.size:
        raise ValueError("measured_aoi_deg and measured_iam must have equal length")
    if measured_aoi.size < 2:
        raise ValueError("measured profiles must contain at least 2 samples")
    if np.unique(measured_aoi).size < 2:
        raise ValueError("measured_aoi_deg must contain at least 2 distinct values")

    try:
        fitted = pvlib.iam.fit(
            measured_aoi,
            measured_values,
            model_name=_PVLIB_FIT_MODEL[model],
        )
    except Exception as exc:
        raise ValueError(f"pvlib IAM fitting failed for model {model}") from exc
    if not isinstance(fitted, Mapping) or set(fitted) != _FIT_PARAMETER_KEYS[model]:
        raise ValueError(f"pvlib IAM fitting returned invalid parameters for {model}")

    fitted_parameters = dict(fitted)
    derivation_note = None
    if model == "physical":
        fitted_parameters["n_ar"] = None
        derivation_note = _PHYSICAL_FIT_NOTE
    parameters = _validated_model_parameters(model, fitted_parameters)

    predicted = _evaluate_model(model, measured_aoi, parameters)
    if not np.isfinite(predicted).all():
        raise ValueError(f"fitted {model} IAM curve contains non-finite values")
    residual = predicted - measured_values

    return _result(
        model=model,
        parameters=parameters,
        method=method,
        source_label=source_label,
        source_reference=source_reference,
        is_fallback=False,
        derivation_note=derivation_note,
        fit_sample_count=int(measured_aoi.size),
        fit_aoi_min_deg=float(np.min(measured_aoi)),
        fit_aoi_max_deg=float(np.max(measured_aoi)),
        fit_rmse=float(np.sqrt(np.mean(residual**2))),
        fit_mae=float(np.mean(np.abs(residual))),
        fit_max_abs_error=float(np.max(np.abs(residual))),
    )


def _validate_model(model: object) -> None:
    if not isinstance(model, str) or model not in _MODEL_PARAMETER_KEYS:
        raise ValueError("model must be 'physical', 'martin-ruiz', or 'ashrae'")


def _validate_method(method: object) -> None:
    if method not in ("direct", "measured_fit", "explicit_fallback"):
        raise ValueError(
            "method must be 'direct', 'measured_fit', or 'explicit_fallback'"
        )


def _validate_provenance(
    source_label: object, source_reference: object
) -> None:
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("source_label must be a non-empty string")
    if source_reference is not None and (
        not isinstance(source_reference, str) or not source_reference.strip()
    ):
        raise ValueError("source_reference must be None or a non-empty string")


def _validated_model_parameters(
    model: BeamIAMModel,
    model_parameters: object,
) -> dict[str, object]:
    if not isinstance(model_parameters, Mapping):
        raise ValueError("model_parameters must be a mapping")
    expected = _MODEL_PARAMETER_KEYS[model]
    actual = set(model_parameters)
    if actual != expected:
        raise ValueError(
            f"model_parameters for {model} must contain exactly {sorted(expected)}"
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

    return {key: _json_scalar(value) for key, value in parameters.items()}


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


def _validated_measurements(
    values: object,
    name: str,
    *,
    minimum: float,
    maximum: float | None,
) -> np.ndarray:
    if (
        isinstance(values, (str, bytes, Mapping, Real))
        or not isinstance(values, (Sequence, np.ndarray, pd.Series))
    ):
        raise ValueError(f"{name} must be a one-dimensional array-like input")
    array = np.asarray(values, dtype=object)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")

    validated: list[float] = []
    for value in array:
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, Real)
            or not np.isfinite(value)
        ):
            raise ValueError(f"{name} values must be finite real numbers")
        if value < minimum or (maximum is not None and value > maximum):
            if maximum is None:
                raise ValueError(f"{name} values must be non-negative")
            raise ValueError(f"{name} values must be between {minimum:g} and {maximum:g}")
        validated.append(float(value))
    return np.asarray(validated, dtype=float)


def _evaluate_model(
    model: BeamIAMModel,
    measured_aoi: np.ndarray,
    parameters: dict[str, object],
) -> np.ndarray:
    if model == "physical":
        predicted = pvlib.iam.physical(measured_aoi, **parameters)
    elif model == "martin-ruiz":
        predicted = pvlib.iam.martin_ruiz(measured_aoi, **parameters)
    else:
        predicted = pvlib.iam.ashrae(measured_aoi, **parameters)
    return np.asarray(predicted, dtype=float)


def _json_scalar(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    return value


def _result(
    *,
    model: BeamIAMModel,
    parameters: dict[str, object],
    method: ResolutionMethod,
    source_label: str,
    source_reference: str | None,
    is_fallback: bool,
    derivation_note: str | None = None,
    fit_sample_count: int | None = None,
    fit_aoi_min_deg: float | None = None,
    fit_aoi_max_deg: float | None = None,
    fit_rmse: float | None = None,
    fit_mae: float | None = None,
    fit_max_abs_error: float | None = None,
) -> dict[str, object]:
    return {
        "model": model,
        "model_parameters": parameters,
        "resolution_method": method,
        "source_label": source_label,
        "source_reference": source_reference,
        "is_fallback": is_fallback,
        "derivation_note": derivation_note,
        "fit_sample_count": fit_sample_count,
        "fit_aoi_min_deg": fit_aoi_min_deg,
        "fit_aoi_max_deg": fit_aoi_max_deg,
        "fit_rmse": fit_rmse,
        "fit_mae": fit_mae,
        "fit_max_abs_error": fit_max_abs_error,
    }
