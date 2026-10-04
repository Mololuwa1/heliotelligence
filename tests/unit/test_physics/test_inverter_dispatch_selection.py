"""Tests for S10C exact feasible-request dispatch selection."""

from __future__ import annotations

import importlib
import math
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter_ac_authority import (
    resolve_topology_inverter_ac_capability_authority,
)
from heliotelligence.physics.inverter_dispatch_selection import (
    TOPOLOGY_INVERTER_DISPATCH_SELECTION_CONTRACT_ID,
    TOPOLOGY_INVERTER_DISPATCH_SELECTION_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_DISPATCH_SELECTION_MODEL_ID,
    TOPOLOGY_INVERTER_DISPATCH_SELECTION_SCOPE,
    TopologyInverterDispatchSelectionDiagnostics,
    _validate_result,
    calculate_topology_inverter_dispatch_selection,
)
from heliotelligence.physics.inverter_thermal_authority import (
    resolve_topology_inverter_thermal_derating_authority,
)

s10b: Any = importlib.import_module("tests.unit.test_physics.test_inverter_dispatch_feasibility")
s94d: Any = importlib.import_module("tests.unit.test_physics.test_inverter_temperature_capability")


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        inverter_lookup,
        "_load_cec_inverter_database",
        s10b.conversion_support._database,
    )
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        s10b.conversion_support._database,
    )


def _run(setup: tuple[Any, ...], *, supplied: Any = None) -> Any:
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
        inverter_ac,
        potential,
    ) = upstream
    ac_authority = resolve_topology_inverter_ac_capability_authority(topology, capabilities)
    thermal_authority = resolve_topology_inverter_thermal_derating_authority(
        topology, thermal_mapping
    )
    feasibility = supplied or s10b._run(setup)
    return calculate_topology_inverter_dispatch_selection(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        inverter_authority,
        limits,
        envelope,
        inverter_ac,
        potential,
        accounting,
        capabilities,
        ac_authority,
        q_requests,
        pqs,
        thermal_mapping,
        thermal_authority,
        temperatures,
        parent,
        p_requests,
        request_authority,
        feasibility,
    )


def _row(**kwargs: Any) -> pd.Series:
    return _run(s10b._setup(**kwargs)).dispatch.iloc[0]


@pytest.mark.parametrize(
    ("p", "q", "direction"),
    [(100.0, 0.0, "zero"), (100.0, 30.0, "injection"), (100.0, -30.0, "absorption")],
)
def test_fully_feasible_request_is_selected_exactly(p: float, q: float, direction: str) -> None:
    row = _row(p=p, q=q)
    assert row["dispatch_selection_state"] == "resolved_selected_dispatch_exact_feasible_request"
    assert row["selected_dispatch_present"]
    assert row["selected_dispatch_state_resolved"]
    assert row["p_selected_w"] == p
    assert row["q_selected_var"] == q
    assert row["s_selected_va"] == math.hypot(p, q)
    assert row["selected_reactive_power_direction"] == direction
    assert row["selected_dispatch_reference_plane"] == "inverter_ac_output"
    assert row["dispatch_selection_method"] == "exact_feasible_request_passthrough"


@pytest.mark.parametrize("q", [0.0, 20.0])
def test_explicit_zero_active_power_is_selected(q: float) -> None:
    row = _row(p=0.0, q=q)
    assert row["selected_dispatch_present"]
    assert row["p_selected_w"] == 0.0
    assert row["q_selected_var"] == q
    assert row["selected_active_power_is_zero"]


def test_lower_than_available_selects_request_not_available() -> None:
    row = _row(p=70.0, q=0.0)
    assert row["p_selected_w"] == 70.0
    assert row["p_selected_w"] != row["p_ac_available_w"]


def test_request_equal_available_is_selected_exactly() -> None:
    setup = s10b._setup()
    available = float(setup[1].capability.iloc[0]["p_ac_available_w"])
    row = _row(p=available, q=0.0)
    assert row["p_selected_w"] == available


def _assert_no_selection(row: pd.Series, state: str) -> None:
    assert row["dispatch_selection_state"] == state
    assert not row["selected_dispatch_present"]
    assert not row["selected_dispatch_state_resolved"]
    assert pd.isna(row["p_selected_w"])
    assert pd.isna(row["q_selected_var"])
    assert pd.isna(row["s_selected_va"])
    assert pd.isna(row["selected_active_power_is_zero"])
    assert row["selected_reactive_power_direction"] == "not_selected"
    assert row["selected_dispatch_reference_plane"] == ""
    assert row["dispatch_selection_method"] == ""


def test_request_above_available_is_not_clamped() -> None:
    setup = s10b._setup()
    available = float(setup[1].capability.iloc[0]["p_ac_available_w"])
    _assert_no_selection(
        _row(p=available + 1.0, q=0.0),
        "resolved_no_selected_dispatch_known_infeasible_request",
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"p": 2000.0, "q": 0.0, "smax": 1000.0},
        {"p": 100.0, "q": 30001.0, "smax": 30000.0},
        {
            "p": 90.0,
            "q": 0.0,
            "thermal": s94d._thermal(active=(70.0, 70.0, 70.0)),
        },
        {
            "p": 60.0,
            "q": 60.0,
            "thermal": s94d._thermal(
                active=None,
                apparent=(70.0, 70.0, 70.0),
                q_min=None,
                q_max=None,
            ),
        },
        {
            "p": 10.0,
            "q": 60.0,
            "thermal": s94d._thermal(
                active=None,
                apparent=None,
                q_min=(-50.0, -50.0, -50.0),
                q_max=(50.0, 50.0, 50.0),
            ),
        },
    ],
)
def test_known_constraint_violation_never_selects_or_clips(kwargs: dict[str, Any]) -> None:
    _assert_no_selection(_row(**kwargs), "resolved_no_selected_dispatch_known_infeasible_request")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"static_full": False},
        {
            "thermal": s94d._thermal(
                active=(1000.0, 1000.0, 1000.0),
                apparent=None,
                q_min=None,
                q_max=None,
            )
        },
    ],
)
def test_partial_authority_never_selects(kwargs: dict[str, Any]) -> None:
    _assert_no_selection(
        _row(**kwargs), "unresolved_no_selected_dispatch_partial_capability_authority"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"p": None},
        {"q": None},
        {"thermal": False},
        {"temperature": False},
        {"temperature": s94d._temperature(50.0, quantity="ambient_air")},
        {"temperature": s94d._temperature(100.0)},
    ],
)
def test_unresolved_parent_never_selects(kwargs: dict[str, Any]) -> None:
    _assert_no_selection(_row(**kwargs), "unresolved_upstream_dispatch_feasibility")


def test_inactive_parent_is_resolved_not_applicable_without_zero_selection() -> None:
    row = _row(zero=True, p=0.0, q=None, thermal=False, temperature=False)
    _assert_no_selection(row, "resolved_dispatch_selection_not_applicable_inactive_ac_state")
    assert row["dispatch_selection_evaluation_resolved"]
    assert not row["dispatch_selection_evaluation_applicable"]


def test_parent_and_selection_provenance_are_exact() -> None:
    row = _row()
    assert row["topology_inverter_dispatch_selection_contract"] == (
        TOPOLOGY_INVERTER_DISPATCH_SELECTION_CONTRACT_ID
    )
    assert row["topology_inverter_dispatch_selection_model"] == (
        TOPOLOGY_INVERTER_DISPATCH_SELECTION_MODEL_ID
    )
    assert row["topology_inverter_dispatch_selection_scope"] == (
        TOPOLOGY_INVERTER_DISPATCH_SELECTION_SCOPE
    )
    assert row["topology_inverter_dispatch_selection_coverage_scope"] == (
        TOPOLOGY_INVERTER_DISPATCH_SELECTION_COVERAGE_SCOPE
    )


@pytest.mark.parametrize(
    "column",
    [
        "p_requested_w",
        "q_requested_var",
        "s_requested_va",
        "dispatch_feasibility_satisfied",
        "dispatch_feasibility_violation_detected",
        "dispatch_feasibility_state",
        "active_power_availability_satisfied",
        "static_apparent_power_limit_satisfied",
        "thermal_active_power_limit_satisfied",
        "topology_inverter_dispatch_feasibility_contract",
    ],
)
def test_s10b_frame_tampering_is_rejected(column: str) -> None:
    setup = s10b._setup()
    supplied = s10b._run(setup)
    frame = supplied.feasibility.copy(deep=True)
    value = frame.iloc[0][column]
    if str(frame[column].dtype) in {"bool", "boolean"}:
        frame.iloc[0, frame.columns.get_loc(column)] = not bool(value)
    elif isinstance(value, str):
        frame.iloc[0, frame.columns.get_loc(column)] = f"tampered-{value}"
    else:
        frame.iloc[0, frame.columns.get_loc(column)] = float(value) + 1.0
    tampered = replace(supplied, feasibility=frame)
    with pytest.raises(ValueError, match="canonical replay"):
        _run(setup, supplied=tampered)


def test_s10b_diagnostics_tampering_is_rejected() -> None:
    setup = s10b._setup()
    supplied = s10b._run(setup)
    tampered = replace(
        supplied,
        diagnostics=replace(supplied.diagnostics, row_count=supplied.diagnostics.row_count + 1),
    )
    with pytest.raises(ValueError, match="diagnostics"):
        _run(setup, supplied=tampered)


@pytest.mark.parametrize(
    "column",
    [
        "p_selected_w",
        "q_selected_var",
        "s_selected_va",
        "selected_dispatch_present",
        "selected_dispatch_state_resolved",
        "selected_active_power_is_zero",
        "selected_reactive_power_direction",
        "selected_dispatch_reference_plane",
        "dispatch_selection_method",
        "dispatch_selection_state",
        "topology_inverter_dispatch_selection_contract",
    ],
)
def test_s10c_validator_rejects_output_tampering(column: str) -> None:
    setup = s10b._setup()
    parent = s10b._run(setup).feasibility
    result = _run(setup)
    frame = result.dispatch.copy(deep=True)
    value = frame.iloc[0][column]
    if str(frame[column].dtype) in {"bool", "boolean"}:
        frame.iloc[0, frame.columns.get_loc(column)] = not bool(value)
    elif isinstance(value, str):
        frame.iloc[0, frame.columns.get_loc(column)] = f"tampered-{value}"
    else:
        frame.iloc[0, frame.columns.get_loc(column)] = float(value) + 1.0
    with pytest.raises(RuntimeError):
        _validate_result(setup[0][0], parent, frame, result.diagnostics)


def test_s10c_validator_rejects_diagnostics_tampering() -> None:
    setup = s10b._setup()
    parent = s10b._run(setup).feasibility
    result = _run(setup)
    diagnostics = replace(result.diagnostics, row_count=result.diagnostics.row_count + 1)
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(setup[0][0], parent, result.dispatch, diagnostics)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("dispatch_feasibility_satisfied", False),
        ("dispatch_feasibility_violation_detected", True),
        ("dispatch_feasibility_evaluation_resolved", False),
        ("dispatch_feasibility_evaluation_applicable", False),
    ],
)
def test_selected_row_requires_all_canonical_full_feasibility_flags(
    column: str, value: bool
) -> None:
    setup = s10b._setup()
    parent = s10b._run(setup).feasibility.copy(deep=True)
    result = _run(setup)
    output = result.dispatch.copy(deep=True)
    parent.iloc[0, parent.columns.get_loc(column)] = value
    output.iloc[0, output.columns.get_loc(column)] = value
    with pytest.raises(RuntimeError, match="fully feasible canonical S10B proof"):
        _validate_result(setup[0][0], parent, output, result.diagnostics)


def test_validator_rejects_coherent_selection_state_mismatch() -> None:
    setup = s10b._setup(p=None)
    parent = s10b._run(setup).feasibility
    result = _run(setup)
    output = result.dispatch.copy(deep=True)
    output.iloc[0, output.columns.get_loc("dispatch_selection_state")] = (
        "resolved_no_selected_dispatch_known_infeasible_request"
    )
    with pytest.raises(RuntimeError):
        _validate_result(setup[0][0], parent, output, result.diagnostics)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"selected_zero_active_power_count": 0, "selected_positive_active_power_count": 0},
            "active-power diagnostics",
        ),
        (
            {
                "selected_q_injection_count": 0,
                "selected_q_absorption_count": 0,
                "selected_q_zero_count": 0,
            },
            "reactive-power diagnostics",
        ),
        (
            {
                "selected_dispatch_count": 0,
                "selected_zero_active_power_count": 0,
                "selected_positive_active_power_count": 0,
                "selected_q_injection_count": 0,
                "selected_q_absorption_count": 0,
                "selected_q_zero_count": 0,
            },
            "selected-dispatch diagnostics",
        ),
    ],
)
def test_validator_rejects_selected_diagnostic_nonclosure(
    changes: dict[str, int], message: str
) -> None:
    setup = s10b._setup(p=0.0, q=20.0)
    parent = s10b._run(setup).feasibility
    result = _run(setup)
    diagnostics = replace(result.diagnostics, **changes)
    with pytest.raises(RuntimeError, match=message):
        _validate_result(setup[0][0], parent, result.dispatch, diagnostics)


def test_output_ownership() -> None:
    setup = s10b._setup()
    first = _run(setup)
    second = _run(setup)
    first.dispatch.iloc[0, first.dispatch.columns.get_loc("p_selected_w")] = 999.0
    assert second.dispatch.iloc[0]["p_selected_w"] != 999.0


def test_two_inverter_canonical_order_is_independent_of_mapping_order() -> None:
    topology = s10b.ElectricalTopologyConfig(
        inverters=[
            s10b.s91_support._topology(inverter_id="inverter-a").inverters[0],
            s10b.s91_support._topology(inverter_id="inverter-b").inverters[0],
        ]
    )
    setup = s10b._setup(topology=topology)
    first = _run(setup)
    reversed_setup = list(setup)
    reversed_setup[2] = dict(reversed(list(setup[2].items())))
    reversed_setup[3] = dict(reversed(list(setup[3].items())))
    reversed_setup[4] = dict(reversed(list(setup[4].items())))
    second = _run(tuple(reversed_setup))
    pd.testing.assert_frame_equal(first.dispatch, second.dispatch, check_exact=True)
    assert first.diagnostics == second.diagnostics
    assert list(first.dispatch.index.get_level_values("inverter_id")) == [
        "inverter-a",
        "inverter-b",
    ]


def test_empty_topology_has_stable_schema_and_dtypes() -> None:
    setup = s10b._setup(topology=s10b.ElectricalTopologyConfig())
    result = _run(setup)
    assert result.dispatch.empty
    assert result.dispatch.index.names == ["timestamp", "inverter_id"]
    assert result.diagnostics == TopologyInverterDispatchSelectionDiagnostics(
        inverter_count=0,
        represented_inverter_count=0,
        timestamp_count=0,
        row_count=0,
        evaluation_resolved_count=0,
        evaluation_unresolved_count=0,
        applicable_count=0,
        selected_dispatch_count=0,
        no_selection_known_infeasible_count=0,
        no_selection_partial_authority_count=0,
        upstream_feasibility_unresolved_count=0,
        inactive_not_applicable_count=0,
        selected_zero_active_power_count=0,
        selected_positive_active_power_count=0,
        selected_q_injection_count=0,
        selected_q_absorption_count=0,
        selected_q_zero_count=0,
        model=TOPOLOGY_INVERTER_DISPATCH_SELECTION_MODEL_ID,
    )
    assert all(
        str(dtype) == "float64"
        for dtype in result.dispatch[["p_selected_w", "q_selected_var", "s_selected_va"]].dtypes
    )
    assert str(result.dispatch["selected_active_power_is_zero"].dtype) == "boolean"


def test_diagnostics_close_for_selected_request() -> None:
    diagnostics = _run(s10b._setup(p=0.0, q=20.0)).diagnostics
    assert diagnostics.evaluation_resolved_count + diagnostics.evaluation_unresolved_count == 1
    assert diagnostics.selected_dispatch_count == 1
    assert diagnostics.selected_zero_active_power_count == 1
    assert diagnostics.selected_q_injection_count == 1
