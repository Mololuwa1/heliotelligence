"""Tests for S10B requested inverter dispatch-feasibility evaluation."""

from __future__ import annotations

import importlib
import math
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter_ac_authority import (
    resolve_topology_inverter_ac_capability_authority,
)
from heliotelligence.physics.inverter_dispatch_feasibility import (
    TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_MODEL_ID,
    TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_SCOPE,
    calculate_topology_inverter_dispatch_feasibility,
)
from heliotelligence.physics.inverter_thermal_authority import (
    InverterThermalDeratingAuthority,
    resolve_topology_inverter_thermal_derating_authority,
)

s10a: Any = importlib.import_module(
    "tests.unit.test_physics.test_inverter_dispatch_request_authority"
)
s94d: Any = importlib.import_module("tests.unit.test_physics.test_inverter_temperature_capability")
pqs_support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_pqs_capability")
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


def _setup(
    *,
    zero: bool = False,
    smax: float = 20000.0,
    static_full: bool = True,
    q: float | None = 0.0,
    p: float | None = 100.0,
    thermal: InverterThermalDeratingAuthority | None | bool = True,
    temperature: Any = True,
    topology: ElectricalTopologyConfig | None = None,
) -> tuple[Any, ...]:
    context = s94d._context(
        zero=zero,
        smax=smax,
        static_full=static_full,
        q=0.0 if q is None else q,
        topology=topology,
    )
    topology_value = context[0]
    if q is None and not zero:
        context = (
            *context[:4],
            {},
            pqs_support._run(context[0], context[1], context[2], context[3], {}),
        )
    thermal_mapping = {}
    if thermal is True:
        thermal_mapping = {inverter.id: s94d._thermal() for inverter in topology_value.inverters}
    elif thermal is not None and thermal is not False:
        thermal_mapping = {inverter.id: thermal for inverter in topology_value.inverters}
    temperatures = {}
    if temperature is True:
        temperatures = {
            (pd.Timestamp(key[0]), str(key[1])): s94d._temperature(50.0)
            for key in context[5].capability.index
        }
    elif temperature not in (None, False):
        temperatures = {
            (pd.Timestamp(key[0]), str(key[1])): temperature for key in context[5].capability.index
        }
    parent, _, _ = s10a._parent(context, thermal_mapping=thermal_mapping, temperatures=temperatures)
    p_requests = (
        {}
        if p is None
        else {
            (pd.Timestamp(key[0]), str(key[1])): s10a._request(p) for key in parent.capability.index
        }
    )
    request_authority = s10a._run(context, parent, thermal_mapping, temperatures, p_requests)
    return context, parent, thermal_mapping, temperatures, p_requests, request_authority


def _run(setup: tuple[Any, ...], *, supplied_parent: Any = None, supplied_s10a: Any = None) -> Any:
    context, parent, thermal_mapping, temperatures, p_requests, request_authority = setup
    topology, upstream, accounting, capabilities, q_requests, pqs = context
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
    ac_authority = resolve_topology_inverter_ac_capability_authority(topology, capabilities)
    thermal_authority = resolve_topology_inverter_thermal_derating_authority(
        topology, thermal_mapping
    )
    return calculate_topology_inverter_dispatch_feasibility(
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
        accounting,
        capabilities,
        ac_authority,
        q_requests,
        pqs,
        thermal_mapping,
        thermal_authority,
        temperatures,
        supplied_parent or parent,
        p_requests,
        supplied_s10a or request_authority,
    )


def _row(setup: tuple[Any, ...]) -> pd.Series:
    return _run(setup).feasibility.iloc[0]


def test_full_feasible_requested_point_and_exact_equations() -> None:
    row = _row(_setup(p=100.0, q=30.0))
    assert row["dispatch_feasibility_state"] == (
        "resolved_requested_dispatch_feasible_full_capability"
    )
    assert row["s_requested_va"] == math.hypot(100.0, 30.0)
    assert row["active_power_availability_margin_w"] == (row["p_ac_available_w"] - 100.0)
    assert row["dispatch_feasibility_satisfied"]


def test_request_equal_available_is_feasible() -> None:
    initial = _setup()
    available = float(initial[1].capability.iloc[0]["p_ac_available_w"])
    row = _row(_setup(p=available))
    assert row["active_power_availability_margin_w"] == 0.0
    assert row["active_power_availability_satisfied"]


@pytest.mark.parametrize(
    ("delta", "satisfied"),
    [(0.5e-8, True), (1.5e-8, False)],
)
def test_availability_tolerance_boundary(delta: float, satisfied: bool) -> None:
    initial = _setup()
    available = float(initial[1].capability.iloc[0]["p_ac_available_w"])
    row = _row(_setup(p=available + delta))
    assert bool(row["active_power_availability_satisfied"]) is satisfied
    if not satisfied:
        assert row["dispatch_feasibility_state"] == ("resolved_requested_dispatch_known_infeasible")


def test_explicit_zero_p_and_q_is_complete_not_missing() -> None:
    row = _row(_setup(p=0.0, q=0.0))
    assert row["active_power_setpoint_is_zero"]
    assert row["requested_pq_complete"]
    assert row["s_requested_va"] == 0.0


@pytest.mark.parametrize(
    ("p", "q", "state"),
    [
        (None, 0.0, "unresolved_no_explicit_active_power_dispatch_request"),
        (100.0, None, "unresolved_no_explicit_reactive_power_request"),
    ],
)
def test_missing_request_components(p: float | None, q: float | None, state: str) -> None:
    assert _row(_setup(p=p, q=q))["dispatch_feasibility_state"] == state


def test_p_alone_over_smax_is_known_infeasible_with_q_missing() -> None:
    row = _row(_setup(p=2000.0, q=None, smax=1000.0))
    assert row["static_apparent_power_limit_evaluated"]
    assert not row["static_apparent_power_limit_satisfied"]
    assert row["dispatch_feasibility_state"] == "resolved_requested_dispatch_known_infeasible"


def test_q_alone_over_smax_is_known_infeasible_with_p_missing() -> None:
    row = _row(_setup(p=None, q=2000.0, smax=1000.0))
    assert row["static_apparent_power_limit_evaluated"]
    assert row["dispatch_feasibility_violation_detected"]


@pytest.mark.parametrize("q", [-30001.0, 30001.0])
def test_static_fixed_q_violations(q: float) -> None:
    row = _row(_setup(p=100.0, q=q, smax=30000.0))
    assert row["static_fixed_q_limit_evaluated"]
    assert not row["static_fixed_q_limit_satisfied"]


def test_static_partial_circle_pass_is_partial() -> None:
    row = _row(_setup(static_full=False, p=100.0, q=0.0))
    assert row["dispatch_feasibility_state"] == (
        "resolved_requested_dispatch_partial_capability_authority"
    )
    assert pd.isna(row["dispatch_feasibility_satisfied"])


def test_explicit_no_derating_is_full_without_synthetic_limits() -> None:
    authority = s94d._thermal(
        mode="explicit_no_derating",
        points=(-20.0, 60.0),
        active=None,
        apparent=None,
        q_min=None,
        q_max=None,
    )
    row = _row(_setup(thermal=authority, p=100.0, q=0.0))
    assert row["full_thermal_capability_authority_resolved"]
    assert pd.isna(row["thermal_active_power_limit_w"])
    assert row["dispatch_feasibility_satisfied"]


@pytest.mark.parametrize(
    ("authority", "p", "q", "field"),
    [
        (
            s94d._thermal(active=(100.0, 100.0, 100.0)),
            101.0,
            0.0,
            "thermal_active_power_limit_satisfied",
        ),
        (
            s94d._thermal(active=None, apparent=(100.0, 100.0, 100.0), q_min=None, q_max=None),
            80.0,
            70.0,
            "thermal_apparent_power_limit_satisfied",
        ),
        (
            s94d._thermal(
                active=None, apparent=None, q_min=(-10.0, -10.0, -10.0), q_max=(10.0, 10.0, 10.0)
            ),
            0.0,
            -11.0,
            "thermal_reactive_power_limit_satisfied",
        ),
        (
            s94d._thermal(
                active=None, apparent=None, q_min=(-10.0, -10.0, -10.0), q_max=(10.0, 10.0, 10.0)
            ),
            0.0,
            11.0,
            "thermal_reactive_power_limit_satisfied",
        ),
    ],
)
def test_thermal_channel_violations(authority: Any, p: float, q: float, field: str) -> None:
    row = _row(_setup(thermal=authority, p=p, q=q, smax=1000.0))
    assert not row[field]
    assert row["dispatch_feasibility_state"] == "resolved_requested_dispatch_known_infeasible"


def test_partial_thermal_pass_and_known_failure() -> None:
    authority = s94d._thermal(active=(100.0, 100.0, 100.0), apparent=None, q_min=None, q_max=None)
    passed = _row(_setup(thermal=authority, p=50.0, q=0.0))
    failed = _row(_setup(thermal=authority, p=101.0, q=0.0))
    assert passed["dispatch_feasibility_state"] == (
        "resolved_requested_dispatch_partial_capability_authority"
    )
    assert failed["dispatch_feasibility_violation_detected"]


@pytest.mark.parametrize(
    ("thermal", "temperature", "expected"),
    [
        (False, True, "unresolved_no_explicit_inverter_thermal_derating_authority"),
        (True, False, "unresolved_no_explicit_inverter_temperature_state"),
        (
            True,
            s94d._temperature(50.0, "ambient_air"),
            "unresolved_inverter_temperature_quantity_mismatch",
        ),
        (True, s94d._temperature(39.0), "unresolved_inverter_temperature_outside_authority_domain"),
        (True, s94d._temperature(61.0), "unresolved_inverter_temperature_outside_authority_domain"),
    ],
)
def test_thermal_unresolved_states(thermal: Any, temperature: Any, expected: str) -> None:
    assert (
        _row(_setup(thermal=thermal, temperature=temperature))["dispatch_feasibility_state"]
        == expected
    )


@pytest.mark.parametrize(("temperature", "expected"), [(50.0, 8000.0), (55.0, 6000.0)])
def test_exact_breakpoint_and_linear_interpolation(temperature: float, expected: float) -> None:
    row = _row(_setup(temperature=s94d._temperature(temperature), p=100.0))
    assert row["thermal_active_power_limit_w"] == expected


def test_inactive_is_resolved_not_applicable() -> None:
    row = _row(_setup(zero=True, p=0.0, q=None, thermal=False, temperature=False))
    assert row["dispatch_feasibility_state"] == (
        "resolved_dispatch_feasibility_not_applicable_inactive_ac_state"
    )
    assert row["dispatch_feasibility_evaluation_resolved"]
    assert not row["dispatch_feasibility_evaluation_applicable"]


def test_available_point_static_failure_is_not_inherited() -> None:
    authority = s94d._thermal(
        mode="explicit_no_derating",
        points=(-20.0, 60.0),
        active=None,
        apparent=None,
        q_min=None,
        q_max=None,
    )
    setup = _setup(smax=1000.0, p=100.0, q=0.0, thermal=authority)
    assert setup[1].capability.iloc[0]["temperature_dependent_capability_violation_detected"]
    row = _row(setup)
    assert not row["dispatch_feasibility_violation_detected"]


def test_available_point_thermal_failure_is_rescued_by_lower_request() -> None:
    authority = s94d._thermal(active=(1000.0, 1000.0, 1000.0), apparent=(20000.0, 20000.0, 20000.0))
    setup = _setup(thermal=authority, p=500.0, q=0.0)
    assert setup[1].capability.iloc[0]["temperature_dependent_capability_violation_detected"]
    assert _row(setup)["dispatch_feasibility_satisfied"]


def test_available_point_pass_but_request_above_available_is_infeasible() -> None:
    initial = _setup()
    available = float(initial[1].capability.iloc[0]["p_ac_available_w"])
    row = _row(_setup(p=available + 1.0, smax=1_000_000.0))
    assert row["dispatch_feasibility_state"] == "resolved_requested_dispatch_known_infeasible"


def test_two_inverter_mapping_order_independence() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[
            s91_support._topology(inverter_id="inverter-a").inverters[0],
            s91_support._topology(inverter_id="inverter-b").inverters[0],
        ]
    )
    setup = _setup(topology=topology)
    first = _run(setup)
    reversed_setup = list(setup)
    reversed_setup[2] = dict(reversed(list(setup[2].items())))
    reversed_setup[3] = dict(reversed(list(setup[3].items())))
    reversed_setup[4] = dict(reversed(list(setup[4].items())))
    second = _run(tuple(reversed_setup))
    pd.testing.assert_frame_equal(first.feasibility, second.feasibility, check_exact=True)
    assert first.diagnostics == second.diagnostics


def test_empty_topology_stable_schema() -> None:
    result = _run(
        _setup(
            topology=ElectricalTopologyConfig(), p=None, q=None, thermal=False, temperature=False
        )
    )
    assert result.feasibility.empty
    assert result.feasibility.index.names == ["timestamp", "inverter_id"]
    assert str(result.feasibility["p_requested_w"].dtype) == "float64"
    assert str(result.feasibility["dispatch_feasibility_satisfied"].dtype) == "boolean"


@pytest.mark.parametrize(
    "kind", ["parent_frame", "parent_diagnostics", "s10a_frame", "s10a_diagnostics", "s10a_mapping"]
)
def test_parent_tamper_rejected(kind: str) -> None:
    setup = _setup()
    parent, s10a_result = setup[1], setup[5]
    if kind == "parent_frame":
        frame = parent.capability.copy(deep=True)
        frame.iloc[0, frame.columns.get_loc("p_ac_available_w")] += 1.0
        parent = replace(parent, capability=frame)
    elif kind == "parent_diagnostics":
        parent = replace(parent, diagnostics=replace(parent.diagnostics, row_count=99))
    elif kind == "s10a_frame":
        frame = s10a_result.states.copy(deep=True)
        frame.iloc[0, frame.columns.get_loc("active_power_setpoint_w")] += 1.0
        s10a_result = replace(s10a_result, states=frame)
    elif kind == "s10a_diagnostics":
        s10a_result = replace(
            s10a_result, diagnostics=replace(s10a_result.diagnostics, row_count=99)
        )
    else:
        s10a_result = replace(s10a_result, requests_by_key={})
    with pytest.raises(ValueError):
        _run(setup, supplied_parent=parent, supplied_s10a=s10a_result)


def test_provenance_diagnostics_and_output_ownership() -> None:
    setup = _setup()
    first = _run(setup)
    second = _run(setup)
    row = first.feasibility.iloc[0]
    assert (
        row["topology_inverter_dispatch_feasibility_contract"]
        == TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_CONTRACT_ID
    )
    assert (
        row["topology_inverter_dispatch_feasibility_model"]
        == TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_MODEL_ID
    )
    assert (
        row["topology_inverter_dispatch_feasibility_scope"]
        == TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_SCOPE
    )
    assert (
        row["topology_inverter_dispatch_feasibility_coverage_scope"]
        == TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_COVERAGE_SCOPE
    )
    first.feasibility.iloc[0, first.feasibility.columns.get_loc("p_requested_w")] = 1.0
    assert second.feasibility.iloc[0]["p_requested_w"] == 100.0
    assert second.diagnostics.row_count == 1


def test_no_selection_loss_network_or_duplicate_q_fields() -> None:
    module = importlib.import_module("heliotelligence.physics.inverter_dispatch_feasibility")
    forbidden = {
        "selected_active_power_w",
        "selected_reactive_power_var",
        "curtailment_loss_w",
        "grid_limit_kwac",
        "reactive_power_dispatch_request",
        "ac_current_a",
    }
    assert not forbidden & set(module._COLUMNS)
