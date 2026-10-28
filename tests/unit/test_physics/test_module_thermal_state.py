"""Per-timestamp native thermal physics, closure, provenance and independent replay."""

from dataclasses import FrozenInstanceError, replace
from typing import Any

import numpy as np
import pandas as pd
import pvlib.temperature
import pytest

from heliotelligence.physics import module_thermal_state as module
from heliotelligence.physics.module_thermal_authority import ModuleThermalMeasurementState
from tests.unit.test_physics.test_module_thermal_authority import (
    conversion,
    evidence,
    faiman,
    pvsyst,
)


def inputs(n: int = 1, **changes: Any) -> dict[str, Any]:
    index = pd.date_range(
        "2024-06-21 10:00", periods=n, freq="5min", tz="Europe/London", name="timestamp"
    )
    return dict(
        {
            "thermal_zone_id": "explicit-zone-A",
            "poa_global_wm2": pd.Series(1000.0, index=index),
            "ambient_air_temperature_c": pd.Series(20.0, index=index),
            "wind_speed_m_per_s": pd.Series(2.0, index=index),
        },
        **changes,
    )


def resolve(**values: Any) -> Any:
    return module.resolve_module_thermal_state(**values)


def first(result: Any) -> Any:
    return result.states.iloc[0]


def test_direct_cell_evidence_needs_no_environment_model_or_conversion() -> None:
    values = inputs()
    for name in ["poa_global_wm2", "ambient_air_temperature_c", "wind_speed_m_per_s"]:
        values[name][:] = np.nan
    values["measurements"] = {
        values["poa_global_wm2"].index[0]: ModuleThermalMeasurementState(evidence(value=0))
    }
    result = resolve(**values)
    row = first(result)
    assert row.cell_temperature_c == 0.0
    assert row.module_thermal_state == "resolved_direct_cell_temperature_evidence"
    assert row.direct_cell_temperature_used
    assert not row.model_temperature_used
    assert row.parameter_source == "sensor record"
    assert result.diagnostics.missing_poa_count == 0


@pytest.mark.parametrize("poa,expected", [(1000, 53), (700, 52.1), (0, 50)])
def test_explicit_module_to_cell_delta_at_reference_irradiance(poa: float, expected: float) -> None:
    values = inputs(conversion_authority=conversion())
    values["poa_global_wm2"][:] = poa
    values["measurements"] = {
        values["poa_global_wm2"].index[0]: ModuleThermalMeasurementState(
            module_back_surface_temperature=evidence("module_back_surface_temperature")
        )
    }
    values["ambient_air_temperature_c"][:] = np.nan
    values["wind_speed_m_per_s"][:] = np.nan
    row = first(resolve(**values))
    assert row.cell_temperature_c == pytest.approx(expected, abs=1e-12)
    assert row.module_back_surface_temperature_c == 50
    assert row.module_thermal_state == "resolved_measured_module_back_to_cell_temperature"
    assert row.conversion_parameter_source == "explicit conversion evidence"
    assert row.module_back_to_cell_conversion_applied
    assert not row.model_temperature_used


@pytest.mark.parametrize("factory", [pvsyst, faiman])
def test_native_models_match_pinned_pvlib_and_preserve_native_parameters(factory: Any) -> None:
    authority = factory()
    values = inputs(model_authority=authority)
    result = resolve(**values)
    row = first(result)
    if factory is pvsyst:
        expected = pvlib.temperature.pvsyst_cell(
            1000, 20, wind_speed=2, u_c=29, u_v=1.2, module_efficiency=0.2, alpha_absorption=0.9
        )
        assert row.selected_thermal_model_family == "pvsyst"
        assert np.isnan(row.model_u0_w_per_m2k)
        assert row.model_u_c_w_per_m2k == 29
    else:
        expected = pvlib.temperature.faiman(1000, 20, wind_speed=2, u0=25, u1=6.84)
        assert row.selected_thermal_model_family == "faiman"
        assert np.isnan(row.model_u_c_w_per_m2k)
        assert row.model_u0_w_per_m2k == 25
    assert row.cell_temperature_c == pytest.approx(expected, rel=1e-12)
    assert row.parameter_source == authority.parameter_source
    assert row.model_wind_speed_basis_description == authority.wind_speed_basis_description
    assert row.model_temperature_used and not row.measured_temperature_present


@pytest.mark.parametrize("with_conversion", [False, True])
def test_faiman_module_output_is_not_automatically_cell_temperature(with_conversion: bool) -> None:
    values = inputs(
        model_authority=faiman(output_temperature_quantity="module_back_surface_temperature")
    )
    if with_conversion:
        values["conversion_authority"] = conversion()
    row = first(resolve(**values))
    back = float(pvlib.temperature.faiman(1000, 20, wind_speed=2, u0=25, u1=6.84))
    assert row.module_back_surface_temperature_c == pytest.approx(back, rel=1e-12)
    assert row.module_back_surface_temperature_present
    if with_conversion:
        assert row.cell_temperature_c == pytest.approx(back + 3, rel=1e-12)
        assert row.module_thermal_state == "resolved_faiman_module_back_to_cell_temperature"
        assert row.module_back_to_cell_conversion_applied
    else:
        assert not row.cell_temperature_resolved
        assert np.isnan(row.cell_temperature_c)
        assert (
            row.module_thermal_state
            == "unresolved_model_output_is_module_temperature_without_conversion"
        )
        assert not row.model_temperature_used  # no selected cell model result


def test_per_row_precedence_and_unresolved_state_on_one_exact_grid() -> None:
    values = inputs(4, model_authority=pvsyst(), conversion_authority=conversion())
    times = values["poa_global_wm2"].index
    values["ambient_air_temperature_c"].iloc[3] = np.nan
    values["measurements"] = {
        times[0]: ModuleThermalMeasurementState(
            evidence(value=40), evidence("module_back_surface_temperature", 35)
        ),
        times[1]: ModuleThermalMeasurementState(
            module_back_surface_temperature=evidence("module_back_surface_temperature")
        ),
    }
    result = resolve(**values)
    assert result.states.module_thermal_state.tolist() == [
        "resolved_direct_cell_temperature_evidence",
        "resolved_measured_module_back_to_cell_temperature",
        "resolved_pvsyst_cell_temperature",
        "unresolved_missing_ambient_temperature",
    ]
    assert result.states.cell_temperature_c.iloc[:2].tolist() == [40.0, 53.0]
    assert result.states.module_back_evidence_parameter_source.iloc[0] == "sensor record"
    assert result.states.module_back_evidence_temperature_c.iloc[0] == 35
    assert result.diagnostics.resolved_timestamp_count == 3
    assert result.diagnostics.unresolved_timestamp_count == 1
    assert result.diagnostics.direct_cell_measurement_count == 1
    assert result.diagnostics.module_back_measurement_count == 2
    assert result.diagnostics.module_back_conversion_count == 1
    assert result.diagnostics.pvsyst_model_count == 1
    assert result.diagnostics.missing_ambient_count == 1
    assert (
        result.states.direct_cell_temperature_used.astype(int)
        + result.states.model_temperature_used.astype(int)
    ).max() == 1
    assert not result.states.temperature_interpolation_applied.any()
    assert not result.states.temperature_extrapolation_applied.any()


def test_sparse_measurements_do_not_trigger_whole_series_switch_or_persistence() -> None:
    values = inputs(3, model_authority=faiman())
    times = values["poa_global_wm2"].index
    values["measurements"] = {
        t: ModuleThermalMeasurementState(evidence(value=v))
        for t, v in [(times[0], 40), (times[2], 42)]
    }
    result = resolve(**values)
    assert result.states.selected_thermal_fidelity.tolist() == [
        "direct_cell_temperature_evidence",
        "faiman_cell_temperature",
        "direct_cell_temperature_evidence",
    ]
    assert result.states.measured_temperature_present.tolist() == [True, False, True]
    assert result.states.cell_temperature_c.iloc[[0, 2]].tolist() == [40, 42]


def test_model_fallback_after_unconvertible_evidence_is_explicit() -> None:
    values = inputs(model_authority=faiman())
    values["measurements"] = {
        values["poa_global_wm2"].index[0]: ModuleThermalMeasurementState(
            module_back_surface_temperature=evidence("module_back_surface_temperature", 90)
        )
    }
    result = resolve(**values)
    row = first(result)
    assert row.model_temperature_used and row.measured_temperature_present
    assert row.model_fallback_after_unusable_measurement
    assert row.measurement_path_unusable_reason == "missing_module_to_cell_conversion_authority"
    assert row.selected_thermal_fidelity == "faiman_cell_temperature"
    assert row.module_back_evidence_temperature_c == 90
    assert row.parameter_source == "explicit Faiman fit"
    assert result.diagnostics.model_fallback_after_unusable_measurement_count == 1
    assert result.diagnostics.module_back_conversion_count == 0


@pytest.mark.parametrize(
    "factory,field", [(pvsyst, "u_v_w_per_m2k_per_ms"), (faiman, "u1_w_per_m2k_per_ms")]
)
@pytest.mark.parametrize("coefficient", [0, 1])
def test_missing_wind_only_blocks_a_model_that_requires_it(
    factory: Any, field: str, coefficient: float
) -> None:
    values = inputs(model_authority=factory(**{field: coefficient}))
    values["wind_speed_m_per_s"][:] = np.nan
    result = resolve(**values)
    row = first(result)
    assert bool(row.cell_temperature_resolved) == (coefficient == 0)
    assert np.isnan(row.wind_speed_m_per_s)  # no fabricated wind observation
    if coefficient:
        assert row.module_thermal_state == "unresolved_missing_wind_speed"
        assert result.diagnostics.missing_required_wind_count == 1


@pytest.mark.parametrize("with_measurement", [False, True])
def test_missing_thermal_poa_stays_unresolved_for_conversion_or_models(
    with_measurement: bool,
) -> None:
    values = inputs(model_authority=pvsyst(), conversion_authority=conversion())
    values["poa_global_wm2"][:] = np.nan
    if with_measurement:
        values["measurements"] = {
            values["poa_global_wm2"].index[0]: ModuleThermalMeasurementState(
                module_back_surface_temperature=evidence("module_back_surface_temperature")
            )
        }
    row = first(resolve(**values))
    assert row.module_thermal_state == "unresolved_missing_thermal_poa"
    assert np.isnan(row.cell_temperature_c)


def test_unresolved_no_evidence_and_missing_measured_conversion() -> None:
    values = inputs()
    assert (
        first(resolve(**values)).module_thermal_state
        == "unresolved_no_temperature_evidence_or_model_authority"
    )
    values["measurements"] = {
        values["poa_global_wm2"].index[0]: ModuleThermalMeasurementState(
            module_back_surface_temperature=evidence("module_back_surface_temperature")
        )
    }
    result = resolve(**values)
    assert (
        first(result).module_thermal_state
        == "unresolved_missing_module_to_cell_conversion_authority"
    )
    assert result.diagnostics.missing_conversion_authority_count == 1


@pytest.mark.parametrize(
    "column,bad",
    [
        ("poa_global_wm2", -1),
        ("poa_global_wm2", np.inf),
        ("poa_global_wm2", True),
        ("poa_global_wm2", "1000"),
        ("ambient_air_temperature_c", -273.15),
        ("ambient_air_temperature_c", -300),
        ("ambient_air_temperature_c", np.inf),
        ("wind_speed_m_per_s", -1),
        ("wind_speed_m_per_s", np.inf),
        ("wind_speed_m_per_s", True),
    ],
)
def test_invalid_environment_rejected_even_when_measurement_would_resolve(
    column: str, bad: Any
) -> None:
    values = inputs()
    values[column] = pd.Series([bad], index=values[column].index)
    with pytest.raises(ValueError):
        resolve(**values)


@pytest.mark.parametrize("kind", ["naive", "duplicate", "nat", "mismatch", "timezone", "order"])
def test_exact_input_grid_validation(kind: str) -> None:
    values = inputs(2)
    index = values["poa_global_wm2"].index
    if kind == "naive":
        for series in [v for v in values.values() if isinstance(v, pd.Series)]:
            series.index = index.tz_localize(None)
    elif kind == "duplicate":
        values["poa_global_wm2"].index = pd.DatetimeIndex([index[0], index[0]])
    elif kind == "nat":
        values["poa_global_wm2"].index = pd.DatetimeIndex([index[0], pd.NaT])
    elif kind == "mismatch":
        values["ambient_air_temperature_c"].index = index + pd.Timedelta(minutes=1)
    elif kind == "timezone":
        values["ambient_air_temperature_c"].index = index.tz_convert("UTC")
    else:
        values["ambient_air_temperature_c"] = values["ambient_air_temperature_c"].iloc[::-1]
    with pytest.raises(ValueError):
        resolve(**values)


@pytest.mark.parametrize("bad", ["", " padded", None, 1])
def test_zone_identity_is_explicit(bad: Any) -> None:
    with pytest.raises(ValueError):
        resolve(**inputs(thermal_zone_id=bad))


@pytest.mark.parametrize("bad", ["pvsyst", {}, 29.0])
def test_unsupported_model_authority_is_not_inferred(bad: Any) -> None:
    with pytest.raises(TypeError):
        resolve(**inputs(model_authority=bad))


@pytest.mark.parametrize(
    "key",
    [
        "2024-06-21 10:00",
        pd.Timestamp("2024-06-21 10:00"),
        pd.Timestamp("2024-06-21 10:00", tz="UTC"),
        pd.NaT,
    ],
)
def test_measurement_keys_must_be_exact_and_on_the_grid(key: Any) -> None:
    values = inputs(measurements={key: ModuleThermalMeasurementState(evidence())})
    with pytest.raises(ValueError):
        resolve(**values)


def test_non_monotonic_grid_order_is_preserved_and_empty_schema_is_typed() -> None:
    values = inputs(3, model_authority=pvsyst())
    for name in ["poa_global_wm2", "ambient_air_temperature_c", "wind_speed_m_per_s"]:
        values[name] = values[name].iloc[[2, 0, 1]]
    result = resolve(**values)
    assert result.states.index.identical(values["poa_global_wm2"].index)
    empty = resolve(**inputs(0))
    assert empty.states.empty
    assert empty.states.cell_temperature_c.dtype == "float64"
    assert empty.states.cell_temperature_resolved.dtype == "bool"
    assert empty.states.thermal_zone_id.dtype == "object"
    assert empty.diagnostics.timestamp_count == 0


def test_finite_but_overflowing_equations_do_not_publish_resolved_values() -> None:
    values = inputs(model_authority=pvsyst(u_c_w_per_m2k=1e-308, u_v_w_per_m2k_per_ms=0))
    values["poa_global_wm2"][:] = 1e308
    row = first(resolve(**values))
    assert row.module_thermal_state == "unresolved_invalid_or_incomplete_model_inputs"
    assert np.isnan(row.cell_temperature_c)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cell_temperature_c", 999),
        ("selected_thermal_fidelity", "direct_cell_temperature_evidence"),
        ("selected_thermal_model_family", "faiman"),
        ("model_u_c_w_per_m2k", 10),
        ("parameter_source", "invented source"),
        ("temperature_interpolation_applied", True),
        ("temperature_extrapolation_applied", True),
        ("module_thermal_state", "unresolved"),
        ("module_thermal_state_contract", "wrong"),
    ],
)
def test_result_field_tampering_is_rejected(field: str, value: Any) -> None:
    values = inputs(model_authority=pvsyst())
    result = resolve(**values)
    altered = result.states.copy(deep=True)
    altered.loc[altered.index[0], field] = value
    with pytest.raises(ValueError, match="independent validation"):
        module.validate_module_thermal_state_result(replace(result, states=altered), **values)


def test_validator_replays_direct_and_conversion_and_diagnostics() -> None:
    values = inputs(2, conversion_authority=conversion())
    times = values["poa_global_wm2"].index
    values["measurements"] = {
        times[0]: ModuleThermalMeasurementState(evidence()),
        times[1]: ModuleThermalMeasurementState(
            module_back_surface_temperature=evidence("module_back_surface_temperature")
        ),
    }
    result = resolve(**values)
    for pos in [0, 1]:
        altered = result.states.copy(deep=True)
        altered.iloc[pos, altered.columns.get_loc("cell_temperature_c")] += 0.01
        with pytest.raises(ValueError):
            module.validate_module_thermal_state_result(replace(result, states=altered), **values)
    with pytest.raises(ValueError, match="diagnostics"):
        module.validate_module_thermal_state_result(
            replace(
                result, diagnostics=replace(result.diagnostics, module_back_conversion_count=99)
            ),
            **values,
        )
    with pytest.raises(TypeError):
        result.diagnostics.state_counts["invented"] = 1  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.diagnostics = result.diagnostics  # type: ignore[misc]


@pytest.mark.parametrize(
    "authority",
    [pvsyst(), faiman(), faiman(output_temperature_quantity="module_back_surface_temperature")],
)
def test_validator_is_independent_of_production_builders_and_pvlib(
    monkeypatch: pytest.MonkeyPatch,
    authority: Any,
) -> None:
    values = inputs(4, model_authority=authority, conversion_authority=conversion())
    times = values["poa_global_wm2"].index
    values["measurements"] = {
        times[0]: ModuleThermalMeasurementState(evidence()),
        times[1]: ModuleThermalMeasurementState(
            module_back_surface_temperature=evidence("module_back_surface_temperature")
        ),
    }
    values["poa_global_wm2"].iloc[3] = np.nan
    result = resolve(**values)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper called")

    for name in [
        "_record",
        "_frame",
        "_diagnostics",
        "_resolve_row",
        "_native_model",
        "_convert",
        "resolve_module_thermal_state",
    ]:
        monkeypatch.setattr(module, name, fail)
    monkeypatch.setattr(pvlib.temperature, "pvsyst_cell", fail)
    monkeypatch.setattr(pvlib.temperature, "faiman", fail)
    module.validate_module_thermal_state_result(result, **values)


def test_contract_metadata_is_canonical_and_not_stage_numbered() -> None:
    assert module.MODULE_THERMAL_STATE_CONTRACT_ID == (
        "admitted_module_temperature_evidence_and_explicit_thermal_model_authority_to_timestamped_cell_temperature_state_v1"
    )
    assert module.MODULE_THERMAL_STATE_MODEL_ID == (
        "per_timestamp_direct_cell_measurement_module_back_conversion_or_explicit_pvsyst_faiman_thermal_resolution_v1"
    )
    assert module.MODULE_THERMAL_STATE_SCOPE == (
        "module_cell_temperature_state_before_temperature_dependent_module_electrical_evaluation"
    )
    assert module.MODULE_THERMAL_STATE_COVERAGE_SCOPE == (
        "explicit_thermal_zone_timestamped_measurement_or_native_model_parameter_authority"
    )
    result = resolve(**inputs())
    assert first(result).module_thermal_state_contract == module.MODULE_THERMAL_STATE_CONTRACT_ID
    assert result.diagnostics.contract == module.MODULE_THERMAL_STATE_CONTRACT_ID


def test_canonical_conversion_is_distinct_from_unchanged_legacy_runtime() -> None:
    from heliotelligence.physics.thermal import calculate_cell_temp
    from tests.unit.test_physics.test_thermal import _test_site

    values = inputs(conversion_authority=conversion())
    values["poa_global_wm2"][:] = 700.0
    module_temperature = pd.Series(50.0, index=values["poa_global_wm2"].index)
    legacy = calculate_cell_temp(
        _test_site(),
        values["poa_global_wm2"],
        values["ambient_air_temperature_c"],
        values["wind_speed_m_per_s"],
        temp_module_measured=module_temperature,
    )
    values["measurements"] = {
        values["poa_global_wm2"].index[0]: ModuleThermalMeasurementState(
            module_back_surface_temperature=evidence("module_back_surface_temperature")
        )
    }
    canonical = first(resolve(**values))
    assert legacy.iloc[0] == pytest.approx(50.021, abs=1e-12)
    assert canonical.cell_temperature_c == pytest.approx(52.1, abs=1e-12)


def test_full_channel_provenance_survives_direct_cell_precedence() -> None:
    values = inputs()
    supplied = evidence(
        "module_back_surface_temperature",
        49,
        evidence_kind="aggregated_sensor_measurement",
        aggregation_description="Documented sensor A/B weighted average",
    )
    cell = evidence(
        value=51,
        evidence_kind="documented_external_temperature_estimate",
        parameter_source="external cell estimate",
        measurement_location_description=None,
    )
    values["measurements"] = {
        values["poa_global_wm2"].index[0]: ModuleThermalMeasurementState(cell, supplied)
    }
    row = first(resolve(**values))
    assert row.cell_temperature_c == 51
    assert row.cell_evidence_evidence_kind == "documented_external_temperature_estimate"
    assert row.module_back_evidence_evidence_kind == "aggregated_sensor_measurement"
    assert row.module_back_evidence_aggregation_description == supplied.aggregation_description
    assert (
        row.module_back_evidence_measurement_location_description
        == supplied.measurement_location_description
    )
    assert row.parameter_source == "external cell estimate"


@pytest.mark.parametrize(
    "kind", ["outside_grid", "equivalent_instant_other_zone", "state_type", "mapping_type"]
)
def test_measurement_admission_cannot_invent_or_ignore_rows(kind: str) -> None:
    values = inputs()
    timestamp = values["poa_global_wm2"].index[0]
    if kind == "outside_grid":
        values["measurements"] = {
            timestamp + pd.Timedelta(minutes=1): ModuleThermalMeasurementState(evidence())
        }
    elif kind == "equivalent_instant_other_zone":
        values["measurements"] = {
            timestamp.tz_convert("UTC"): ModuleThermalMeasurementState(evidence())
        }
    elif kind == "state_type":
        values["measurements"] = {timestamp: {"cell_temperature": 50}}
    else:
        values["measurements"] = [ModuleThermalMeasurementState(evidence())]
    with pytest.raises((ValueError, TypeError)):
        resolve(**values)


def test_invalid_supplied_authority_cannot_hide_behind_a_measurement() -> None:
    authority = pvsyst()
    object.__setattr__(authority, "u_c_w_per_m2k", -1)
    values = inputs(model_authority=authority)
    values["measurements"] = {
        values["poa_global_wm2"].index[0]: ModuleThermalMeasurementState(evidence())
    }
    with pytest.raises(ValueError):
        resolve(**values)


def test_result_is_independently_validated_before_return(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pvlib.temperature, "faiman", lambda **kwargs: 999.0)
    with pytest.raises(ValueError, match="independent validation"):
        resolve(**inputs(model_authority=faiman()))


@pytest.mark.parametrize("change", ["timestamp", "extra_row", "schema"])
def test_validator_rejects_changed_row_universe_or_schema(change: str) -> None:
    values = inputs(model_authority=pvsyst())
    result = resolve(**values)
    altered = result.states.copy(deep=True)
    if change == "timestamp":
        altered.index = altered.index + pd.Timedelta(minutes=1)
    elif change == "extra_row":
        extra = altered.copy(deep=True)
        extra.index = extra.index + pd.Timedelta(minutes=5)
        altered = pd.concat([altered, extra])
    else:
        altered = altered.drop(columns="model_parameter_source")
    with pytest.raises(ValueError, match="independent validation"):
        module.validate_module_thermal_state_result(replace(result, states=altered), **values)
