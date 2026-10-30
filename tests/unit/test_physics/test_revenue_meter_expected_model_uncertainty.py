from __future__ import annotations

import ast
import math
from dataclasses import FrozenInstanceError, asdict, fields, replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import revenue_meter_expected_model_uncertainty as m
from tests.unit.test_physics import test_mv_hv_operating_solution as parent

T = pd.Timestamp("2026-01-01", tz="UTC")


def assert_records(left: pd.Series, right: pd.Series) -> None:
    # Record dictionary insertion order is private; public frame order is exact.
    pd.testing.assert_series_equal(left, right, check_like=True)


def authority(**changes: Any) -> m.RevenueMeterExpectedModelUncertaintyAuthority:
    values = dict(
        active_power_relative_error_bound_fraction=0.01,
        active_power_absolute_error_bound_w=5.0,
        reactive_power_relative_error_bound_fraction=0.02,
        reactive_power_absolute_error_bound_var=3.0,
        uncertainty_interpretation=m.UNCERTAINTY_INTERPRETATION,
        relative_error_reference_basis=m.RELATIVE_ERROR_REFERENCE_BASIS,
        combination_basis=m.COMBINATION_BASIS,
        model_chain_scope=m.MODEL_CHAIN_SCOPE,
        expected_time_semantics=m.EXPECTED_TIME_SEMANTICS,
        evidence_kind="validated_complete_model_chain_bound",
        parameter_source="explicit complete-model study",
        confidence="medium",
        method_reference="externally admitted maximum bound",
        applicability_description="specified model version, meter, operating domain and dates",
    )
    values.update(changes)
    return m.RevenueMeterExpectedModelUncertaintyAuthority(**values)


def numerical_row(p: float = 1000, q: float = 200) -> pd.Series:
    # Isolated equation unit inputs; canonical parent integration is tested separately.
    return pd.Series(
        dict(
            mv_hv_operating_solution_resolved=True,
            revenue_meter_expected_state="resolved_expected_revenue_meter_boundary_power",
            expected_p_at_revenue_meter_w=p,
            expected_q_at_revenue_meter_var=q,
        )
    )


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: Any) -> None:
    database = parent.support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


def build_values(**kwargs: Any) -> dict[str, Any]:
    values = parent._values(**kwargs)
    values["mv_hv_operating_solution"] = m.calculate_topology_mv_hv_operating_solution(**values)
    return values


def resolve(values: Any, mapping: Any = None) -> Any:
    return m.resolve_topology_revenue_meter_expected_model_uncertainty(
        **values, revenue_meter_expected_model_uncertainty_by_meter_id=mapping
    )


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    with pytest.MonkeyPatch.context() as patch:
        database = parent.support.conversion_support._database
        patch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
        patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)
        return build_values(p=1000, q=200)


@pytest.fixture(scope="module")
def valid_result(baseline: Any) -> Any:
    with pytest.MonkeyPatch.context() as patch:
        database = parent.support.conversion_support._database
        patch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
        patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)
        return resolve(baseline, {"meter": authority()})


@pytest.mark.parametrize(
    "p,bound,lower,upper", [(1000, 15, 985, 1015), (-1000, 15, -1015, -985), (0, 5, -5, 5)]
)
def test_exact_signed_examples(p: float, bound: float, lower: float, upper: float) -> None:
    row = numerical_row(p)
    record = m._record(T, row, authority())
    assert record["active_power_expected_model_uncertainty_bound_w"] == bound
    assert record["expected_active_power_lower_bound_w"] == lower
    assert record["expected_active_power_upper_bound_w"] == upper
    assert record["active_power_relative_uncertainty_component_w"] == abs(p) * 0.01
    assert record == m._validator_record(T, row, authority())


@pytest.mark.parametrize("channel", ["active", "reactive", "both"])
@pytest.mark.parametrize(
    "relative,absolute", [(0, None), (None, 0), (0.01, None), (None, 5), (0.01, 5), (2, 5)]
)
def test_channel_independence_and_explicit_terms(
    channel: str, relative: Any, absolute: Any
) -> None:
    terms = dict.fromkeys(m._AUTHORITY_NUMBERS)
    for name, unit, _ in m._CHANNELS:
        if channel in (name, "both"):
            terms[f"{name}_power_relative_error_bound_fraction"] = relative
            terms[f"{name}_power_absolute_error_bound_{unit}"] = absolute
    a = authority(**terms)
    out = m._record(T, numerical_row(), a)
    expected = m._validator_record(T, numerical_row(), a)
    assert_records(pd.Series(out), pd.Series(expected))
    for name, unit, source in m._CHANNELS:
        selected = channel in (name, "both")
        assert out[f"{name}_power_expected_model_uncertainty_resolved"] == selected
        if selected:
            assert out[f"{name}_power_expected_model_uncertainty_bound_{unit}"] == (
                abs(numerical_row()[source]) * (relative or 0) + (absolute or 0)
            )
        else:
            assert math.isnan(out[f"{name}_power_expected_model_uncertainty_bound_{unit}"])


@pytest.mark.parametrize("field", m._AUTHORITY_NUMBERS)
@pytest.mark.parametrize("value", [-1, math.nan, math.inf, -math.inf, True, "0.01", 10**1000])
def test_invalid_numerical_authority(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        authority(**{field: value})


@pytest.mark.parametrize("field", (*m._SEMANTICS, *m._PROVENANCE, *m._OPTIONAL))
@pytest.mark.parametrize("value", ["", " padded", "padded ", 123])
def test_exact_text(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        authority(**{field: value})


@pytest.mark.parametrize("field", (*m._SEMANTICS, "evidence_kind", "confidence"))
def test_unsupported_semantics_and_forged_frozen_instance(field: str, baseline: Any) -> None:
    with pytest.raises(ValueError):
        authority(**{field: "unsupported"})
    a = authority()
    object.__setattr__(a, field, "unsupported")
    with pytest.raises(ValueError):
        m._admit_authorities({"meter": a}, ("meter",))
    # Validator owns its admission and must reject the same forged evidence.
    with pytest.raises(ValueError):
        m._validate_result(
            baseline["mv_hv_network_authority"],
            baseline["mv_hv_operating_solution"],
            m.RevenueMeterExpectedModelUncertaintyResult(pd.DataFrame(), None),
            {"meter": a},
        )


def test_explicit_attestation_and_frozen_authority() -> None:
    with pytest.raises(ValueError):
        authority(**dict.fromkeys(m._AUTHORITY_NUMBERS))
    a = authority()
    with pytest.raises(FrozenInstanceError):
        a.confidence = "high"
    values = asdict(a)
    del values["relative_error_reference_basis"]
    with pytest.raises(TypeError):
        m.RevenueMeterExpectedModelUncertaintyAuthority(**values)
    assert (
        a.relative_error_reference_basis
        == "absolute_same_channel_expected_power_in_primary_engineering_units"
    )


@pytest.mark.parametrize(
    "basis",
    [
        "unknown_true_value",
        "rated_power",
        "plant_capacity",
        "full_scale",
        "inverter_capacity",
        "transformer_rating",
        "current",
        "irradiance",
        "another_channel",
        "another_plane",
    ],
)
def test_other_reference_bases_not_directly_admissible(basis: str) -> None:
    with pytest.raises(ValueError):
        authority(relative_error_reference_basis=basis)


@pytest.mark.parametrize(
    "lower,upper,expected",
    [
        (0, 0, True),
        (-1, 1, True),
        (1, None, False),
        (None, -1, False),
        (None, 0, True),
        (0, None, True),
        (None, None, True),
    ],
)
def test_inclusive_pointwise_validity(lower: Any, upper: Any, expected: bool) -> None:
    a = authority(
        valid_from_timestamp=None if lower is None else T + pd.Timedelta(seconds=lower),
        valid_to_timestamp=None if upper is None else T + pd.Timedelta(seconds=upper),
    )
    out = m._record(T, numerical_row(), a)
    assert out["expected_model_uncertainty_temporally_applicable"] == expected
    assert_records(pd.Series(out), pd.Series(m._validator_record(T, numerical_row(), a)))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"valid_from_timestamp": pd.NaT},
        {"valid_to_timestamp": "2026-01-01"},
        {"valid_from_timestamp": T, "valid_to_timestamp": T - pd.Timedelta(seconds=1)},
        {"valid_from_timestamp": T, "valid_to_timestamp": T.tz_localize(None)},
    ],
)
def test_invalid_validity(kwargs: Any) -> None:
    with pytest.raises(ValueError):
        authority(**kwargs)


@pytest.mark.parametrize("naive", [False, True])
def test_timezone_comparison_and_preserved_representation(naive: bool) -> None:
    limit = T.tz_localize(None) if naive else T.tz_convert("Europe/Paris")
    a = authority(valid_from_timestamp=limit, valid_to_timestamp=limit)
    out = m._record(T, numerical_row(), a)
    assert out["expected_model_uncertainty_temporally_applicable"] == (not naive)
    assert str(out["valid_from_timestamp"].tz) == str(limit.tz)
    assert_records(pd.Series(out), pd.Series(m._validator_record(T, numerical_row(), a)))


@pytest.mark.parametrize(
    "mapping", [[], "meter", {1: None}, {"unknown": None}, {"meter": object()}]
)
def test_mapping_rejection(mapping: Any) -> None:
    with pytest.raises(ValueError):
        m._admit_authorities(mapping, ("meter",))


def test_public_admission_revalidates_forged_authority(baseline: Any) -> None:
    a = authority()
    object.__setattr__(a, "active_power_absolute_error_bound_w", -1)
    with pytest.raises(ValueError):
        resolve(baseline, {"meter": a})


def test_canonical_baseline_unchanged_and_no_interval_fields(
    baseline: Any, valid_result: Any
) -> None:
    source = baseline["mv_hv_operating_solution"].revenue_meter_states
    original = source.copy(deep=True)
    pd.testing.assert_frame_equal(valid_result.states[source.columns], source)
    row = valid_result.states.iloc[0]
    assert row.expected_time_semantics == m.EXPECTED_TIME_SEMANTICS
    assert row.active_power_expected_model_uncertainty_bound_w == (
        abs(row.expected_p_at_revenue_meter_w) * 0.01 + 5
    )
    assert row.reactive_power_expected_model_uncertainty_bound_var == (
        abs(row.expected_q_at_revenue_meter_var) * 0.02 + 3
    )
    assert not any("energy" in key or "interval" in key for key in valid_result.states.columns)
    fresh = resolve(baseline, {"meter": authority()})
    fresh.states.loc[fresh.states.index[0], "expected_p_at_revenue_meter_w"] += 1
    pd.testing.assert_frame_equal(source, original)


def test_missing_authority_preserves_baseline(baseline: Any) -> None:
    result = resolve(baseline)
    assert result.states.iloc[0].expected_model_uncertainty_state == m._STATES[2]
    assert result.diagnostics.uncertainty_authority_missing_count == 1
    assert result.states.iloc[0].expected_power_state_resolved


def test_unresolved_s13c_is_not_a_missing_authority_gap() -> None:
    values = parent._values()
    values["grid_boundary_voltage_by_key"] = {}
    values["mv_hv_grid_boundary_voltage_authority"] = parent.module._call(
        parent.resolve_topology_mv_hv_grid_boundary_voltage_authority, values
    )
    values["mv_hv_operating_solution"] = m.calculate_topology_mv_hv_operating_solution(**values)
    result = resolve(values)
    assert result.states.iloc[0].expected_model_uncertainty_state == m._STATES[1]
    assert result.diagnostics.uncertainty_authority_missing_count == 0
    assert result.diagnostics.expected_operating_solution_unresolved_count == 1
    pd.testing.assert_frame_equal(
        result.states[values["mv_hv_operating_solution"].revenue_meter_states.columns],
        values["mv_hv_operating_solution"].revenue_meter_states,
    )


def test_missing_row_state_is_distinct_without_fabricating_physics() -> None:
    out = m._record(T, None, authority())
    assert out["expected_model_uncertainty_state"] == m._STATES[0]
    assert not out["expected_power_state_present"]
    assert_records(pd.Series(out), pd.Series(m._validator_record(T, None, authority())))


@pytest.mark.parametrize(
    "parent_name,mode",
    [
        ("mv_hv_network_authority", "frame"),
        ("mv_hv_operating_solution", "missing"),
        ("mv_hv_operating_solution", "value"),
        ("mv_hv_operating_solution", "diagnostics"),
    ],
)
def test_exact_parent_replay_rejects_modified_or_missing_rows(
    baseline: Any, parent_name: str, mode: str
) -> None:
    values = dict(baseline)
    result = values[parent_name]
    if parent_name == "mv_hv_network_authority":
        frame = result.transformer_states.copy(deep=True)
        frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
        values[parent_name] = replace(result, transformer_states=frame)
    elif mode == "diagnostics":
        values[parent_name] = replace(
            result, diagnostics=replace(result.diagnostics, timestamp_count=99)
        )
    else:
        frame = result.revenue_meter_states.copy(deep=True)
        if mode == "missing":
            frame = frame.iloc[:0]
        else:
            frame.iloc[0, frame.columns.get_loc("expected_p_at_revenue_meter_w")] = 123
        values[parent_name] = replace(result, revenue_meter_states=frame)
    with pytest.raises(ValueError, match="S13"):
        resolve(values, {"meter": authority()})


def test_two_meters_partial_mapping_reuse_and_deterministic_order(baseline: Any) -> None:
    values = dict(baseline)
    meter = values["revenue_meter_boundary_by_id"]["meter"]
    # Separate canonical grid trees: S13A forbids two meters on one TX path.
    values["mv_hv_node_by_id"] = {
        **values["mv_hv_node_by_id"],
        "other-grid": parent._node("other-grid", "network_exit"),
    }
    values["mv_hv_grid_boundary_by_id"] = {
        **values["mv_hv_grid_boundary_by_id"],
        "grid-b": replace(
            values["mv_hv_grid_boundary_by_id"]["grid"],
            grid_boundary_id="grid-b",
            node_id="other-grid",
        ),
    }
    timestamp = next(iter(values["grid_boundary_voltage_by_key"]))[0]
    values["grid_boundary_voltage_by_key"] = {
        **values["grid_boundary_voltage_by_key"],
        (timestamp, "grid-b"): next(iter(values["grid_boundary_voltage_by_key"].values())),
    }
    values["revenue_meter_boundary_by_id"] = {
        "meter-b": replace(meter, revenue_meter_id="meter-b", node_id="other-grid"),
        "meter-a": replace(meter, revenue_meter_id="meter-a"),
    }
    values["mv_hv_network_authority"] = m._call(m.resolve_topology_mv_hv_network_authority, values)
    values["mv_hv_grid_boundary_voltage_authority"] = parent.module._call(
        parent.resolve_topology_mv_hv_grid_boundary_voltage_authority, values
    )
    values["mv_hv_operating_solution"] = m.calculate_topology_mv_hv_operating_solution(**values)
    a = authority()
    partial = resolve(values, {"meter-a": a})
    assert partial.diagnostics.uncertainty_authority_missing_count == 1
    assert partial.diagnostics.active_power_uncertainty_resolved_count == 1
    first = resolve(values, {"meter-a": a, "meter-b": a})
    second = resolve(values, {"meter-b": a, "meter-a": a})
    pd.testing.assert_frame_equal(first.states, second.states)
    assert list(first.states.index.get_level_values("revenue_meter_id")) == ["meter-a", "meter-b"]
    assert first.diagnostics == second.diagnostics


@pytest.mark.parametrize(
    "p,relative,absolute", [(1000, 1e308, None), (1, 1e308, 1e308), (1e308, None, 1e308)]
)
def test_nonfinite_product_sum_or_bound_not_published(
    p: float, relative: Any, absolute: Any
) -> None:
    a = authority(
        active_power_relative_error_bound_fraction=relative,
        active_power_absolute_error_bound_w=absolute,
        reactive_power_relative_error_bound_fraction=None,
        reactive_power_absolute_error_bound_var=None,
    )
    out = m._record(T, numerical_row(p), a)
    assert out["expected_model_uncertainty_state"] == m._STATES[7]
    assert math.isnan(out["active_power_expected_model_uncertainty_bound_w"])
    assert_records(pd.Series(out), pd.Series(m._validator_record(T, numerical_row(p), a)))


def test_descriptive_metadata_and_confidence_do_not_change_arithmetic(
    baseline: Any, valid_result: Any
) -> None:
    a = authority(confidence="unknown", **dict.fromkeys(m._OPTIONAL, "another model/study/version"))
    changed = resolve(baseline, {"meter": a})
    pd.testing.assert_frame_equal(
        valid_result.states[list(m._FLOAT)], changed.states[list(m._FLOAT)]
    )


@pytest.mark.parametrize("field", m._EXTRA_COLUMNS)
def test_every_public_uncertainty_field_tamper(
    baseline: Any, valid_result: Any, field: str
) -> None:
    frame = valid_result.states.copy(deep=True)
    old = frame.iloc[0][field]
    bad = not bool(old) if field in m._BOOL else 123.456 if field in m._FLOAT else "forged"
    frame.loc[frame.index[0], field] = bad
    with pytest.raises(ValueError):
        m._validate_result(
            baseline["mv_hv_network_authority"],
            baseline["mv_hv_operating_solution"],
            replace(valid_result, states=frame),
            {"meter": authority()},
        )


@pytest.mark.parametrize(
    "field", [f.name for f in fields(m.RevenueMeterExpectedModelUncertaintyDiagnostics)]
)
def test_every_diagnostic_tamper(baseline: Any, valid_result: Any, field: str) -> None:
    value = getattr(valid_result.diagnostics, field)
    bad = "forged" if field == "model" else () if field == "state_counts" else value + 1
    with pytest.raises(ValueError):
        m._validate_result(
            baseline["mv_hv_network_authority"],
            baseline["mv_hv_operating_solution"],
            replace(valid_result, diagnostics=replace(valid_result.diagnostics, **{field: bad})),
            {"meter": authority()},
        )


@pytest.mark.parametrize("mode", ["both", "active", "reactive", "missing", "outside"])
def test_public_validator_independent_of_all_production_uncertainty_helpers(
    monkeypatch: Any, baseline: Any, valid_result: Any, mode: str
) -> None:
    changes: dict[str, Any] = {}
    if mode == "active":
        changes.update(
            reactive_power_relative_error_bound_fraction=None,
            reactive_power_absolute_error_bound_var=None,
        )
    elif mode == "reactive":
        changes.update(
            active_power_relative_error_bound_fraction=None,
            active_power_absolute_error_bound_w=None,
        )
    elif mode == "outside":
        timestamp = baseline["mv_hv_operating_solution"].revenue_meter_states.index[0][0]
        changes["valid_from_timestamp"] = timestamp + pd.Timedelta(seconds=1)
    mapping = {} if mode == "missing" else {"meter": authority(**changes)}
    result = valid_result if mode == "both" else resolve(baseline, mapping)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("production uncertainty helper invoked")

    for name in (
        "_parents",
        "_admit_authorities",
        "_record",
        "_channel",
        "_frame",
        "_diagnostics",
        "resolve_topology_revenue_meter_expected_model_uncertainty",
    ):
        monkeypatch.setattr(m, name, fail)
    m.validate_revenue_meter_expected_model_uncertainty(
        result,
        **baseline,
        revenue_meter_expected_model_uncertainty_by_meter_id=mapping,
    )


def test_contract_literals_and_no_cross_layer_imports() -> None:
    assert m.REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_AUTHORITY_CONTRACT_ID == (
        "explicit_complete_expected_model_chain_quantitative_uncertainty_authority_v1"
    )
    assert m.REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_CONTRACT_ID == (
        "admitted_s13a_s13c_and_expected_model_uncertainty_authority_to_timestamped_"
        "revenue_meter_expected_model_uncertainty_state_v1"
    )
    assert m.REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_MODEL_ID == (
        "explicit_complete_chain_symmetric_pq_expected_model_uncertainty_bound_evaluation_v1"
    )
    tree = ast.parse(Path(m.__file__).read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(
        name
        and (
            "measurement_uncertainty" in name
            or "revenue_meter_interval" in name
            or "revenue_meter_power" in name
            or "loss_attribution" in name
        )
        for name in imports
    )


def test_non_exact_authority_type_is_rejected() -> None:
    class Derived(m.RevenueMeterExpectedModelUncertaintyAuthority):
        pass

    instance = Derived(**asdict(authority()))
    with pytest.raises(ValueError):
        m._admit_authorities({"meter": instance}, ("meter",))


@pytest.mark.parametrize("field", m._VALIDITY)
def test_equivalent_instant_timezone_representation_tamper(baseline: Any, field: str) -> None:
    timestamp = baseline["mv_hv_operating_solution"].revenue_meter_states.index[0][0]
    mapping = {"meter": authority(**{field: timestamp})}
    result = resolve(baseline, mapping)
    frame = result.states.copy(deep=True)
    frame.loc[frame.index[0], field] = timestamp.tz_convert("Europe/Paris")
    with pytest.raises(ValueError):
        m._validate_result(
            baseline["mv_hv_network_authority"],
            baseline["mv_hv_operating_solution"],
            replace(result, states=frame),
            mapping,
        )


@pytest.mark.parametrize("energised,sign", [(False, 0), (True, -1)])
def test_canonical_zero_and_import_expected_power(energised: bool, sign: int) -> None:
    options = {"p": 0.0, "energised": energised}
    if not energised:
        options["boundary_voltage"] = 11000.0
    values = build_values(**options)
    result = resolve(values, {"meter": authority()})
    row = result.states.iloc[0]
    assert row.expected_power_state_resolved
    assert row.active_power_expected_model_uncertainty_resolved
    assert (
        row.expected_p_at_revenue_meter_w == 0
        if sign == 0
        else row.expected_p_at_revenue_meter_w < 0
    )
    assert (
        row.active_power_expected_model_uncertainty_bound_w
        == abs(row.expected_p_at_revenue_meter_w) * 0.01 + 5
    )


def test_empty_canonical_meter_universe_has_exact_typed_schema(baseline: Any) -> None:
    values = dict(baseline, revenue_meter_boundary_by_id={})
    values["mv_hv_network_authority"] = m._call(m.resolve_topology_mv_hv_network_authority, values)
    values["mv_hv_grid_boundary_voltage_authority"] = parent.module._call(
        parent.resolve_topology_mv_hv_grid_boundary_voltage_authority, values
    )
    values["mv_hv_operating_solution"] = m.calculate_topology_mv_hv_operating_solution(**values)
    result = resolve(values)
    assert result.states.empty
    assert result.diagnostics.row_count == result.diagnostics.revenue_meter_count == 0
    for field in m._BOOL:
        assert str(result.states[field].dtype) == "bool"
    for field in m._FLOAT:
        assert str(result.states[field].dtype) == "float64"
