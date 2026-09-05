"""Tests for shared environmental-state routing into module I-V curves."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pvlib.ivtools.sdm
import pvlib.pvsystem
import pytest

from heliotelligence.config.site import (
    ElectricalTopologyConfig,
    InverterUnitConfig,
    ModuleConfig,
    MPPTConfig,
    SiteConfig,
    StringConfig,
)
from heliotelligence.physics import electrical
from heliotelligence.physics.electrical import (
    StringModuleIVInputs,
    calculate_module_iv_curves,
    calculate_physical_mismatch,
    calculate_topology_module_iv_curves,
    calculate_topology_module_iv_curves_from_environment_states,
    calculate_topology_mppt_mismatch,
    calculate_topology_string_iv_curves,
    scale_module_iv_to_string,
)


def _site(module: ModuleConfig | None = None) -> SiteConfig:
    return SiteConfig(
        id="environment-routing-test",
        name="Environment Routing Test",
        latitude=52.56,
        longitude=1.21,
        altitude_m=35.0,
        timezone="Europe/London",
        capacity_kwp=1.0,
        solcast_resource_id="test",
        module=module
        or ModuleConfig(
            local_module_name="JKM570N-72HL4-BDV",
            technology="mono_si",
        ),
    )


def _tier_four_site() -> SiteConfig:
    return _site(
        ModuleConfig(
            v_mp=41.64,
            i_mp=13.69,
            v_oc=50.60,
            i_sc=14.36,
            alpha_sc=0.045,
            beta_voc=-0.25,
            gamma_pmp=-0.29,
            cells_in_series=144,
            pnom_wp=570.0,
        )
    )


def _tier_five_site() -> SiteConfig:
    return _site(ModuleConfig(pnom_wp=570.0, gamma_pmp=-0.29))


def _index(*hours: int) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [pd.Timestamp(f"2024-06-21 {hour:02d}:00", tz="Europe/London") for hour in hours]
    )


def _inputs(
    poa: list[float] | None = None,
    temperature: list[float] | None = None,
    *,
    index: pd.Index | None = None,
    spectral: bool = False,
) -> StringModuleIVInputs:
    poa = [900.0] if poa is None else poa
    temperature = [30.0] if temperature is None else temperature
    index = _index(12) if index is None else index
    return StringModuleIVInputs(
        poa_total=pd.Series(poa, index=index, dtype=float, name="poa"),
        t_cell=pd.Series(temperature, index=index, dtype=float, name="temperature"),
        solar_zenith=(
            pd.Series([35.0] * len(index), index=index, dtype=float, name="zenith")
            if spectral
            else None
        ),
        precipitable_water=(
            pd.Series([1.5] * len(index), index=index, dtype=float, name="water")
            if spectral
            else None
        ),
    )


def _string(
    string_id: str,
    modules: int = 1,
    *,
    zone_id: str | None = None,
) -> StringConfig:
    return StringConfig(
        id=string_id,
        modules_per_string=modules,
        zone_id=zone_id,
        label=f"label-{string_id}",
    )


def _topology(*strings: StringConfig) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="inverter-A",
                group_id="group-A",
                model_ref="generic-model",
                mppts=[MPPTConfig(id="mppt-1", strings=list(strings))],
            )
        ]
    )


def _direct(
    site: SiteConfig,
    inputs: StringModuleIVInputs,
    points: int = 11,
) -> pd.DataFrame:
    return calculate_module_iv_curves(
        site,
        inputs.poa_total,
        inputs.t_cell,
        solar_zenith=inputs.solar_zenith,
        precipitable_water=inputs.precipitable_water,
        voltage_points=points,
    )


def _count_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, int], dict[str, Callable[..., object]]]:
    calls = {
        "validate": 0,
        "resolve": 0,
        "fit": 0,
        "effective": 0,
        "calcparams": 0,
        "evaluate": 0,
    }
    real = {
        "validate": electrical._validate_iv_curve_inputs,
        "resolve": electrical.resolve_module_params,
        "fit": pvlib.ivtools.sdm.fit_desoto_batzelis,
        "effective": electrical._calculate_effective_irradiance,
        "calcparams": pvlib.pvsystem.calcparams_desoto,
        "evaluate": electrical._evaluate_module_iv_curves,
    }

    def wrap(name: str) -> Callable[..., object]:
        def counted(*args: object, **kwargs: object) -> object:
            calls[name] += 1
            return real[name](*args, **kwargs)

        return counted

    monkeypatch.setattr(electrical, "_validate_iv_curve_inputs", wrap("validate"))
    monkeypatch.setattr(electrical, "resolve_module_params", wrap("resolve"))
    monkeypatch.setattr(pvlib.ivtools.sdm, "fit_desoto_batzelis", wrap("fit"))
    monkeypatch.setattr(
        electrical, "_calculate_effective_irradiance", wrap("effective")
    )
    monkeypatch.setattr(pvlib.pvsystem, "calcparams_desoto", wrap("calcparams"))
    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", wrap("evaluate"))
    return calls, real


def test_empty_topology_and_mappings_return_empty_before_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _count_physics(monkeypatch)

    result = calculate_topology_module_iv_curves_from_environment_states(
        _tier_four_site(), ElectricalTopologyConfig(inverters=[]), {}, {}, voltage_points=11
    )

    assert result == {}
    assert calls == {
        "validate": 0,
        "resolve": 0,
        "fit": 0,
        "effective": 0,
        "calcparams": 0,
        "evaluate": 0,
    }


def test_invalid_voltage_points_precedes_empty_return_and_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _count_physics(monkeypatch)

    with pytest.raises(ValueError, match="voltage_points must be at least 3"):
        calculate_topology_module_iv_curves_from_environment_states(
            _tier_four_site(), ElectricalTopologyConfig(inverters=[]), {}, {}, voltage_points=2
        )

    assert calls == {
        "validate": 0,
        "resolve": 0,
        "fit": 0,
        "effective": 0,
        "calcparams": 0,
        "evaluate": 0,
    }


@pytest.mark.parametrize(
    ("assignments", "message"),
    [
        ({"string-b": "state-b"}, "missing string ids: string-a"),
        (
            {"string-a": "state-a", "string-b": "state-b", "string-z": "state-z"},
            "unexpected string ids: string-z",
        ),
        (
            {"string-z": "state-z"},
            "missing string ids: string-a, string-b; unexpected string ids: string-z",
        ),
    ],
)
def test_string_assignment_agreement_is_exact_and_precedes_physics(
    monkeypatch: pytest.MonkeyPatch,
    assignments: dict[str, str],
    message: str,
) -> None:
    calls, _ = _count_physics(monkeypatch)
    topology = _topology(_string("string-b"), _string("string-a"))

    with pytest.raises(ValueError) as error:
        calculate_topology_module_iv_curves_from_environment_states(
            _tier_four_site(), topology, assignments, {}
        )

    assert str(error.value) == (
        "environment_state_id_by_string_id does not match electrical topology: "
        + message
    )
    assert calls == {
        "validate": 0,
        "resolve": 0,
        "fit": 0,
        "effective": 0,
        "calcparams": 0,
        "evaluate": 0,
    }


@pytest.mark.parametrize(
    ("states", "message"),
    [
        ({"state-a": _inputs()}, "missing environment state ids: state-b"),
        (
            {"state-a": _inputs(), "state-b": _inputs(), "state-z": _inputs()},
            "unexpected environment state ids: state-z",
        ),
        (
            {"state-z": _inputs()},
            "missing environment state ids: state-a, state-b; "
            "unexpected environment state ids: state-z",
        ),
    ],
)
def test_state_id_agreement_is_exact_and_precedes_physics(
    monkeypatch: pytest.MonkeyPatch,
    states: dict[str, StringModuleIVInputs],
    message: str,
) -> None:
    calls, _ = _count_physics(monkeypatch)
    topology = _topology(_string("string-a"), _string("string-b"))
    assignments = {"string-a": "state-b", "string-b": "state-a"}

    with pytest.raises(ValueError) as error:
        calculate_topology_module_iv_curves_from_environment_states(
            _tier_four_site(), topology, assignments, states
        )

    assert str(error.value) == (
        "module_iv_inputs_by_state_id does not match referenced environment states: "
        + message
    )
    assert calls == {
        "validate": 0,
        "resolve": 0,
        "fit": 0,
        "effective": 0,
        "calcparams": 0,
        "evaluate": 0,
    }


def test_empty_topology_rejects_unused_state_input() -> None:
    with pytest.raises(
        ValueError,
        match="unexpected environment state ids: state-unused",
    ):
        calculate_topology_module_iv_curves_from_environment_states(
            _site(),
            ElectricalTopologyConfig(inverters=[]),
            {},
            {"state-unused": _inputs()},
        )


def test_all_unique_states_are_prevalidated_in_first_use_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _count_physics(monkeypatch)
    topology = _topology(
        _string("string-a"), _string("string-b"), _string("string-c")
    )
    bad = _inputs()
    bad = StringModuleIVInputs(
        bad.poa_total,
        pd.Series([30.0], index=_index(13), dtype=float),
    )

    with pytest.raises(ValueError) as error:
        calculate_topology_module_iv_curves_from_environment_states(
            _tier_four_site(),
            topology,
            {"string-a": "state-z", "string-b": "state-a", "string-c": "state-z"},
            {"state-a": bad, "state-z": _inputs()},
            voltage_points=11,
        )

    assert str(error.value) == (
        "environment state 'state-a': poa_total and t_cell indexes must align exactly"
    )
    assert "string-b" not in str(error.value)
    assert calls == {
        "validate": 2,
        "resolve": 0,
        "fit": 0,
        "effective": 0,
        "calcparams": 0,
        "evaluate": 0,
    }


def test_five_strings_three_tier_four_states_evaluate_unique_states_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _count_physics(monkeypatch)
    topology = _topology(*(_string(f"s{number}") for number in range(1, 6)))
    assignments = {
        "s1": "state-a",
        "s2": "state-a",
        "s3": "state-b",
        "s4": "state-c",
        "s5": "state-c",
    }

    result = calculate_topology_module_iv_curves_from_environment_states(
        _tier_four_site(),
        topology,
        assignments,
        {
            "state-c": _inputs([500.0], [45.0]),
            "state-a": _inputs([1000.0], [20.0]),
            "state-b": _inputs([750.0], [32.0]),
        },
        voltage_points=11,
    )

    assert list(result) == ["s1", "s2", "s3", "s4", "s5"]
    assert calls == {
        "validate": 3,
        "resolve": 1,
        "fit": 1,
        "effective": 3,
        "calcparams": 3,
        "evaluate": 3,
    }


def test_identical_payloads_with_distinct_state_ids_are_evaluated_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_a = _inputs([850.0], [28.0], spectral=True)
    state_b = _inputs([850.0], [28.0], spectral=True)
    calls, _ = _count_physics(monkeypatch)

    result = calculate_topology_module_iv_curves_from_environment_states(
        _tier_four_site(),
        _topology(_string("string-a"), _string("string-b")),
        {"string-a": "state-a", "string-b": "state-b"},
        {"state-a": state_a, "state-b": state_b},
        voltage_points=11,
    )

    assert calls == {
        "validate": 2,
        "resolve": 1,
        "fit": 1,
        "effective": 2,
        "calcparams": 2,
        "evaluate": 2,
    }
    pd.testing.assert_frame_equal(result["string-a"], result["string-b"])
    assert result["string-a"] is not result["string-b"]


def test_tier_one_evaluates_once_per_unique_state_without_datasheet_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cec_name = pvlib.pvsystem.retrieve_sam("CECMod").columns[0]
    site = _site(ModuleConfig(cec_name=cec_name))
    calls, _ = _count_physics(monkeypatch)

    calculate_topology_module_iv_curves_from_environment_states(
        site,
        _topology(_string("s1"), _string("s2"), _string("s3")),
        {"s1": "state-a", "s2": "state-a", "s3": "state-b"},
        {
            "state-a": _inputs([900.0], [25.0]),
            "state-b": _inputs([600.0], [40.0]),
        },
        voltage_points=11,
    )

    assert calls == {
        "validate": 2,
        "resolve": 1,
        "fit": 0,
        "effective": 2,
        "calcparams": 2,
        "evaluate": 2,
    }


def test_unique_states_are_evaluated_in_first_use_topology_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[float] = []
    real = electrical._evaluate_module_iv_curves

    def evaluator(*args: object, **kwargs: object) -> pd.DataFrame:
        effective_irradiance = args[4]
        assert isinstance(effective_irradiance, pd.Series)
        order.append(float(effective_irradiance.iloc[0]))
        return real(*args, **kwargs)

    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", evaluator)
    topology = _topology(
        _string("string-a"),
        _string("string-b"),
        _string("string-c"),
        _string("string-d"),
    )

    calculate_topology_module_iv_curves_from_environment_states(
        _tier_four_site(),
        topology,
        {
            "string-d": "state-b",
            "string-c": "state-z",
            "string-b": "state-a",
            "string-a": "state-z",
        },
        {
            "state-a": _inputs([200.0], [30.0]),
            "state-b": _inputs([300.0], [30.0]),
            "state-z": _inputs([100.0], [30.0]),
        },
        voltage_points=11,
    )

    assert order == [100.0, 200.0, 300.0]


def test_shared_outputs_match_direct_results_and_do_not_alias() -> None:
    site = _tier_four_site()
    shared = _inputs([850.0, 950.0], [25.0, 35.0], index=_index(11, 12), spectral=True)
    other = _inputs([500.0], [45.0])
    topology = _topology(
        _string("string-a", 10, zone_id="unrelated-zone-a"),
        _string("string-b", 20, zone_id="unrelated-zone-b"),
        _string("string-c", 30),
    )
    source_copies = [
        series.copy(deep=True)
        for series in (
            shared.poa_total,
            shared.t_cell,
            shared.solar_zenith,
            shared.precipitable_water,
        )
        if series is not None
    ]

    result = calculate_topology_module_iv_curves_from_environment_states(
        site,
        topology,
        {"string-c": "other", "string-b": "shared", "string-a": "shared"},
        {"other": other, "shared": shared},
        voltage_points=11,
    )

    expected_shared = _direct(site, shared)
    pd.testing.assert_frame_equal(result["string-a"], expected_shared)
    pd.testing.assert_frame_equal(result["string-b"], expected_shared)
    pd.testing.assert_frame_equal(result["string-c"], _direct(site, other))
    assert result["string-a"] is not result["string-b"]
    untouched_b = result["string-b"].copy(deep=True)
    result["string-a"].loc[0, "power_w"] = -999.0
    result["string-a"].loc[0, "voltage_v"] = -888.0
    pd.testing.assert_frame_equal(result["string-b"], untouched_b)
    for before, after in zip(
        source_copies,
        (
            shared.poa_total,
            shared.t_cell,
            shared.solar_zenith,
            shared.precipitable_water,
        ),
        strict=True,
    ):
        assert after is not None
        pd.testing.assert_series_equal(after, before)


def test_result_matches_existing_explicit_per_string_api() -> None:
    site = _tier_four_site()
    state_a = _inputs([1000.0], [20.0])
    state_b = _inputs([450.0], [50.0])
    topology = _topology(
        _string("string-b"), _string("string-a"), _string("string-c")
    )
    assignments = {
        "string-a": "state-a",
        "string-b": "state-b",
        "string-c": "state-a",
    }

    shared = calculate_topology_module_iv_curves_from_environment_states(
        site,
        topology,
        assignments,
        {"state-a": state_a, "state-b": state_b},
        voltage_points=11,
    )
    explicit = calculate_topology_module_iv_curves(
        site,
        topology,
        {string_id: {"state-a": state_a, "state-b": state_b}[state_id]
         for string_id, state_id in assignments.items()},
        voltage_points=11,
    )

    assert list(shared) == ["string-b", "string-a", "string-c"]
    for string_id in shared:
        pd.testing.assert_frame_equal(shared[string_id], explicit[string_id])


def test_mapping_order_and_topology_order_do_not_change_string_numerics() -> None:
    site = _tier_four_site()
    state_a = _inputs([950.0], [22.0])
    state_b = _inputs([525.0], [47.0])
    topology_ab = _topology(_string("string-a"), _string("string-b"))
    topology_ba = _topology(_string("string-b"), _string("string-a"))

    result_ab = calculate_topology_module_iv_curves_from_environment_states(
        site,
        topology_ab,
        {"string-b": "state-b", "string-a": "state-a"},
        {"state-b": state_b, "state-a": state_a},
        voltage_points=11,
    )
    result_ba = calculate_topology_module_iv_curves_from_environment_states(
        site,
        topology_ba,
        {"string-a": "state-a", "string-b": "state-b"},
        {"state-a": state_a, "state-b": state_b},
        voltage_points=11,
    )

    assert list(result_ab) == ["string-a", "string-b"]
    assert list(result_ba) == ["string-b", "string-a"]
    for string_id in ("string-a", "string-b"):
        pd.testing.assert_frame_equal(result_ab[string_id], result_ba[string_id])


def test_repeated_invocations_are_identical() -> None:
    topology = _topology(_string("string-a"), _string("string-b"))
    args = (
        _tier_four_site(),
        topology,
        {"string-a": "shared", "string-b": "shared"},
        {"shared": _inputs([800.0], [31.0])},
    )

    first = calculate_topology_module_iv_curves_from_environment_states(
        *args, voltage_points=11
    )
    second = calculate_topology_module_iv_curves_from_environment_states(
        *args, voltage_points=11
    )

    for string_id in first:
        pd.testing.assert_frame_equal(first[string_id], second[string_id])


def test_different_state_timestamps_are_independent() -> None:
    state_a = _inputs([800.0, 900.0], [25.0, 30.0], index=_index(10, 11))
    state_b = _inputs([700.0], [35.0], index=_index(14))

    result = calculate_topology_module_iv_curves_from_environment_states(
        _tier_four_site(),
        _topology(_string("string-a"), _string("string-b")),
        {"string-a": "state-a", "string-b": "state-b"},
        {"state-a": state_a, "state-b": state_b},
        voltage_points=11,
    )

    assert result["string-a"]["timestamp"].nunique() == 2
    assert result["string-b"]["timestamp"].nunique() == 1


def test_valid_empty_shared_state_returns_distinct_canonical_empty_frames() -> None:
    empty = _inputs([], [], index=pd.DatetimeIndex([]))
    result = calculate_topology_module_iv_curves_from_environment_states(
        _tier_four_site(),
        _topology(_string("string-a"), _string("string-b")),
        {"string-a": "empty", "string-b": "empty"},
        {"empty": empty},
        voltage_points=11,
    )

    pd.testing.assert_frame_equal(result["string-a"], _direct(_tier_four_site(), empty))
    pd.testing.assert_frame_equal(result["string-b"], result["string-a"])
    assert result["string-a"] is not result["string-b"]


def test_shared_night_state_preserves_canonical_zero_curve_and_isolation() -> None:
    night = _inputs([0.0, -5.0], [20.0, 18.0], index=_index(1, 2))
    result = calculate_topology_module_iv_curves_from_environment_states(
        _tier_four_site(),
        _topology(_string("string-a"), _string("string-b")),
        {"string-a": "night", "string-b": "night"},
        {"night": night},
        voltage_points=11,
    )

    assert len(result["string-a"]) == 22
    assert (result["string-a"][["voltage_v", "current_a", "power_w"]] == 0).all().all()
    pd.testing.assert_frame_equal(result["string-a"], result["string-b"])
    assert result["string-a"] is not result["string-b"]


def test_shared_dynamic_failure_has_state_not_topology_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_: object, **__: object) -> pd.DataFrame:
        raise ValueError("dynamic solve failed")

    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", fail)
    topology = _topology(
        _string("string-first"), _string("string-second")
    )

    with pytest.raises(ValueError) as error:
        calculate_topology_module_iv_curves_from_environment_states(
            _tier_four_site(),
            topology,
            {"string-first": "state-shared", "string-second": "state-shared"},
            {"state-shared": _inputs()},
        )

    assert str(error.value) == "environment state 'state-shared': dynamic solve failed"
    for topology_id in ("string-first", "string-second", "inverter-A", "mppt-1"):
        assert topology_id not in str(error.value)


def test_tier_five_fails_at_module_level_before_state_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _count_physics(monkeypatch)

    with pytest.raises(ValueError, match="Tier 5 PVWatts fallback parameters") as error:
        calculate_topology_module_iv_curves_from_environment_states(
            _tier_five_site(),
            _topology(_string("string-a")),
            {"string-a": "state-a"},
            {"state-a": _inputs()},
        )

    assert "string-a" not in str(error.value)
    assert calls == {
        "validate": 1,
        "resolve": 1,
        "fit": 0,
        "effective": 0,
        "calcparams": 0,
        "evaluate": 0,
    }


def test_nonphysical_static_fit_fails_before_state_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, real = _count_physics(monkeypatch)

    def nonphysical(*args: object, **kwargs: object) -> dict[str, float]:
        calls["fit"] += 1
        result = real["fit"](*args, **kwargs)
        assert isinstance(result, dict)
        return {**result, "R_sh_ref": 0.0}

    monkeypatch.setattr(pvlib.ivtools.sdm, "fit_desoto_batzelis", nonphysical)

    with pytest.raises(ValueError, match="do not produce a physical single-diode fit") as error:
        calculate_topology_module_iv_curves_from_environment_states(
            _tier_four_site(),
            _topology(_string("string-a"), _string("string-b")),
            {"string-a": "state-a", "string-b": "state-b"},
            {"state-a": _inputs(), "state-b": _inputs([700.0], [40.0])},
        )

    assert "state-a" not in str(error.value)
    assert "string-a" not in str(error.value)
    assert calls == {
        "validate": 2,
        "resolve": 1,
        "fit": 1,
        "effective": 0,
        "calcparams": 0,
        "evaluate": 0,
    }


def test_full_shared_state_module_string_mppt_round_trip_matches_direct() -> None:
    site = _tier_four_site()
    state_a = _inputs([900.0, 950.0], [25.0, 30.0], index=_index(11, 12))
    state_b = _inputs([650.0, 700.0], [40.0, 42.0], index=_index(11, 12))
    topology = _topology(
        _string("string-a", 10),
        _string("string-b", 14),
        _string("string-c", 12),
    )

    modules = calculate_topology_module_iv_curves_from_environment_states(
        site,
        topology,
        {"string-a": "state-a", "string-b": "state-a", "string-c": "state-b"},
        {"state-a": state_a, "state-b": state_b},
        voltage_points=11,
    )
    routed = calculate_topology_mppt_mismatch(
        topology, calculate_topology_string_iv_curves(topology, modules)
    )
    direct = calculate_physical_mismatch(
        [
            scale_module_iv_to_string(_direct(site, state_a), 10),
            scale_module_iv_to_string(_direct(site, state_a), 14),
            scale_module_iv_to_string(_direct(site, state_b), 12),
        ]
    )

    pd.testing.assert_frame_equal(
        routed.drop(columns=["inverter_id", "mppt_id"]), direct
    )
