from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import revenue_meter_loss_attribution as module
from heliotelligence.physics.revenue_meter_interval_benchmark import (
    calculate_topology_revenue_meter_interval_benchmark,
)
from heliotelligence.physics.revenue_meter_power_benchmark import (
    calculate_topology_revenue_meter_power_benchmark,
)
from tests.unit.test_physics import test_inverter_dispatch_feasibility as support
from tests.unit.test_physics.test_revenue_meter_power_benchmark import _values as _s14a_values

_CACHE: dict[str, Any] | None = None


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


def _values(*, measured_offset: float = 0.0, meter_node: str = "grid-node") -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        values = _s14a_values(
            measured_p_offset=0.0,
            measured_q=0.0,
            meter_node=meter_node,
        )
        values["revenue_meter_power_benchmark"] = calculate_topology_revenue_meter_power_benchmark(
            **values
        )
        values["revenue_meter_interval_benchmark"] = (
            calculate_topology_revenue_meter_interval_benchmark(**values)
        )
        _CACHE = values
    values = dict(_CACHE)
    if measured_offset:
        benchmark = values["revenue_meter_power_benchmark"]
        states = benchmark.states.copy(deep=True)
        row = states.iloc[0]
        measured = float(row["expected_active_power_w"]) + measured_offset
        states.iloc[0, states.columns.get_loc("measured_active_power_w")] = measured
        states.iloc[
            0, states.columns.get_loc("active_power_residual_measured_minus_expected_w")
        ] = measured_offset
        values["revenue_meter_power_benchmark"] = replace(benchmark, states=states)
    return values


def _parents() -> tuple[Any, ...]:
    return module._parents(_values())


def _instant_result(parents: tuple[Any, ...]) -> Any:
    index = parents[5].states.index.copy()
    records = [module._instant_record(parents, key) for key in index]
    frame = module._frame(index, records, interval=False)
    interval_index = parents[6].states.index.copy()
    interval = module._frame(
        interval_index,
        [module._interval_record(parents, key) for key in interval_index],
        interval=True,
    )
    return module.TopologyRevenueMeterDeliveryLossAttributionResult(
        frame, interval, module._diagnostics(parents[3], frame, interval)
    )


def _interval_parents() -> tuple[Any, ...]:
    parents = list(_parents())
    s11c, _s12a, s12m, _s13a, s13c, _s14a, s14b = parents
    end, meter_id = s14b.states.index[0]
    start = end - pd.Timedelta(minutes=30)

    def duplicate(frame: pd.DataFrame, identity: str) -> pd.DataFrame:
        result = frame.copy(deep=True)
        source = result.loc[(end, identity)].copy(deep=True)
        result.loc[(start, identity), :] = source
        return result.sort_index()

    parents[0] = replace(
        s11c, collection_exit_states=duplicate(s11c.collection_exit_states, "exit")
    )
    parents[2] = replace(s12m, states=duplicate(s12m.states, "tx-1"))
    parents[4] = replace(s13c, revenue_meter_states=duplicate(s13c.revenue_meter_states, meter_id))
    expected_p = float(
        s13c.revenue_meter_states.loc[(end, meter_id)]["expected_p_at_revenue_meter_w"]
    )
    measured_p = expected_p + 10.0
    states = s14b.states.copy(deep=True)
    values: dict[str, object] = {
        "s14b_benchmark_eligible": True,
        "benchmark_eligible": True,
        "interval_start_timestamp": start,
        "averaging_interval_seconds": 1800.0,
        "expected_interval_sample_timestamps": (start, end),
        "expected_active_energy_wh": expected_p * 0.5,
        "measured_active_energy_wh": measured_p * 0.5,
        "active_energy_residual_measured_minus_expected_wh": 5.0,
        "revenue_meter_interval_benchmark_state": (
            "resolved_interval_average_revenue_meter_energy_benchmark"
        ),
    }
    for column, value in values.items():
        if column in states.columns:
            states.at[(end, meter_id), column] = value
    parents[6] = replace(s14b, states=states)
    return tuple(parents)


def test_public_instantaneous_accounting_uses_owned_components_once() -> None:
    result = module.calculate_topology_revenue_meter_delivery_loss_attribution(**_values())
    row = result.instantaneous_states.iloc[0]
    assert row["revenue_meter_delivery_attribution_state"] == (
        "resolved_instantaneous_revenue_meter_delivery_attribution"
    )
    assert row["contributing_transformer_ids"] == ("tx-1",)
    assert row["contributing_collection_exit_ids"] == ("exit",)
    assert row["selected_inverter_ac_source_power_w"] == pytest.approx(
        row["lv_ac_delivered_to_transformer_collection_power_w"]
        + row["lv_ac_owned_series_loss_w"]
        + row["lv_ac_conservation_residual_w"]
    )
    assert row["modeled_delivery_active_consumption_w"] == pytest.approx(
        row["lv_ac_owned_series_loss_w"]
        + row["transformer_owned_active_loss_w"]
        + row["mv_hv_active_consumption_to_meter_w"]
    )
    assert row["expected_revenue_meter_active_power_w"] == pytest.approx(
        row["reconstructed_expected_meter_active_power_w"]
        + row["model_accounting_closure_residual_w"]
    )
    assert row["measured_revenue_meter_active_power_w"] == pytest.approx(
        row["reconstructed_measured_meter_active_power_w"]
    )
    assert row["unexplained_meter_residual_measured_minus_expected_w"] == 0.0


@pytest.mark.parametrize("residual", [20.0, -20.0])
def test_signed_unexplained_residual_is_preserved_without_causal_label(residual: float) -> None:
    parents = list(_parents())
    benchmark = parents[5]
    states = benchmark.states.copy(deep=True)
    expected = float(states.iloc[0]["expected_active_power_w"])
    states.iloc[0, states.columns.get_loc("measured_active_power_w")] = expected + residual
    states.iloc[0, states.columns.get_loc("active_power_residual_measured_minus_expected_w")] = (
        residual
    )
    parents[5] = replace(benchmark, states=states)
    row = _instant_result(tuple(parents)).instantaneous_states.iloc[0]
    assert row["unexplained_meter_residual_measured_minus_expected_w"] == residual
    assert row["reconstructed_measured_meter_active_power_w"] == pytest.approx(expected + residual)


def test_missing_unresolved_and_boundary_mismatch_have_controlled_states() -> None:
    base = _parents()
    timestamp, _meter = base[5].states.index[0]
    cases: list[tuple[int, Any, str]] = []
    missing = base[0].collection_exit_states.drop(index=(timestamp, "exit"))
    cases.append(
        (
            0,
            replace(base[0], collection_exit_states=missing),
            "unresolved_missing_delivery_component_state",
        )
    )
    unresolved = base[0].collection_exit_states.copy(deep=True)
    unresolved.at[(timestamp, "exit"), "lv_ac_operating_solution_resolved"] = False
    cases.append(
        (
            0,
            replace(base[0], collection_exit_states=unresolved),
            "unresolved_delivery_component_operating_solution",
        )
    )
    mismatch = base[2].states.copy(deep=True)
    mismatch.at[(timestamp, "tx-1"), "collection_p_w"] += 1.0
    cases.append((2, replace(base[2], states=mismatch), "unresolved_component_boundary_closure"))
    for position, parent, expected_state in cases:
        parents = list(base)
        parents[position] = parent
        row = _instant_result(tuple(parents)).instantaneous_states.iloc[0]
        assert row["revenue_meter_delivery_attribution_state"] == expected_state
        assert pd.isna(row["modeled_delivery_active_consumption_w"])


def test_interval_half_hour_integrates_exact_support_and_closes_energy() -> None:
    parents = _interval_parents()
    key = parents[6].states.index[0]
    record = module._interval_record(parents, key)
    assert record["revenue_meter_interval_delivery_attribution_state"] == (
        "resolved_interval_revenue_meter_delivery_attribution"
    )
    assert record["selected_inverter_ac_source_energy_wh"] == pytest.approx(
        float(parents[0].collection_exit_states.iloc[0]["selected_p_total_w"]) * 0.5
    )
    assert record["unexplained_meter_residual_measured_minus_expected_wh"] == 5.0
    assert record["measured_revenue_meter_active_energy_wh"] == pytest.approx(
        record["reconstructed_measured_meter_active_energy_wh"]
    )


def test_interval_missing_interior_component_is_not_bridged() -> None:
    parents = list(_interval_parents())
    end, meter = parents[6].states.index[0]
    start = end - pd.Timedelta(minutes=30)
    middle = start + pd.Timedelta(minutes=10)
    s14b = parents[6]
    states = s14b.states.copy(deep=True)
    states.at[(end, meter), "expected_interval_sample_timestamps"] = (start, middle, end)
    parents[6] = replace(s14b, states=states)
    record = module._interval_record(tuple(parents), (end, meter))
    assert record["revenue_meter_interval_delivery_attribution_state"] == (
        "unresolved_missing_interval_delivery_component_state"
    )


def test_result_tampering_and_diagnostics_are_rejected() -> None:
    parents = _parents()
    result = _instant_result(parents)
    for column, value in (
        ("selected_inverter_ac_source_power_w", 1.0),
        ("transformer_owned_active_loss_w", 2.0),
        ("mv_hv_active_consumption_to_meter_w", 3.0),
        ("model_accounting_closure_residual_w", 4.0),
        ("revenue_meter_delivery_attribution_state", "wrong"),
    ):
        states = result.instantaneous_states.copy(deep=True)
        states.at[states.index[0], column] = value
        with pytest.raises(RuntimeError, match="independent exact closure"):
            module._validate_result(parents, replace(result, instantaneous_states=states))
    with pytest.raises(RuntimeError, match="diagnostics"):
        module._validate_result(
            parents,
            replace(
                result,
                diagnostics=replace(result.diagnostics, instantaneous_attribution_resolved_count=0),
            ),
        )


def test_empty_schemas_dtypes_and_source_plane_exclusions() -> None:
    index = pd.MultiIndex.from_tuples([], names=["timestamp", "revenue_meter_id"])
    instant = module._frame(index, [], interval=False)
    interval = module._frame(index, [], interval=True)
    assert tuple(instant.columns) == module._INSTANT_COLUMNS
    assert tuple(interval.columns) == module._INTERVAL_COLUMNS
    assert instant["contributing_transformer_count"].dtype == "int64"
    assert instant["s14a_benchmark_eligible"].dtype == "bool"
    assert instant["selected_inverter_ac_source_power_w"].dtype == "float64"
    assert interval["selected_inverter_ac_source_energy_wh"].dtype == "float64"
    source = Path(module.__file__).read_text()
    for excluded in (
        "dc_collection",
        "inverter_accounting",
        "conversion_loss_w",
        "clipping_loss_w",
        "p_mppt_input_mismatch_w",
    ):
        assert excluded not in source
    assert "percentage" not in source
    assert "root_cause" not in source
