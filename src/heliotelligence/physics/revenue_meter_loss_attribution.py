"""Post-inverter delivery-loss accounting and unexplained meter residual (S14C)."""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeVar, cast

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.lv_ac_collection_operating import (
    TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID,
    calculate_topology_lv_ac_collection_operating_solution,
)
from heliotelligence.physics.mv_hv_network_authority import (
    MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
    resolve_topology_mv_hv_network_authority,
)
from heliotelligence.physics.mv_hv_operating_solution import (
    MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
    calculate_topology_mv_hv_operating_solution,
)
from heliotelligence.physics.revenue_meter_interval_benchmark import (
    REVENUE_METER_INTERVAL_BENCHMARK_CONTRACT_ID,
    calculate_topology_revenue_meter_interval_benchmark,
)
from heliotelligence.physics.revenue_meter_power_benchmark import (
    REVENUE_METER_POWER_BENCHMARK_CONTRACT_ID,
    calculate_topology_revenue_meter_power_benchmark,
)
from heliotelligence.physics.transformer_advanced_operating_solution import (
    TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID,
    calculate_topology_transformer_advanced_operating_solution,
)
from heliotelligence.physics.transformer_authority import (
    TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
    resolve_transformer_static_authority,
)

REVENUE_METER_DELIVERY_ATTRIBUTION_CONTRACT_ID = (
    "admitted_s11c_s12a_s12m_s13a_s13c_s14a_s14b_to_revenue_meter_delivery_loss_attribution_v1"
)
REVENUE_METER_DELIVERY_ATTRIBUTION_MODEL_ID = (
    "post_inverter_selected_ac_to_revenue_meter_component_consumption_"
    "and_unexplained_residual_accounting_v1"
)
REVENUE_METER_DELIVERY_ATTRIBUTION_SCOPE = (
    "instantaneous_and_interval_post_inverter_active_power_energy_"
    "delivery_accounting_without_causal_claim"
)
REVENUE_METER_DELIVERY_ATTRIBUTION_COVERAGE_SCOPE = (
    "resolved_revenue_meter_benchmarks_with_canonical_lv_transformer_"
    "and_mv_hv_delivery_component_authority"
)
SOURCE_REFERENCE_PLANE = "selected_inverter_ac_output"
ACCOUNTING_ATTRIBUTION_SEMANTICS = (
    "deterministic_boundary_and_owned_component_accounting_not_statistical_causality_v1"
)
CAUSAL_CLAIM_SEMANTICS = (
    "no_causal_claim_unexplained_residual_is_measurement_minus_model_"
    "after_admitted_delivery_accounting"
)
MV_HV_CONSUMPTION_SEMANTICS = (
    "contributing_transformer_network_terminal_power_minus_expected_revenue_meter_boundary_flow_v1"
)
COMPONENT_INTEGRATION_SEMANTICS = (
    "s14b_exact_support_timestamp_piecewise_linear_component_power_trapezoidal_energy_accounting_v1"
)
METER_REFERENCE_PLANE = "revenue_meter_boundary"
_ABS_TOL = 1e-6
_REL_TOL = 1e-9
_S12M_READY = {
    "resolved_coupled_advanced_transformer_terminal_solution",
    "resolved_deenergised_transformer_zero_advanced_transfer",
}

_INSTANT_STATES = (
    "unresolved_instantaneous_benchmark_not_eligible",
    "unresolved_no_contributing_transformer_path",
    "unresolved_missing_delivery_component_state",
    "unresolved_delivery_component_operating_solution",
    "unresolved_component_boundary_closure",
    "unresolved_nonfinite_delivery_accounting",
    "resolved_instantaneous_revenue_meter_delivery_attribution",
)
_INTERVAL_STATES = (
    "unresolved_interval_benchmark_not_eligible",
    "unresolved_no_contributing_transformer_path",
    "unresolved_missing_interval_delivery_component_state",
    "unresolved_interval_delivery_component_operating_solution",
    "unresolved_interval_component_boundary_closure",
    "unresolved_nonfinite_interval_delivery_accounting",
    "resolved_interval_revenue_meter_delivery_attribution",
)

_INSTANT_COLUMNS = (
    "contributing_transformer_count",
    "contributing_transformer_ids",
    "contributing_collection_exit_ids",
    "s14a_benchmark_eligible",
    "s14a_benchmark_state",
    "expected_revenue_meter_active_power_w",
    "measured_revenue_meter_active_power_w",
    "s14a_active_power_residual_w",
    "delivery_component_rows_complete",
    "delivery_component_operating_states_resolved",
    "component_boundary_closure_satisfied",
    "missing_component_transformer_ids",
    "unresolved_component_transformer_ids",
    "boundary_mismatch_transformer_ids",
    "selected_inverter_ac_source_power_w",
    "lv_ac_delivered_to_transformer_collection_power_w",
    "lv_ac_owned_series_loss_w",
    "lv_ac_conservation_residual_w",
    "transformer_collection_input_power_w",
    "transformer_network_terminal_power_w",
    "transformer_owned_active_loss_w",
    "transformer_conservation_residual_w",
    "mv_hv_active_consumption_to_meter_w",
    "mv_hv_active_consumption_semantics",
    "modeled_delivery_active_consumption_w",
    "reconstructed_expected_meter_active_power_w",
    "model_accounting_closure_residual_w",
    "unexplained_meter_residual_measured_minus_expected_w",
    "reconstructed_measured_meter_active_power_w",
    "source_reference_plane",
    "meter_reference_plane",
    "accounting_attribution_semantics",
    "causal_claim_semantics",
    "revenue_meter_delivery_attribution_state",
    "s11c_contract",
    "s12a_contract",
    "s12m_contract",
    "s13a_contract",
    "s13c_contract",
    "s14a_contract",
    "revenue_meter_delivery_attribution_contract",
    "revenue_meter_delivery_attribution_model",
    "revenue_meter_delivery_attribution_scope",
    "revenue_meter_delivery_attribution_coverage_scope",
)
_INTERVAL_COLUMNS = (
    "contributing_transformer_count",
    "contributing_transformer_ids",
    "contributing_collection_exit_ids",
    "s14b_benchmark_eligible",
    "s14b_benchmark_state",
    "interval_start_timestamp",
    "interval_end_timestamp",
    "averaging_interval_seconds",
    "expected_interval_sample_timestamps",
    "expected_revenue_meter_active_energy_wh",
    "measured_revenue_meter_active_energy_wh",
    "s14b_active_energy_residual_wh",
    "interval_delivery_component_rows_complete",
    "interval_delivery_component_states_resolved",
    "interval_component_boundary_closure_satisfied",
    "missing_component_transformer_ids",
    "unresolved_component_transformer_ids",
    "boundary_mismatch_transformer_ids",
    "selected_inverter_ac_source_energy_wh",
    "lv_ac_owned_series_loss_energy_wh",
    "transformer_owned_active_loss_energy_wh",
    "transformer_network_terminal_energy_wh",
    "mv_hv_active_consumption_to_meter_energy_wh",
    "modeled_delivery_active_consumption_energy_wh",
    "reconstructed_expected_meter_active_energy_wh",
    "model_accounting_closure_residual_wh",
    "unexplained_meter_residual_measured_minus_expected_wh",
    "reconstructed_measured_meter_active_energy_wh",
    "component_integration_semantics",
    "mv_hv_active_consumption_semantics",
    "accounting_attribution_semantics",
    "causal_claim_semantics",
    "revenue_meter_interval_delivery_attribution_state",
    "s11c_contract",
    "s12a_contract",
    "s12m_contract",
    "s13a_contract",
    "s13c_contract",
    "s14b_contract",
    "revenue_meter_delivery_attribution_contract",
    "revenue_meter_delivery_attribution_model",
    "revenue_meter_delivery_attribution_scope",
    "revenue_meter_delivery_attribution_coverage_scope",
)
_I_BOOL = {
    "s14a_benchmark_eligible",
    "delivery_component_rows_complete",
    "delivery_component_operating_states_resolved",
    "component_boundary_closure_satisfied",
}
_N_BOOL = {
    "s14b_benchmark_eligible",
    "interval_delivery_component_rows_complete",
    "interval_delivery_component_states_resolved",
    "interval_component_boundary_closure_satisfied",
}
_I_FLOAT = {c for c in _INSTANT_COLUMNS if c.endswith("_w")}
_N_FLOAT = {c for c in _INTERVAL_COLUMNS if c.endswith("_wh")} | {"averaging_interval_seconds"}


@dataclass(frozen=True)
class TopologyRevenueMeterDeliveryLossAttributionDiagnostics:
    revenue_meter_count: int
    instantaneous_row_count: int
    instantaneous_benchmark_eligible_count: int
    instantaneous_attribution_resolved_count: int
    instantaneous_attribution_unresolved_count: int
    interval_row_count: int
    interval_benchmark_eligible_count: int
    interval_attribution_resolved_count: int
    interval_attribution_unresolved_count: int
    contributing_transformer_link_count: int
    instantaneous_state_counts: tuple[tuple[str, int], ...]
    interval_state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyRevenueMeterDeliveryLossAttributionResult:
    instantaneous_states: pd.DataFrame
    interval_states: pd.DataFrame
    diagnostics: TopologyRevenueMeterDeliveryLossAttributionDiagnostics


F = TypeVar("F", bound=Callable[..., Any])


def _call(function: F, values: Mapping[str, Any]) -> Any:
    parameters = inspect.signature(function).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return function(**values)
    return function(**{name: values[name] for name in parameters})


def _replay(label: str, supplied: object, canonical: object) -> None:
    if type(supplied) is not type(canonical):
        raise ValueError(f"supplied {label} result type is invalid")
    for name, expected in vars(canonical).items():
        actual = getattr(supplied, name)
        if isinstance(expected, pd.DataFrame):
            try:
                pd.testing.assert_frame_equal(actual, expected, check_exact=True)
            except AssertionError as error:
                raise ValueError(f"supplied {label} frame failed canonical replay") from error
        elif isinstance(expected, Mapping):
            if type(actual) is not MappingProxyType or tuple(actual.items()) != tuple(
                expected.items()
            ):
                raise ValueError(f"supplied {label} mapping failed canonical replay")
        elif actual != expected:
            raise ValueError(f"supplied {label} diagnostics failed canonical replay")


def _parents(values: Mapping[str, Any]) -> tuple[Any, ...]:
    canonical = dict(values)
    s11c = _call(calculate_topology_lv_ac_collection_operating_solution, canonical)
    _replay("S11C", values["lv_ac_collection_operating_solution"], s11c)
    canonical["lv_ac_collection_operating_solution"] = s11c
    s12a = _call(resolve_transformer_static_authority, canonical)
    _replay("S12A", values["transformer_static_authority"], s12a)
    canonical["transformer_static_authority"] = s12a
    s12m = _call(calculate_topology_transformer_advanced_operating_solution, canonical)
    _replay("S12M", values["transformer_advanced_operating_solution"], s12m)
    canonical["transformer_advanced_operating_solution"] = s12m
    s13a = _call(resolve_topology_mv_hv_network_authority, canonical)
    _replay("S13A", values["mv_hv_network_authority"], s13a)
    canonical["mv_hv_network_authority"] = s13a
    s13c = _call(calculate_topology_mv_hv_operating_solution, canonical)
    _replay("S13C", values["mv_hv_operating_solution"], s13c)
    canonical["mv_hv_operating_solution"] = s13c
    s14a = _call(calculate_topology_revenue_meter_power_benchmark, canonical)
    _replay("S14A", values["revenue_meter_power_benchmark"], s14a)
    s14b = _call(calculate_topology_revenue_meter_interval_benchmark, canonical)
    _replay("S14B", values["revenue_meter_interval_benchmark"], s14b)
    return s11c, s12a, s12m, s13a, s13c, s14a, s14b


def _mapping(s13a: Any, s12a: Any, meter_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    transformers = tuple(
        str(transformer_id)
        for transformer_id, row in s13a.transformer_states.iterrows()
        if bool(row["revenue_meter_on_transformer_path"]) and row["revenue_meter_id"] == meter_id
    )
    exits = tuple(s12a.topology_by_id[item].s11_collection_exit_node_id for item in transformers)
    return transformers, exits


def _base(columns: tuple[str, ...], bools: set[str]) -> dict[str, object]:
    result: dict[str, object] = {column: "" for column in columns}
    for column in bools:
        result[column] = False
    for column in _I_FLOAT if columns is _INSTANT_COLUMNS else _N_FLOAT:
        result[column] = math.nan
    result["contributing_transformer_count"] = 0
    result["contributing_transformer_ids"] = ()
    result["contributing_collection_exit_ids"] = ()
    result["missing_component_transformer_ids"] = ()
    result["unresolved_component_transformer_ids"] = ()
    result["boundary_mismatch_transformer_ids"] = ()
    result.update(
        accounting_attribution_semantics=ACCOUNTING_ATTRIBUTION_SEMANTICS,
        causal_claim_semantics=CAUSAL_CLAIM_SEMANTICS,
        mv_hv_active_consumption_semantics=MV_HV_CONSUMPTION_SEMANTICS,
        s11c_contract=TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID,
        s12a_contract=TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        s12m_contract=TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID,
        s13a_contract=MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        s13c_contract=MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
        revenue_meter_delivery_attribution_contract=REVENUE_METER_DELIVERY_ATTRIBUTION_CONTRACT_ID,
        revenue_meter_delivery_attribution_model=REVENUE_METER_DELIVERY_ATTRIBUTION_MODEL_ID,
        revenue_meter_delivery_attribution_scope=REVENUE_METER_DELIVERY_ATTRIBUTION_SCOPE,
        revenue_meter_delivery_attribution_coverage_scope=(
            REVENUE_METER_DELIVERY_ATTRIBUTION_COVERAGE_SCOPE
        ),
    )
    return result


def _point(parents: tuple[Any, ...], timestamp: pd.Timestamp, meter_id: str) -> dict[str, object]:
    s11c, s12a, s12m, s13a, _s13c, _s14a, _s14b = parents
    txs, exits = _mapping(s13a, s12a, meter_id)
    missing: list[str] = []
    unresolved: list[str] = []
    mismatch: list[str] = []
    values: list[tuple[float, ...]] = []
    for transformer_id, exit_id in zip(txs, exits, strict=True):
        lk, tk = (timestamp, exit_id), (timestamp, transformer_id)
        if lk not in s11c.collection_exit_states.index or tk not in s12m.states.index:
            missing.append(transformer_id)
            continue
        lv, tx = s11c.collection_exit_states.loc[lk], s12m.states.loc[tk]
        if (
            not bool(lv["lv_ac_operating_solution_resolved"])
            or tx["transformer_advanced_operating_solution_state"] not in _S12M_READY
        ):
            unresolved.append(transformer_id)
            continue
        delivered, collection = (
            float(lv["p_delivered_at_collection_exit_w"]),
            float(tx["collection_p_w"]),
        )
        if not math.isclose(delivered, collection, rel_tol=_REL_TOL, abs_tol=_ABS_TOL):
            mismatch.append(transformer_id)
        values.append(
            (
                float(lv["selected_p_total_w"]),
                delivered,
                float(lv["total_active_series_loss_w"]),
                float(lv["active_power_conservation_residual_w"]),
                collection,
                float(tx["p_network_terminal_w"]),
                float(tx["p_total_transformer_active_loss_w"]),
                float(tx["active_power_conservation_residual_w"]),
            )
        )
    result: dict[str, object] = {
        "transformers": txs,
        "exits": exits,
        "missing": tuple(missing),
        "unresolved": tuple(unresolved),
        "mismatch": tuple(mismatch),
    }
    if not missing and not unresolved:
        try:
            totals = tuple(math.fsum(row[i] for row in values) for i in range(8))
            if all(math.isfinite(item) for item in totals):
                result["totals"] = totals
        except (OverflowError, ValueError):
            pass
    return result


def _instant_record(parents: tuple[Any, ...], key: tuple[pd.Timestamp, str]) -> dict[str, object]:
    *_head, s14a, _s14b = parents
    timestamp, meter_id = key
    row = s14a.states.loc[key]
    record = _base(_INSTANT_COLUMNS, _I_BOOL)
    point = _point(parents, timestamp, meter_id)
    txs = cast(tuple[str, ...], point["transformers"])
    exits = cast(tuple[str, ...], point["exits"])
    missing = cast(tuple[str, ...], point["missing"])
    unresolved = cast(tuple[str, ...], point["unresolved"])
    mismatch = cast(tuple[str, ...], point["mismatch"])
    record.update(
        contributing_transformer_count=len(txs),
        contributing_transformer_ids=txs,
        contributing_collection_exit_ids=exits,
        s14a_benchmark_eligible=bool(row["benchmark_eligible"]),
        s14a_benchmark_state=row["revenue_meter_power_benchmark_state"],
        expected_revenue_meter_active_power_w=row["expected_active_power_w"],
        measured_revenue_meter_active_power_w=row["measured_active_power_w"],
        s14a_active_power_residual_w=row["active_power_residual_measured_minus_expected_w"],
        missing_component_transformer_ids=missing,
        unresolved_component_transformer_ids=unresolved,
        boundary_mismatch_transformer_ids=mismatch,
        delivery_component_rows_complete=bool(txs) and not missing,
        delivery_component_operating_states_resolved=(
            bool(txs) and not missing and not unresolved
        ),
        component_boundary_closure_satisfied=(
            bool(txs) and not missing and not unresolved and not mismatch
        ),
        source_reference_plane=SOURCE_REFERENCE_PLANE,
        meter_reference_plane=METER_REFERENCE_PLANE,
        s14a_contract=REVENUE_METER_POWER_BENCHMARK_CONTRACT_ID,
    )
    if not bool(row["benchmark_eligible"]):
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[0]
        return record
    if not txs:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[1]
        return record
    if missing:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[2]
        return record
    if unresolved:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[3]
        return record
    if mismatch:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[4]
        return record
    totals = point.get("totals")
    if totals is None:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[5]
        return record
    source, delivered, lv_loss, lv_res, tx_input, tx_network, tx_loss, tx_res = cast(
        tuple[float, ...], totals
    )
    expected = float(row["expected_active_power_w"])
    measured = float(row["measured_active_power_w"])
    unexplained = float(row["active_power_residual_measured_minus_expected_w"])
    try:
        mv = tx_network - expected
        consumption = math.fsum((lv_loss, tx_loss, mv))
        reconstructed_expected = source - consumption
        closure = expected - reconstructed_expected
        reconstructed_measured = reconstructed_expected + closure + unexplained
        derived = (mv, consumption, reconstructed_expected, closure, reconstructed_measured)
        valid = all(math.isfinite(item) for item in derived) and math.isclose(
            measured, reconstructed_measured, rel_tol=_REL_TOL, abs_tol=_ABS_TOL
        )
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[5]
        return record
    record.update(
        selected_inverter_ac_source_power_w=source,
        lv_ac_delivered_to_transformer_collection_power_w=delivered,
        lv_ac_owned_series_loss_w=lv_loss,
        lv_ac_conservation_residual_w=lv_res,
        transformer_collection_input_power_w=tx_input,
        transformer_network_terminal_power_w=tx_network,
        transformer_owned_active_loss_w=tx_loss,
        transformer_conservation_residual_w=tx_res,
        mv_hv_active_consumption_to_meter_w=mv,
        modeled_delivery_active_consumption_w=consumption,
        reconstructed_expected_meter_active_power_w=reconstructed_expected,
        model_accounting_closure_residual_w=closure,
        unexplained_meter_residual_measured_minus_expected_w=unexplained,
        reconstructed_measured_meter_active_power_w=reconstructed_measured,
        revenue_meter_delivery_attribution_state=_INSTANT_STATES[6],
    )
    return record


def _integrate(
    times: tuple[pd.Timestamp, ...], series: list[tuple[float, ...]]
) -> tuple[float, ...] | None:
    components: list[list[float]] = [[] for _ in range(5)]
    try:
        for index in range(len(times) - 1):
            hours = (times[index + 1] - times[index]).value / 3_600_000_000_000.0
            if not math.isfinite(hours) or hours <= 0:
                return None
            for position in range(5):
                value = (series[index][position] / 2 + series[index + 1][position] / 2) * hours
                if not math.isfinite(value):
                    return None
                components[position].append(value)
        totals = tuple(math.fsum(values) for values in components)
        return totals if all(math.isfinite(item) for item in totals) else None
    except (OverflowError, ValueError, TypeError):
        return None


def _interval_record(parents: tuple[Any, ...], key: tuple[pd.Timestamp, str]) -> dict[str, object]:
    *_head, _s14a, s14b = parents
    end, meter_id = key
    row = s14b.states.loc[key]
    record = _base(_INTERVAL_COLUMNS, _N_BOOL)
    times = tuple(row["expected_interval_sample_timestamps"])
    first_point = _point(parents, times[0], meter_id) if times else _point(parents, end, meter_id)
    txs = cast(tuple[str, ...], first_point["transformers"])
    exits = cast(tuple[str, ...], first_point["exits"])
    record.update(
        contributing_transformer_count=len(txs),
        contributing_transformer_ids=txs,
        contributing_collection_exit_ids=exits,
        s14b_benchmark_eligible=bool(row["benchmark_eligible"]),
        s14b_benchmark_state=row["revenue_meter_interval_benchmark_state"],
        interval_start_timestamp=row["interval_start_timestamp"],
        interval_end_timestamp=end,
        averaging_interval_seconds=row["averaging_interval_seconds"],
        expected_interval_sample_timestamps=times,
        expected_revenue_meter_active_energy_wh=row["expected_active_energy_wh"],
        measured_revenue_meter_active_energy_wh=row["measured_active_energy_wh"],
        s14b_active_energy_residual_wh=row["active_energy_residual_measured_minus_expected_wh"],
        component_integration_semantics=COMPONENT_INTEGRATION_SEMANTICS,
        s14b_contract=REVENUE_METER_INTERVAL_BENCHMARK_CONTRACT_ID,
    )
    if not bool(row["benchmark_eligible"]):
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[0]
        return record
    if not txs:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[1]
        return record
    points = [_point(parents, timestamp, meter_id) for timestamp in times]
    missing = tuple(
        dict.fromkeys(item for point in points for item in cast(tuple[str, ...], point["missing"]))
    )
    unresolved = tuple(
        dict.fromkeys(
            item for point in points for item in cast(tuple[str, ...], point["unresolved"])
        )
    )
    mismatch = tuple(
        dict.fromkeys(item for point in points for item in cast(tuple[str, ...], point["mismatch"]))
    )
    record.update(
        missing_component_transformer_ids=missing,
        unresolved_component_transformer_ids=unresolved,
        boundary_mismatch_transformer_ids=mismatch,
        interval_delivery_component_rows_complete=not missing,
        interval_delivery_component_states_resolved=not missing and not unresolved,
        interval_component_boundary_closure_satisfied=(
            not missing and not unresolved and not mismatch
        ),
    )
    if missing:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[2]
        return record
    if unresolved:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[3]
        return record
    if mismatch:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[4]
        return record
    series: list[tuple[float, ...]] = []
    try:
        for timestamp, point in zip(times, points, strict=True):
            totals = point.get("totals")
            if totals is None:
                raise ValueError
            (
                source,
                _delivered,
                lv_loss,
                _lv_res,
                _tx_input,
                tx_network,
                tx_loss,
                _tx_res,
            ) = cast(tuple[float, ...], totals)
            expected = float(
                parents[4].revenue_meter_states.loc[(timestamp, meter_id)][
                    "expected_p_at_revenue_meter_w"
                ]
            )
            series.append((source, lv_loss, tx_loss, tx_network, tx_network - expected))
    except (KeyError, ValueError, TypeError):
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[5]
        return record
    energies = _integrate(times, series)
    if energies is None:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[5]
        return record
    source, lv_loss, tx_loss, tx_network, mv = energies
    expected = float(row["expected_active_energy_wh"])
    measured = float(row["measured_active_energy_wh"])
    unexplained = float(row["active_energy_residual_measured_minus_expected_wh"])
    try:
        consumption = math.fsum((lv_loss, tx_loss, mv))
        reconstructed_expected = source - consumption
        closure = expected - reconstructed_expected
        reconstructed_measured = reconstructed_expected + closure + unexplained
        derived = (consumption, reconstructed_expected, closure, reconstructed_measured)
        valid = all(math.isfinite(item) for item in (*energies, *derived)) and math.isclose(
            measured, reconstructed_measured, rel_tol=_REL_TOL, abs_tol=_ABS_TOL
        )
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[5]
        return record
    record.update(
        selected_inverter_ac_source_energy_wh=source,
        lv_ac_owned_series_loss_energy_wh=lv_loss,
        transformer_owned_active_loss_energy_wh=tx_loss,
        transformer_network_terminal_energy_wh=tx_network,
        mv_hv_active_consumption_to_meter_energy_wh=mv,
        modeled_delivery_active_consumption_energy_wh=consumption,
        reconstructed_expected_meter_active_energy_wh=reconstructed_expected,
        model_accounting_closure_residual_wh=closure,
        unexplained_meter_residual_measured_minus_expected_wh=unexplained,
        reconstructed_measured_meter_active_energy_wh=reconstructed_measured,
        revenue_meter_interval_delivery_attribution_state=_INTERVAL_STATES[6],
    )
    return record


def _frame(
    index: pd.MultiIndex, records: list[dict[str, object]], *, interval: bool
) -> pd.DataFrame:
    columns = _INTERVAL_COLUMNS if interval else _INSTANT_COLUMNS
    bools = _N_BOOL if interval else _I_BOOL
    floats = _N_FLOAT if interval else _I_FLOAT
    frame = pd.DataFrame.from_records(records, columns=columns, index=index)
    frame.index = index
    frame["contributing_transformer_count"] = frame["contributing_transformer_count"].astype(
        "int64"
    )
    for column in bools:
        frame[column] = frame[column].astype("bool")
    for column in floats:
        frame[column] = frame[column].astype("float64")
    for column in set(columns) - bools - floats - {"contributing_transformer_count"}:
        frame[column] = frame[column].astype("object")
    return frame


def _diagnostics(
    s13a: Any, instant: pd.DataFrame, interval: pd.DataFrame
) -> TopologyRevenueMeterDeliveryLossAttributionDiagnostics:
    istate = instant["revenue_meter_delivery_attribution_state"]
    nstate = interval["revenue_meter_interval_delivery_attribution_state"]
    return TopologyRevenueMeterDeliveryLossAttributionDiagnostics(
        len(s13a.revenue_meter_boundary_by_id),
        len(instant),
        int(instant["s14a_benchmark_eligible"].sum()),
        int((istate == _INSTANT_STATES[-1]).sum()),
        int((istate != _INSTANT_STATES[-1]).sum()),
        len(interval),
        int(interval["s14b_benchmark_eligible"].sum()),
        int((nstate == _INTERVAL_STATES[-1]).sum()),
        int((nstate != _INTERVAL_STATES[-1]).sum()),
        sum(
            bool(row["revenue_meter_on_transformer_path"])
            for _, row in s13a.transformer_states.iterrows()
        ),
        tuple((state, int((istate == state).sum())) for state in _INSTANT_STATES),
        tuple((state, int((nstate == state).sum())) for state in _INTERVAL_STATES),
        REVENUE_METER_DELIVERY_ATTRIBUTION_MODEL_ID,
    )


def calculate_topology_revenue_meter_delivery_loss_attribution(
    **values: Any,
) -> TopologyRevenueMeterDeliveryLossAttributionResult:
    """Build instantaneous and interval post-inverter delivery accounting."""
    parents = _parents(values)
    s13a, s14a, s14b = parents[3], parents[5], parents[6]
    instant_index = s14a.states.index.copy()
    interval_index = s14b.states.index.copy()
    instant = _frame(
        instant_index, [_instant_record(parents, key) for key in instant_index], interval=False
    )
    interval = _frame(
        interval_index, [_interval_record(parents, key) for key in interval_index], interval=True
    )
    result = TopologyRevenueMeterDeliveryLossAttributionResult(
        instant, interval, _diagnostics(s13a, instant, interval)
    )
    _validate_result(parents, result)
    return result


def _validator_mapping(
    s13a: Any, s12a: Any, meter_id: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    transformer_ids: list[str] = []
    collection_exit_ids: list[str] = []
    for transformer_id, state in s13a.transformer_states.iterrows():
        if (
            bool(state["revenue_meter_on_transformer_path"])
            and state["revenue_meter_id"] == meter_id
        ):
            identifier = str(transformer_id)
            transformer_ids.append(identifier)
            collection_exit_ids.append(
                s12a.topology_by_id[identifier].s11_collection_exit_node_id
            )
    return tuple(transformer_ids), tuple(collection_exit_ids)


def _validator_base(columns: tuple[str, ...], bools: set[str]) -> dict[str, object]:
    record: dict[str, object] = {column: "" for column in columns}
    for column in bools:
        record[column] = False
    floats = _N_FLOAT if columns == _INTERVAL_COLUMNS else _I_FLOAT
    for column in floats:
        record[column] = math.nan
    record.update(
        contributing_transformer_count=0,
        contributing_transformer_ids=(),
        contributing_collection_exit_ids=(),
        missing_component_transformer_ids=(),
        unresolved_component_transformer_ids=(),
        boundary_mismatch_transformer_ids=(),
        accounting_attribution_semantics=ACCOUNTING_ATTRIBUTION_SEMANTICS,
        causal_claim_semantics=CAUSAL_CLAIM_SEMANTICS,
        mv_hv_active_consumption_semantics=MV_HV_CONSUMPTION_SEMANTICS,
        s11c_contract=TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID,
        s12a_contract=TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        s12m_contract=TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID,
        s13a_contract=MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        s13c_contract=MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
        revenue_meter_delivery_attribution_contract=(
            REVENUE_METER_DELIVERY_ATTRIBUTION_CONTRACT_ID
        ),
        revenue_meter_delivery_attribution_model=REVENUE_METER_DELIVERY_ATTRIBUTION_MODEL_ID,
        revenue_meter_delivery_attribution_scope=REVENUE_METER_DELIVERY_ATTRIBUTION_SCOPE,
        revenue_meter_delivery_attribution_coverage_scope=(
            REVENUE_METER_DELIVERY_ATTRIBUTION_COVERAGE_SCOPE
        ),
    )
    return record


def _validator_point(
    parents: tuple[Any, ...], timestamp: pd.Timestamp, meter_id: str
) -> dict[str, object]:
    s11c, s12a, s12m, s13a, _s13c, _s14a, _s14b = parents
    transformer_ids, exit_ids = _validator_mapping(s13a, s12a, meter_id)
    missing: list[str] = []
    unresolved: list[str] = []
    mismatched: list[str] = []
    component_rows: list[tuple[float, ...]] = []
    for transformer_id, exit_id in zip(transformer_ids, exit_ids, strict=True):
        lv_key = (timestamp, exit_id)
        transformer_key = (timestamp, transformer_id)
        if (
            lv_key not in s11c.collection_exit_states.index
            or transformer_key not in s12m.states.index
        ):
            missing.append(transformer_id)
            continue
        lv_state = s11c.collection_exit_states.loc[lv_key]
        transformer_state = s12m.states.loc[transformer_key]
        if (
            not bool(lv_state["lv_ac_operating_solution_resolved"])
            or transformer_state["transformer_advanced_operating_solution_state"]
            not in _S12M_READY
        ):
            unresolved.append(transformer_id)
            continue
        delivered = float(lv_state["p_delivered_at_collection_exit_w"])
        collection_input = float(transformer_state["collection_p_w"])
        if not math.isclose(
            delivered, collection_input, rel_tol=_REL_TOL, abs_tol=_ABS_TOL
        ):
            mismatched.append(transformer_id)
        component_rows.append(
            (
                float(lv_state["selected_p_total_w"]),
                delivered,
                float(lv_state["total_active_series_loss_w"]),
                float(lv_state["active_power_conservation_residual_w"]),
                collection_input,
                float(transformer_state["p_network_terminal_w"]),
                float(transformer_state["p_total_transformer_active_loss_w"]),
                float(transformer_state["active_power_conservation_residual_w"]),
            )
        )
    result: dict[str, object] = {
        "transformers": transformer_ids,
        "exits": exit_ids,
        "missing": tuple(missing),
        "unresolved": tuple(unresolved),
        "mismatch": tuple(mismatched),
    }
    if not missing and not unresolved:
        try:
            aggregates = tuple(
                math.fsum(component[position] for component in component_rows)
                for position in range(8)
            )
            if all(math.isfinite(value) for value in aggregates):
                result["totals"] = aggregates
        except (OverflowError, ValueError):
            pass
    return result


def _validator_instant_record(
    parents: tuple[Any, ...], key: tuple[pd.Timestamp, str]
) -> dict[str, object]:
    timestamp, meter_id = key
    benchmark = parents[5].states.loc[key]
    point = _validator_point(parents, timestamp, meter_id)
    transformer_ids = cast(tuple[str, ...], point["transformers"])
    exit_ids = cast(tuple[str, ...], point["exits"])
    missing = cast(tuple[str, ...], point["missing"])
    unresolved = cast(tuple[str, ...], point["unresolved"])
    mismatched = cast(tuple[str, ...], point["mismatch"])
    record = _validator_base(_INSTANT_COLUMNS, _I_BOOL)
    record.update(
        contributing_transformer_count=len(transformer_ids),
        contributing_transformer_ids=transformer_ids,
        contributing_collection_exit_ids=exit_ids,
        s14a_benchmark_eligible=bool(benchmark["benchmark_eligible"]),
        s14a_benchmark_state=benchmark["revenue_meter_power_benchmark_state"],
        expected_revenue_meter_active_power_w=benchmark["expected_active_power_w"],
        measured_revenue_meter_active_power_w=benchmark["measured_active_power_w"],
        s14a_active_power_residual_w=(
            benchmark["active_power_residual_measured_minus_expected_w"]
        ),
        delivery_component_rows_complete=bool(transformer_ids) and not missing,
        delivery_component_operating_states_resolved=(
            bool(transformer_ids) and not missing and not unresolved
        ),
        component_boundary_closure_satisfied=(
            bool(transformer_ids) and not missing and not unresolved and not mismatched
        ),
        missing_component_transformer_ids=missing,
        unresolved_component_transformer_ids=unresolved,
        boundary_mismatch_transformer_ids=mismatched,
        source_reference_plane=SOURCE_REFERENCE_PLANE,
        meter_reference_plane=METER_REFERENCE_PLANE,
        s14a_contract=REVENUE_METER_POWER_BENCHMARK_CONTRACT_ID,
    )
    if not bool(benchmark["benchmark_eligible"]):
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[0]
        return record
    if not transformer_ids:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[1]
        return record
    if missing:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[2]
        return record
    if unresolved:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[3]
        return record
    if mismatched:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[4]
        return record
    aggregates = point.get("totals")
    if aggregates is None:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[5]
        return record
    source, delivered, lv_loss, lv_residual, tx_input, tx_network, tx_loss, tx_residual = cast(
        tuple[float, ...], aggregates
    )
    expected = float(benchmark["expected_active_power_w"])
    measured = float(benchmark["measured_active_power_w"])
    unexplained = float(benchmark["active_power_residual_measured_minus_expected_w"])
    try:
        mv_hv_consumption = tx_network - expected
        delivery_consumption = math.fsum((lv_loss, tx_loss, mv_hv_consumption))
        reconstructed_expected = source - delivery_consumption
        accounting_residual = expected - reconstructed_expected
        reconstructed_measured = reconstructed_expected + accounting_residual + unexplained
        derived = (
            mv_hv_consumption,
            delivery_consumption,
            reconstructed_expected,
            accounting_residual,
            reconstructed_measured,
        )
        valid = all(math.isfinite(value) for value in derived) and math.isclose(
            measured, reconstructed_measured, rel_tol=_REL_TOL, abs_tol=_ABS_TOL
        )
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        record["revenue_meter_delivery_attribution_state"] = _INSTANT_STATES[5]
        return record
    record.update(
        selected_inverter_ac_source_power_w=source,
        lv_ac_delivered_to_transformer_collection_power_w=delivered,
        lv_ac_owned_series_loss_w=lv_loss,
        lv_ac_conservation_residual_w=lv_residual,
        transformer_collection_input_power_w=tx_input,
        transformer_network_terminal_power_w=tx_network,
        transformer_owned_active_loss_w=tx_loss,
        transformer_conservation_residual_w=tx_residual,
        mv_hv_active_consumption_to_meter_w=mv_hv_consumption,
        modeled_delivery_active_consumption_w=delivery_consumption,
        reconstructed_expected_meter_active_power_w=reconstructed_expected,
        model_accounting_closure_residual_w=accounting_residual,
        unexplained_meter_residual_measured_minus_expected_w=unexplained,
        reconstructed_measured_meter_active_power_w=reconstructed_measured,
        revenue_meter_delivery_attribution_state=_INSTANT_STATES[6],
    )
    return record


def _validator_integrate(
    timestamps: tuple[pd.Timestamp, ...], component_points: list[tuple[float, ...]]
) -> tuple[float, ...] | None:
    segment_energies: list[list[float]] = [[], [], [], [], []]
    try:
        for index, (left_timestamp, right_timestamp) in enumerate(
            zip(timestamps, timestamps[1:], strict=False)
        ):
            elapsed_hours = (
                (right_timestamp - left_timestamp).value / 3_600_000_000_000.0
            )
            if not math.isfinite(elapsed_hours) or elapsed_hours <= 0.0:
                return None
            for position, energy_values in enumerate(segment_energies):
                contribution = (
                    component_points[index][position] / 2.0
                    + component_points[index + 1][position] / 2.0
                ) * elapsed_hours
                if not math.isfinite(contribution):
                    return None
                energy_values.append(contribution)
        totals = tuple(math.fsum(values) for values in segment_energies)
        return totals if all(math.isfinite(value) for value in totals) else None
    except (OverflowError, TypeError, ValueError):
        return None


def _validator_interval_record(
    parents: tuple[Any, ...], key: tuple[pd.Timestamp, str]
) -> dict[str, object]:
    interval_end, meter_id = key
    benchmark = parents[6].states.loc[key]
    timestamps = tuple(benchmark["expected_interval_sample_timestamps"])
    mapping_point = _validator_point(
        parents, timestamps[0] if timestamps else interval_end, meter_id
    )
    transformer_ids = cast(tuple[str, ...], mapping_point["transformers"])
    exit_ids = cast(tuple[str, ...], mapping_point["exits"])
    record = _validator_base(_INTERVAL_COLUMNS, _N_BOOL)
    record.update(
        contributing_transformer_count=len(transformer_ids),
        contributing_transformer_ids=transformer_ids,
        contributing_collection_exit_ids=exit_ids,
        s14b_benchmark_eligible=bool(benchmark["benchmark_eligible"]),
        s14b_benchmark_state=benchmark["revenue_meter_interval_benchmark_state"],
        interval_start_timestamp=benchmark["interval_start_timestamp"],
        interval_end_timestamp=interval_end,
        averaging_interval_seconds=benchmark["averaging_interval_seconds"],
        expected_interval_sample_timestamps=timestamps,
        expected_revenue_meter_active_energy_wh=benchmark["expected_active_energy_wh"],
        measured_revenue_meter_active_energy_wh=benchmark["measured_active_energy_wh"],
        s14b_active_energy_residual_wh=(
            benchmark["active_energy_residual_measured_minus_expected_wh"]
        ),
        component_integration_semantics=COMPONENT_INTEGRATION_SEMANTICS,
        s14b_contract=REVENUE_METER_INTERVAL_BENCHMARK_CONTRACT_ID,
    )
    if not bool(benchmark["benchmark_eligible"]):
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[0]
        return record
    if not transformer_ids:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[1]
        return record
    points = [_validator_point(parents, timestamp, meter_id) for timestamp in timestamps]
    missing = tuple(
        dict.fromkeys(
            transformer
            for point in points
            for transformer in cast(tuple[str, ...], point["missing"])
        )
    )
    unresolved = tuple(
        dict.fromkeys(
            transformer
            for point in points
            for transformer in cast(tuple[str, ...], point["unresolved"])
        )
    )
    mismatched = tuple(
        dict.fromkeys(
            transformer
            for point in points
            for transformer in cast(tuple[str, ...], point["mismatch"])
        )
    )
    record.update(
        interval_delivery_component_rows_complete=not missing,
        interval_delivery_component_states_resolved=not missing and not unresolved,
        interval_component_boundary_closure_satisfied=(
            not missing and not unresolved and not mismatched
        ),
        missing_component_transformer_ids=missing,
        unresolved_component_transformer_ids=unresolved,
        boundary_mismatch_transformer_ids=mismatched,
    )
    if missing:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[2]
        return record
    if unresolved:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[3]
        return record
    if mismatched:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[4]
        return record
    component_series: list[tuple[float, ...]] = []
    try:
        for timestamp, point in zip(timestamps, points, strict=True):
            aggregates = point.get("totals")
            if aggregates is None:
                raise ValueError
            source, _, lv_loss, _, _, tx_network, tx_loss, _ = cast(
                tuple[float, ...], aggregates
            )
            expected_power = float(
                parents[4].revenue_meter_states.loc[(timestamp, meter_id)][
                    "expected_p_at_revenue_meter_w"
                ]
            )
            component_series.append(
                (source, lv_loss, tx_loss, tx_network, tx_network - expected_power)
            )
    except (KeyError, TypeError, ValueError):
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[5]
        return record
    energies = _validator_integrate(timestamps, component_series)
    if energies is None:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[5]
        return record
    source, lv_loss, tx_loss, tx_network, mv_hv_consumption = energies
    expected_energy = float(benchmark["expected_active_energy_wh"])
    measured_energy = float(benchmark["measured_active_energy_wh"])
    unexplained = float(benchmark["active_energy_residual_measured_minus_expected_wh"])
    try:
        delivery_consumption = math.fsum((lv_loss, tx_loss, mv_hv_consumption))
        reconstructed_expected = source - delivery_consumption
        accounting_residual = expected_energy - reconstructed_expected
        reconstructed_measured = reconstructed_expected + accounting_residual + unexplained
        derived = (
            delivery_consumption,
            reconstructed_expected,
            accounting_residual,
            reconstructed_measured,
        )
        valid = all(math.isfinite(value) for value in (*energies, *derived)) and math.isclose(
            measured_energy,
            reconstructed_measured,
            rel_tol=_REL_TOL,
            abs_tol=_ABS_TOL,
        )
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        record["revenue_meter_interval_delivery_attribution_state"] = _INTERVAL_STATES[5]
        return record
    record.update(
        selected_inverter_ac_source_energy_wh=source,
        lv_ac_owned_series_loss_energy_wh=lv_loss,
        transformer_owned_active_loss_energy_wh=tx_loss,
        transformer_network_terminal_energy_wh=tx_network,
        mv_hv_active_consumption_to_meter_energy_wh=mv_hv_consumption,
        modeled_delivery_active_consumption_energy_wh=delivery_consumption,
        reconstructed_expected_meter_active_energy_wh=reconstructed_expected,
        model_accounting_closure_residual_wh=accounting_residual,
        unexplained_meter_residual_measured_minus_expected_wh=unexplained,
        reconstructed_measured_meter_active_energy_wh=reconstructed_measured,
        revenue_meter_interval_delivery_attribution_state=_INTERVAL_STATES[6],
    )
    return record


def _validator_frame(
    index: pd.MultiIndex, records: list[dict[str, object]], *, interval: bool
) -> pd.DataFrame:
    columns = _INTERVAL_COLUMNS if interval else _INSTANT_COLUMNS
    booleans = _N_BOOL if interval else _I_BOOL
    floats = _N_FLOAT if interval else _I_FLOAT
    expected = pd.DataFrame.from_records(records, columns=columns, index=index)
    expected.index = index
    expected["contributing_transformer_count"] = expected[
        "contributing_transformer_count"
    ].astype("int64")
    for column in booleans:
        expected[column] = expected[column].astype("bool")
    for column in floats:
        expected[column] = expected[column].astype("float64")
    object_columns = (
        set(columns) - booleans - floats - {"contributing_transformer_count"}
    )
    for column in object_columns:
        expected[column] = expected[column].astype("object")
    return expected


def _validator_diagnostics(
    s13a: Any, instant: pd.DataFrame, interval: pd.DataFrame
) -> TopologyRevenueMeterDeliveryLossAttributionDiagnostics:
    instant_states = instant["revenue_meter_delivery_attribution_state"]
    interval_states = interval["revenue_meter_interval_delivery_attribution_state"]
    link_count = 0
    for _, state in s13a.transformer_states.iterrows():
        if bool(state["revenue_meter_on_transformer_path"]):
            link_count += 1
    return TopologyRevenueMeterDeliveryLossAttributionDiagnostics(
        revenue_meter_count=len(s13a.revenue_meter_boundary_by_id),
        instantaneous_row_count=len(instant),
        instantaneous_benchmark_eligible_count=int(instant["s14a_benchmark_eligible"].sum()),
        instantaneous_attribution_resolved_count=int(
            (instant_states == _INSTANT_STATES[-1]).sum()
        ),
        instantaneous_attribution_unresolved_count=int(
            (instant_states != _INSTANT_STATES[-1]).sum()
        ),
        interval_row_count=len(interval),
        interval_benchmark_eligible_count=int(interval["s14b_benchmark_eligible"].sum()),
        interval_attribution_resolved_count=int(
            (interval_states == _INTERVAL_STATES[-1]).sum()
        ),
        interval_attribution_unresolved_count=int(
            (interval_states != _INTERVAL_STATES[-1]).sum()
        ),
        contributing_transformer_link_count=link_count,
        instantaneous_state_counts=tuple(
            (state, int((instant_states == state).sum())) for state in _INSTANT_STATES
        ),
        interval_state_counts=tuple(
            (state, int((interval_states == state).sum())) for state in _INTERVAL_STATES
        ),
        model=REVENUE_METER_DELIVERY_ATTRIBUTION_MODEL_ID,
    )


def _validator_build(parents: tuple[Any, ...]) -> TopologyRevenueMeterDeliveryLossAttributionResult:
    s13a, s14a, s14b = parents[3], parents[5], parents[6]
    instant_index = s14a.states.index.copy()
    interval_index = s14b.states.index.copy()
    instant = _validator_frame(
        instant_index,
        [_validator_instant_record(parents, key) for key in instant_index],
        interval=False,
    )
    interval = _validator_frame(
        interval_index,
        [_validator_interval_record(parents, key) for key in interval_index],
        interval=True,
    )
    return TopologyRevenueMeterDeliveryLossAttributionResult(
        instant,
        interval,
        _validator_diagnostics(s13a, instant, interval),
    )


def _validate_result(
    parents: tuple[Any, ...], result: TopologyRevenueMeterDeliveryLossAttributionResult
) -> None:
    expected = _validator_build(parents)
    try:
        pd.testing.assert_frame_equal(
            result.instantaneous_states, expected.instantaneous_states, check_exact=True
        )
        pd.testing.assert_frame_equal(
            result.interval_states, expected.interval_states, check_exact=True
        )
    except AssertionError as error:
        raise RuntimeError("S14C result failed independent exact closure") from error
    if result.diagnostics != expected.diagnostics:
        raise RuntimeError("S14C diagnostics failed independent exact closure")
