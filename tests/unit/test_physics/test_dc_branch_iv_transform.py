"""Tests for canonical S8-3B resistive DC branch I-V transformation."""

from __future__ import annotations

import copy
import importlib
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

import heliotelligence.physics.dc_collection as dc_collection  # type: ignore[import-untyped]
from heliotelligence.config.site import (  # type: ignore[import-untyped]
    DcBranchPathConfig,
    ElectricalTopologyConfig,
    InverterUnitConfig,
    MPPTConfig,
    SiteConfig,
    StringConfig,
)
from heliotelligence.physics.dc_collection import (
    DC_BRANCH_IV_TRANSFORM_CONTRACT_ID,
    DC_BRANCH_IV_TRANSFORM_COVERAGE_SCOPE,
    DC_BRANCH_IV_TRANSFORM_MODEL_ID,
    DC_BRANCH_IV_TRANSFORM_SCOPE,
    MPPT_INPUT_REFERENCE_PLANE,
    STRING_TERMINAL_REFERENCE_PLANE,
    DcBranchPathAuthorityResult,
    TopologyMpptInputStringIVResult,
    calculate_topology_mppt_input_string_iv,
    resolve_dc_branch_path_authority,
)
from heliotelligence.physics.electrical import (  # type: ignore[import-untyped]
    TopologyStringIVResult,
)

s8_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_state_aware_mppt_mismatch"
)


def _path(resistance: float | None) -> DcBranchPathConfig | None:
    if resistance is None:
        return None
    return DcBranchPathConfig(
        series_resistance_ohm=resistance,
        parameter_source="as_built_schedule:test",
        confidence="high",
    )


def _topology(
    resistance: float | None = 0.0,
    *,
    string_id: str = "string-1",
    zone_id: str | None = "zone-a",
) -> ElectricalTopologyConfig:
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
                                modules_per_string=24,
                                zone_id=zone_id,
                                dc_branch_path=_path(resistance),
                            )
                        ],
                    )
                ],
            )
        ]
    )


def _real_s81(
    topology: ElectricalTopologyConfig,
    *,
    zero: bool = False,
    periods: int = 1,
    receiver_count: int = 1,
) -> TopologyStringIVResult:
    _, result = s8_support._real_s81(
        topology,
        zero=zero,
        periods=periods,
        receiver_count=receiver_count,
    )
    return result


def _replace_curve(
    result: TopologyStringIVResult,
    string_id: str,
    voltage: list[float],
    current: list[float],
) -> TopologyStringIVResult:
    state = result.states.xs(string_id, level="string_id").iloc[0]
    timestamp = result.states.index.get_level_values("timestamp")[0]
    count = len(voltage)
    volts = np.asarray(voltage, dtype=float)
    amps = np.asarray(current, dtype=float)
    curve = pd.DataFrame(
        {
            "timestamp": [timestamp] * count,
            "curve_point": range(count),
            "voltage_v": volts,
            "current_a": amps,
            "power_w": volts * amps,
            "effective_irradiance_wm2": [
                state["spectral_electrical_equivalent_irradiance_wm2"]
            ]
            * count,
            "tier_used": [state["tier_used"]] * count,
            "fit_quality": [state["fit_quality"]] * count,
        }
    )
    curves = {
        key: value.copy(deep=True)
        for key, value in result.string_iv_curves_by_string_id.items()
    }
    curves[string_id] = curve
    diagnostics = replace(
        result.diagnostics,
        voltage_points=count,
        iv_curve_row_count=count,
    )
    return replace(
        result,
        string_iv_curves_by_string_id=curves,
        diagnostics=diagnostics,
    )


def _run(
    topology: ElectricalTopologyConfig,
    upstream: TopologyStringIVResult,
    authority: DcBranchPathAuthorityResult | None = None,
) -> TopologyMpptInputStringIVResult:
    return calculate_topology_mppt_input_string_iv(
        topology,
        upstream,
        authority or resolve_dc_branch_path_authority(topology),
    )


def test_explicit_zero_resistance_is_exact_identity() -> None:
    topology = _topology(0.0)
    upstream = _real_s81(topology)

    result = _run(topology, upstream)

    output = result.mppt_input_iv_curves_by_string_id["string-1"]
    source = upstream.string_iv_curves_by_string_id["string-1"]
    pd.testing.assert_frame_equal(output, source, check_exact=True)
    state = result.states.iloc[0]
    assert state["mppt_input_iv_state"] == "resolved_zero_resistance_identity"
    assert state["source_reference_plane"] == STRING_TERMINAL_REFERENCE_PLANE
    assert state["sink_reference_plane"] == MPPT_INPUT_REFERENCE_PLANE
    assert result.diagnostics.inserted_zero_crossing_count == 0
    assert result.diagnostics.zero_resistance_identity_state_count == 1


def test_known_positive_resistance_inserts_interpolated_zero_crossing() -> None:
    topology = _topology(1.0)
    upstream = _replace_curve(
        _real_s81(topology),
        "string-1",
        [0.0, 5.0, 10.0, 15.0],
        [5.0, 4.0, 2.0, 0.0],
    )

    result = _run(topology, upstream)
    curve = result.mppt_input_iv_curves_by_string_id["string-1"]

    assert curve["voltage_v"].tolist() == pytest.approx([0.0, 1.0, 8.0, 15.0])
    assert curve["current_a"].tolist() == pytest.approx(
        [5.0 + (5.0 / 6.0) * (4.0 - 5.0), 4.0, 2.0, 0.0]
    )
    assert curve.iloc[0]["voltage_v"] == 0.0
    assert curve.iloc[0]["power_w"] == 0.0
    assert curve["curve_point"].tolist() == [0, 1, 2, 3]
    assert np.allclose(curve["power_w"], curve["voltage_v"] * curve["current_a"])
    assert result.states.iloc[0]["mppt_input_iv_state"] == "resolved_resistive_branch_iv"
    assert result.diagnostics.inserted_zero_crossing_count == 1


def test_positive_resistance_with_no_negative_domain_inserts_nothing() -> None:
    topology = _topology(1.0)
    upstream = _replace_curve(
        _real_s81(topology),
        "string-1",
        [0.0, 5.0, 10.0, 15.0],
        [0.0, 1.0, 1.0, 0.0],
    )

    result = _run(topology, upstream)
    curve = result.mppt_input_iv_curves_by_string_id["string-1"]

    assert curve["voltage_v"].tolist() == pytest.approx([0.0, 4.0, 9.0, 15.0])
    assert len(curve) == 4
    assert result.diagnostics.inserted_zero_crossing_count == 0


def test_all_negative_transformed_domain_is_explicitly_unresolved() -> None:
    topology = _topology(10.0)
    upstream = _replace_curve(
        _real_s81(topology),
        "string-1",
        [0.0, 5.0, 10.0, 15.0],
        [5.0, 5.0, 5.0, 5.0],
    )

    result = _run(topology, upstream)

    assert result.mppt_input_iv_curves_by_string_id["string-1"].empty
    state = result.states.iloc[0]
    assert state["mppt_input_iv_resolved"] == False  # noqa: E712
    assert (
        state["mppt_input_iv_state"]
        == "unresolved_no_nonnegative_mppt_input_voltage_domain"
    )
    assert result.diagnostics.no_nonnegative_domain_state_count == 1


def test_missing_branch_authority_never_becomes_zero_resistance() -> None:
    topology = _topology(None)
    upstream = _real_s81(topology)

    result = _run(topology, upstream)
    state = result.states.iloc[0]

    assert state["mppt_input_iv_state"] == "unresolved_no_explicit_dc_branch_path"
    assert state["mppt_input_iv_resolved"] == False  # noqa: E712
    assert pd.isna(state["series_resistance_ohm"])
    assert result.mppt_input_iv_curves_by_string_id["string-1"].empty
    assert result.diagnostics.missing_authority_state_count == 1


def test_resolved_zero_string_remains_exact_zero_through_positive_resistance() -> None:
    topology = _topology(50.0)
    upstream = _real_s81(topology, zero=True)

    result = _run(topology, upstream)
    source = upstream.string_iv_curves_by_string_id["string-1"]
    output = result.mppt_input_iv_curves_by_string_id["string-1"]

    pd.testing.assert_frame_equal(output, source, check_exact=True)
    assert output[["voltage_v", "current_a", "power_w"]].eq(0.0).all().all()
    assert result.states.iloc[0]["mppt_input_iv_state"] == "resolved_zero_string_iv"
    assert result.diagnostics.zero_string_state_count == 1


def test_upstream_unresolved_root_cause_is_preserved_without_transform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(0.5)
    upstream = s8_support._set_string_unresolved(_real_s81(topology), "string-1")
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("transform must not run")

    monkeypatch.setattr(dc_collection, "_transform_curve_to_mppt_input", forbidden)
    result = _run(topology, upstream)

    assert calls == 0
    assert (
        result.states.iloc[0]["mppt_input_iv_state"]
        == "unresolved_receiver_module_electrical"
    )
    assert result.diagnostics.upstream_unresolved_state_count == 1


def test_mixed_topology_order_repeated_mppt_ids_and_diagnostic_closure() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="inverter-b",
                mppts=[
                    MPPTConfig(
                        id="mppt-1",
                        strings=[
                            StringConfig(
                                id="positive",
                                modules_per_string=24,
                                dc_branch_path=_path(0.5),
                            ),
                            StringConfig(
                                id="zero",
                                modules_per_string=24,
                                dc_branch_path=_path(0.0),
                            ),
                        ],
                    )
                ],
            ),
            InverterUnitConfig(
                id="inverter-a",
                mppts=[
                    MPPTConfig(
                        id="mppt-1",
                        strings=[StringConfig(id="missing", modules_per_string=24)],
                    )
                ],
            ),
        ]
    )
    upstream = _real_s81(topology, receiver_count=3)

    result = _run(topology, upstream)

    assert list(result.mppt_input_iv_curves_by_string_id) == ["positive", "zero", "missing"]
    assert result.states.index.get_level_values("string_id").tolist() == [
        "positive",
        "zero",
        "missing",
    ]
    diagnostics = result.diagnostics
    assert diagnostics.inverter_count == 2
    assert diagnostics.mppt_count == 2
    assert diagnostics.string_count == 3
    assert diagnostics.state_row_count == 3
    assert diagnostics.resolved_state_count == 2
    assert diagnostics.unresolved_state_count == 1
    assert diagnostics.zero_resistance_identity_state_count == 1
    assert diagnostics.positive_resistance_transform_state_count == 1
    assert diagnostics.missing_authority_state_count == 1


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("topology_string_iv_contract", "forged"),
        ("topology_string_iv_model", "forged"),
        ("topology_string_iv_scope", "forged"),
        ("string_iv_state", "forged"),
    ],
)
def test_tampered_s81_authority_is_rejected_before_transform(
    column: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(0.5)
    upstream = _real_s81(topology)
    states = upstream.states.copy(deep=True)
    states[column] = value
    forged = replace(upstream, states=states)
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("transform must not run")

    monkeypatch.setattr(dc_collection, "_transform_curve_to_mppt_input", forbidden)
    with pytest.raises(ValueError):
        _run(topology, forged)
    assert calls == 0


def test_tampered_s81_diagnostics_and_curve_are_rejected() -> None:
    topology = _topology(0.5)
    upstream = _real_s81(topology)
    stale = replace(
        upstream,
        diagnostics=replace(upstream.diagnostics, state_row_count=99),
    )
    with pytest.raises(ValueError, match="diagnostics"):
        _run(topology, stale)

    curves = {
        key: value.copy(deep=True)
        for key, value in upstream.string_iv_curves_by_string_id.items()
    }
    curves["string-1"].loc[0, "power_w"] += 1.0
    forged = replace(upstream, string_iv_curves_by_string_id=curves)
    with pytest.raises(ValueError, match="power"):
        _run(topology, forged)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("source_plane", "source reference plane"),
        ("resistance", "finite and non-negative"),
        ("resolved_flag", "unresolved branch authority"),
        ("provenance", "provenance"),
        ("topology", "topology identity"),
        ("diagnostics", "diagnostics"),
    ],
)
def test_tampered_branch_authority_is_rejected_before_transform(
    mutation: str,
    match: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(0.5)
    upstream = _real_s81(topology)
    authority = resolve_dc_branch_path_authority(topology)
    paths = authority.paths.copy(deep=True)
    diagnostics = authority.diagnostics
    if mutation == "source_plane":
        paths.iloc[0, paths.columns.get_loc("source_reference_plane")] = "forged"
    elif mutation == "resistance":
        paths.iloc[0, paths.columns.get_loc("series_resistance_ohm")] = -1.0
    elif mutation == "resolved_flag":
        paths.iloc[0, paths.columns.get_loc("branch_path_resolved")] = False
    elif mutation == "provenance":
        paths.iloc[0, paths.columns.get_loc("dc_branch_path_model")] = "forged"
    elif mutation == "topology":
        paths.index = pd.MultiIndex.from_tuples(
            [("wrong", "mppt-1", "string-1")],
            names=paths.index.names,
        )
    else:
        diagnostics = replace(diagnostics, resolved_path_count=0)
    forged = replace(authority, paths=paths, diagnostics=diagnostics)
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("transform must not run")

    monkeypatch.setattr(dc_collection, "_transform_curve_to_mppt_input", forbidden)
    with pytest.raises(ValueError, match=match):
        _run(topology, upstream, forged)
    assert calls == 0


def test_inputs_are_not_mutated_outputs_do_not_alias_and_calls_are_deterministic() -> None:
    topology = _topology(0.5)
    upstream = _real_s81(topology)
    authority = resolve_dc_branch_path_authority(topology)
    topology_snapshot = copy.deepcopy(topology)
    states_snapshot = upstream.states.copy(deep=True)
    curves_snapshot = {
        key: value.copy(deep=True)
        for key, value in upstream.string_iv_curves_by_string_id.items()
    }
    paths_snapshot = authority.paths.copy(deep=True)

    first = _run(topology, upstream, authority)
    second = _run(topology, upstream, authority)

    assert topology == topology_snapshot
    pd.testing.assert_frame_equal(upstream.states, states_snapshot)
    pd.testing.assert_frame_equal(authority.paths, paths_snapshot)
    for key, snapshot in curves_snapshot.items():
        pd.testing.assert_frame_equal(upstream.string_iv_curves_by_string_id[key], snapshot)
        assert first.mppt_input_iv_curves_by_string_id[key] is not snapshot
        pd.testing.assert_frame_equal(
            first.mppt_input_iv_curves_by_string_id[key],
            second.mppt_input_iv_curves_by_string_id[key],
        )
    pd.testing.assert_frame_equal(first.states, second.states)
    assert first.diagnostics == second.diagnostics


def test_empty_topology_and_empty_mppt_return_exact_empty_result() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[InverterUnitConfig(id="inverter", mppts=[MPPTConfig(id="empty")])]
    )
    upstream = _real_s81(topology)

    result = _run(topology, upstream)

    assert result.mppt_input_iv_curves_by_string_id == {}
    assert result.states.empty
    assert result.states.index.names == ["timestamp", "string_id"]
    assert result.diagnostics.inverter_count == 1
    assert result.diagnostics.mppt_count == 1
    assert result.diagnostics.string_count == 0
    assert result.diagnostics.state_row_count == 0
    assert result.diagnostics.output_curve_row_count == 0


def test_legacy_wiring_loss_and_zone_are_not_transform_authority() -> None:
    topology = _topology(0.5, zone_id="zone-a")
    upstream = _real_s81(topology)
    site = SiteConfig.model_validate(
        {
            "id": "site",
            "name": "non-authority",
            "latitude": 52.0,
            "longitude": 1.0,
            "timezone": "Europe/London",
            "capacity_kwp": 1000.0,
            "solcast_resource_id": "resource",
            "module": {"wiring_loss_dc_pct": 99.0},
            "electrical_topology": topology.model_dump(),
        }
    )
    assert site.electrical_topology is not None
    changed_zone = site.electrical_topology.model_copy(deep=True)
    changed_zone.inverters[0].mppts[0].strings[0].zone_id = "unrelated-zone"

    first = _run(topology, upstream)
    second = _run(
        changed_zone,
        upstream,
        resolve_dc_branch_path_authority(changed_zone),
    )

    pd.testing.assert_frame_equal(
        first.mppt_input_iv_curves_by_string_id["string-1"],
        second.mppt_input_iv_curves_by_string_id["string-1"],
    )


def test_contract_and_diagnostic_provenance() -> None:
    topology = _topology(0.5)
    result = _run(topology, _real_s81(topology))
    row = result.states.iloc[0]

    assert row["dc_branch_iv_transform_contract"] == DC_BRANCH_IV_TRANSFORM_CONTRACT_ID
    assert row["dc_branch_iv_transform_model"] == DC_BRANCH_IV_TRANSFORM_MODEL_ID
    assert row["dc_branch_iv_transform_scope"] == DC_BRANCH_IV_TRANSFORM_SCOPE
    assert row["dc_branch_iv_transform_coverage_scope"] == (
        DC_BRANCH_IV_TRANSFORM_COVERAGE_SCOPE
    )
    assert result.diagnostics.transformation_model == DC_BRANCH_IV_TRANSFORM_MODEL_ID
