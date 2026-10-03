"""Tests for S9-4D inverter temperature-dependent capability evaluation."""

from __future__ import annotations

import importlib
import math
from dataclasses import replace
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter_ac_authority import (
    resolve_topology_inverter_ac_capability_authority,
)
from heliotelligence.physics.inverter_temperature_capability import (
    TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_MODEL_ID,
    TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_SCOPE,
    InverterTemperatureState,
    calculate_topology_inverter_temperature_capability,
)
from heliotelligence.physics.inverter_thermal_authority import (
    InverterThermalDeratingAuthority,
    resolve_topology_inverter_thermal_derating_authority,
)

pqs_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_inverter_pqs_capability"
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


def _temperature(value: float, quantity: str = "heatsink") -> InverterTemperatureState:
    return InverterTemperatureState(value, quantity, "sensor:test", "high")


def _thermal(
    *,
    mode: str = "piecewise_linear_limits",
    points: tuple[float, ...] = (40.0, 50.0, 60.0),
    active: tuple[float, ...] | None = (10000.0, 8000.0, 4000.0),
    apparent: tuple[float, ...] | None = (11000.0, 9000.0, 5000.0),
    q_min: tuple[float, ...] | None = (-5000.0, -4000.0, -2000.0),
    q_max: tuple[float, ...] | None = (5000.0, 4000.0, 2000.0),
) -> InverterThermalDeratingAuthority:
    return InverterThermalDeratingAuthority(
        temperature_quantity="heatsink",
        derating_mode=mode,  # type: ignore[arg-type]
        temperature_points_c=points,
        active_power_limit_w=active,
        apparent_power_limit_va=apparent,
        reactive_power_min_var=q_min,
        reactive_power_max_var=q_max,
        parameter_source="manufacturer:test",
        confidence="high",
    )


def _context(
    *, zero: bool = False, static_full: bool = True, q: float = 0.0,
    smax: float = 20000.0,
) -> tuple[
    ElectricalTopologyConfig,
    tuple[Any, ...],
    Any,
    dict[str, Any],
    dict[Any, Any],
    Any,
]:
    topology = s91_support._topology()
    upstream, accounting = pqs_support._chain(topology, zero=zero)
    capabilities = {
        "inverter-1": pqs_support._authority(
            smax, -smax if static_full else None, smax if static_full else None
        )
    }
    requests = {} if zero else {pqs_support._key(accounting): pqs_support._request(q)}
    pqs = pqs_support._run(topology, upstream, accounting, capabilities, requests)
    return topology, upstream, accounting, capabilities, requests, pqs


def _run(
    context: tuple[Any, ...], thermal_mapping: dict[str, InverterThermalDeratingAuthority],
    temperatures: dict[tuple[pd.Timestamp, str], InverterTemperatureState],
    *, supplied_pqs: Any = None, supplied_thermal: Any = None,
) -> Any:
    topology, upstream, accounting, capabilities, requests, pqs = context
    (
        topology_string_iv, branch_authority, mppt_input_string_iv,
        mppt_input_operating_points, names, inverter_authority, limits, envelope,
        ac, potential,
    ) = upstream
    ac_authority = resolve_topology_inverter_ac_capability_authority(topology, capabilities)
    thermal_authority = supplied_thermal or (
        resolve_topology_inverter_thermal_derating_authority(topology, thermal_mapping)
    )
    return calculate_topology_inverter_temperature_capability(
        topology, topology_string_iv, branch_authority, mppt_input_string_iv,
        mppt_input_operating_points, names, inverter_authority, limits, envelope,
        ac, potential, accounting, capabilities, ac_authority, requests,
        supplied_pqs or pqs, thermal_mapping, thermal_authority, temperatures,
    )


def _key(context: tuple[Any, ...]) -> tuple[pd.Timestamp, str]:
    return cast(tuple[pd.Timestamp, str], pqs_support._key(context[2]))


def test_temperature_state_validation() -> None:
    for value in (True, False, float("nan"), float("inf"), "25"):
        with pytest.raises(ValueError):
            InverterTemperatureState(value, "heatsink", "sensor", "high")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="temperature_quantity"):
        InverterTemperatureState(25.0, " ", "sensor", "high")
    with pytest.raises(ValueError, match="parameter_source"):
        InverterTemperatureState(25.0, "heatsink", "", "high")
    with pytest.raises(ValueError, match="confidence"):
        InverterTemperatureState(25.0, "heatsink", "sensor", "certain")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("temperature", "expected", "state", "performed"),
    [
        (40.0, 10000.0, "exact_authority_point", False),
        (50.0, 8000.0, "exact_authority_point", False),
        (60.0, 4000.0, "exact_authority_point", False),
        (45.0, 9000.0, "between_authority_points", True),
        (55.0, 6000.0, "between_authority_points", True),
    ],
)
def test_exact_points_and_piecewise_interpolation(
    temperature: float, expected: float, state: str, performed: bool
) -> None:
    context = _context()
    result = _run(context, {"inverter-1": _thermal()}, {_key(context): _temperature(temperature)})
    row = result.capability.iloc[0]
    assert row["thermal_active_power_limit_w"] == expected
    assert row["thermal_interpolation_state"] == state
    assert bool(row["thermal_interpolation_performed"]) is performed
    assert row["temperature_capability_state"] == (
        "resolved_temperature_dependent_within_full_capability"
    )


def test_nonuniform_grid_uses_explicit_linear_formula() -> None:
    context = _context()
    authority = _thermal(
        points=(0.0, 10.0, 40.0), active=(10000.0, 9000.0, 6000.0),
        apparent=None, q_min=None, q_max=None,
    )
    row = _run(
        context, {"inverter-1": authority}, {_key(context): _temperature(25.0)}
    ).capability.iloc[0]
    assert row["thermal_active_power_limit_w"] == 7500.0
    assert row["thermal_interpolation_performed"]


def test_explicit_no_derating_full_and_partial_static_semantics() -> None:
    authority = _thermal(
        mode="explicit_no_derating", points=(-20.0, 70.0), active=None,
        apparent=None, q_min=None, q_max=None,
    )
    full = _context(static_full=True)
    full_row = _run(
        full, {"inverter-1": authority}, {_key(full): _temperature(25.0)}
    ).capability.iloc[0]
    assert full_row["thermal_capability_satisfied"]
    assert full_row["full_thermal_capability_authority_resolved"]
    assert full_row["temperature_dependent_capability_satisfied"]
    assert math.isnan(full_row["thermal_active_power_limit_w"])
    partial = _context(static_full=False)
    partial_row = _run(
        partial, {"inverter-1": authority}, {_key(partial): _temperature(25.0)}
    ).capability.iloc[0]
    assert partial_row["temperature_capability_state"] == (
        "resolved_temperature_dependent_partial_capability_authority"
    )
    assert pd.isna(partial_row["temperature_dependent_capability_satisfied"])


@pytest.mark.parametrize(
    ("mapping", "temperatures", "state"),
    [
        ({}, "valid", "unresolved_no_explicit_inverter_thermal_derating_authority"),
        ("authority", {}, "unresolved_no_explicit_inverter_temperature_state"),
        ("authority", "mismatch", "unresolved_inverter_temperature_quantity_mismatch"),
        ("authority", "below", "unresolved_inverter_temperature_outside_authority_domain"),
        ("authority", "above", "unresolved_inverter_temperature_outside_authority_domain"),
    ],
)
def test_missing_mismatch_and_outside_domain_are_unresolved(
    mapping: object, temperatures: object, state: str
) -> None:
    context = _context()
    authority_mapping = {} if mapping == {} else {"inverter-1": _thermal()}
    if temperatures == "valid":
        temperature_mapping = {_key(context): _temperature(50.0)}
    elif temperatures == "mismatch":
        temperature_mapping = {_key(context): _temperature(50.0, "ambient_air")}
    elif temperatures == "below":
        temperature_mapping = {_key(context): _temperature(39.999)}
    elif temperatures == "above":
        temperature_mapping = {_key(context): _temperature(60.001)}
    else:
        temperature_mapping = {}
    row = _run(context, authority_mapping, temperature_mapping).capability.iloc[0]
    assert row["temperature_capability_state"] == state
    assert not row["temperature_capability_evaluation_resolved"]
    assert math.isnan(row["thermal_active_power_limit_w"])


@pytest.mark.parametrize(
    ("authority", "q", "failed"),
    [
        (_thermal(active=(0.0, 0.0, 0.0), apparent=None, q_min=None, q_max=None), 0.0, "active"),
        (_thermal(active=None, apparent=(1.0, 1.0, 1.0), q_min=None, q_max=None), 0.0, "apparent"),
        (
            _thermal(
                active=None, apparent=None, q_min=(-1.0, -1.0, -1.0),
                q_max=(10.0, 10.0, 10.0),
            ),
            -2.0,
            "reactive",
        ),
        (
            _thermal(
                active=None, apparent=None, q_min=(-10.0, -10.0, -10.0),
                q_max=(1.0, 1.0, 1.0),
            ),
            2.0,
            "reactive",
        ),
    ],
)
def test_known_thermal_channel_violations_are_definitive(
    authority: InverterThermalDeratingAuthority, q: float, failed: str
) -> None:
    context = _context(q=q)
    row = _run(
        context, {"inverter-1": authority}, {_key(context): _temperature(50.0)}
    ).capability.iloc[0]
    assert row[f"thermal_{failed}_power_limit_satisfied"] is False or (
        row[f"thermal_{failed}_power_limit_satisfied"] == False  # noqa: E712
    )
    assert row["thermal_capability_violation_detected"]
    assert not row["temperature_dependent_capability_satisfied"]
    assert row["temperature_capability_state"] == (
        "resolved_temperature_dependent_known_capability_violation"
    )


def test_partial_thermal_pass_remains_unknown() -> None:
    context = _context()
    authority = _thermal(apparent=None, q_min=None, q_max=None)
    row = _run(
        context, {"inverter-1": authority}, {_key(context): _temperature(50.0)}
    ).capability.iloc[0]
    assert not row["full_thermal_capability_authority_resolved"]
    assert not row["thermal_capability_violation_detected"]
    assert pd.isna(row["thermal_capability_satisfied"])
    assert pd.isna(row["temperature_dependent_capability_satisfied"])
    assert row["temperature_capability_state"] == (
        "resolved_temperature_dependent_partial_capability_authority"
    )


def test_upstream_known_violation_precedes_missing_thermal_inputs() -> None:
    context = _context(smax=1.0)
    row = _run(context, {}, {}).capability.iloc[0]
    assert row["capability_violation_detected"]
    assert row["temperature_capability_evaluation_resolved"]
    assert row["temperature_capability_evaluation_applicable"]
    assert row["temperature_capability_state"] == (
        "resolved_temperature_dependent_known_capability_violation"
    )


def test_night_tare_is_resolved_not_applicable_without_inputs() -> None:
    context = _context(zero=True)
    row = _run(context, {}, {}).capability.iloc[0]
    assert row["temperature_capability_state"] == (
        "resolved_temperature_capability_not_applicable_inactive_ac_state"
    )
    assert row["temperature_capability_evaluation_resolved"]
    assert not row["temperature_capability_evaluation_applicable"]


def test_temperature_key_and_exact_type_admission() -> None:
    context = _context()
    authority = {"inverter-1": _thermal()}
    with pytest.raises(ValueError, match="unexpected"):
        _run(context, authority, {(pd.Timestamp("1999-01-01"), "x"): _temperature(50.0)})
    with pytest.raises(TypeError, match="exact state type"):
        _run(context, authority, {_key(context): 50.0})  # type: ignore[dict-item]


def test_s9_4b_and_s9_4c_tampering_is_rejected() -> None:
    context = _context()
    thermal_mapping = {"inverter-1": _thermal()}
    topology, _, _, _, _, pqs = context
    tampered_frame = pqs.capability.copy(deep=True)
    tampered_frame.iloc[0, tampered_frame.columns.get_loc("p_ac_available_w")] += 1.0
    with pytest.raises(ValueError, match="S9-4B"):
        _run(
            context, thermal_mapping, {_key(context): _temperature(50.0)},
            supplied_pqs=replace(pqs, capability=tampered_frame),
        )
    thermal = resolve_topology_inverter_thermal_derating_authority(topology, thermal_mapping)
    tampered_thermal = thermal.states.copy(deep=True)
    tampered_thermal.loc["inverter-1", "temperature_min_c"] += 1.0
    with pytest.raises(ValueError, match="S9-4C"):
        _run(
            context, thermal_mapping, {_key(context): _temperature(50.0)},
            supplied_thermal=replace(thermal, states=tampered_thermal),
        )


def test_provenance_dtypes_diagnostics_and_empty_result() -> None:
    context = _context()
    result = _run(
        context, {"inverter-1": _thermal()}, {_key(context): _temperature(50.0)}
    )
    row = result.capability.iloc[0]
    assert row["topology_inverter_temperature_capability_contract"] == (
        TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_CONTRACT_ID
    )
    assert row["topology_inverter_temperature_capability_model"] == (
        TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_MODEL_ID
    )
    assert row["topology_inverter_temperature_capability_scope"] == (
        TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_SCOPE
    )
    assert row["topology_inverter_temperature_capability_coverage_scope"] == (
        TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_COVERAGE_SCOPE
    )
    assert result.diagnostics.row_count == 1
    assert result.diagnostics.resolved_count == 1
    assert result.capability["thermal_capability_satisfied"].dtype == "boolean"

    empty_topology = ElectricalTopologyConfig()
    empty_upstream, empty_accounting = pqs_support._chain(empty_topology)
    empty_capabilities: dict[str, Any] = {}
    empty_requests: dict[Any, Any] = {}
    empty_pqs = pqs_support._run(
        empty_topology, empty_upstream, empty_accounting, empty_capabilities, empty_requests
    )
    empty_context = (
        empty_topology, empty_upstream, empty_accounting, empty_capabilities,
        empty_requests, empty_pqs,
    )
    empty = _run(empty_context, {}, {})
    assert empty.capability.empty
    assert empty.capability.index.names == ["timestamp", "inverter_id"]
    assert empty.capability.dtypes.to_dict() == result.capability.dtypes.to_dict()
    assert empty.diagnostics.row_count == 0


def test_output_ownership_and_mapping_order_independence() -> None:
    context = _context()
    mapping = {"inverter-1": _thermal()}
    temperatures = {_key(context): _temperature(50.0)}
    first = _run(context, mapping, temperatures)
    second = _run(
        context,
        dict(reversed(list(mapping.items()))),
        dict(reversed(list(temperatures.items()))),
    )
    pd.testing.assert_frame_equal(first.capability, second.capability, check_exact=True)
    assert first.diagnostics == second.diagnostics
    first.capability.iloc[0, first.capability.columns.get_loc("inverter_temperature_c")] = -999.0
    assert second.capability.iloc[0]["inverter_temperature_c"] == 50.0
