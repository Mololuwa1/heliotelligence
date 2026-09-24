"""Tests for explicit S7E-1 receiver-to-string module-I-V routing."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

import heliotelligence.physics.electrical as electrical
from heliotelligence.config.site import (
    ElectricalTopologyConfig,
    InverterUnitConfig,
    ModuleConfig,
    MPPTConfig,
    SiteConfig,
    StringConfig,
)
from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.electrical import (
    RECEIVER_STRING_MODULE_IV_CONTRACT_ID,
    RECEIVER_STRING_MODULE_IV_COVERAGE_SCOPE,
    RECEIVER_STRING_MODULE_IV_MODEL_ID,
    RECEIVER_STRING_MODULE_IV_SCOPE,
    ReceiverModuleElectricalResult,
    calculate_module_iv_curves,
    calculate_receiver_module_operating_points_from_spectral_response,
    calculate_topology_module_iv_curves_from_receiver_electrical,
)
from heliotelligence.physics.spectral_response import SpectralResponseResult

handoff_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_spectral_electrical_handoff"
)


def _receivers(count: int = 1) -> list[PVReceiver]:
    return cast(list[PVReceiver], handoff_support._receivers(count))


def _site(*, tier5: bool = False) -> SiteConfig:
    return cast(SiteConfig, handoff_support._site(tier5=tier5))


def _tier4_site(*, variant: str) -> SiteConfig:
    parameters = (
        {
            "pnom_wp": 570.0,
            "v_mp": 41.64,
            "i_mp": 13.69,
            "v_oc": 50.60,
            "i_sc": 14.36,
            "alpha_sc": 0.045,
            "beta_voc": -0.25,
            "gamma_pmp": -0.29,
            "cells_in_series": 144,
        }
        if variant == "a"
        else {
            "pnom_wp": 450.0,
            "v_mp": 34.5,
            "i_mp": 13.04,
            "v_oc": 41.5,
            "i_sc": 13.75,
            "alpha_sc": 0.04,
            "beta_voc": -0.28,
            "gamma_pmp": -0.34,
            "cells_in_series": 120,
        }
    )
    return _site().model_copy(
        update={"module": ModuleConfig(technology="mono_si", **parameters)}
    )


def _spectral(
    receivers: list[PVReceiver],
    *,
    periods: int = 1,
    front: float = 800.0,
    rear: float = 200.0,
    bifacial: bool = True,
    front_factor: float = 0.95,
    rear_factor: float = 1.05,
    front_activation: str = "enabled",
    rear_treatment: str = "explicit_factor",
) -> SpectralResponseResult:
    return cast(
        SpectralResponseResult,
        handoff_support._spectral(
            receivers,
            periods=periods,
            front=front,
            rear=rear,
            bifacial=bifacial,
            front_factor=front_factor,
            rear_factor=rear_factor,
            front_activation=front_activation,
            rear_treatment=rear_treatment,
        ),
    )


def _electrical(
    receivers: list[PVReceiver],
    *,
    site: SiteConfig | None = None,
    spectral: SpectralResponseResult | None = None,
) -> ReceiverModuleElectricalResult:
    active_site = site or _site()
    active_spectral = spectral or _spectral(receivers)
    return calculate_receiver_module_operating_points_from_spectral_response(
        active_site,
        receivers,
        active_spectral,
        cell_temperature_c=pd.Series(25.0, index=active_spectral.irradiance.index),
    )


def _topology(
    string_specs: list[tuple[str, str | None, int]] | None = None,
) -> ElectricalTopologyConfig:
    specs = string_specs or [("string-1", "misleading-zone", 24)]
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="inverter-1",
                mppts=[
                    MPPTConfig(
                        id="mppt-1",
                        strings=[
                            StringConfig(
                                id=string_id,
                                zone_id=zone_id,
                                modules_per_string=modules,
                            )
                            for string_id, zone_id, modules in specs
                        ],
                    )
                ],
            )
        ]
    )


def _route(
    receivers: list[PVReceiver],
    electrical_result: ReceiverModuleElectricalResult,
    *,
    topology: ElectricalTopologyConfig | None = None,
    assignments: dict[str, str] | None = None,
    policy: str = "require_all_receivers",
    site: SiteConfig | None = None,
    voltage_points: int = 11,
) -> Any:
    active_topology = topology or _topology()
    mapping = {"string-1": receivers[0].id} if assignments is None else assignments
    return calculate_topology_module_iv_curves_from_receiver_electrical(
        site or _site(),
        receivers,
        active_topology,
        electrical_result,
        receiver_id_by_string_id=mapping,
        receiver_coverage_policy=cast(Any, policy),
        voltage_points=voltage_points,
    )


def _mutate(
    result: ReceiverModuleElectricalResult,
    column: str,
    value: object,
) -> ReceiverModuleElectricalResult:
    frame = result.operating_points.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc(column)] = value
    return replace(result, operating_points=frame)


def test_explicit_mapping_overrides_zone_and_uses_928_without_second_spectral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receivers = _receivers(2)
    spectral = _spectral(receivers)
    handoff = _electrical(receivers, spectral=spectral)
    topology = _topology([("string-1", receivers[1].id, 24)])

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("legacy spectral path called")

    monkeypatch.setattr(electrical, "_compute_spectral_factor", forbidden)
    monkeypatch.setattr(electrical, "_calculate_effective_irradiance", forbidden)
    result = _route(
        receivers,
        handoff,
        topology=topology,
        assignments={"string-1": receivers[0].id},
        policy="allow_unassigned_receivers",
    )
    assert result.states.iloc[0]["receiver_id"] == receivers[0].id
    curve = result.module_iv_curves_by_string_id["string-1"]
    assert curve["effective_irradiance_wm2"].eq(928.0).all()
    assert not curve["effective_irradiance_wm2"].eq(960.0).any()
    assert curve["tier_used"].eq(3).all()
    assert result.diagnostics.unreferenced_receiver_count == 1


def test_receiver_sharing_evaluates_once_and_returns_deep_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receivers = _receivers()
    handoff = _electrical(receivers)
    topology = _topology(
        [("string-a", "x", 24), ("string-b", "y", 30), ("string-c", "z", 36)]
    )
    original = electrical._evaluate_module_iv_curves_from_electrical_irradiance
    calls = 0

    def recording(
        site: SiteConfig,
        irradiance: pd.Series,
        temperature: pd.Series,
        resolution: dict[str, Any],
        voltage_points: int,
        *,
        datasheet_reference: Any = None,
    ) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return original(
            site,
            irradiance,
            temperature,
            resolution,
            voltage_points,
            datasheet_reference=datasheet_reference,
        )

    monkeypatch.setattr(
        electrical,
        "_evaluate_module_iv_curves_from_electrical_irradiance",
        recording,
    )
    assignments = {string_id: receivers[0].id for string_id in ("string-a", "string-b", "string-c")}
    result = _route(
        receivers,
        handoff,
        topology=topology,
        assignments=assignments,
    )
    assert calls == 1
    assert result.diagnostics.shared_receiver_count == 1
    curves = result.module_iv_curves_by_string_id
    pd.testing.assert_frame_equal(curves["string-a"], curves["string-b"])
    original_b = curves["string-b"].copy(deep=True)
    curves["string-a"].loc[0, "power_w"] = -99.0
    pd.testing.assert_frame_equal(curves["string-b"], original_b)
    assert curves["string-b"]["voltage_v"].max() < 100.0


@pytest.mark.parametrize(
    "mapping",
    [
        {},
        {"string-1": "r0", "extra": "r0"},
        {"string-1": "unknown"},
        {"string-1": ""},
        {"string-1": "   "},
        {"string-1": cast(Any, ["r0"])},
    ],
)
def test_exact_assignment_contract_rejects_invalid_mapping(mapping: dict[str, str]) -> None:
    receivers = _receivers()
    with pytest.raises(ValueError):
        _route(receivers, _electrical(receivers), assignments=mapping)


def test_receiver_coverage_policy_and_geometry_order_independence() -> None:
    receivers = _receivers(2)
    handoff = _electrical(receivers)
    mapping = {"string-1": receivers[0].id}
    with pytest.raises(ValueError):
        _route(receivers, handoff, assignments=mapping)
    first = _route(
        receivers,
        handoff,
        assignments=mapping,
        policy="allow_unassigned_receivers",
    )
    second = _route(
        list(reversed(receivers)),
        replace(
            handoff,
            operating_points=handoff.operating_points.sample(frac=1.0, random_state=3),
        ),
        assignments=mapping,
        policy="allow_unassigned_receivers",
    )
    pd.testing.assert_frame_equal(first.states, second.states)
    pd.testing.assert_frame_equal(
        first.module_iv_curves_by_string_id["string-1"],
        second.module_iv_curves_by_string_id["string-1"],
    )


def test_unity_parity_and_no_modules_per_string_scaling() -> None:
    receivers = _receivers()
    spectral = _spectral(
        receivers,
        bifacial=False,
        front=850.0,
        front_activation="disabled",
    )
    handoff = _electrical(receivers, spectral=spectral)
    result = _route(receivers, handoff, topology=_topology([("string-1", None, 24)]))
    timestamp = pd.DatetimeIndex(
        handoff.operating_points.index.get_level_values("timestamp").unique()
    )
    legacy = calculate_module_iv_curves(
        _site(),
        pd.Series(850.0, index=timestamp),
        pd.Series(25.0, index=timestamp),
        voltage_points=11,
    )
    curve = result.module_iv_curves_by_string_id["string-1"]
    np.testing.assert_allclose(curve["voltage_v"], legacy["voltage_v"])
    np.testing.assert_allclose(curve["current_a"], legacy["current_a"])
    np.testing.assert_allclose(curve["power_w"], legacy["power_w"])


def test_tier5_positive_unavailable_and_zero_resolves_exact_curve() -> None:
    receivers = _receivers()
    site = _site(tier5=True)
    positive = _electrical(receivers, site=site)
    positive_result = _route(receivers, positive, site=site)
    assert positive_result.module_iv_curves_by_string_id["string-1"].empty
    assert positive_result.states.iloc[0]["module_iv_state"] == (
        "unresolved_tier5_voltage_dependent_iv_unavailable"
    )

    zero_spectral = _spectral(receivers, front=0.0, rear=0.0)
    zero = _electrical(receivers, site=site, spectral=zero_spectral)
    zero_result = _route(receivers, zero, site=site, voltage_points=7)
    curve = zero_result.module_iv_curves_by_string_id["string-1"]
    assert len(curve) == 7
    assert curve[["voltage_v", "current_a", "power_w"]].eq(0.0).all().all()
    assert zero_result.states.iloc[0]["module_iv_state"] == "resolved_zero_module_iv"


def test_mixed_positive_zero_unresolved_state_and_curve_closure() -> None:
    receivers = _receivers()
    spectral = _spectral(receivers, periods=3)
    handoff = _electrical(receivers, spectral=spectral)
    frame = handoff.operating_points.copy(deep=True)
    zero_index = frame.index[1]
    frame.loc[zero_index, "spectral_electrical_equivalent_irradiance_wm2"] = 0.0
    frame.loc[zero_index, "p_mp_w"] = 0.0
    frame.loc[zero_index, "v_mp_v"] = 0.0
    frame.loc[zero_index, "i_mp_a"] = 0.0
    frame.loc[zero_index, "module_electrical_state"] = (
        "resolved_zero_spectral_electrical_irradiance"
    )
    unresolved_index = frame.index[2]
    frame.loc[unresolved_index, "spectral_electrical_equivalent_irradiance_wm2"] = np.nan
    frame.loc[unresolved_index, "spectral_electrical_equivalent_resolved"] = False
    frame.loc[unresolved_index, "spectral_electrical_equivalent_state"] = (
        "unresolved_front_spectral_response"
    )
    frame.loc[unresolved_index, ["p_mp_w", "v_mp_v", "i_mp_a"]] = np.nan
    frame.loc[unresolved_index, "module_electrical_resolved"] = False
    frame.loc[unresolved_index, "module_electrical_state"] = (
        "unresolved_spectral_electrical_equivalent_irradiance"
    )
    mixed = replace(
        handoff,
        operating_points=frame,
        diagnostics=replace(
            handoff.diagnostics,
            resolved_row_count=2,
            unresolved_row_count=1,
            zero_irradiance_row_count=1,
            solver_row_count=1,
        ),
    )
    result = _route(receivers, mixed, voltage_points=7)
    assert result.states["module_iv_state"].tolist() == [
        "resolved_module_iv",
        "resolved_zero_module_iv",
        "unresolved_receiver_module_electrical",
    ]
    assert len(result.module_iv_curves_by_string_id["string-1"]) == 14
    assert result.diagnostics.resolved_iv_state_count == 2
    assert result.diagnostics.unresolved_iv_state_count == 1


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("electrical_handoff_contract", "wrong"),
        ("electrical_handoff_model", "wrong"),
        ("electrical_handoff_scope", "wrong"),
        ("spectral_response_contract", "wrong"),
        ("spectral_response_model", "wrong"),
        ("spectral_response_scope", "wrong"),
        ("module_electrical_state", "custom_resolved"),
        ("p_mp_w", -1.0),
    ],
)
def test_s7e1_provenance_and_row_tampering_rejected(column: str, value: object) -> None:
    receivers = _receivers()
    with pytest.raises(ValueError):
        _route(receivers, _mutate(_electrical(receivers), column, value))


def test_s7e1_type_grid_diagnostics_and_site_staleness_rejected() -> None:
    receivers = _receivers()
    handoff = _electrical(receivers)
    with pytest.raises(ValueError):
        calculate_topology_module_iv_curves_from_receiver_electrical(
            _site(),
            receivers,
            _topology(),
            cast(Any, handoff.operating_points),
            receiver_id_by_string_id={"string-1": "r0"},
            receiver_coverage_policy="require_all_receivers",
        )
    with pytest.raises(ValueError):
        _route(
            receivers,
            replace(handoff, diagnostics=replace(handoff.diagnostics, row_count=99)),
        )
    with pytest.raises(ValueError):
        _route(receivers, replace(handoff, operating_points=handoff.operating_points.iloc[0:0]))
    with pytest.raises(ValueError):
        _route(receivers, handoff, site=_site(tier5=True))


def test_same_tier_and_fit_quality_stale_module_is_rejected() -> None:
    receivers = _receivers()
    site_a = _tier4_site(variant="a")
    site_b = _tier4_site(variant="b")
    resolution_a = electrical._resolve_module_configuration(site_a)
    resolution_b = electrical._resolve_module_configuration(site_b)
    assert (resolution_a["tier"], resolution_a["fit_quality"]) == (4, "low")
    assert (resolution_b["tier"], resolution_b["fit_quality"]) == (4, "low")
    handoff = _electrical(receivers, site=site_a)

    with pytest.raises(ValueError, match="operating point is stale"):
        _route(receivers, handoff, site=site_b)


@pytest.mark.parametrize("column", ["p_mp_w", "v_mp_v", "i_mp_a"])
def test_positive_operating_point_component_tamper_is_rejected(column: str) -> None:
    receivers = _receivers()
    handoff = _electrical(receivers)
    original = float(handoff.operating_points.iloc[0][column])

    with pytest.raises(ValueError, match="operating point is stale"):
        _route(receivers, _mutate(handoff, column, original * 0.9))


def test_tier5_same_tier_stale_power_authority_is_rejected() -> None:
    receivers = _receivers()
    site_a = _site(tier5=True)
    site_b = site_a.model_copy(
        update={
            "module": ModuleConfig(
                technology="mono_si",
                pnom_wp=800.0,
                gamma_pmp=0.0,
            )
        }
    )
    resolution_a = electrical._resolve_module_configuration(site_a)
    resolution_b = electrical._resolve_module_configuration(site_b)
    assert (resolution_a["tier"], resolution_a["fit_quality"]) == (5, "pvwatts")
    assert (resolution_b["tier"], resolution_b["fit_quality"]) == (5, "pvwatts")
    handoff = _electrical(receivers, site=site_a)

    with pytest.raises(ValueError, match="operating point is stale"):
        _route(receivers, handoff, site=site_b)


def test_receiver_admission_empty_topology_and_empty_time_axis() -> None:
    receivers = _receivers()
    handoff = _electrical(receivers)
    with pytest.raises(ValueError):
        _route([replace(receivers[0], receiver_kind=ReceiverKind.TRACKER_TABLE)], handoff)
    empty_topology = ElectricalTopologyConfig(inverters=[])
    empty = _route(
        receivers,
        handoff,
        topology=empty_topology,
        assignments={},
        policy="allow_unassigned_receivers",
    )
    assert empty.module_iv_curves_by_string_id == {}
    assert empty.states.empty
    with pytest.raises(ValueError):
        _route(receivers, handoff, topology=empty_topology, assignments={})

    spectral_empty = _spectral(receivers, periods=0)
    electrical_empty = _electrical(receivers, spectral=spectral_empty)
    result = _route(receivers, electrical_empty)
    assert set(result.module_iv_curves_by_string_id) == {"string-1"}
    assert (
        result.module_iv_curves_by_string_id["string-1"].columns.tolist()
        == electrical._IV_CURVE_COLUMNS
    )
    assert result.states.empty
    assert result.states.index.names == ["timestamp", "string_id"]
    assert result.diagnostics.state_row_count == 0


def test_determinism_immutability_and_contract_provenance() -> None:
    receivers = _receivers(2)
    topology = _topology([("string-b", "r0", 24), ("string-a", "r1", 24)])
    handoff = _electrical(receivers, spectral=_spectral(receivers, periods=2))
    mapping = {"string-b": "r0", "string-a": "r1"}
    frame_before = handoff.operating_points.copy(deep=True)
    diagnostics_before = handoff.diagnostics
    mapping_before = mapping.copy()
    vertices = [receiver.mesh.vertices_enu_m.copy() for receiver in receivers]
    first = _route(receivers, handoff, topology=topology, assignments=mapping)
    second = _route(
        list(reversed(receivers)),
        replace(
            handoff,
            operating_points=handoff.operating_points.sample(frac=1.0, random_state=5),
        ),
        topology=topology,
        assignments={"string-a": "r1", "string-b": "r0"},
    )
    pd.testing.assert_frame_equal(first.states, second.states)
    for string_id in mapping:
        pd.testing.assert_frame_equal(
            first.module_iv_curves_by_string_id[string_id],
            second.module_iv_curves_by_string_id[string_id],
        )
    assert first.states.index.get_level_values("string_id").tolist()[:2] == [
        "string-b",
        "string-a",
    ]
    assert first.states["receiver_string_module_iv_contract"].eq(
        RECEIVER_STRING_MODULE_IV_CONTRACT_ID
    ).all()
    assert first.states["receiver_string_module_iv_model"].eq(
        RECEIVER_STRING_MODULE_IV_MODEL_ID
    ).all()
    assert first.states["receiver_string_module_iv_scope"].eq(
        RECEIVER_STRING_MODULE_IV_SCOPE
    ).all()
    assert first.states["receiver_string_module_iv_coverage_scope"].eq(
        RECEIVER_STRING_MODULE_IV_COVERAGE_SCOPE
    ).all()
    pd.testing.assert_frame_equal(handoff.operating_points, frame_before)
    assert handoff.diagnostics == diagnostics_before
    assert mapping == mapping_before
    for receiver, original_vertices in zip(receivers, vertices, strict=True):
        np.testing.assert_array_equal(receiver.mesh.vertices_enu_m, original_vertices)
