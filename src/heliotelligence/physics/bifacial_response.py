"""Canonical electrical rear-response coefficient resolution."""

from __future__ import annotations

from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

BIFACIAL_RESPONSE_CONTRACT_ID = "bifacial_electrical_response_parameters_v1"
BIFACIAL_RESPONSE_MODEL_ID = "iec_phi_isc_equivalent_irradiance_v1"
BIFACIAL_RESPONSE_COEFFICIENT_KIND = "phi_isc"
BIFACIAL_RESPONSE_STANDARD_BASIS = "iec_ts_60904_1_2_2024_amd1_2026"
BIFACIAL_RESPONSE_SCOPE = "rear_to_front_electrical_photocurrent_equivalence_only"
EQUIVALENT_IRRADIANCE_FORMULA = "front_plus_phi_isc_times_rear"

BifacialResponseResolutionMethod = Literal[
    "direct",
    "derived_stc_isc_ratio",
    "explicit_fallback",
    "monofacial_declared",
]

_METHODS = {
    "direct",
    "derived_stc_isc_ratio",
    "explicit_fallback",
    "monofacial_declared",
}
_OUTPUT_KEYS = (
    "bifacial_enabled",
    "isc_bifaciality_factor",
    "bifaciality_coefficient_kind",
    "resolution_method",
    "source_label",
    "source_reference",
    "is_fallback",
    "front_isc_stc_a",
    "rear_isc_stc_a",
    "derivation_note",
    "equivalent_irradiance_formula",
    "bifacial_response_contract",
    "bifacial_response_model",
    "bifacial_response_standard_basis",
    "bifacial_response_scope",
)


def resolve_bifacial_response_parameters(
    *,
    bifacial_enabled: bool,
    method: BifacialResponseResolutionMethod,
    source_label: str,
    source_reference: str | None = None,
    isc_bifaciality_factor: object | None = None,
    front_isc_stc_a: object | None = None,
    rear_isc_stc_a: object | None = None,
) -> dict[str, object]:
    """Resolve an explicit IEC phi_Isc coefficient without composing irradiance."""
    if type(bifacial_enabled) is not bool:
        raise ValueError("bifacial_enabled must be a Python bool")
    if not isinstance(method, str) or method not in _METHODS:
        raise ValueError("method is not a supported bifacial response resolution method")
    label = _nonempty_string(source_label, "source_label")
    reference = _reference(source_reference)

    factor: float
    front_current: float | None = None
    rear_current: float | None = None
    fallback = False

    if not bifacial_enabled:
        if method != "monofacial_declared":
            raise ValueError("disabled bifacial response requires monofacial_declared")
        _require_none(
            isc_bifaciality_factor,
            front_isc_stc_a,
            rear_isc_stc_a,
            message="monofacial declaration does not accept bifacial measurements",
        )
        factor = 0.0
        note = "rear electrical response disabled by explicit monofacial declaration"
    else:
        if method == "monofacial_declared":
            raise ValueError("bifacial modules cannot use monofacial_declared")
        if method in ("direct", "explicit_fallback"):
            if front_isc_stc_a is not None or rear_isc_stc_a is not None:
                raise ValueError(f"{method} accepts only isc_bifaciality_factor")
            factor = _factor(isc_bifaciality_factor)
            fallback = method == "explicit_fallback"
            note = (
                "explicit fallback phi_Isc supplied by caller"
                if fallback
                else "phi_Isc supplied directly"
            )
        elif method == "derived_stc_isc_ratio":
            if isc_bifaciality_factor is not None:
                raise ValueError("derived_stc_isc_ratio does not accept an explicit factor")
            front_current = _positive_current(front_isc_stc_a, "front_isc_stc_a")
            rear_current = _positive_current(rear_isc_stc_a, "rear_isc_stc_a")
            factor = _factor(rear_current / front_current)
            note = "phi_Isc derived as rear_isc_stc_a / front_isc_stc_a"
        else:  # pragma: no cover - exhaustive after validation
            raise AssertionError("unreachable resolution method")

    result: dict[str, object] = {
        "bifacial_enabled": bifacial_enabled,
        "isc_bifaciality_factor": factor,
        "bifaciality_coefficient_kind": BIFACIAL_RESPONSE_COEFFICIENT_KIND,
        "resolution_method": method,
        "source_label": label,
        "source_reference": reference,
        "is_fallback": fallback,
        "front_isc_stc_a": front_current,
        "rear_isc_stc_a": rear_current,
        "derivation_note": note,
        "equivalent_irradiance_formula": EQUIVALENT_IRRADIANCE_FORMULA,
        "bifacial_response_contract": BIFACIAL_RESPONSE_CONTRACT_ID,
        "bifacial_response_model": BIFACIAL_RESPONSE_MODEL_ID,
        "bifacial_response_standard_basis": BIFACIAL_RESPONSE_STANDARD_BASIS,
        "bifacial_response_scope": BIFACIAL_RESPONSE_SCOPE,
    }
    if tuple(result) != _OUTPUT_KEYS:
        raise RuntimeError("bifacial response output schema is unstable")
    return result


def _factor(value: object) -> float:
    result = _real(value, "isc_bifaciality_factor")
    if result <= 0.0 or result > 1.0:
        raise ValueError("bifacial phi_Isc must satisfy 0 < factor <= 1")
    return result


def _positive_current(value: object, name: str) -> float:
    result = _real(value, name)
    if result <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return result


def _real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite non-Boolean real")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _reference(value: object) -> str | None:
    if value is None:
        return None
    if pd.isna(value) or not isinstance(value, str) or not value.strip():
        raise ValueError("source_reference must be None or a non-empty string")
    return value


def _require_none(*values: object, message: str) -> None:
    if any(value is not None for value in values):
        raise ValueError(message)
