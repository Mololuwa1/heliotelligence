"""Tests for S9-4B inverter P/Q/S capability-state evaluation."""

from __future__ import annotations

import importlib
import inspect
import math
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter_ac_authority import (
    InverterAcCapabilityAuthority,
    resolve_topology_inverter_ac_capability_authority,
)
from heliotelligence.physics.inverter_pqs_capability import (
    TOPOLOGY_INVERTER_PQS_CAPABILITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_PQS_CAPABILITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_PQS_CAPABILITY_MODEL_ID,
    TOPOLOGY_INVERTER_PQS_CAPABILITY_SCOPE,
    InverterReactivePowerRequest,
    calculate_topology_inverter_pqs_capability,
)

accounting_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_inverter_accounting"
)
conversion_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_inverter_conversion"
)
s91_support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_topology")


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        inverter_lookup, "_load_cec_inverter_database", conversion_support._database
    )
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        conversion_support._database,
    )


def _authority(
    smax: float = 5000.0,
    q_min: float | None = -4000.0,
    q_max: float | None = 4000.0,
) -> InverterAcCapabilityAuthority:
    return InverterAcCapabilityAuthority(
        nominal_ac_voltage_v=400.0,
        ac_voltage_basis="line_to_line",
        phase_configuration="three_phase",
        rated_apparent_power_va=smax,
        reactive_power_min_var=q_min,
        reactive_power_max_var=q_max,
        parameter_source="manufacturer:test",
        confidence="high",
    )


def _chain(
    topology: ElectricalTopologyConfig,
    *,
    current: float = 5.0,
    zero: bool = False,
) -> tuple[tuple[Any, ...], Any]:
    values, ac, potential = accounting_support._inputs(topology, current=current, zero=zero)
    accounting = accounting_support._call(topology, values, ac, potential)
    return (*values, ac, potential), accounting


def _run(
    topology: ElectricalTopologyConfig,
    upstream: tuple[Any, ...],
    accounting: Any,
    capabilities: dict[str, InverterAcCapabilityAuthority],
    requests: dict[tuple[pd.Timestamp, str], InverterReactivePowerRequest],
    *,
    supplied_capability: Any = None,
    supplied_accounting: Any = None,
) -> Any:
    (
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        inverter_authority,
        limits,
        envelope,
        ac,
        potential,
    ) = upstream
    authority = supplied_capability or resolve_topology_inverter_ac_capability_authority(
        topology, capabilities
    )
    return calculate_topology_inverter_pqs_capability(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        inverter_authority,
        limits,
        envelope,
        ac,
        potential,
        supplied_accounting or accounting,
        capabilities,
        authority,
        requests,
    )


def _request(q: float) -> InverterReactivePowerRequest:
    return InverterReactivePowerRequest(q, "controller:test", "high")


def _key(accounting: Any) -> tuple[pd.Timestamp, str]:
    timestamp, inverter_id = accounting.accounting.index[0]
    return pd.Timestamp(timestamp), str(inverter_id)


@pytest.mark.parametrize(
    ("q", "direction"), [(0.0, "zero"), (100.0, "injection"), (-100.0, "absorption")]
)
def test_explicit_q_request_is_preserved_and_direction_is_locked(q: float, direction: str) -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    result = _run(
        topology,
        upstream,
        accounting,
        {"inverter-1": _authority()},
        {_key(accounting): _request(q)},
    )
    row = result.capability.iloc[0]
    assert row["q_requested_var"] == q
    assert row["reactive_power_request_direction"] == direction
    assert row["p_ac_available_w"] == accounting.accounting.iloc[0]["p_ac_available_w"]
    assert row["pqs_capability_state"] == "resolved_pqs_within_explicit_capability"


def test_apparent_power_and_power_factor_close() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    q = 400.0
    result = _run(
        topology,
        upstream,
        accounting,
        {"inverter-1": _authority()},
        {_key(accounting): _request(q)},
    )
    row = result.capability.iloc[0]
    expected = math.hypot(row["p_ac_available_w"], q)
    assert row["s_requested_va"] == expected
    assert row["power_factor_magnitude"] == row["p_ac_available_w"] / expected
    assert row["apparent_power_margin_va"] == row["rated_apparent_power_va"] - expected


def test_exact_smax_boundary_is_inclusive() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    p = float(accounting.accounting.iloc[0]["p_ac_available_w"])
    result = _run(
        topology,
        upstream,
        accounting,
        {"inverter-1": _authority(p, -p, p)},
        {_key(accounting): _request(0.0)},
    )
    row = result.capability.iloc[0]
    assert row["s_requested_va"] == p
    assert row["apparent_power_margin_va"] == 0.0
    assert row["apparent_power_limit_satisfied"]
    assert row["pqs_capability_satisfied"]


def test_circle_boundary_and_outside_are_classified() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    p = float(accounting.accounting.iloc[0]["p_ac_available_w"])
    smax = p + 1000.0
    q_boundary = math.sqrt(smax * smax - p * p)
    capabilities = {"inverter-1": _authority(smax, -smax, smax)}
    boundary = _run(
        topology, upstream, accounting, capabilities, {_key(accounting): _request(q_boundary)}
    ).capability.iloc[0]
    outside = _run(
        topology, upstream, accounting, capabilities, {_key(accounting): _request(q_boundary + 1.0)}
    ).capability.iloc[0]
    assert boundary["apparent_power_limit_satisfied"]
    assert boundary["apparent_power_margin_va"] == pytest.approx(0.0, abs=1e-8)
    assert not outside["apparent_power_limit_satisfied"]
    assert outside["apparent_power_margin_va"] < 0.0
    assert outside["pqs_capability_state"] == "resolved_pqs_known_capability_violation"


@pytest.mark.parametrize("q", [-4000.0, 4000.0])
def test_fixed_q_boundaries_are_inclusive(q: float) -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    row = _run(
        topology,
        upstream,
        accounting,
        {"inverter-1": _authority()},
        {_key(accounting): _request(q)},
    ).capability.iloc[0]
    assert row["fixed_q_limit_satisfied"]


@pytest.mark.parametrize("q", [-4000.1, 4000.1])
def test_fixed_q_violations_preserve_request(q: float) -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    row = _run(
        topology,
        upstream,
        accounting,
        {"inverter-1": _authority()},
        {_key(accounting): _request(q)},
    ).capability.iloc[0]
    assert row["q_requested_var"] == q
    assert not row["fixed_q_limit_satisfied"]
    assert row["capability_violation_detected"]
    assert not row["pqs_capability_satisfied"]


def test_explicit_zero_fixed_q_is_distinct_from_missing_q_authority() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    zero_authority = {"inverter-1": _authority(5000.0, 0.0, 0.0)}
    assert _run(
        topology, upstream, accounting, zero_authority, {_key(accounting): _request(0.0)}
    ).capability.iloc[0]["fixed_q_limit_satisfied"]
    row = _run(
        topology, upstream, accounting, zero_authority, {_key(accounting): _request(1.0)}
    ).capability.iloc[0]
    assert not row["fixed_q_limit_satisfied"]


def test_partial_authority_pass_is_unknown_and_violation_is_definite() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    partial = {"inverter-1": _authority(5000.0, None, None)}
    passing = _run(
        topology, upstream, accounting, partial, {_key(accounting): _request(0.0)}
    ).capability.iloc[0]
    failing = _run(
        topology, upstream, accounting, partial, {_key(accounting): _request(10000.0)}
    ).capability.iloc[0]
    assert passing["pqs_capability_state"] == "resolved_pqs_partial_no_fixed_q_authority"
    assert pd.isna(passing["fixed_q_limit_satisfied"])
    assert pd.isna(passing["pqs_capability_satisfied"])
    assert failing["pqs_capability_state"] == "resolved_pqs_known_capability_violation"
    assert failing["pqs_capability_satisfied"] is False or not failing["pqs_capability_satisfied"]


def test_missing_request_is_not_zero_but_p_alone_violation_is_known() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    p = float(accounting.accounting.iloc[0]["p_ac_available_w"])
    missing = _run(
        topology,
        upstream,
        accounting,
        {"inverter-1": _authority(p + 1.0, -(p + 1.0), p + 1.0)},
        {},
    ).capability.iloc[0]
    violation = _run(
        topology,
        upstream,
        accounting,
        {"inverter-1": _authority(p - 1.0, -(p - 1.0), p - 1.0)},
        {},
    ).capability.iloc[0]
    assert missing["pqs_capability_state"] == "unresolved_no_explicit_reactive_power_request"
    assert not missing["reactive_power_request_present"]
    assert pd.isna(missing["q_requested_var"])
    assert violation["pqs_capability_state"] == "resolved_pqs_known_capability_violation"
    assert violation["active_power_alone_exceeds_smax"]
    assert not violation["pqs_capability_satisfied"]


def test_night_tare_is_resolved_not_applicable_without_request() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology, zero=True)
    row = _run(topology, upstream, accounting, {"inverter-1": _authority()}, {}).capability.iloc[0]
    assert row["inverter_conversion_state"] == "resolved_sandia_night_tare"
    assert row["pqs_capability_state"] == "resolved_pqs_not_applicable_inactive_ac_state"
    assert row["pqs_evaluation_resolved"]
    assert not row["pqs_evaluation_applicable"]
    assert pd.isna(row["s_requested_va"])
    assert pd.isna(row["pqs_capability_satisfied"])


def test_missing_ac_capability_authority_is_unresolved() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    row = _run(
        topology, upstream, accounting, {}, {_key(accounting): _request(0.0)}
    ).capability.iloc[0]
    assert row["pqs_capability_state"] == "unresolved_no_explicit_ac_capability_authority"
    assert not row["pqs_evaluation_resolved"]


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf"), "1"])
def test_request_rejects_invalid_numeric_values(value: object) -> None:
    with pytest.raises(ValueError):
        InverterReactivePowerRequest(value, "test", "high")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0.0, 1.0, -1.0, 1e100])
def test_request_accepts_any_finite_value(value: float) -> None:
    assert (
        InverterReactivePowerRequest(value, "test", "unknown").reactive_power_request_var == value
    )


def test_request_metadata_and_mapping_validation() -> None:
    with pytest.raises(ValueError):
        InverterReactivePowerRequest(0.0, " ", "high")
    with pytest.raises(ValueError):
        InverterReactivePowerRequest(0.0, "test", "invalid")  # type: ignore[arg-type]
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    with pytest.raises(TypeError):
        _run(topology, upstream, accounting, {"inverter-1": _authority()}, {_key(accounting): {}})  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _run(
            topology,
            upstream,
            accounting,
            {"inverter-1": _authority()},
            {(pd.Timestamp("2030-01-01"), "inverter-1"): _request(0.0)},
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("p_ac_available_w", 1.0),
        ("accounting_resolved", False),
        ("accounting_state", "forged"),
        ("inverter_conversion_state", "forged"),
        ("available_reference_plane", "forged"),
        ("topology_sandia_inverter_accounting_contract", "forged"),
    ],
)
def test_s93b_tampering_is_rejected(column: str, value: object) -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    forged = accounting.accounting.copy(deep=True)
    forged.loc[forged.index[0], column] = value
    supplied = replace(accounting, accounting=forged)
    with pytest.raises(ValueError, match="S9-3B"):
        _run(
            topology,
            upstream,
            accounting,
            {"inverter-1": _authority()},
            {_key(accounting): _request(0.0)},
            supplied_accounting=supplied,
        )


def test_s93b_diagnostics_tampering_is_rejected() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    supplied = replace(accounting, diagnostics=replace(accounting.diagnostics, row_count=99))
    with pytest.raises(ValueError, match="S9-3B diagnostics"):
        _run(
            topology,
            upstream,
            accounting,
            {"inverter-1": _authority()},
            {},
            supplied_accounting=supplied,
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("rated_apparent_power_va", 1.0),
        ("reactive_power_min_var", -1.0),
        ("fixed_reactive_power_limits_resolved", False),
        ("phase_configuration", "single_phase"),
        ("ac_voltage_basis", "line_to_neutral"),
        ("ac_capability_authority_resolved", False),
        ("ac_capability_authority_state", "forged"),
        ("parameter_source", "forged"),
        ("confidence", "low"),
        ("topology_inverter_ac_capability_authority_contract", "forged"),
    ],
)
def test_s94a_tampering_is_rejected(column: str, value: object) -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    capabilities = {"inverter-1": _authority()}
    authority = resolve_topology_inverter_ac_capability_authority(topology, capabilities)
    forged = authority.states.copy(deep=True)
    forged.loc["inverter-1", column] = value
    supplied = replace(authority, states=forged)
    with pytest.raises(ValueError, match="S9-4A"):
        _run(topology, upstream, accounting, capabilities, {}, supplied_capability=supplied)


def test_s94a_diagnostics_tampering_is_rejected() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    capabilities = {"inverter-1": _authority()}
    authority = resolve_topology_inverter_ac_capability_authority(topology, capabilities)
    supplied = replace(authority, diagnostics=replace(authority.diagnostics, inverter_count=99))
    with pytest.raises(ValueError, match="S9-4A diagnostics"):
        _run(topology, upstream, accounting, capabilities, {}, supplied_capability=supplied)


def test_empty_topology_has_stable_schema_and_dtypes() -> None:
    topology = ElectricalTopologyConfig()
    upstream, accounting = _chain(topology)
    result = _run(topology, upstream, accounting, {}, {})
    assert result.capability.empty
    assert result.capability.index.names == ["timestamp", "inverter_id"]
    assert result.diagnostics.row_count == 0
    assert result.capability["p_ac_available_w"].dtype == "float64"
    assert result.capability["pqs_capability_satisfied"].dtype == "boolean"


def test_diagnostics_provenance_ownership_and_ordering() -> None:
    topology = s91_support._topology()
    upstream, accounting = _chain(topology)
    capabilities = {"inverter-1": _authority()}
    requests = {_key(accounting): _request(0.0)}
    first = _run(topology, upstream, accounting, capabilities, requests)
    second = _run(
        topology,
        upstream,
        accounting,
        dict(reversed(list(capabilities.items()))),
        dict(reversed(list(requests.items()))),
    )
    pd.testing.assert_frame_equal(first.capability, second.capability, check_exact=True)
    assert first.diagnostics == second.diagnostics
    row = first.capability.iloc[0]
    assert (
        row["topology_inverter_pqs_capability_contract"]
        == TOPOLOGY_INVERTER_PQS_CAPABILITY_CONTRACT_ID
    )
    assert (
        row["topology_inverter_pqs_capability_model"] == TOPOLOGY_INVERTER_PQS_CAPABILITY_MODEL_ID
    )
    assert row["topology_inverter_pqs_capability_scope"] == TOPOLOGY_INVERTER_PQS_CAPABILITY_SCOPE
    assert (
        row["topology_inverter_pqs_capability_coverage_scope"]
        == TOPOLOGY_INVERTER_PQS_CAPABILITY_COVERAGE_SCOPE
    )
    mutated = first.capability
    mutated.iloc[0, mutated.columns.get_loc("q_requested_var")] = 123.0
    assert accounting.accounting.iloc[0]["p_ac_available_w"] == row["p_ac_available_w"]
    assert requests[_key(accounting)].reactive_power_request_var == 0.0


def test_module_has_no_control_current_thermal_network_or_pvlib_logic() -> None:
    source = inspect.getsource(
        importlib.import_module("heliotelligence.physics.inverter_pqs_capability")
    )
    forbidden = (
        "import pvlib",
        "total_loss",
        "ac_current",
        "power_factor_compliant",
        "grid_code",
        "transformer_loss",
        "thermal_derating",
    )
    assert all(token not in source for token in forbidden)
