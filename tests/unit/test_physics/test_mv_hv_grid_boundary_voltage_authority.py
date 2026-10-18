from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import mv_hv_grid_boundary_voltage_authority as module
from heliotelligence.physics.mv_hv_grid_boundary_voltage_authority import (
    MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_CONTRACT_ID,
    MvHvGridBoundaryVoltageState,
    resolve_topology_mv_hv_grid_boundary_voltage_authority,
)
from heliotelligence.physics.mv_hv_network_authority import (
    resolve_topology_mv_hv_network_authority,
)
from tests.unit.test_physics.test_mv_hv_network_authority import (
    _grid,
    _level,
    _node,
)
from tests.unit.test_physics.test_mv_hv_network_authority import (
    _inputs as _s13a_inputs,
)

T1 = pd.Timestamp("2026-01-01T00:00:00Z")
T2 = pd.Timestamp("2026-01-01T00:05:00Z")


def _voltage(value: float = 10_650.0) -> MvHvGridBoundaryVoltageState:
    return MvHvGridBoundaryVoltageState(
        value,
        "line_to_line_rms",
        "grid_interconnection_boundary",
        "grid SCADA",
        "high",
    )


def _inputs(
    evidence: dict[tuple[pd.Timestamp, str], MvHvGridBoundaryVoltageState] | None = None,
) -> dict[str, Any]:
    values = _s13a_inputs()
    parent = resolve_topology_mv_hv_network_authority(**values)
    return {
        **values,
        "mv_hv_network_authority": parent,
        "grid_boundary_voltage_by_key": (
            evidence if evidence is not None else {(T1, "grid"): _voltage()}
        ),
    }


def _resolve(values: dict[str, Any] | None = None) -> Any:
    return resolve_topology_mv_hv_grid_boundary_voltage_authority(**(values or _inputs()))


def _two_boundary_inputs() -> dict[str, Any]:
    values = _s13a_inputs()
    values["mv_hv_voltage_level_by_id"] = {
        "11-kv": _level(),
        "33-kv": _level("33-kv", 33_000.0),
    }
    values["mv_hv_node_by_id"] = {
        **values["mv_hv_node_by_id"],
        "exit-b": _node("exit-b", "network_exit", "33-kv"),
    }
    values["mv_hv_grid_boundary_by_id"] = {
        "grid-a": _grid("grid-a", "exit"),
        "grid-b": _grid("grid-b", "exit-b"),
    }
    parent = resolve_topology_mv_hv_network_authority(**values)
    return {
        **values,
        "mv_hv_network_authority": parent,
        "grid_boundary_voltage_by_key": {
            (T2, "grid-b"): _voltage(33_100.0),
            (T1, "grid-a"): _voltage(11_050.0),
        },
    }


def test_positive_voltage_resolves_with_static_context() -> None:
    result = _resolve()
    row = result.states.loc[(T1, "grid")]
    assert row["grid_boundary_voltage_authority_state"] == (
        "resolved_explicit_grid_interconnection_boundary_voltage_state"
    )
    assert row["grid_boundary_node_id"] == "exit"
    assert row["grid_boundary_voltage_level_id"] == "11-kv"
    assert row["nominal_line_to_line_rms_v"] == 11_000.0
    assert row["voltage_line_to_line_rms_v"] == 10_650.0
    assert not row["voltage_is_zero"]


def test_zero_voltage_is_explicit_and_distinct_from_missing() -> None:
    values = _two_boundary_inputs()
    values["grid_boundary_voltage_by_key"] = {(T1, "grid-a"): _voltage(0.0)}
    result = _resolve(values)
    assert result.states.loc[(T1, "grid-a"), "voltage_is_zero"]
    assert result.states.loc[(T1, "grid-a"), "grid_boundary_voltage_authority_resolved"]
    assert pd.isna(result.states.loc[(T1, "grid-b"), "voltage_is_zero"])
    assert pd.isna(result.states.loc[(T1, "grid-b"), "voltage_line_to_line_rms_v"])


def test_cartesian_timestamp_boundary_closure_has_no_cross_boundary_inference() -> None:
    result = _resolve(_two_boundary_inputs())
    assert tuple(result.states.index) == (
        (T1, "grid-a"),
        (T1, "grid-b"),
        (T2, "grid-a"),
        (T2, "grid-b"),
    )
    assert result.states.loc[(T1, "grid-a"), "voltage_line_to_line_rms_v"] == 11_050.0
    assert pd.isna(result.states.loc[(T1, "grid-b"), "voltage_line_to_line_rms_v"])
    assert pd.isna(result.states.loc[(T2, "grid-a"), "voltage_line_to_line_rms_v"])
    assert result.states.loc[(T2, "grid-b"), "voltage_line_to_line_rms_v"] == 33_100.0
    assert result.diagnostics.row_count == 4
    assert result.diagnostics.voltage_state_missing_count == 2


def test_mapping_insertion_order_does_not_change_result() -> None:
    first = _two_boundary_inputs()
    second = _two_boundary_inputs()
    second["grid_boundary_voltage_by_key"] = dict(
        reversed(tuple(second["grid_boundary_voltage_by_key"].items()))
    )
    one, two = _resolve(first), _resolve(second)
    pd.testing.assert_frame_equal(one.states, two.states, check_exact=True)
    assert tuple(one.voltage_states_by_key.items()) == tuple(two.voltage_states_by_key.items())


def test_empty_evidence_has_stable_empty_schema() -> None:
    result = _resolve(_inputs({}))
    assert result.states.empty
    assert list(result.states.index.names) == ["timestamp", "grid_boundary_id"]
    assert tuple(result.states.columns) == module._COLUMNS
    assert result.diagnostics.timestamp_count == result.diagnostics.row_count == 0
    assert str(result.states["voltage_is_zero"].dtype) == "boolean"


def test_empty_boundary_universe_has_stable_empty_schema() -> None:
    values = _s13a_inputs()
    values["mv_hv_grid_boundary_by_id"] = {}
    parent = resolve_topology_mv_hv_network_authority(**values)
    result = _resolve(
        {**values, "mv_hv_network_authority": parent, "grid_boundary_voltage_by_key": {}}
    )
    assert result.states.empty
    assert result.diagnostics.grid_boundary_count == 0
    assert tuple(result.states.columns) == module._COLUMNS


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), float("-inf"), True, "11000"])
def test_invalid_voltage_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="voltage_line_to_line_rms_v"):
        MvHvGridBoundaryVoltageState(
            value,  # type: ignore[arg-type]
            "line_to_line_rms",
            "grid_interconnection_boundary",
            "source",
            "high",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("voltage_basis", "phase_to_neutral"),
        ("reference_plane", "revenue_meter_boundary"),
        ("parameter_source", " source "),
        ("confidence", "certain"),
    ],
)
def test_invalid_voltage_metadata_is_rejected(field: str, value: str) -> None:
    kwargs: dict[str, object] = {
        "voltage_line_to_line_rms_v": 11_000.0,
        "voltage_basis": "line_to_line_rms",
        "reference_plane": "grid_interconnection_boundary",
        "parameter_source": "source",
        "confidence": "high",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        MvHvGridBoundaryVoltageState(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "key",
    [
        T1,
        (T1,),
        (datetime(2026, 1, 1), "grid"),
        (pd.NaT, "grid"),
        (T1, " grid"),
    ],
)
def test_malformed_keys_are_rejected(key: object) -> None:
    values = _inputs()
    values["grid_boundary_voltage_by_key"] = {key: _voltage()}
    with pytest.raises((TypeError, ValueError)):
        _resolve(values)


def test_unknown_boundary_and_node_id_substitution_are_rejected() -> None:
    for identifier in ("unknown", "exit"):
        values = _inputs()
        values["grid_boundary_voltage_by_key"] = {(T1, identifier): _voltage()}
        with pytest.raises(ValueError, match="unknown grid boundary"):
            _resolve(values)


def test_incompatible_timezone_semantics_are_rejected() -> None:
    values = _inputs()
    values["grid_boundary_voltage_by_key"] = {
        (T1, "grid"): _voltage(),
        (pd.Timestamp("2026-01-02"), "grid"): _voltage(),
    }
    with pytest.raises(ValueError, match="incompatible timezone semantics"):
        _resolve(values)


def test_missing_network_basis_preserves_voltage_but_is_unresolved() -> None:
    values = _inputs()
    values["mv_hv_network_basis"] = None
    values["mv_hv_network_authority"] = resolve_topology_mv_hv_network_authority(
        **{key: value for key, value in values.items() if key not in {
            "mv_hv_network_authority", "grid_boundary_voltage_by_key"
        }}
    )
    result = _resolve(values)
    row = result.states.loc[(T1, "grid")]
    assert row["voltage_line_to_line_rms_v"] == 10_650.0
    assert row["parameter_source"] == "grid SCADA"
    assert not row["grid_boundary_voltage_authority_resolved"]
    assert row["grid_boundary_voltage_authority_state"] == (
        "unresolved_no_mv_hv_network_basis_authority"
    )


def test_result_mapping_is_detached_and_immutable() -> None:
    supplied = {(T1, "grid"): _voltage()}
    result = _resolve(_inputs(supplied))
    supplied.clear()
    assert (T1, "grid") in result.voltage_states_by_key
    assert type(result.voltage_states_by_key) is MappingProxyType
    with pytest.raises(TypeError):
        result.voltage_states_by_key[(T2, "grid")] = _voltage()  # type: ignore[index]


@pytest.mark.parametrize(
    "component",
    [
        "transformer_states",
        "voltage_levels_by_id",
        "nodes_by_id",
        "grid_boundary_by_id",
        "diagnostics",
    ],
)
def test_strong_s13a_parent_replay_rejects_tampering(component: str) -> None:
    values = _inputs()
    parent = values["mv_hv_network_authority"]
    if component == "transformer_states":
        changed = parent.transformer_states.copy(deep=True)
        changed.iloc[0, 0] = not changed.iloc[0, 0]
        tampered = replace(parent, transformer_states=changed)
    elif component == "diagnostics":
        tampered = replace(
            parent, diagnostics=replace(parent.diagnostics, grid_boundary_count=99)
        )
    else:
        mapping = dict(getattr(parent, component))
        mapping.pop(next(iter(mapping)))
        tampered = replace(parent, **{component: MappingProxyType(mapping)})
    values["mv_hv_network_authority"] = tampered
    with pytest.raises(RuntimeError, match="supplied S13A"):
        _resolve(values)


def test_validator_is_independent_of_production_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    values = _inputs()
    result = _resolve(values)

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("production builder was called")

    monkeypatch.setattr(module, "_record", fail)
    monkeypatch.setattr(module, "_frame", fail)
    monkeypatch.setattr(module, "_diagnostics", fail)
    module._validate_result(values["mv_hv_network_authority"], result)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("voltage_line_to_line_rms_v", 1.0),
        ("voltage_is_zero", True),
        ("grid_boundary_node_id", "wrong"),
        ("nominal_line_to_line_rms_v", 1.0),
        ("grid_boundary_voltage_state_present", False),
        ("grid_boundary_voltage_authority_resolved", False),
        ("parameter_source", "wrong"),
        ("grid_boundary_voltage_authority_state", "wrong"),
        ("mv_hv_grid_boundary_voltage_authority_contract", "wrong"),
    ],
)
def test_independent_validator_rejects_representative_frame_tampering(
    column: str, value: object
) -> None:
    values = _inputs()
    result = _resolve(values)
    changed = result.states.copy(deep=True)
    changed.iloc[0, changed.columns.get_loc(column)] = value
    with pytest.raises(RuntimeError, match="independent exact closure"):
        module._validate_result(
            values["mv_hv_network_authority"], replace(result, states=changed)
        )


def test_validator_rejects_diagnostics_tampering() -> None:
    values = _inputs()
    result = _resolve(values)
    tampered = replace(
        result,
        diagnostics=replace(result.diagnostics, voltage_state_present_count=99),
    )
    with pytest.raises(RuntimeError, match="diagnostics"):
        module._validate_result(values["mv_hv_network_authority"], tampered)


def test_public_schema_order_and_dtypes_are_explicit() -> None:
    result = _resolve()
    assert tuple(result.states.columns) == module._COLUMNS
    assert len(module._COLUMNS) == len(set(module._COLUMNS))
    assert list(result.states.index.names) == ["timestamp", "grid_boundary_id"]
    assert str(result.states["network_basis_resolved"].dtype) == "bool"
    assert str(result.states["nominal_line_to_line_rms_v"].dtype) == "float64"
    assert str(result.states["voltage_line_to_line_rms_v"].dtype) == "float64"
    assert str(result.states["voltage_is_zero"].dtype) == "boolean"
    assert result.states.iloc[0]["mv_hv_grid_boundary_voltage_authority_contract"] == (
        MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_CONTRACT_ID
    )


def test_source_has_no_s12m_or_operating_power_dependency() -> None:
    source = module.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    for forbidden in (
        "transformer_advanced_operating_solution",
        "p_network_terminal_w",
        "q_network_terminal_var",
        "revenue_meter_telemetry",
    ):
        assert forbidden not in text
