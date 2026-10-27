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


def test_no_contributing_transformer_never_claims_component_readiness() -> None:
    instant_parents = list(_parents())
    authority = instant_parents[3]
    transformer_states = authority.transformer_states.copy(deep=True)
    transformer_states.loc[:, "revenue_meter_on_transformer_path"] = False
    instant_parents[3] = replace(authority, transformer_states=transformer_states)
    instant = _instant_result(tuple(instant_parents)).instantaneous_states.iloc[0]
    assert instant["revenue_meter_delivery_attribution_state"] == (
        "unresolved_no_contributing_transformer_path"
    )
    assert not instant["delivery_component_rows_complete"]
    assert not instant["delivery_component_operating_states_resolved"]
    assert not instant["component_boundary_closure_satisfied"]
    for column in (
        "selected_inverter_ac_source_power_w",
        "lv_ac_owned_series_loss_w",
        "transformer_owned_active_loss_w",
        "mv_hv_active_consumption_to_meter_w",
        "modeled_delivery_active_consumption_w",
    ):
        assert pd.isna(instant[column])

    interval_parents = list(_interval_parents())
    interval_authority = interval_parents[3]
    interval_transformers = interval_authority.transformer_states.copy(deep=True)
    interval_transformers.loc[:, "revenue_meter_on_transformer_path"] = False
    interval_parents[3] = replace(interval_authority, transformer_states=interval_transformers)
    key = interval_parents[6].states.index[0]
    interval = module._interval_record(tuple(interval_parents), key)
    assert interval["revenue_meter_interval_delivery_attribution_state"] == (
        "unresolved_no_contributing_transformer_path"
    )
    assert not interval["interval_delivery_component_rows_complete"]
    assert not interval["interval_delivery_component_states_resolved"]
    assert not interval["interval_component_boundary_closure_satisfied"]


def test_internal_meter_boundary_delta_excludes_gridward_network_consumption() -> None:
    values = _s14a_values(
        measured_p_offset=0.0,
        measured_q=0.0,
        meter_node="tx-node",
        resistance=5.0,
    )
    values["revenue_meter_power_benchmark"] = calculate_topology_revenue_meter_power_benchmark(
        **values
    )
    values["revenue_meter_interval_benchmark"] = (
        calculate_topology_revenue_meter_interval_benchmark(**values)
    )
    result = module.calculate_topology_revenue_meter_delivery_loss_attribution(**values)
    row = result.instantaneous_states.iloc[0]
    whole_tree_consumption = float(
        values["mv_hv_operating_solution"].network_exit_states.iloc[0][
            "net_network_active_consumption_w"
        ]
    )
    expected_boundary_delta = float(row["transformer_network_terminal_power_w"]) - float(
        row["expected_revenue_meter_active_power_w"]
    )
    assert row["mv_hv_active_consumption_to_meter_w"] == pytest.approx(expected_boundary_delta)
    assert whole_tree_consumption > 0.0
    assert row["mv_hv_active_consumption_to_meter_w"] != pytest.approx(whole_tree_consumption)
    assert row["expected_revenue_meter_active_power_w"] == pytest.approx(
        row["reconstructed_expected_meter_active_power_w"]
        + row["model_accounting_closure_residual_w"]
    )


def test_validator_is_independent_of_all_production_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parents = _parents()
    result = _instant_result(parents)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production helper used by validator")

    for name in (
        "_mapping",
        "_point",
        "_instant_record",
        "_integrate",
        "_interval_record",
        "_frame",
        "_diagnostics",
    ):
        monkeypatch.setattr(module, name, fail)
    module._validate_result(parents, result)


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
    assert instant["s12m_load_loss_fallback_present"].dtype == "bool"
    assert interval["s12m_load_loss_fallback_present"].dtype == "bool"
    assert instant["s12m_fallback_transformer_ids"].dtype == "object"
    assert interval["s12m_fallback_transformer_ids"].dtype == "object"
    assert instant["selected_inverter_ac_source_power_w"].dtype == "float64"
    assert interval["selected_inverter_ac_source_energy_wh"].dtype == "float64"
    source = Path(module.__file__).read_text()
    assert "__wrapped__" not in source
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


_FIDELITY_CACHE: dict[str, tuple[dict[str, Any], Any, tuple[Any, ...]]] = {}


def _attribution_fidelity_case(
    mode: str = "fallback",
) -> tuple[dict[str, Any], Any, tuple[Any, ...]]:
    if mode not in _FIDELITY_CACHE:
        options: dict[str, Any] = {"fallback": mode != "advanced", "measured_p_offset": 12.0}
        if mode == "deenergised":
            options.update(p=0.0, energised=False, boundary_voltage=11_000.0)
        values = _s14a_values(**options)
        values["revenue_meter_power_benchmark"] = calculate_topology_revenue_meter_power_benchmark(
            **values
        )
        values["revenue_meter_interval_benchmark"] = (
            calculate_topology_revenue_meter_interval_benchmark(**values)
        )
        result = module.calculate_topology_revenue_meter_delivery_loss_attribution(**values)
        parents = tuple(
            values[name]
            for name in (
                "lv_ac_collection_operating_solution",
                "transformer_static_authority",
                "transformer_advanced_operating_solution",
                "mv_hv_network_authority",
                "mv_hv_operating_solution",
                "revenue_meter_power_benchmark",
                "revenue_meter_interval_benchmark",
            )
        )
        _FIDELITY_CACHE[mode] = values, result, parents
    return _FIDELITY_CACHE[mode]


def _fidelity_interval_parents(mode: str) -> tuple[Any, ...]:
    """Exact stationary boundary support from real advanced/fallback parent solves.

    Only the admitted timestamp boundary is assembled internally; every component
    value and fidelity label is retained from its canonical single-point chain.
    """
    from heliotelligence.physics import revenue_meter_interval_benchmark as interval_module
    from heliotelligence.physics.revenue_meter_measurement_authority import (
        resolve_topology_revenue_meter_measurement_authority,
    )
    from tests.unit.test_physics.test_revenue_meter_power_benchmark import _measurement

    values, _, fallback = _attribution_fidelity_case()
    _, _, advanced = _attribution_fidelity_case("advanced")
    parents = list(advanced if mode == "advanced" else fallback)
    end, meter_id = parents[5].states.index[0]
    times = (end - pd.Timedelta(minutes=30), end - pd.Timedelta(minutes=15), end)

    def support_frame(position: int, frame_name: str, identity: str) -> pd.DataFrame:
        frames = []
        for index, timestamp in enumerate(times):
            use_fallback = mode == "all_fallback" or (mode == "subset" and index == 1)
            source = fallback if use_fallback else advanced
            frame = getattr(source[position], frame_name).loc[[(end, identity)]].copy(deep=True)
            frame.index = pd.MultiIndex.from_tuples(
                [(timestamp, identity)], names=frame.index.names
            )
            frames.append(frame)
        return pd.concat(frames).sort_index()

    parents[0] = replace(
        parents[0], collection_exit_states=support_frame(0, "collection_exit_states", "exit")
    )
    parents[2] = replace(parents[2], states=support_frame(2, "states", "tx-1"))
    parents[4] = replace(
        parents[4], revenue_meter_states=support_frame(4, "revenue_meter_states", meter_id)
    )
    meter = parents[4].revenue_meter_states.iloc[0]
    p, q = (
        float(meter["expected_p_at_revenue_meter_w"]),
        float(meter["expected_q_at_revenue_meter_var"]),
    )
    measurement_values = dict(
        values,
        revenue_meter_measured_power_by_key={
            (end, meter_id): _measurement(
                p + 10.0, q, temporal="interval_average_ending_at_timestamp", interval=1800.0
            ),
        },
    )
    measured = module._call(
        resolve_topology_revenue_meter_measurement_authority, measurement_values
    )
    interval_parents = parents[3], parents[4], measured
    record = interval_module._record(*interval_parents, end, meter_id)
    frame = interval_module._frame(((end, meter_id),), [record])
    benchmark = interval_module.TopologyRevenueMeterIntervalBenchmarkResult(
        frame,
        interval_module._diagnostics((meter_id,), (end,), frame),
    )
    interval_module._validate_result(interval_parents, benchmark)
    assert benchmark.states.iloc[0]["benchmark_eligible"]
    parents[6] = benchmark
    return tuple(parents)


@pytest.mark.parametrize(
    "mode,fallback_ids",
    [
        ("fallback", ("tx-1",)),
        ("advanced", ()),
        ("deenergised", ()),
    ],
)
def test_downstream_instantaneous_attribution_preserves_transformer_fidelity(
    mode: str,
    fallback_ids: tuple[str, ...],
) -> None:
    values, result, parents = _attribution_fidelity_case(mode)
    row = result.instantaneous_states.iloc[0]
    assert row["revenue_meter_delivery_attribution_state"] == (
        "resolved_instantaneous_revenue_meter_delivery_attribution"
    )
    assert row["unresolved_component_transformer_ids"] == ()
    assert row["s12m_fallback_transformer_ids"] == fallback_ids
    assert bool(row["s12m_load_loss_fallback_present"]) == bool(fallback_ids)
    tx = values["transformer_advanced_operating_solution"].states.iloc[0]
    assert row["transformer_owned_active_loss_w"] == tx["p_total_transformer_active_loss_w"]
    assert row["transformer_owned_active_loss_w"] == pytest.approx(
        tx["collection_p_w"] - tx["p_network_terminal_w"],
        rel=module._REL_TOL,
        abs=module._ABS_TOL,
    )
    assert row["modeled_delivery_active_consumption_w"] == pytest.approx(
        row["lv_ac_owned_series_loss_w"]
        + row["transformer_owned_active_loss_w"]
        + row["mv_hv_active_consumption_to_meter_w"],
        rel=module._REL_TOL,
        abs=module._ABS_TOL,
    )
    assert row["reconstructed_expected_meter_active_power_w"] == pytest.approx(
        row["expected_revenue_meter_active_power_w"],
        rel=module._REL_TOL,
        abs=module._ABS_TOL,
    )
    assert row["unexplained_meter_residual_measured_minus_expected_w"] == pytest.approx(
        row["measured_revenue_meter_active_power_w"] - row["expected_revenue_meter_active_power_w"],
        rel=module._REL_TOL,
        abs=module._ABS_TOL,
    )
    module._validate_result(parents, result)


@pytest.mark.parametrize(
    "mode,expected_ids",
    [
        ("all_fallback", ("tx-1",)),
        ("subset", ("tx-1",)),
        ("advanced", ()),
    ],
)
def test_downstream_interval_fallback_provenance_unions_exact_support(
    mode: str,
    expected_ids: tuple[str, ...],
) -> None:
    parents = _fidelity_interval_parents(mode)
    result = _instant_result(parents)
    module._validate_result(parents, result)
    row = result.interval_states.iloc[0]
    assert row["revenue_meter_interval_delivery_attribution_state"] == (
        "resolved_interval_revenue_meter_delivery_attribution"
    )
    assert row["s12m_fallback_transformer_ids"] == expected_ids
    assert bool(row["s12m_load_loss_fallback_present"]) == bool(expected_ids)
    times = row["expected_interval_sample_timestamps"]
    assert len(times) == 3
    losses = [
        float(parents[2].states.loc[(t, "tx-1")]["p_total_transformer_active_loss_w"])
        for t in times
    ]
    expected_energy = sum(
        (losses[i] + losses[i + 1]) * 0.5 * (times[i + 1] - times[i]).total_seconds() / 3600.0
        for i in range(len(times) - 1)
    )
    assert row["transformer_owned_active_loss_energy_wh"] == pytest.approx(
        expected_energy, rel=module._REL_TOL, abs=module._ABS_TOL
    )
    assert row["modeled_delivery_active_consumption_energy_wh"] == pytest.approx(
        row["lv_ac_owned_series_loss_energy_wh"]
        + row["transformer_owned_active_loss_energy_wh"]
        + row["mv_hv_active_consumption_to_meter_energy_wh"],
        rel=module._REL_TOL,
        abs=module._ABS_TOL,
    )
    assert abs(row["model_accounting_closure_residual_wh"]) <= module._ABS_TOL
    assert row["unexplained_meter_residual_measured_minus_expected_wh"] == pytest.approx(5.0)
    if mode == "subset":
        assert not parents[2].states.loc[(times[0], "tx-1")]["load_loss_fallback_applied"]
        assert parents[2].states.loc[(times[1], "tx-1")]["load_loss_fallback_applied"]
        assert not parents[2].states.loc[(times[2], "tx-1")]["load_loss_fallback_applied"]


def test_downstream_mixed_transformer_fidelity_accounting_closes() -> None:
    from heliotelligence.physics import mv_hv_operating_solution as s13c_module
    from heliotelligence.physics import revenue_meter_power_benchmark as s14a_module
    from tests.unit.test_physics import test_mv_hv_network_authority as network_support
    from tests.unit.test_physics.test_mv_hv_operating_solution import _mixed_fidelity_parents

    values, _, base = _attribution_fidelity_case("advanced")
    parents = list(base)
    mixed_s12m, network, boundary = _mixed_fidelity_parents()
    s13c = s13c_module._build_result((mixed_s12m, network, boundary))
    s13c_module._validate_result((mixed_s12m, network, boundary), s13c)
    frames = []
    for exit_id in ("exit-0", "exit-1"):
        frame = base[0].collection_exit_states.copy(deep=True)
        frame.index = pd.MultiIndex.from_tuples(
            [(t, exit_id) for t, _ in frame.index],
            names=frame.index.names,
        )
        frames.append(frame)
    parents[0] = replace(base[0], collection_exit_states=pd.concat(frames).sort_index())
    parents[1] = network_support._parents(("tx-a", "tx-b"))["transformer_static_authority"]
    parents[2], parents[3], parents[4] = mixed_s12m, network, s13c
    timestamp, meter_id = base[5].states.index[0]
    benchmark_parents = network, s13c, values["revenue_meter_measurement_authority"]
    frame = s14a_module._frame(
        ((timestamp, meter_id),), [s14a_module._record(*benchmark_parents, timestamp, meter_id)]
    )
    benchmark = replace(
        base[5],
        states=frame,
        diagnostics=s14a_module._diagnostics((meter_id,), (timestamp,), frame),
    )
    s14a_module._validate_result(benchmark_parents, benchmark)
    parents[5] = benchmark
    result = _instant_result(tuple(parents))
    module._validate_result(tuple(parents), result)
    row = result.instantaneous_states.iloc[0]
    assert (
        row["revenue_meter_delivery_attribution_state"]
        == "resolved_instantaneous_revenue_meter_delivery_attribution"
    )
    assert row["contributing_transformer_ids"] == ("tx-a", "tx-b")
    assert row["s12m_fallback_transformer_ids"] == ("tx-b",)
    assert row["s12m_load_loss_fallback_present"]
    assert row["transformer_owned_active_loss_w"] == pytest.approx(
        mixed_s12m.states["p_total_transformer_active_loss_w"].sum(),
        rel=module._REL_TOL,
        abs=module._ABS_TOL,
    )
    assert abs(row["model_accounting_closure_residual_w"]) <= module._ABS_TOL


@pytest.mark.parametrize("interval", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [
        ("s12m_fallback_transformer_ids", ()),
        ("s12m_load_loss_fallback_present", False),
    ],
)
def test_downstream_fallback_audit_fields_are_independently_validated(
    interval: bool,
    field: str,
    value: object,
) -> None:
    if interval:
        parents = _fidelity_interval_parents("subset")
        result = _instant_result(parents)
    else:
        _, result, parents = _attribution_fidelity_case()
    frame_name = "interval_states" if interval else "instantaneous_states"
    frame = getattr(result, frame_name).copy(deep=True)
    frame.at[frame.index[0], field] = value
    with pytest.raises(RuntimeError, match="independent exact closure"):
        module._validate_result(parents, replace(result, **{frame_name: frame}))


def test_downstream_fallback_attribution_validator_is_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parents = _fidelity_interval_parents("subset")
    result = _instant_result(parents)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production attribution helper invoked")

    for name in (
        "_mapping",
        "_base",
        "_point",
        "_instant_record",
        "_integrate",
        "_interval_record",
        "_frame",
        "_diagnostics",
    ):
        monkeypatch.setattr(module, name, fail)
    module._validate_result(parents, result)
