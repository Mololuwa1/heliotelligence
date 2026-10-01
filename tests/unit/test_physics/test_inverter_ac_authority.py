"""Tests for S9-4A explicit inverter AC capability authority."""

from __future__ import annotations

import copy
import importlib
import inspect
import math
from dataclasses import FrozenInstanceError

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import (
    ElectricalTopologyConfig,
    InverterUnitConfig,
    MPPTConfig,
    StringConfig,
)
from heliotelligence.physics.inverter_ac_authority import (
    TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_MODEL_ID,
    TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_SCOPE,
    InverterAcCapabilityAuthority,
    resolve_topology_inverter_ac_capability_authority,
)


def _topology(*ids: str) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inverter_id,
                group_id="misleading-group",
                model_ref="misleading-cec-model",
                mppts=[
                    MPPTConfig(
                        id="mppt-1",
                        strings=[StringConfig(id=f"string-{inverter_id}", modules_per_string=24)],
                    )
                ],
            )
            for inverter_id in ids
        ]
    )


def _authority(
    *,
    voltage: float = 400.0,
    basis: str = "line_to_line",
    phase: str = "three_phase",
    apparent: float = 7000.0,
    q_min: float | None = None,
    q_max: float | None = None,
) -> InverterAcCapabilityAuthority:
    return InverterAcCapabilityAuthority(
        nominal_ac_voltage_v=voltage,
        ac_voltage_basis=basis,  # type: ignore[arg-type]
        phase_configuration=phase,  # type: ignore[arg-type]
        rated_apparent_power_va=apparent,
        reactive_power_min_var=q_min,
        reactive_power_max_var=q_max,
        parameter_source="manufacturer_datasheet:test",
        confidence="high",
    )


def test_resolved_authority_and_exact_schema() -> None:
    result = resolve_topology_inverter_ac_capability_authority(
        _topology("inverter-1"), {"inverter-1": _authority()}
    )
    row = result.states.loc["inverter-1"]
    assert row["ac_capability_authority_state"] == ("resolved_explicit_ac_capability_authority")
    assert row["nominal_ac_voltage_v"] == 400.0
    assert row["rated_apparent_power_va"] == 7000.0
    assert not row["fixed_reactive_power_limits_resolved"]
    assert row["topology_inverter_ac_capability_authority_contract"] == (
        TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_CONTRACT_ID
    )
    assert row["topology_inverter_ac_capability_authority_model"] == (
        TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_MODEL_ID
    )
    assert row["topology_inverter_ac_capability_authority_scope"] == (
        TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_SCOPE
    )
    assert row["topology_inverter_ac_capability_authority_coverage_scope"] == (
        TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_COVERAGE_SCOPE
    )
    assert result.states.index.names == ["inverter_id"]
    assert result.states["ac_capability_authority_resolved"].dtype == bool


def test_topology_order_and_mapping_order_independence() -> None:
    topology = _topology("inverter-b", "inverter-a")
    mapping = {
        "inverter-a": _authority(voltage=230.0, basis="line_to_neutral"),
        "inverter-b": _authority(),
    }
    first = resolve_topology_inverter_ac_capability_authority(topology, mapping)
    second = resolve_topology_inverter_ac_capability_authority(
        topology, dict(reversed(list(mapping.items())))
    )
    assert first.states.index.tolist() == ["inverter-b", "inverter-a"]
    pd.testing.assert_frame_equal(first.states, second.states, check_exact=True)
    assert first.diagnostics == second.diagnostics


def test_missing_and_mixed_authority_are_explicit() -> None:
    topology = _topology("resolved", "missing")
    result = resolve_topology_inverter_ac_capability_authority(topology, {"resolved": _authority()})
    missing = result.states.loc["missing"]
    assert not missing["ac_capability_authority_resolved"]
    assert missing["ac_capability_authority_state"] == (
        "unresolved_no_explicit_ac_capability_authority"
    )
    assert math.isnan(missing["nominal_ac_voltage_v"])
    assert math.isnan(missing["rated_apparent_power_va"])
    assert result.diagnostics.resolved_inverter_count == 1
    assert result.diagnostics.unresolved_inverter_count == 1


def test_no_inference_from_topology_or_other_inverter_metadata() -> None:
    topology = _topology("inverter-with-plausible-metadata")
    result = resolve_topology_inverter_ac_capability_authority(topology, {})
    row = result.states.iloc[0]
    assert row["ac_capability_authority_state"] == (
        "unresolved_no_explicit_ac_capability_authority"
    )
    assert row["ac_voltage_basis"] == ""
    assert row["phase_configuration"] == ""
    source = inspect.getsource(
        importlib.import_module("heliotelligence.physics.inverter_ac_authority")
    )
    for forbidden in (
        "Paco",
        "Vac",
        "pnom_kwac",
        "grid_limit_kwac",
        "model_ref",
        "retrieve_sam",
        "wiring_loss_ac_pct",
    ):
        assert forbidden not in source


@pytest.mark.parametrize(
    ("basis", "phase"),
    [
        ("line_to_line", "three_phase"),
        ("line_to_neutral", "three_phase"),
        ("single_phase_terminal", "single_phase"),
    ],
)
def test_supported_voltage_and_phase_authorities(basis: str, phase: str) -> None:
    authority = _authority(basis=basis, phase=phase)
    assert authority.ac_voltage_basis == basis
    assert authority.phase_configuration == phase


def test_three_phase_single_phase_terminal_is_rejected() -> None:
    with pytest.raises(ValueError, match="three_phase"):
        _authority(basis="single_phase_terminal", phase="three_phase")


@pytest.mark.parametrize(
    ("basis", "phase"),
    [
        ("line_to_line", "three_phase"),
        ("line_to_neutral", "three_phase"),
        ("single_phase_terminal", "single_phase"),
    ],
)
def test_phase_voltage_basis_compatible_pairs_are_accepted(basis: str, phase: str) -> None:
    assert _authority(basis=basis, phase=phase).phase_configuration == phase


@pytest.mark.parametrize("field", ["voltage", "apparent"])
@pytest.mark.parametrize("value", [0.0, -1.0, True, False, float("nan"), float("inf")])
def test_positive_finite_core_values_required(field: str, value: object) -> None:
    kwargs: dict[str, object] = {field: value}
    with pytest.raises(ValueError):
        _authority(**kwargs)  # type: ignore[arg-type]


def test_missing_q_and_explicit_zero_q_are_distinct() -> None:
    topology = _topology("missing-q", "zero-q")
    result = resolve_topology_inverter_ac_capability_authority(
        topology,
        {
            "missing-q": _authority(),
            "zero-q": _authority(q_min=0.0, q_max=0.0),
        },
    )
    missing = result.states.loc["missing-q"]
    zero = result.states.loc["zero-q"]
    assert not missing["fixed_reactive_power_limits_resolved"]
    assert math.isnan(missing["reactive_power_min_var"])
    assert zero["fixed_reactive_power_limits_resolved"]
    assert zero["reactive_power_min_var"] == 0.0
    assert zero["reactive_power_max_var"] == 0.0


@pytest.mark.parametrize(
    ("q_min", "q_max"),
    [(-3000.0, 3000.0), (-2500.0, 1000.0), (100.0, 500.0)],
)
def test_valid_fixed_q_ranges(q_min: float, q_max: float) -> None:
    authority = _authority(q_min=q_min, q_max=q_max)
    assert authority.reactive_power_min_var == q_min
    assert authority.reactive_power_max_var == q_max


@pytest.mark.parametrize(
    ("q_min", "q_max"),
    [(0.0, None), (None, 0.0), (2.0, 1.0), (-7001.0, 0.0), (0.0, 7001.0)],
)
def test_invalid_q_ranges_rejected(q_min: float | None, q_max: float | None) -> None:
    with pytest.raises(ValueError):
        _authority(q_min=q_min, q_max=q_max)


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("boundary", ["q_min", "q_max"])
def test_nonfinite_and_boolean_q_boundaries_rejected(boundary: str, value: object) -> None:
    values: dict[str, object] = {"q_min": 0.0, "q_max": 0.0, boundary: value}
    with pytest.raises(ValueError):
        _authority(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"basis": "phase_guess"},
        {"phase": "two_phase"},
    ],
)
def test_invalid_enums_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _authority(**kwargs)  # type: ignore[arg-type]


def test_invalid_source_confidence_and_loose_authority_rejected() -> None:
    with pytest.raises(ValueError):
        InverterAcCapabilityAuthority(400.0, "line_to_line", "three_phase", 7000.0)
    with pytest.raises(ValueError):
        InverterAcCapabilityAuthority(
            400.0,
            "line_to_line",
            "three_phase",
            7000.0,
            parameter_source="test",
            confidence="certain",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        resolve_topology_inverter_ac_capability_authority(
            _topology("inverter-1"),
            {"inverter-1": {}},  # type: ignore[dict-item]
        )


def test_unexpected_id_and_empty_topology() -> None:
    with pytest.raises(ValueError, match="unexpected"):
        resolve_topology_inverter_ac_capability_authority(
            _topology("inverter-1"), {"inverter-z": _authority()}
        )
    result = resolve_topology_inverter_ac_capability_authority(ElectricalTopologyConfig(), {})
    assert result.states.empty
    assert result.states.index.names == ["inverter_id"]
    assert result.diagnostics.inverter_count == 0


def test_empty_and_populated_results_have_identical_column_dtypes() -> None:
    empty = resolve_topology_inverter_ac_capability_authority(ElectricalTopologyConfig(), {})
    populated = resolve_topology_inverter_ac_capability_authority(
        _topology("inverter-1"), {"inverter-1": _authority()}
    )
    assert empty.states.dtypes.to_dict() == populated.states.dtypes.to_dict()
    for column in (
        "nominal_ac_voltage_v",
        "rated_apparent_power_va",
        "reactive_power_min_var",
        "reactive_power_max_var",
    ):
        assert str(populated.states[column].dtype) == "float64"
    for column in (
        "fixed_reactive_power_limits_resolved",
        "ac_capability_authority_resolved",
    ):
        assert str(populated.states[column].dtype) == "bool"


def test_diagnostics_closure_immutability_and_output_ownership() -> None:
    topology = _topology("single", "three")
    mapping = {
        "single": _authority(basis="single_phase_terminal", phase="single_phase"),
        "three": _authority(q_min=-1000.0, q_max=2000.0),
    }
    topology_before = copy.deepcopy(topology)
    mapping_before = dict(mapping)
    result = resolve_topology_inverter_ac_capability_authority(topology, mapping)
    diagnostics = result.diagnostics
    assert diagnostics.resolved_inverter_count + diagnostics.unresolved_inverter_count == 2
    assert (
        diagnostics.fixed_q_limit_authority_count + diagnostics.no_fixed_q_limit_authority_count
        == 2
    )
    assert diagnostics.single_phase_count + diagnostics.three_phase_count == 2
    assert diagnostics.authority_model == TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_MODEL_ID
    assert topology == topology_before
    assert mapping == mapping_before
    with pytest.raises(TypeError):
        result.authorities_by_inverter_id["new"] = _authority()  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.diagnostics.inverter_count = 99  # type: ignore[misc]
    result.states.iloc[0, 0] = 999.0
    repeated = resolve_topology_inverter_ac_capability_authority(topology, mapping)
    assert repeated.states.iloc[0]["nominal_ac_voltage_v"] != 999.0


def test_module_has_no_operating_or_network_physics() -> None:
    source = inspect.getsource(
        importlib.import_module("heliotelligence.physics.inverter_ac_authority")
    )
    for forbidden in (
        "import pvlib",
        "power_factor",
        "ac_current",
        "math.sqrt",
        "numpy.sqrt",
        "calculate_sandia",
        "operating_points",
    ):
        assert forbidden not in source
