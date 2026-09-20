"""Tests for the canonical S7D-0 phi_Isc parameter contract."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ModuleConfig
from heliotelligence.physics.bifacial_response import (
    BIFACIAL_RESPONSE_COEFFICIENT_KIND,
    BIFACIAL_RESPONSE_CONTRACT_ID,
    BIFACIAL_RESPONSE_MODEL_ID,
    BIFACIAL_RESPONSE_SCOPE,
    BIFACIAL_RESPONSE_STANDARD_BASIS,
    EQUIVALENT_IRRADIANCE_FORMULA,
    resolve_bifacial_response_parameters,
)


def _direct(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "bifacial_enabled": True,
        "method": "direct",
        "source_label": "manufacturer IEC report",
        "source_reference": "report-42",
        "isc_bifaciality_factor": 0.8,
    }
    values.update(overrides)
    return resolve_bifacial_response_parameters(**values)  # type: ignore[arg-type]


def test_direct_contract_and_standard_provenance() -> None:
    result = _direct()
    assert result["isc_bifaciality_factor"] == 0.8
    assert result["bifaciality_coefficient_kind"] == BIFACIAL_RESPONSE_COEFFICIENT_KIND
    assert result["bifacial_response_contract"] == BIFACIAL_RESPONSE_CONTRACT_ID
    assert result["bifacial_response_model"] == BIFACIAL_RESPONSE_MODEL_ID
    assert result["bifacial_response_standard_basis"] == BIFACIAL_RESPONSE_STANDARD_BASIS
    assert result["bifacial_response_scope"] == BIFACIAL_RESPONSE_SCOPE
    assert result["equivalent_irradiance_formula"] == EQUIVALENT_IRRADIANCE_FORMULA
    assert result["is_fallback"] is False
    assert result["front_isc_stc_a"] is None
    assert result["rear_isc_stc_a"] is None


def test_derived_stc_isc_ratio_retains_current_provenance() -> None:
    result = resolve_bifacial_response_parameters(
        bifacial_enabled=True,
        method="derived_stc_isc_ratio",
        source_label="independent STC test",
        front_isc_stc_a=14.0,
        rear_isc_stc_a=11.2,
    )
    assert result["isc_bifaciality_factor"] == pytest.approx(0.8)
    assert result["front_isc_stc_a"] == 14.0
    assert result["rear_isc_stc_a"] == 11.2
    assert result["is_fallback"] is False


def test_explicit_fallback_and_monofacial() -> None:
    fallback = resolve_bifacial_response_parameters(
        bifacial_enabled=True,
        method="explicit_fallback",
        source_label="engineering fallback",
        isc_bifaciality_factor=0.75,
    )
    assert fallback["isc_bifaciality_factor"] == 0.75
    assert fallback["is_fallback"] is True
    monofacial = resolve_bifacial_response_parameters(
        bifacial_enabled=False,
        method="monofacial_declared",
        source_label="module declaration",
    )
    assert monofacial["isc_bifaciality_factor"] == 0.0
    assert monofacial["is_fallback"] is False


@pytest.mark.parametrize("bad", [0, 1, np.bool_(True), "True", None, np.nan])
def test_bifacial_enabled_requires_python_bool(bad: object) -> None:
    with pytest.raises(ValueError, match="Python bool"):
        _direct(bifacial_enabled=bad)


@pytest.mark.parametrize("bad", [True, False, 0, -0.1, 1.01, 80, np.nan, np.inf, -np.inf, "0.8"])
@pytest.mark.parametrize("method", ["direct", "explicit_fallback"])
def test_invalid_direct_and_fallback_factors(method: str, bad: object) -> None:
    with pytest.raises(ValueError, match="finite|factor|real"):
        _direct(method=method, isc_bifaciality_factor=bad)


@pytest.mark.parametrize("field", ["front_isc_stc_a", "rear_isc_stc_a"])
@pytest.mark.parametrize("bad", [True, 0, -1, np.nan, np.inf, "12"])
def test_invalid_derived_currents(field: str, bad: object) -> None:
    values: dict[str, object] = {
        "bifacial_enabled": True,
        "method": "derived_stc_isc_ratio",
        "source_label": "STC report",
        "front_isc_stc_a": 14.0,
        "rear_isc_stc_a": 11.2,
    }
    values[field] = bad
    with pytest.raises(ValueError, match="finite|positive|real"):
        resolve_bifacial_response_parameters(**values)  # type: ignore[arg-type]


def test_derived_ratio_above_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="factor"):
        resolve_bifacial_response_parameters(
            bifacial_enabled=True,
            method="derived_stc_isc_ratio",
            source_label="STC report",
            front_isc_stc_a=10.0,
            rear_isc_stc_a=11.0,
        )


@pytest.mark.parametrize(
    "values",
    [
        {"method": "direct", "front_isc_stc_a": 14.0},
        {
            "method": "derived_stc_isc_ratio",
            "isc_bifaciality_factor": 0.8,
            "front_isc_stc_a": 14.0,
            "rear_isc_stc_a": 11.2,
        },
        {"method": "explicit_fallback", "rear_isc_stc_a": 11.2},
        {"bifacial_enabled": True, "method": "monofacial_declared", "isc_bifaciality_factor": None},
        {"bifacial_enabled": False, "method": "direct"},
        {
            "bifacial_enabled": False,
            "method": "derived_stc_isc_ratio",
            "isc_bifaciality_factor": None,
            "front_isc_stc_a": 14.0,
            "rear_isc_stc_a": 11.2,
        },
        {"bifacial_enabled": False, "method": "explicit_fallback"},
        {"bifacial_enabled": False, "method": "monofacial_declared", "isc_bifaciality_factor": 0.8},
    ],
)
def test_method_and_input_exclusivity(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _direct(**values)


@pytest.mark.parametrize("bad", [None, "", "   ", 42])
def test_invalid_source_label(bad: object) -> None:
    with pytest.raises(ValueError, match="source_label"):
        _direct(source_label=bad)


@pytest.mark.parametrize("bad", ["", "   ", pd.NA, np.nan, 42])
def test_invalid_source_reference(bad: object) -> None:
    with pytest.raises(ValueError, match="source_reference"):
        _direct(source_reference=bad)


def test_none_source_reference_is_allowed() -> None:
    assert _direct(source_reference=None)["source_reference"] is None


def test_legacy_module_bifaciality_is_not_consumed() -> None:
    legacy = ModuleConfig(bifacial=True, bifaciality_factor=0.8)
    assert legacy.bifaciality_factor == 0.8
    with pytest.raises(ValueError):
        resolve_bifacial_response_parameters(
            bifacial_enabled=True,
            method="direct",
            source_label="explicit contract still required",
        )


@pytest.mark.parametrize(
    "result",
    [
        _direct(),
        resolve_bifacial_response_parameters(
            bifacial_enabled=True,
            method="derived_stc_isc_ratio",
            source_label="STC",
            front_isc_stc_a=14.0,
            rear_isc_stc_a=11.2,
        ),
        resolve_bifacial_response_parameters(
            bifacial_enabled=True,
            method="explicit_fallback",
            source_label="fallback",
            isc_bifaciality_factor=0.75,
        ),
        resolve_bifacial_response_parameters(
            bifacial_enabled=False,
            method="monofacial_declared",
            source_label="declaration",
        ),
    ],
)
def test_json_safe_deterministic_exact_schema(result: dict[str, object]) -> None:
    assert json.loads(json.dumps(result)) == result
    assert result == dict(result)
    assert not any("pmax" in key.lower() or "voc" in key.lower() for key in result)
    assert result["bifaciality_coefficient_kind"] == "phi_isc"
    for value in result.values():
        assert not isinstance(value, (np.generic, pd.api.extensions.ExtensionArray))


def test_repeated_calls_are_exactly_equal() -> None:
    assert _direct() == _direct()
