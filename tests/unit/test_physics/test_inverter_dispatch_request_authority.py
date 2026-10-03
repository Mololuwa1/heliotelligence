"""Tests for S10A explicit inverter active-power dispatch-request authority."""

from __future__ import annotations

import importlib
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter_ac_authority import (
    resolve_topology_inverter_ac_capability_authority,
)
from heliotelligence.physics.inverter_dispatch_request_authority import (
    TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_MODEL_ID,
    TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_SCOPE,
    InverterActivePowerDispatchRequest,
    resolve_topology_inverter_active_power_dispatch_request_authority,
)
from heliotelligence.physics.inverter_thermal_authority import (
    resolve_topology_inverter_thermal_derating_authority,
)

s94d: Any = importlib.import_module(
    "tests.unit.test_physics.test_inverter_temperature_capability"
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


def _request(
    value: float = 7500.0,
    *, source: str = "ppc:active_power_setpoint",
    confidence: str = "high",
    mode: str | None = "power_setpoint",
) -> InverterActivePowerDispatchRequest:
    return InverterActivePowerDispatchRequest(
        value,
        "inverter_ac_output",
        "absolute_active_power_setpoint",
        source,
        confidence,  # type: ignore[arg-type]
        mode,
    )


def _parent(
    context: tuple[Any, ...],
    *, thermal_mapping: dict[str, Any] | None = None,
    temperatures: dict[tuple[pd.Timestamp, str], Any] | None = None,
) -> tuple[Any, dict[str, Any], dict[tuple[pd.Timestamp, str], Any]]:
    topology = context[0]
    thermal_mapping = thermal_mapping if thermal_mapping is not None else {
        inverter.id: s94d._thermal() for inverter in topology.inverters
    }
    temperatures = temperatures if temperatures is not None else {
        (pd.Timestamp(key[0]), str(key[1])): s94d._temperature(50.0)
        for key in context[5].capability.index
    }
    return s94d._run(context, thermal_mapping, temperatures), thermal_mapping, temperatures


def _run(
    context: tuple[Any, ...],
    parent: Any,
    thermal_mapping: dict[str, Any],
    temperatures: dict[tuple[pd.Timestamp, str], Any],
    requests: Any,
) -> Any:
    topology, upstream, accounting, capabilities, q_requests, pqs = context
    (
        topology_string_iv, branch_authority, mppt_input_string_iv,
        mppt_input_operating_points, names, inverter_authority, limits, envelope,
        ac, potential,
    ) = upstream
    ac_authority = resolve_topology_inverter_ac_capability_authority(topology, capabilities)
    thermal_authority = resolve_topology_inverter_thermal_derating_authority(
        topology, thermal_mapping
    )
    return resolve_topology_inverter_active_power_dispatch_request_authority(
        topology, topology_string_iv, branch_authority, mppt_input_string_iv,
        mppt_input_operating_points, names, inverter_authority, limits, envelope,
        ac, potential, accounting, capabilities, ac_authority, q_requests, pqs,
        thermal_mapping, thermal_authority, temperatures, parent, requests,
    )


def _key(parent: Any) -> tuple[pd.Timestamp, str]:
    timestamp, inverter_id = parent.capability.index[0]
    return pd.Timestamp(timestamp), str(inverter_id)


@pytest.mark.parametrize("value", [0, 1, 2_000_000_000.0])
def test_request_accepts_nonnegative_finite_values(value: float) -> None:
    assert _request(value).active_power_setpoint_w == float(value)


@pytest.mark.parametrize(
    "value", [-1.0, True, False, float("nan"), float("inf"), -float("inf"), "1"]
)
def test_request_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError):
        _request(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reference_plane": "poi"},
        {"request_semantics": "maximum_power_cap"},
        {"parameter_source": " "},
        {"confidence": "certain"},
        {"controller_mode": ""},
        {"controller_mode": 1},
    ],
)
def test_request_rejects_invalid_contract_fields(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "active_power_setpoint_w": 1.0,
        "reference_plane": "inverter_ac_output",
        "request_semantics": "absolute_active_power_setpoint",
        "parameter_source": "scada:test",
        "confidence": "high",
        "controller_mode": None,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        InverterActivePowerDispatchRequest(**values)  # type: ignore[arg-type]


def test_missing_and_explicit_zero_are_distinct() -> None:
    context = s94d._context()
    parent, thermal, temperatures = _parent(context)
    missing = _run(context, parent, thermal, temperatures, {})
    zero = _run(context, parent, thermal, temperatures, {_key(parent): _request(0.0)})
    missing_row = missing.states.iloc[0]
    zero_row = zero.states.iloc[0]
    assert not missing_row["dispatch_request_authority_resolved"]
    assert pd.isna(missing_row["active_power_setpoint_w"])
    assert pd.isna(missing_row["active_power_setpoint_is_zero"])
    assert zero_row["dispatch_request_authority_resolved"]
    assert zero_row["active_power_setpoint_w"] == 0.0
    assert zero_row["active_power_setpoint_is_zero"]


@pytest.mark.parametrize(
    ("context", "thermal", "temperatures"),
    [
        (lambda: s94d._context(), {}, {}),
        (lambda: s94d._context(zero=True), {}, {}),
        (lambda: s94d._context(smax=1.0), None, None),
    ],
)
def test_request_resolution_is_independent_of_parent_state(
    context: Any, thermal: Any, temperatures: Any
) -> None:
    built = context()
    parent, admitted_thermal, admitted_temperatures = _parent(
        built, thermal_mapping=thermal, temperatures=temperatures
    )
    result = _run(
        built, parent, admitted_thermal, admitted_temperatures, {_key(parent): _request()}
    )
    assert result.states.iloc[0]["dispatch_request_authority_resolved"]


def test_good_parent_does_not_imply_request() -> None:
    context = s94d._context()
    parent, thermal, temperatures = _parent(context)
    row = _run(context, parent, thermal, temperatures, {}).states.iloc[0]
    assert row["dispatch_request_authority_state"] == (
        "unresolved_no_explicit_inverter_active_power_dispatch_request"
    )


class _RequestSubclass(InverterActivePowerDispatchRequest):
    pass


@pytest.mark.parametrize(
    "mapping",
    [
        {("bad", "inverter-1"): _request()},
        {(pd.Timestamp("1999-01-01"), "inverter-1"): _request()},
        {(pd.Timestamp("2025-01-01"), 1): _request()},
        {(pd.Timestamp("2025-01-01"),): _request()},
        {(pd.Timestamp("2025-01-01"), "inverter-1"): 1.0},
        {(pd.Timestamp("2025-01-01"), "inverter-1"): {"active_power_setpoint_w": 1.0}},
    ],
)
def test_key_and_exact_request_admission(mapping: dict[Any, Any]) -> None:
    context = s94d._context()
    parent, thermal, temperatures = _parent(context)
    with pytest.raises((TypeError, ValueError)):
        _run(context, parent, thermal, temperatures, mapping)
    with pytest.raises(TypeError):
        _run(
            context, parent, thermal, temperatures,
            {
                _key(parent): _RequestSubclass(
                    1,
                    "inverter_ac_output",
                    "absolute_active_power_setpoint",
                    "x",
                    "high",
                )
            },
        )


def test_mapping_order_is_independent_and_topology_order_is_canonical() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[
            s91_support._topology(inverter_id="inverter-a").inverters[0],
            s91_support._topology(inverter_id="inverter-b").inverters[0],
        ]
    )
    context = s94d._context(topology=topology)
    parent, thermal, temperatures = _parent(context)
    keys = [(pd.Timestamp(k[0]), str(k[1])) for k in parent.capability.index]
    forward = {keys[0]: _request(7500, source="a"), keys[1]: _request(0, source="b")}
    reverse = dict(reversed(list(forward.items())))
    first = _run(context, parent, thermal, temperatures, forward)
    second = _run(
        context,
        parent,
        dict(reversed(list(thermal.items()))),
        dict(reversed(list(temperatures.items()))),
        reverse,
    )
    pd.testing.assert_frame_equal(first.states, second.states, check_exact=True)
    assert first.diagnostics == second.diagnostics
    assert list(first.states.index.get_level_values("inverter_id")) == ["inverter-a", "inverter-b"]


@pytest.mark.parametrize(
    "column",
    [
        "p_ac_available_w",
        "inverter_temperature_c",
        "temperature_capability_state",
        "thermal_active_power_limit_w",
        "topology_inverter_temperature_capability_contract",
    ],
)
def test_tampered_s94d_frame_is_rejected(column: str) -> None:
    context = s94d._context()
    parent, thermal, temperatures = _parent(context)
    changed = parent.capability.copy(deep=True)
    value = changed.iloc[0][column]
    changed.iloc[0, changed.columns.get_loc(column)] = (
        "tampered" if isinstance(value, str) else float(value) + 1.0
    )
    tampered = replace(parent, capability=changed)
    with pytest.raises(ValueError, match="canonical replay"):
        _run(context, tampered, thermal, temperatures, {})


def test_tampered_s94d_diagnostics_is_rejected() -> None:
    context = s94d._context()
    parent, thermal, temperatures = _parent(context)
    tampered = replace(parent, diagnostics=replace(parent.diagnostics, row_count=99))
    with pytest.raises(ValueError, match="diagnostics"):
        _run(context, tampered, thermal, temperatures, {})


def test_schema_provenance_dtypes_and_diagnostics_close() -> None:
    context = s94d._context()
    parent, thermal, temperatures = _parent(context)
    result = _run(context, parent, thermal, temperatures, {_key(parent): _request(10.0, mode=None)})
    row = result.states.iloc[0]
    assert row[
        "topology_inverter_active_power_dispatch_request_authority_contract"
    ] == TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_CONTRACT_ID
    assert row[
        "topology_inverter_active_power_dispatch_request_authority_model"
    ] == TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_MODEL_ID
    assert row[
        "topology_inverter_active_power_dispatch_request_authority_scope"
    ] == TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_SCOPE
    assert row[
        "topology_inverter_active_power_dispatch_request_authority_coverage_scope"
    ] == TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_COVERAGE_SCOPE
    assert str(result.states["active_power_setpoint_w"].dtype) == "float64"
    assert str(result.states["active_power_setpoint_is_zero"].dtype) == "boolean"
    assert result.diagnostics.resolved_request_count == 1
    assert result.diagnostics.controller_mode_absent_count == 1


def test_output_ownership_and_mapping_immutability() -> None:
    context = s94d._context()
    parent, thermal, temperatures = _parent(context)
    source = {_key(parent): _request()}
    first = _run(context, parent, thermal, temperatures, source)
    second = _run(context, parent, thermal, temperatures, source)
    source.clear()
    first.states.iloc[0, first.states.columns.get_loc("active_power_setpoint_w")] = 1.0
    assert second.states.iloc[0]["active_power_setpoint_w"] == 7500.0
    assert len(first.requests_by_key) == 1
    assert isinstance(first.requests_by_key, MappingProxyType)
    with pytest.raises(TypeError):
        first.requests_by_key[_key(parent)] = _request()  # type: ignore[index]


def test_empty_topology_has_stable_schema_and_zero_diagnostics() -> None:
    context = s94d._context(topology=ElectricalTopologyConfig())
    parent, thermal, temperatures = _parent(context)
    result = _run(context, parent, thermal, temperatures, {})
    assert result.states.empty
    assert result.states.index.names == ["timestamp", "inverter_id"]
    assert str(result.states["active_power_setpoint_w"].dtype) == "float64"
    assert str(result.states["active_power_setpoint_is_zero"].dtype) == "boolean"
    assert result.diagnostics.row_count == 0
    assert not result.requests_by_key


def test_s10a_has_no_duplicate_q_or_selection_fields() -> None:
    module = importlib.import_module(
        "heliotelligence.physics.inverter_dispatch_request_authority"
    )
    columns = set(module._COLUMNS)
    assert not columns & {
        "reactive_power_setpoint_var", "q_dispatch_request_var", "power_factor_request",
        "selected_active_power_w", "selected_reactive_power_var", "grid_limit_kwac",
    }
