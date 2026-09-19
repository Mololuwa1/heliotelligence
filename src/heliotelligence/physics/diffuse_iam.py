"""Component-specific front diffuse IAM delegated to pvlib Marion integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real

import numpy as np
import pvlib.iam  # type: ignore[import-untyped]

from heliotelligence.physics.iam import BeamIAMModel, calculate_beam_iam

DIFFUSE_IAM_MODEL_ID = "pvlib_marion_component_diffuse_iam_v1"
_PVLIB_MODELS = {
    "physical": "physical",
    "ashrae": "ashrae",
    "martin-ruiz": "martin_ruiz",
}
_TOLERANCE = 1e-12


@dataclass(frozen=True)
class DiffuseIAMResult:
    diffuse_sky_iam_factor: float
    diffuse_horizon_iam_factor: float
    diffuse_ground_iam_factor: float
    resolved: bool
    model: str
    source_beam_iam_model: str


def calculate_diffuse_iam(
    *,
    surface_tilt_deg: float,
    beam_iam_model: BeamIAMModel,
    model_parameters: Mapping[str, object],
) -> DiffuseIAMResult:
    """Calculate Marion sky, horizon, and ground IAM from one beam-IAM family."""
    tilt = _bounded_real(surface_tilt_deg, "surface_tilt_deg", 0.0, 180.0)
    if beam_iam_model not in _PVLIB_MODELS:
        raise ValueError("beam_iam_model must be 'physical', 'martin-ruiz', or 'ashrae'")
    # Reuse the canonical parameter validation without duplicating its contract.
    import pandas as pd  # type: ignore[import-untyped]

    empty_index = pd.DatetimeIndex([], tz="UTC", name="time")
    calculate_beam_iam(
        pd.Series(index=empty_index, dtype=float),
        model=beam_iam_model,
        model_parameters=model_parameters,
    )
    values = pvlib.iam.marion_diffuse(_PVLIB_MODELS[beam_iam_model], tilt, **dict(model_parameters))
    factors = tuple(
        _validated_factor(values[name], f"diffuse {name} IAM")
        for name in ("sky", "horizon", "ground")
    )
    return DiffuseIAMResult(
        diffuse_sky_iam_factor=factors[0],
        diffuse_horizon_iam_factor=factors[1],
        diffuse_ground_iam_factor=factors[2],
        resolved=True,
        model=DIFFUSE_IAM_MODEL_ID,
        source_beam_iam_model=beam_iam_model,
    )


def _bounded_real(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be a finite real number")
    if result < minimum or result > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return result


def _validated_factor(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise RuntimeError(f"{name} must be a finite real number")
    result = float(value)
    if not np.isfinite(result):
        raise RuntimeError(f"{name} must be a finite real number")
    if result < -_TOLERANCE or result > 1.0 + _TOLERANCE:
        raise RuntimeError(f"{name} is outside [0, 1]")
    return float(np.clip(result, 0.0, 1.0))
