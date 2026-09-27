"""Tests for S9-1 topology-aware inverter DC-envelope classification."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import (
    DcBranchPathConfig,
    ElectricalTopologyConfig,
    InverterUnitConfig,
    MPPTConfig,
    StringConfig,
)
from heliotelligence.physics import (
    dc_collection,
    inverter,
    inverter_envelope,
    inverter_envelope_lookup,
    inverter_lookup,
)
from heliotelligence.physics.inverter_authority import (
    resolve_topology_inverter_authority,
)
from heliotelligence.physics.inverter_topology import (
    TOPOLOGY_INVERTER_DC_ENVELOPE_CONTRACT_ID,
    TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID,
    MpptDcCurrentLimitAuthority,
    evaluate_topology_inverter_dc_envelope,
)

s8_support: Any = importlib.import_module("tests.unit.test_physics.test_state_aware_mppt_mismatch")
s83c_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_dc_mppt_input_common_voltage"
)

MODEL = "Manufacturer_Model_A"


def _database() -> pd.DataFrame:
    return pd.DataFrame(
        {
            MODEL: {
                "Paco": 6000.0,
                "Pdco": 6158.0,
                "Vdco": 360.0,
                "Pso": 36.0,
                "C0": 0.0,
                "C1": 0.0,
                "C2": 0.0,
                "C3": 0.0,
                "Pnt": 1.8,
                "Vdcmax": 600.0,
                "Idcmax": 32.0,
                "Mppt_low": 200.0,
                "Mppt_high": 500.0,
            }
        }
    )


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", _database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", _database)


def _topology(
    mppt_ids: tuple[str, ...] = ("mppt-1",),
    *,
    inverter_id: str = "inverter-1",
    populated: bool = True,
) -> ElectricalTopologyConfig:
    path = DcBranchPathConfig(
        series_resistance_ohm=0.0,
        parameter_source="as_built:test",
        confidence="high",
    )
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inverter_id,
                mppts=[
                    MPPTConfig(
                        id=mppt_id,
                        strings=(
                            [
                                StringConfig(
                                    id=f"{inverter_id}-{mppt_id}-string",
                                    modules_per_string=24,
                                    dc_branch_path=path,
                                )
                            ]
                            if populated
                            else []
                        ),
                    )
                    for mppt_id in mppt_ids
                ],
            )
        ]
    )


def _upstream(
    topology: ElectricalTopologyConfig,
    *,
    voltage: float = 360.0,
    current: float = 10.0,
    zero: bool = False,
) -> tuple[Any, Any, Any, Any]:
    _, s81 = s8_support._real_s81(topology, zero=zero, receiver_count=max(topology.string_count, 1))
    if not zero and topology.string_count:
        replacements = {
            string.id: s83c_support._curve_like(
                s81,
                string.id,
                [0.0, voltage, max(voltage + 1.0, voltage * 1.2)],
                [current, current, 0.0],
            )
            for inv in topology.inverters
            for mppt in inv.mppts
            for string in mppt.strings
        }
        s81 = s83c_support._replace_s81_curves(s81, replacements)
    branch = dc_collection.resolve_dc_branch_path_authority(topology)
    transformed = dc_collection.calculate_topology_mppt_input_string_iv(topology, s81, branch)
    operating = dc_collection.calculate_topology_mppt_input_operating_points(
        topology, s81, branch, transformed
    )
    return s81, branch, transformed, operating


def _run(
    topology: ElectricalTopologyConfig,
    upstream: tuple[Any, Any, Any, Any],
    *,
    names: dict[str, str] | None = None,
    limits: dict[tuple[str, str], MpptDcCurrentLimitAuthority] | None = None,
    authority: Any = None,
) -> Any:
    s81, branch, transformed, operating = upstream
    names = names if names is not None else {inverter.id: MODEL for inverter in topology.inverters}
    authority = authority or resolve_topology_inverter_authority(topology, names)
    return evaluate_topology_inverter_dc_envelope(
        topology, s81, branch, transformed, operating, names, authority, limits or {}
    )


@pytest.mark.parametrize(
    ("voltage", "expected"),
    [
        (200.0, "resolved_within_dc_envelope"),
        (500.0, "resolved_within_dc_envelope"),
        (199.0, "resolved_below_mppt_voltage"),
        (501.0, "resolved_above_mppt_voltage"),
        (600.0, "resolved_above_mppt_voltage"),
        (601.0, "resolved_absolute_dc_overvoltage"),
    ],
)
def test_voltage_boundaries_and_precedence(voltage: float, expected: str) -> None:
    topology = _topology()
    row = _run(topology, _upstream(topology, voltage=voltage)).states.iloc[0]
    assert row["dc_envelope_state"] == expected
    assert bool(row["dc_limits_satisfied"]) is (expected == "resolved_within_dc_envelope")


@pytest.mark.parametrize(
    ("current", "expected"),
    [(32.0, "resolved_within_dc_envelope"), (32.1, "resolved_dc_current_limit_exceeded")],
)
def test_single_populated_mppt_uses_inverter_idcmax_boundary(current: float, expected: str) -> None:
    topology = _topology()
    row = _run(topology, _upstream(topology, current=current)).states.iloc[0]
    assert row["dc_current_limit_source_kind"] == ("inverter_idcmax_single_populated_mppt")
    assert row["dc_current_max_a"] == 32.0
    assert row["dc_envelope_state"] == expected


def test_single_mppt_parity_with_existing_envelope_evaluator() -> None:
    topology = _topology()
    upstream = _upstream(topology, voltage=360.0, current=10.0)
    result = _run(topology, upstream)
    authority = resolve_topology_inverter_authority(topology, {"inverter-1": MODEL})
    row = result.states.iloc[0]
    direct = inverter_envelope.evaluate_inverter_dc_operating_envelope(
        pd.Series([row["v_mppt_input_v"]]),
        pd.Series([row["i_mppt_input_a"]]),
        pd.Series([row["p_mppt_input_w"]]),
        authority.dc_envelopes_by_inverter_id["inverter-1"],
    ).iloc[0]
    assert row["below_mppt_voltage_limit"] == direct["below_mppt_voltage_limit"]
    assert row["above_mppt_voltage_limit"] == direct["above_mppt_voltage_limit"]
    assert row["above_absolute_dc_voltage_limit"] == direct["above_absolute_dc_voltage_limit"]
    assert row["above_dc_current_limit"] == direct["above_dc_current_limit"]
    assert row["dc_limits_satisfied"] == direct["dc_limits_satisfied"]


def test_explicit_limit_overrides_single_input_current_dimension() -> None:
    topology = _topology()
    limit = MpptDcCurrentLimitAuthority(8.0, "datasheet:tracker", "high")
    row = _run(
        topology,
        _upstream(topology, current=10.0),
        limits={("inverter-1", "mppt-1"): limit},
    ).states.iloc[0]
    assert row["dc_current_limit_source_kind"] == "explicit_mppt_current_limit"
    assert row["dc_current_max_a"] == 8.0
    assert row["dc_envelope_state"] == "resolved_dc_current_limit_exceeded"


def test_multi_mppt_requires_separate_explicit_tracker_limits() -> None:
    topology = _topology(("mppt-1", "mppt-2"))
    result = _run(topology, _upstream(topology))
    assert result.states["dc_current_max_a"].isna().all()
    assert result.states["above_dc_current_limit"].isna().all()
    assert result.states["dc_limits_satisfied"].isna().all()
    assert (
        result.states["dc_envelope_state"]
        .eq("unresolved_no_explicit_mppt_current_limit_for_multi_mppt")
        .all()
    )


def test_multi_mppt_composite_limits_route_independently_without_summing() -> None:
    topology = _topology(("mppt-1", "mppt-2"))
    limits = {
        ("inverter-1", "mppt-2"): MpptDcCurrentLimitAuthority(12.0, "tracker:2", "medium"),
        ("inverter-1", "mppt-1"): MpptDcCurrentLimitAuthority(8.0, "tracker:1", "high"),
    }
    result = _run(topology, _upstream(topology, current=10.0), limits=limits)
    assert result.states["dc_current_max_a"].tolist() == [8.0, 12.0]
    assert result.states["i_mppt_input_a"].tolist() == [10.0, 10.0]
    assert result.states["dc_envelope_state"].tolist() == [
        "resolved_dc_current_limit_exceeded",
        "resolved_within_dc_envelope",
    ]


def test_definite_voltage_violation_resolves_without_multi_mppt_current_limit() -> None:
    topology = _topology(("mppt-1", "mppt-2"))
    result = _run(topology, _upstream(topology, voltage=601.0))
    assert result.states["above_dc_current_limit"].isna().all()
    assert result.states["dc_limits_satisfied"].eq(False).all()  # noqa: E712
    assert result.states["dc_envelope_resolved"].all()
    assert result.states["dc_envelope_state"].eq("resolved_absolute_dc_overvoltage").all()


def test_zero_state_is_inactive_and_does_not_fail_voltage_window() -> None:
    topology = _topology(("mppt-1", "mppt-2"))
    result = _run(topology, _upstream(topology, zero=True))
    assert result.states["dc_envelope_state"].eq("resolved_inactive_dc_input").all()
    assert result.states["dc_limits_satisfied"].eq(True).all()  # noqa: E712
    assert not result.states["below_mppt_voltage_limit"].any()


def test_missing_inverter_authority_remains_unresolved() -> None:
    topology = _topology()
    result = _run(topology, _upstream(topology), names={})
    row = result.states.iloc[0]
    assert row["dc_envelope_state"] == ("unresolved_no_explicit_inverter_model_reference")
    assert pd.isna(row["dc_limits_satisfied"])


def test_repeated_mppt_ids_across_inverters_remain_distinct() -> None:
    first = _topology(inverter_id="inverter-a").inverters[0]
    second = _topology(inverter_id="inverter-b").inverters[0]
    topology = ElectricalTopologyConfig(inverters=[first, second])
    result = _run(topology, _upstream(topology))
    assert result.states.index.get_level_values("inverter_id").tolist() == [
        "inverter-a",
        "inverter-b",
    ]


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), True])
def test_current_authority_numeric_validation(value: object) -> None:
    with pytest.raises(ValueError):
        MpptDcCurrentLimitAuthority(value, "source", "high")  # type: ignore[arg-type]


def test_unexpected_current_key_rejected_before_upstream_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology()
    upstream = _upstream(topology)
    monkeypatch.setattr(
        dc_collection,
        "calculate_topology_mppt_input_operating_points",
        lambda *args: pytest.fail("upstream physics called"),
    )
    with pytest.raises(ValueError, match="unexpected MPPT current-limit key"):
        _run(
            topology,
            upstream,
            limits={("inverter-1", "unknown"): MpptDcCurrentLimitAuthority(1.0, "source", "high")},
        )


def test_exact_s83c_replay_rejects_coherent_operating_point_tamper() -> None:
    topology = _topology()
    s81, branch, transformed, operating = _upstream(topology)
    forged_frame = operating.operating_points.copy(deep=True)
    forged_frame["v_mppt_input_v"] *= 0.9
    forged_frame["p_mppt_input_w"] = forged_frame["v_mppt_input_v"] * forged_frame["i_mppt_input_a"]
    forged = replace(operating, operating_points=forged_frame)
    with pytest.raises(ValueError, match="do not match canonical replay"):
        _run(topology, (s81, branch, transformed, forged))


def test_s83c_diagnostics_and_s90_state_object_tampering_are_rejected() -> None:
    topology = _topology()
    upstream = _upstream(topology)
    s81, branch, transformed, operating = upstream
    stale = replace(
        operating,
        diagnostics=replace(operating.diagnostics, state_row_count=99),
    )
    with pytest.raises(ValueError, match="diagnostics"):
        _run(topology, (s81, branch, transformed, stale))

    names = {"inverter-1": MODEL}
    authority = resolve_topology_inverter_authority(topology, names)
    changed = authority.states.copy(deep=True)
    changed.loc["inverter-1", "inverter_model_reference"] = "forged"
    with pytest.raises(ValueError, match="states"):
        _run(topology, upstream, names=names, authority=replace(authority, states=changed))
    forged_objects = replace(authority, dc_envelopes_by_inverter_id={})
    with pytest.raises(ValueError, match="equipment objects"):
        _run(topology, upstream, names=names, authority=forged_objects)


def test_empty_topology_and_empty_mppt_are_deterministic() -> None:
    for topology in (ElectricalTopologyConfig(), _topology(populated=False)):
        result = _run(topology, _upstream(topology), names={})
        assert result.states.empty
        assert result.states.index.names == ["timestamp", "inverter_id", "mppt_id"]
        assert result.diagnostics.row_count == 0


def test_nullable_dtypes_provenance_diagnostics_immutability_and_ownership() -> None:
    topology = _topology(("mppt-1", "mppt-2"))
    upstream = _upstream(topology)
    snapshots = [
        value.states.copy(deep=True) if hasattr(value, "states") else None for value in upstream
    ]
    first = _run(topology, upstream)
    second = _run(topology, upstream)
    pd.testing.assert_frame_equal(first.states, second.states, check_exact=True)
    assert str(first.states["above_dc_current_limit"].dtype) == "boolean"
    assert str(first.states["dc_limits_satisfied"].dtype) == "boolean"
    assert (
        first.states["topology_inverter_dc_envelope_contract"]
        .eq(TOPOLOGY_INVERTER_DC_ENVELOPE_CONTRACT_ID)
        .all()
    )
    assert first.diagnostics.envelope_model == TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID
    assert first.diagnostics.row_count == (
        first.diagnostics.resolved_envelope_count + first.diagnostics.unresolved_envelope_count
    )
    first.states.iloc[0, 0] = 999.0
    assert upstream[-1].operating_points.iloc[0]["v_mppt_input_v"] != 999.0
    for value, snapshot in zip(upstream, snapshots, strict=True):
        if snapshot is not None:
            pd.testing.assert_frame_equal(value.states, snapshot, check_exact=True)


def test_no_conversion_or_operating_point_correction_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology()
    upstream = _upstream(topology)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("conversion or envelope mutation called")

    monkeypatch.setattr(inverter, "calculate_sandia_inverter_ac_power", forbidden)
    monkeypatch.setattr(inverter_envelope, "evaluate_inverter_dc_operating_envelope", forbidden)
    pvlib_inverter: Any = importlib.import_module("pvlib.inverter")
    monkeypatch.setattr(pvlib_inverter, "sandia", forbidden)
    monkeypatch.setattr(pvlib_inverter, "sandia_multi", forbidden)
    result = _run(topology, upstream)
    assert (
        result.states.iloc[0]["v_mppt_input_v"]
        == (upstream[-1].operating_points.iloc[0]["v_mppt_input_v"])
    )
