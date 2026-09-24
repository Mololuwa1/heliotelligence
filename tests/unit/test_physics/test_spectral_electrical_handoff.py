"""Tests for the canonical S7E spectral-to-electrical handoff."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

import heliotelligence.physics.electrical as electrical
from heliotelligence.config.site import InverterConfig, ModuleConfig, SiteConfig
from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.electrical import (
    _SPECTRAL_HANDOFF_OUTPUT_COLUMNS,
    SPECTRAL_ELECTRICAL_HANDOFF_CONTRACT_ID,
    SPECTRAL_ELECTRICAL_HANDOFF_MODEL_ID,
    SPECTRAL_ELECTRICAL_HANDOFF_SCOPE,
    ReceiverModuleElectricalResult,
    calculate_module_operating_point,
    calculate_receiver_module_operating_points_from_spectral_response,
)
from heliotelligence.physics.spectral_response import (
    FirstSolarAtmosphere,
    FrontSpectralCorrectionAdmission,
    RearSpectralCorrectionAdmission,
    SpectralResponseResult,
    calculate_spectral_electrical_equivalent_irradiance,
)

spectral_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_spectral_response"
)


def _receivers(count: int = 1) -> list[PVReceiver]:
    return cast(list[PVReceiver], spectral_support._receivers(count))


def _site(*, technology: str = "mono_si", tier5: bool = True) -> SiteConfig:
    module = (
        ModuleConfig(technology=technology, pnom_wp=1000.0, gamma_pmp=0.0)
        if tier5
        else ModuleConfig(local_module_name="JKM570N-72HL4-BDV", technology=technology)
    )
    return SiteConfig(
        id="s7e-handoff",
        name="S7E Handoff",
        latitude=52.56,
        longitude=1.21,
        timezone="Europe/London",
        capacity_kwp=1.0,
        solcast_resource_id="test",
        module=module,
        inverter=InverterConfig(),
    )


def _atmosphere(index: pd.DatetimeIndex) -> FirstSolarAtmosphere:
    return cast(FirstSolarAtmosphere, spectral_support._atmosphere(index))


def _spectral(
    receivers: list[PVReceiver],
    *,
    periods: int = 1,
    front: float = 800.0,
    rear: float = 200.0,
    bifacial: bool = True,
    front_factor: float = 0.95,
    rear_factor: float = 1.05,
) -> SpectralResponseResult:
    upstream = spectral_support._s7d(receivers, bifacial=bifacial, periods=periods)
    if bifacial:
        upstream = spectral_support._set_optical_values(
            upstream, front=front, rear=rear, phi=0.8
        )
    else:
        upstream_frame = upstream.irradiance.copy(deep=True)
        upstream_frame.loc[:, "poa_front_effective_optical_wm2"] = front
        upstream_frame.loc[:, "bifacial_electrical_equivalent_irradiance_wm2"] = front
        upstream = replace(upstream, irradiance=upstream_frame)
    upstream_frame = upstream.irradiance.copy(deep=True)
    upstream_frame.index = upstream_frame.index.set_names(["timestamp", "receiver_id"])
    upstream = replace(upstream, irradiance=upstream_frame)
    index = pd.DatetimeIndex(upstream.irradiance.index.get_level_values("timestamp").unique())
    front_admission = {
        receiver.id: FrontSpectralCorrectionAdmission(
            activation_state="enabled",
            activation_source_label="project",
            coefficient_mode="explicit_coefficients",
            coefficients=(front_factor, 0.0, 0.0, 0.0, 0.0, 0.0),
            coefficient_source_label="test constant response",
        )
        for receiver in receivers
    }
    bifacial_ids = [receiver.id for receiver in receivers] if bifacial else []
    rear_admission = {
        receiver_id: RearSpectralCorrectionAdmission(
            treatment="explicit_factor",
            source_label="rear model",
            model_id="rear-explicit-v1",
        )
        for receiver_id in bifacial_ids
    }
    factors = (
        pd.Series(
            rear_factor,
            index=pd.MultiIndex.from_product(
                (index, sorted(bifacial_ids)), names=["timestamp", "receiver_id"]
            ),
        )
        if bifacial_ids
        else None
    )
    return calculate_spectral_electrical_equivalent_irradiance(
        receivers,
        upstream,
        front_spectral_admission_by_receiver=front_admission,
        rear_spectral_admission_by_receiver=rear_admission,
        atmosphere=_atmosphere(index),
        explicit_rear_spectral_factor=factors,
    )


def _temperature(result: SpectralResponseResult, value: float = 25.0) -> pd.Series:
    return pd.Series(value, index=result.irradiance.index, name="cell_temperature_c")


def _calculate(
    receivers: list[PVReceiver],
    result: SpectralResponseResult,
    *,
    site: SiteConfig | None = None,
    temperature: pd.Series | None = None,
) -> ReceiverModuleElectricalResult:
    return calculate_receiver_module_operating_points_from_spectral_response(
        site or _site(),
        receivers,
        result,
        cell_temperature_c=temperature if temperature is not None else _temperature(result),
    )


def _mutate(
    result: SpectralResponseResult, column: str, value: object, *, row: int = 0
) -> SpectralResponseResult:
    frame = result.irradiance.copy(deep=True)
    frame.iloc[row, frame.columns.get_loc(column)] = value
    return replace(result, irradiance=frame)


def test_critical_928_not_960_tier5_handoff() -> None:
    receivers = _receivers()
    spectral = _spectral(receivers)
    source = spectral.irradiance.iloc[0]
    assert source["front_spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(760.0)
    assert source["rear_spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(168.0)
    assert source["spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(928.0)
    assert source["bifacial_electrical_equivalent_irradiance_wm2"] == pytest.approx(960.0)

    result = _calculate(receivers, spectral)
    row = result.operating_points.iloc[0]
    assert row["spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(928.0)
    assert row["p_mp_w"] == pytest.approx(928.0)
    assert pd.isna(row["v_mp_v"])
    assert pd.isna(row["i_mp_a"])
    assert row["module_electrical_state"] == "resolved_pvwatts_power_only"
    assert result.diagnostics.solver_row_count == 1


def test_canonical_path_never_calls_legacy_spectral_helper_for_hjt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receivers = _receivers()
    spectral = _spectral(receivers)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("legacy spectral helper called")

    monkeypatch.setattr(electrical, "_compute_spectral_factor", forbidden)
    result = _calculate(receivers, spectral, site=_site(technology="hjt"))
    assert result.operating_points["p_mp_w"].iloc[0] == pytest.approx(928.0)


def test_zero_missing_temperature_and_unresolved_states_skip_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receivers = _receivers()
    zero = _spectral(receivers, front=0.0, rear=0.0)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("solver called")

    monkeypatch.setattr(
        electrical, "_calculate_module_operating_point_from_electrical_irradiance", forbidden
    )
    missing = pd.Series(np.nan, index=zero.irradiance.index)
    row = _calculate(receivers, zero, temperature=missing).operating_points.iloc[0]
    assert (row[["p_mp_w", "v_mp_v", "i_mp_a"]] == 0.0).all()
    assert row["module_electrical_state"] == "resolved_zero_spectral_electrical_irradiance"


def test_positive_missing_temperature_and_real_unresolved_spectral_rows() -> None:
    receivers = _receivers()
    positive = _spectral(receivers)
    missing = pd.Series(np.nan, index=positive.irradiance.index)
    row = _calculate(receivers, positive, temperature=missing).operating_points.iloc[0]
    assert row["module_electrical_state"] == "unresolved_cell_temperature"
    assert row[["p_mp_w", "v_mp_v", "i_mp_a"]].isna().all()

    upstream = spectral_support._s7d(receivers, bifacial=False, periods=1)
    upstream_frame = upstream.irradiance.copy(deep=True)
    upstream_frame.index = upstream_frame.index.set_names(["timestamp", "receiver_id"])
    upstream = replace(upstream, irradiance=upstream_frame)
    unknown = calculate_spectral_electrical_equivalent_irradiance(
        receivers,
        upstream,
        front_spectral_admission_by_receiver={
            "r0": FrontSpectralCorrectionAdmission(
                activation_state="unknown", activation_source_label="unknown"
            )
        },
        rear_spectral_admission_by_receiver={},
        atmosphere=None,
        explicit_rear_spectral_factor=None,
    )
    unresolved = _calculate(receivers, unknown).operating_points.iloc[0]
    assert unresolved["module_electrical_state"] == (
        "unresolved_spectral_electrical_equivalent_irradiance"
    )
    both = _calculate(
        receivers, unknown, temperature=pd.Series(np.nan, index=unknown.irradiance.index)
    ).operating_points.iloc[0]
    assert both["module_electrical_state"] == "unresolved_spectral_and_cell_temperature"


def test_mixed_rows_only_positive_resolved_row_enters_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receivers = _receivers()
    spectral = _spectral(receivers, periods=3)
    frame = spectral.irradiance.copy(deep=True)
    second = frame.index[1]
    frame.loc[second, "poa_front_effective_optical_wm2"] = 0.0
    frame.loc[second, "front_spectral_electrical_equivalent_irradiance_wm2"] = 0.0
    frame.loc[second, "front_spectral_electrical_equivalent_state"] = (
        "resolved_zero_front_effective_irradiance"
    )
    frame.loc[second, "poa_rear_effective_optical_wm2"] = 0.0
    frame.loc[second, "poa_rear_spectral_effective_irradiance_wm2"] = 0.0
    frame.loc[second, "rear_spectral_effective_state"] = (
        "resolved_zero_rear_effective_irradiance"
    )
    frame.loc[second, "rear_spectral_electrical_equivalent_irradiance_wm2"] = 0.0
    frame.loc[second, "rear_spectral_electrical_equivalent_state"] = (
        "resolved_zero_rear_effective_irradiance"
    )
    frame.loc[second, "spectral_electrical_equivalent_irradiance_wm2"] = 0.0
    third = frame.index[2]
    frame.loc[third, "front_spectral_mismatch_factor"] = np.nan
    frame.loc[third, "front_spectral_factor_resolved"] = False
    frame.loc[third, "front_spectral_factor_state"] = "unresolved_spectral_activation_unknown"
    frame.loc[third, "front_spectral_electrical_equivalent_irradiance_wm2"] = np.nan
    frame.loc[third, "front_spectral_electrical_equivalent_resolved"] = False
    frame.loc[third, "front_spectral_electrical_equivalent_state"] = (
        "unresolved_front_spectral_factor"
    )
    frame.loc[third, "spectral_electrical_equivalent_irradiance_wm2"] = np.nan
    frame.loc[third, "spectral_electrical_equivalent_resolved"] = False
    frame.loc[third, "spectral_electrical_equivalent_state"] = (
        "unresolved_front_spectral_response"
    )
    diagnostics = replace(
        spectral.diagnostics,
        front_factor_resolved_row_count=2,
        front_factor_unresolved_row_count=1,
        spectral_total_resolved_row_count=2,
        spectral_total_unresolved_row_count=1,
    )
    mixed = replace(spectral, irradiance=frame, diagnostics=diagnostics)
    original = electrical._calculate_module_operating_point_from_electrical_irradiance
    seen: list[list[float]] = []

    def recording(
        site: SiteConfig,
        irradiance: pd.Series,
        temperature: pd.Series,
        *,
        resolution: dict[Any, Any] | None = None,
    ) -> tuple[pd.DataFrame, dict[Any, Any]]:
        seen.append(irradiance.tolist())
        return cast(
            tuple[pd.DataFrame, dict[Any, Any]],
            original(site, irradiance, temperature, resolution=resolution),
        )

    monkeypatch.setattr(
        electrical, "_calculate_module_operating_point_from_electrical_irradiance", recording
    )
    result = _calculate(receivers, mixed)
    assert seen == [[928.0]]
    assert result.diagnostics.solver_row_count == 1
    assert result.diagnostics.zero_irradiance_row_count == 1
    assert result.diagnostics.unresolved_row_count == 1


def test_disabled_spectral_tier3_parity_with_legacy_unity_path() -> None:
    receivers = _receivers()
    spectral = _spectral(
        receivers, bifacial=False, front=850.0, rear=0.0, front_factor=1.0
    )
    site = _site(tier5=False)
    canonical = _calculate(receivers, spectral, site=site).operating_points.iloc[0]
    timestamp = spectral.irradiance.index.get_level_values("timestamp").unique()
    legacy = calculate_module_operating_point(
        site, pd.Series(850.0, index=timestamp), pd.Series(25.0, index=timestamp)
    ).iloc[0]
    assert canonical["p_mp_w"] == pytest.approx(legacy["p_mp_w"])
    assert canonical["v_mp_v"] == pytest.approx(legacy["v_mp_v"])
    assert canonical["i_mp_a"] == pytest.approx(legacy["i_mp_a"])


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("spectral_response_contract", "wrong"),
        ("spectral_response_model", "wrong"),
        ("spectral_response_coverage_scope", "wrong"),
        ("spectral_response_scope", "wrong"),
        ("firstsolar_model", "wrong"),
        ("pvlib_version", ""),
        ("front_spectral_mismatch_factor", np.nan),
        ("front_spectral_electrical_equivalent_irradiance_wm2", 999.0),
        ("rear_spectral_electrical_equivalent_irradiance_wm2", 999.0),
        ("spectral_electrical_equivalent_irradiance_wm2", 960.0),
        ("spectral_electrical_equivalent_state", "wrong"),
    ],
)
def test_contract_and_algebra_tampering_rejected(column: str, value: object) -> None:
    receivers = _receivers()
    with pytest.raises(ValueError):
        _calculate(receivers, _mutate(_spectral(receivers), column, value))


def test_type_receiver_grid_and_diagnostic_tampering_rejected() -> None:
    receivers = _receivers()
    spectral = _spectral(receivers)
    with pytest.raises(ValueError):
        calculate_receiver_module_operating_points_from_spectral_response(
            _site(), receivers, spectral.irradiance, cell_temperature_c=_temperature(spectral)
        )
    with pytest.raises(ValueError):
        _calculate([receivers[0], receivers[0]], spectral)
    with pytest.raises(ValueError):
        _calculate([replace(receivers[0], receiver_kind=ReceiverKind.TRACKER_TABLE)], spectral)
    with pytest.raises(ValueError):
        _calculate(
            receivers,
            replace(spectral, diagnostics=replace(spectral.diagnostics, row_count=9)),
        )
    with pytest.raises(ValueError):
        _calculate(receivers, replace(spectral, irradiance=spectral.irradiance.iloc[0:0]))


@pytest.mark.parametrize("bad_value", [np.inf, -np.inf, True, "25"])
def test_temperature_values_reject_nonfinite_boolean_and_string(bad_value: object) -> None:
    receivers = _receivers()
    spectral = _spectral(receivers)
    temperature = _temperature(spectral).astype(object)
    temperature.iloc[0] = bad_value
    with pytest.raises(ValueError):
        _calculate(receivers, spectral, temperature=temperature)


def test_temperature_grid_rejects_naive_wrong_names_duplicates_and_shift() -> None:
    receivers = _receivers()
    spectral = _spectral(receivers)
    temperature = _temperature(spectral)
    variants = []
    naive = temperature.copy()
    naive.index = naive.index.set_levels(naive.index.levels[0].tz_localize(None), level=0)
    variants.append(naive)
    wrong_names = temperature.copy()
    wrong_names.index = wrong_names.index.set_names(["time", "receiver_id"])
    variants.append(wrong_names)
    variants.append(pd.concat([temperature, temperature.iloc[[0]]]))
    shifted = temperature.copy()
    shifted.index = shifted.index.set_levels(
        shifted.index.levels[0] + pd.Timedelta(hours=1), level=0
    )
    variants.append(shifted)
    for variant in variants:
        with pytest.raises(ValueError):
            _calculate(receivers, spectral, temperature=variant)


def test_empty_exact_schema_determinism_and_single_module_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receivers = _receivers(2)
    spectral = _spectral(receivers, periods=0)
    temperature = pd.Series(dtype=float, index=spectral.irradiance.index)
    original = electrical._resolve_module_configuration
    calls = 0

    def recording(site: SiteConfig) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return cast(dict[str, object], original(site))

    monkeypatch.setattr(electrical, "_resolve_module_configuration", recording)
    first = _calculate(receivers, spectral, temperature=temperature)
    second = _calculate(list(reversed(receivers)), spectral, temperature=temperature)
    assert calls == 2
    assert first.operating_points.empty
    assert tuple(first.operating_points.columns) == _SPECTRAL_HANDOFF_OUTPUT_COLUMNS
    assert first.operating_points.index.names == ["timestamp", "receiver_id"]
    assert first.diagnostics.row_count == 0
    pd.testing.assert_frame_equal(first.operating_points, second.operating_points)


def test_nonempty_determinism_and_immutability() -> None:
    receivers = _receivers(2)
    spectral = _spectral(receivers, periods=2)
    temperature = _temperature(spectral)
    spectral_before = spectral.irradiance.copy(deep=True)
    diagnostics_before = spectral.diagnostics
    temperature_before = temperature.copy(deep=True)
    receiver_vertices = [receiver.mesh.vertices_enu_m.copy() for receiver in receivers]
    first = _calculate(receivers, spectral, temperature=temperature)
    shuffled_spectral = replace(
        spectral, irradiance=spectral.irradiance.sample(frac=1.0, random_state=3)
    )
    shuffled_temperature = temperature.sample(frac=1.0, random_state=4)
    second = _calculate(
        list(reversed(receivers)), shuffled_spectral, temperature=shuffled_temperature
    )
    pd.testing.assert_frame_equal(first.operating_points, second.operating_points)
    pd.testing.assert_frame_equal(spectral.irradiance, spectral_before)
    assert spectral.diagnostics == diagnostics_before
    pd.testing.assert_series_equal(temperature, temperature_before)
    for receiver, vertices in zip(receivers, receiver_vertices, strict=True):
        np.testing.assert_array_equal(receiver.mesh.vertices_enu_m, vertices)
    assert first.operating_points["electrical_handoff_contract"].eq(
        SPECTRAL_ELECTRICAL_HANDOFF_CONTRACT_ID
    ).all()
    assert first.diagnostics.electrical_handoff_model == SPECTRAL_ELECTRICAL_HANDOFF_MODEL_ID
    assert first.operating_points["electrical_handoff_scope"].eq(
        SPECTRAL_ELECTRICAL_HANDOFF_SCOPE
    ).all()
