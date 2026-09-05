"""Tests for explicit per-string environmental state to module I-V curves."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

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
    calculate_topology_mppt_mismatch,
    calculate_topology_string_iv_curves,
    scale_module_iv_to_string,
)


def _site(module: ModuleConfig | None = None) -> SiteConfig:
    return SiteConfig(
        id="topology-module-iv-test",
        name="Topology Module I-V Test",
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
    index = index if index is not None else _index(12)
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


def _topology(
    *inverters: tuple[str, list[tuple[str, list[StringConfig]]]],
) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inverter_id,
                group_id=f"group-{inverter_id}",
                model_ref="generic-model",
                mppts=[
                    MPPTConfig(id=mppt_id, strings=strings)
                    for mppt_id, strings in mppts
                ],
            )
            for inverter_id, mppts in inverters
        ]
    )


def _direct(site: SiteConfig, inputs: StringModuleIVInputs, points: int = 11) -> pd.DataFrame:
    return calculate_module_iv_curves(
        site,
        inputs.poa_total,
        inputs.t_cell,
        solar_zenith=inputs.solar_zenith,
        precipitable_water=inputs.precipitable_water,
        voltage_points=points,
    )


def test_input_container_is_frozen() -> None:
    inputs = _inputs()

    with pytest.raises(FrozenInstanceError):
        inputs.poa_total = pd.Series(dtype=float)  # type: ignore[misc]


def test_empty_topology_returns_empty_without_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_calls = 0
    evaluator_calls = 0

    def resolver(_: object) -> dict:
        nonlocal resolver_calls
        resolver_calls += 1
        raise AssertionError("resolver must not run")

    def evaluator(*_: object) -> pd.DataFrame:
        nonlocal evaluator_calls
        evaluator_calls += 1
        raise AssertionError("evaluator must not run")

    monkeypatch.setattr(electrical, "resolve_module_params", resolver)
    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", evaluator)

    result = calculate_topology_module_iv_curves(
        _site(), ElectricalTopologyConfig(inverters=[]), {}, voltage_points=11
    )

    assert type(result) is dict
    assert result == {}
    assert resolver_calls == 0
    assert evaluator_calls == 0


def test_invalid_voltage_points_is_rejected_before_empty_topology_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_calls = 0

    def resolver(_: object) -> dict:
        nonlocal resolver_calls
        resolver_calls += 1
        raise AssertionError("resolver must not run")

    monkeypatch.setattr(electrical, "resolve_module_params", resolver)
    with pytest.raises(ValueError, match="voltage_points must be at least 3"):
        calculate_topology_module_iv_curves(
            _site(), ElectricalTopologyConfig(inverters=[]), {}, voltage_points=2
        )
    assert resolver_calls == 0


def test_empty_topology_rejects_unexpected_state_without_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_calls = 0

    def resolver(_: object) -> dict:
        nonlocal resolver_calls
        resolver_calls += 1
        raise AssertionError("resolver must not run")

    monkeypatch.setattr(electrical, "resolve_module_params", resolver)
    with pytest.raises(ValueError) as error:
        calculate_topology_module_iv_curves(
            _site(),
            ElectricalTopologyConfig(inverters=[]),
            {"string-x": _inputs()},
        )

    assert str(error.value) == (
        "module_iv_inputs_by_string_id does not match electrical topology: "
        "unexpected string ids: string-x"
    )
    assert resolver_calls == 0


def test_one_string_with_spectral_inputs_matches_direct_canonical_result() -> None:
    site = _site()
    inputs = _inputs([850.0, 1000.0], [35.0, 25.0], index=_index(14, 12), spectral=True)
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a", 12)])])
    )

    result = calculate_topology_module_iv_curves(
        site, topology, {"string-a": inputs}, voltage_points=11
    )

    assert list(result) == ["string-a"]
    pd.testing.assert_frame_equal(result["string-a"], _direct(site, inputs))


def test_different_environmental_states_match_their_direct_results() -> None:
    site = _site()
    high_cool = _inputs([1000.0], [20.0])
    low_hot = _inputs([500.0], [55.0])
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-a"), _string("string-b")])],
        )
    )

    result = calculate_topology_module_iv_curves(
        site,
        topology,
        {"string-a": high_cool, "string-b": low_hot},
        voltage_points=11,
    )

    pd.testing.assert_frame_equal(result["string-a"], _direct(site, high_cool))
    pd.testing.assert_frame_equal(result["string-b"], _direct(site, low_hot))
    assert result["string-a"]["power_w"].max() > result["string-b"]["power_w"].max()
    assert result["string-a"]["effective_irradiance_wm2"].iloc[0] == 1000.0
    assert result["string-b"]["effective_irradiance_wm2"].iloc[0] == 500.0


def test_module_counts_and_zone_ids_do_not_affect_module_curves() -> None:
    site = _site()
    inputs_a = _inputs()
    inputs_b = _inputs()
    topology = _topology(
        (
            "inverter-A",
            [
                (
                    "mppt-1",
                    [
                        _string("string-a", 10, zone_id="zone-one"),
                        _string("string-b", 20, zone_id="zone-two"),
                    ],
                )
            ],
        )
    )

    result = calculate_topology_module_iv_curves(
        site,
        topology,
        {"string-a": inputs_a, "string-b": inputs_b},
        voltage_points=11,
    )

    pd.testing.assert_frame_equal(result["string-a"], result["string-b"])


def test_topology_order_overrides_mapping_order_and_repeated_mppt_ids_are_safe() -> None:
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-b"), _string("string-a")])],
        ),
        ("inverter-B", [("mppt-1", [_string("string-c")])]),
    )
    states = {
        "string-a": _inputs([700.0], [30.0]),
        "string-b": _inputs([800.0], [30.0]),
        "string-c": _inputs([900.0], [30.0]),
    }

    result = calculate_topology_module_iv_curves(
        _site(), topology, states, voltage_points=7
    )

    assert list(result) == ["string-b", "string-a", "string-c"]


@pytest.mark.parametrize(
    ("topology", "states", "message"),
    [
        (
            _topology(
                (
                    "inverter-A",
                    [("mppt-1", [_string("string-a"), _string("string-b")])],
                )
            ),
            {"string-a": _inputs()},
            "missing string ids: string-b",
        ),
        (
            _topology(("inverter-A", [("mppt-1", [_string("string-a")])])),
            {"string-a": _inputs(), "string-extra": _inputs()},
            "unexpected string ids: string-extra",
        ),
    ],
)
def test_single_category_id_mismatch_is_rejected(
    topology: ElectricalTopologyConfig,
    states: dict[str, StringModuleIVInputs],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_topology_module_iv_curves(_site(), topology, states)


def test_multiple_id_mismatches_are_sorted_with_missing_first() -> None:
    topology = _topology(
        (
            "inverter-A",
            [
                (
                    "mppt-1",
                    [
                        _string("string-z"),
                        _string("string-a"),
                        _string("string-b"),
                    ],
                )
            ],
        )
    )

    with pytest.raises(ValueError) as error:
        calculate_topology_module_iv_curves(
            _site(),
            topology,
            {"string-y": _inputs(), "string-a": _inputs(), "string-c": _inputs()},
        )

    assert str(error.value) == (
        "module_iv_inputs_by_string_id does not match electrical topology: "
        "missing string ids: string-b, string-z; "
        "unexpected string ids: string-c, string-y"
    )


def test_invalid_id_contract_runs_no_resolver_or_evaluator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-a"), _string("string-b")])],
        )
    )
    calls = {"resolver": 0, "fit": 0, "dynamic": 0, "evaluator": 0}

    def resolver(_: object) -> dict:
        calls["resolver"] += 1
        raise AssertionError("resolver must not run")

    def evaluator(*_: object) -> pd.DataFrame:
        calls["evaluator"] += 1
        raise AssertionError("evaluator must not run")

    def fit(**_: object) -> dict:
        calls["fit"] += 1
        raise AssertionError("fit must not run")

    def dynamic(**_: object) -> tuple:
        calls["dynamic"] += 1
        raise AssertionError("dynamic calculation must not run")

    monkeypatch.setattr(electrical, "resolve_module_params", resolver)
    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", evaluator)
    monkeypatch.setattr(pvlib.ivtools.sdm, "fit_desoto_batzelis", fit)
    monkeypatch.setattr(pvlib.pvsystem, "calcparams_desoto", dynamic)
    with pytest.raises(ValueError):
        calculate_topology_module_iv_curves(
            _site(),
            topology,
            {"string-a": _inputs(), "string-extra": _inputs()},
        )

    assert calls == {"resolver": 0, "fit": 0, "dynamic": 0, "evaluator": 0}


def test_invalid_later_state_is_contextual_and_prevents_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        (
            "inverter-A",
            [("mppt-7", [_string("string-a"), _string("string-b")])],
        )
    )
    valid = _inputs()
    invalid = StringModuleIVInputs(
        poa_total=pd.Series([800.0], index=_index(12), dtype=float),
        t_cell=pd.Series([25.0], index=_index(13), dtype=float),
    )
    calls = {"resolver": 0, "fit": 0, "dynamic": 0}

    def resolver(_: object) -> dict:
        calls["resolver"] += 1
        raise AssertionError("resolver must not run")

    def fit(**_: object) -> dict:
        calls["fit"] += 1
        raise AssertionError("fit must not run")

    def dynamic(**_: object) -> tuple:
        calls["dynamic"] += 1
        raise AssertionError("dynamic calculation must not run")

    monkeypatch.setattr(electrical, "resolve_module_params", resolver)
    monkeypatch.setattr(pvlib.ivtools.sdm, "fit_desoto_batzelis", fit)
    monkeypatch.setattr(pvlib.pvsystem, "calcparams_desoto", dynamic)
    with pytest.raises(
        ValueError,
        match=(
            "inverter 'inverter-A' MPPT 'mppt-7' string 'string-b'.*"
            "poa_total and t_cell indexes must align exactly"
        ),
    ) as error:
        calculate_topology_module_iv_curves(
            _site(), topology, {"string-a": valid, "string-b": invalid}
        )

    assert calls == {"resolver": 0, "fit": 0, "dynamic": 0}
    assert isinstance(error.value.__cause__, ValueError)


def test_three_strings_resolve_once_and_evaluate_once_each_in_topology_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        (
            "inverter-A",
            [
                ("empty", []),
                ("mppt-1", [_string("string-b"), _string("string-a")]),
            ],
        ),
        ("inverter-B", [("mppt-1", [_string("string-c")])]),
    )
    states = {
        "string-a": _inputs([700.0], [30.0]),
        "string-b": _inputs([800.0], [31.0]),
        "string-c": _inputs([900.0], [32.0]),
    }
    real_resolver = electrical.resolve_module_params
    real_evaluator = electrical._evaluate_module_iv_curves
    resolver_calls = 0
    evaluated_poa: list[pd.Series] = []

    def resolve(module: ModuleConfig) -> dict:
        nonlocal resolver_calls
        resolver_calls += 1
        return real_resolver(module)

    def evaluate(*args: object, **kwargs: object) -> pd.DataFrame:
        evaluated_poa.append(args[1])  # type: ignore[arg-type]
        return real_evaluator(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(electrical, "resolve_module_params", resolve)
    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", evaluate)
    result = calculate_topology_module_iv_curves(
        _site(), topology, states, voltage_points=7
    )

    assert resolver_calls == 1
    assert evaluated_poa == [
        states["string-b"].poa_total,
        states["string-a"].poa_total,
        states["string-c"].poa_total,
    ]
    assert list(result) == ["string-b", "string-a", "string-c"]


def test_tier_four_batch_fits_once_and_calculates_each_dynamic_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        (
            "inverter-A",
            [
                (
                    "mppt-1",
                    [_string("string-a"), _string("string-b"), _string("string-c")],
                )
            ],
        )
    )
    states = {
        "string-a": _inputs([700.0], [25.0]),
        "string-b": _inputs([800.0], [30.0]),
        "string-c": _inputs([900.0], [35.0]),
    }
    real_resolver = electrical.resolve_module_params
    real_fit = pvlib.ivtools.sdm.fit_desoto_batzelis
    real_dynamic = pvlib.pvsystem.calcparams_desoto
    real_evaluator = electrical._evaluate_module_iv_curves
    calls = {"resolver": 0, "fit": 0, "dynamic": 0, "evaluator": 0}

    def resolve(module: ModuleConfig) -> dict:
        calls["resolver"] += 1
        return real_resolver(module)

    def fit(**kwargs: float) -> dict:
        calls["fit"] += 1
        return real_fit(**kwargs)

    def dynamic(**kwargs: object) -> tuple:
        calls["dynamic"] += 1
        return real_dynamic(**kwargs)

    def evaluate(*args: object, **kwargs: object) -> pd.DataFrame:
        calls["evaluator"] += 1
        return real_evaluator(*args, **kwargs)

    monkeypatch.setattr(electrical, "resolve_module_params", resolve)
    monkeypatch.setattr(pvlib.ivtools.sdm, "fit_desoto_batzelis", fit)
    monkeypatch.setattr(pvlib.pvsystem, "calcparams_desoto", dynamic)
    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", evaluate)

    calculate_topology_module_iv_curves(
        _tier_four_site(), topology, states, voltage_points=7
    )

    assert calls == {"resolver": 1, "fit": 1, "dynamic": 3, "evaluator": 3}


def test_nonphysical_shared_fit_has_module_ownership_and_stops_dynamic_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-first")])]),
        ("inverter-B", [("mppt-2", [_string("string-second")])]),
    )
    states = {"string-first": _inputs(), "string-second": _inputs()}
    real_resolver = electrical.resolve_module_params
    calls = {"resolver": 0, "fit": 0, "dynamic": 0, "evaluator": 0}

    def resolve(module: ModuleConfig) -> dict:
        calls["resolver"] += 1
        return real_resolver(module)

    def fit(**_: float) -> dict:
        calls["fit"] += 1
        return {"R_sh_ref": 0.0}

    def dynamic(**_: object) -> tuple:
        calls["dynamic"] += 1
        raise AssertionError("dynamic calculation must not run")

    def evaluator(*_: object, **__: object) -> pd.DataFrame:
        calls["evaluator"] += 1
        raise AssertionError("evaluator must not run")

    monkeypatch.setattr(electrical, "resolve_module_params", resolve)
    monkeypatch.setattr(pvlib.ivtools.sdm, "fit_desoto_batzelis", fit)
    monkeypatch.setattr(pvlib.pvsystem, "calcparams_desoto", dynamic)
    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", evaluator)

    with pytest.raises(ValueError) as error:
        calculate_topology_module_iv_curves(
            _tier_four_site(), topology, states, voltage_points=7
        )

    assert str(error.value) == (
        "Voltage-dependent module I-V is unavailable because the site/module "
        "datasheet parameters do not produce a physical single-diode fit; the "
        "scalar model can only use its PVWatts fallback"
    )
    for topology_id in (
        "string-first",
        "string-second",
        "inverter-A",
        "inverter-B",
        "mppt-1",
        "mppt-2",
    ):
        assert topology_id not in str(error.value)
    assert calls == {"resolver": 1, "fit": 1, "dynamic": 0, "evaluator": 0}


def test_nonphysical_shared_fit_error_is_topology_order_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = {"string-a": _inputs(), "string-b": _inputs()}
    topology_ab = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a"), _string("string-b")])])
    )
    topology_ba = _topology(
        ("inverter-A", [("mppt-1", [_string("string-b"), _string("string-a")])])
    )

    monkeypatch.setattr(
        pvlib.ivtools.sdm,
        "fit_desoto_batzelis",
        lambda **_: {"R_sh_ref": 0.0},
    )

    messages: list[str] = []
    for topology in (topology_ab, topology_ba):
        with pytest.raises(ValueError) as error:
            calculate_topology_module_iv_curves(
                _tier_four_site(), topology, states, voltage_points=7
            )
        messages.append(str(error.value))

    assert messages[0] == messages[1]


def test_public_tier_four_module_iv_fits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_fit = pvlib.ivtools.sdm.fit_desoto_batzelis
    fit_calls = 0

    def fit(**kwargs: float) -> dict:
        nonlocal fit_calls
        fit_calls += 1
        return real_fit(**kwargs)

    monkeypatch.setattr(pvlib.ivtools.sdm, "fit_desoto_batzelis", fit)
    result = calculate_module_iv_curves(
        _tier_four_site(),
        pd.Series([800.0], index=_index(12)),
        pd.Series([30.0], index=_index(12)),
        voltage_points=7,
    )

    assert fit_calls == 1
    assert len(result) == 7


def test_shared_datasheet_reference_is_topology_order_independent() -> None:
    site = _tier_four_site()
    states = {
        "string-a": _inputs([700.0], [25.0]),
        "string-b": _inputs([950.0], [42.0]),
    }
    topology_ab = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a"), _string("string-b")])])
    )
    topology_ba = _topology(
        ("inverter-A", [("mppt-1", [_string("string-b"), _string("string-a")])])
    )

    result_ab = calculate_topology_module_iv_curves(
        site, topology_ab, states, voltage_points=7
    )
    result_ba = calculate_topology_module_iv_curves(
        site, topology_ba, states, voltage_points=7
    )

    assert list(result_ab) == ["string-a", "string-b"]
    assert list(result_ba) == ["string-b", "string-a"]
    pd.testing.assert_frame_equal(result_ab["string-a"], result_ba["string-a"])
    pd.testing.assert_frame_equal(result_ab["string-b"], result_ba["string-b"])


def test_repeated_tier_four_batch_invocations_are_identical() -> None:
    site = _tier_four_site()
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a"), _string("string-b")])])
    )
    states = {
        "string-a": _inputs([700.0], [25.0]),
        "string-b": _inputs([950.0], [42.0]),
    }

    first = calculate_topology_module_iv_curves(
        site, topology, states, voltage_points=7
    )
    second = calculate_topology_module_iv_curves(
        site, topology, states, voltage_points=7
    )

    pd.testing.assert_frame_equal(first["string-a"], second["string-a"])
    pd.testing.assert_frame_equal(first["string-b"], second["string-b"])


def test_tier_five_rejection_is_module_level_and_precedes_string_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tier_five_site = _site(ModuleConfig(pnom_wp=500.0, gamma_pmp=-0.3))
    topology = _topology(
        ("inverter-A", [("mppt-2", [_string("string-a")])])
    )

    calls = {"fit": 0, "dynamic": 0, "evaluator": 0}

    def fit(**_: object) -> dict:
        calls["fit"] += 1
        raise AssertionError("fit must not run")

    def dynamic(**_: object) -> tuple:
        calls["dynamic"] += 1
        raise AssertionError("dynamic calculation must not run")

    def evaluator(*_: object, **__: object) -> pd.DataFrame:
        calls["evaluator"] += 1
        raise AssertionError("evaluator must not run")

    monkeypatch.setattr(pvlib.ivtools.sdm, "fit_desoto_batzelis", fit)
    monkeypatch.setattr(pvlib.pvsystem, "calcparams_desoto", dynamic)
    monkeypatch.setattr(electrical, "_evaluate_module_iv_curves", evaluator)

    with pytest.raises(ValueError) as error:
        calculate_topology_module_iv_curves(
            tier_five_site, topology, {"string-a": _inputs()}, voltage_points=7
        )

    assert str(error.value) == (
        "Voltage-dependent module I-V is unavailable for Tier 5 PVWatts "
        "fallback parameters"
    )
    assert "string-a" not in str(error.value)
    assert calls == {"fit": 0, "dynamic": 0, "evaluator": 0}


def test_night_representation_matches_canonical_module_curve() -> None:
    site = _site()
    inputs = _inputs([0.0, -20.0], [15.0, 10.0], index=_index(1, 2))
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a")])])
    )

    result = calculate_topology_module_iv_curves(
        site, topology, {"string-a": inputs}, voltage_points=7
    )["string-a"]

    pd.testing.assert_frame_equal(result, _direct(site, inputs, points=7))
    assert len(result) == 14
    assert result[["voltage_v", "current_a", "power_w"]].eq(0.0).all().all()


def test_valid_empty_state_returns_canonical_empty_curve() -> None:
    site = _site()
    empty_index = pd.DatetimeIndex([], tz="Europe/London")
    inputs = _inputs([], [], index=empty_index, spectral=True)
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a")])])
    )

    result = calculate_topology_module_iv_curves(
        site, topology, {"string-a": inputs}, voltage_points=7
    )

    assert list(result) == ["string-a"]
    pd.testing.assert_frame_equal(result["string-a"], _direct(site, inputs, points=7))
    assert result["string-a"].empty


def test_different_timestamp_sets_are_processed_independently() -> None:
    site = _site()
    inputs_a = _inputs([700.0, 800.0], [25.0, 26.0], index=_index(10, 11))
    inputs_b = _inputs([900.0, 600.0], [30.0, 35.0], index=_index(14, 13))
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-a"), _string("string-b")])],
        )
    )

    result = calculate_topology_module_iv_curves(
        site,
        topology,
        {"string-a": inputs_a, "string-b": inputs_b},
        voltage_points=7,
    )

    assert result["string-a"]["timestamp"].drop_duplicates().tolist() == list(_index(10, 11))
    assert result["string-b"]["timestamp"].drop_duplicates().tolist() == list(_index(14, 13))


def test_inputs_are_not_mutated_and_outputs_do_not_alias_series() -> None:
    site = _site()
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a", 12, zone_id="zone-x")])])
    )
    inputs = _inputs([800.0, 900.0], [25.0, 30.0], index=_index(11, 12), spectral=True)
    mapping = {"string-a": inputs}
    site_before = site.model_dump(mode="python")
    topology_before = topology.model_dump(mode="python")
    mapping_before = list(mapping.items())
    series_before = {
        name: series.copy(deep=True)
        for name, series in (
            ("poa", inputs.poa_total),
            ("temperature", inputs.t_cell),
            ("zenith", inputs.solar_zenith),
            ("water", inputs.precipitable_water),
        )
        if series is not None
    }

    result = calculate_topology_module_iv_curves(
        site, topology, mapping, voltage_points=7
    )

    assert site.model_dump(mode="python") == site_before
    assert topology.model_dump(mode="python") == topology_before
    assert list(mapping.items()) == mapping_before
    pd.testing.assert_series_equal(inputs.poa_total, series_before["poa"])
    pd.testing.assert_series_equal(inputs.t_cell, series_before["temperature"])
    pd.testing.assert_series_equal(inputs.solar_zenith, series_before["zenith"])
    pd.testing.assert_series_equal(inputs.precipitable_water, series_before["water"])
    result["string-a"].loc[0, "effective_irradiance_wm2"] = -999.0
    pd.testing.assert_series_equal(inputs.poa_total, series_before["poa"])
    pd.testing.assert_series_equal(inputs.t_cell, series_before["temperature"])
    pd.testing.assert_series_equal(inputs.solar_zenith, series_before["zenith"])
    pd.testing.assert_series_equal(inputs.precipitable_water, series_before["water"])


def test_complete_physical_round_trip_matches_direct_canonical_chain() -> None:
    site = _site()
    index = _index(12)
    inputs_a = _inputs([1000.0], [20.0], index=index)
    inputs_b = _inputs([650.0], [45.0], index=index)
    topology = _topology(
        (
            "inverter-A",
            [
                (
                    "mppt-1",
                    [_string("string-a", 10), _string("string-b", 14)],
                )
            ],
        )
    )

    module_curves = calculate_topology_module_iv_curves(
        site,
        topology,
        {"string-a": inputs_a, "string-b": inputs_b},
        voltage_points=21,
    )
    string_curves = calculate_topology_string_iv_curves(topology, module_curves)
    routed = calculate_topology_mppt_mismatch(topology, string_curves)
    direct = calculate_physical_mismatch(
        [
            scale_module_iv_to_string(_direct(site, inputs_a, points=21), 10),
            scale_module_iv_to_string(_direct(site, inputs_b, points=21), 14),
        ]
    )

    pd.testing.assert_frame_equal(
        routed.drop(columns=["inverter_id", "mppt_id"]), direct
    )
