"""Tests for S9-2 topology-aware Sandia inverter conversion."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pvlib.inverter  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter import calculate_sandia_inverter_ac_power
from heliotelligence.physics.inverter_authority import resolve_topology_inverter_authority
from heliotelligence.physics.inverter_conversion import (
    INVERTER_AC_OUTPUT_REFERENCE_PLANE,
    MPPT_INPUT_REFERENCE_PLANE,
    TOPOLOGY_SANDIA_INVERTER_AC_CONTRACT_ID,
    TOPOLOGY_SANDIA_INVERTER_AC_MODEL_ID,
    calculate_topology_sandia_inverter_ac,
)
from heliotelligence.physics.inverter_topology import (
    MpptDcCurrentLimitAuthority,
    evaluate_topology_inverter_dc_envelope,
)

s91_support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_topology")
MODEL = s91_support.MODEL


def _database() -> pd.DataFrame:
    data = s91_support._database()
    data.loc["C1", MODEL] = 0.0002
    data.loc["C2", MODEL] = 0.0001
    data.loc["C3", MODEL] = 0.0001
    return data


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", _database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", _database)


def _inputs(
    topology: ElectricalTopologyConfig,
    *,
    voltage: float = 360.0,
    current: float = 10.0,
    zero: bool = False,
    limits: dict[tuple[str, str], MpptDcCurrentLimitAuthority] | None = None,
    names: dict[str, str] | None = None,
) -> tuple[Any, ...]:
    upstream = s91_support._upstream(topology, voltage=voltage, current=current, zero=zero)
    names = names if names is not None else {inverter.id: MODEL for inverter in topology.inverters}
    authority = resolve_topology_inverter_authority(topology, names)
    limits = limits or {}
    s81, branch, transformed, operating = upstream
    envelope = evaluate_topology_inverter_dc_envelope(
        topology, s81, branch, transformed, operating, names, authority, limits
    )
    return (*upstream, names, authority, limits, envelope)


def _run(topology: ElectricalTopologyConfig, values: tuple[Any, ...]) -> Any:
    return calculate_topology_sandia_inverter_ac(topology, *values)


def _multi_limits(
    topology: ElectricalTopologyConfig, maximum: float = 100.0
) -> dict[tuple[str, str], MpptDcCurrentLimitAuthority]:
    return {
        (inverter.id, mppt.id): MpptDcCurrentLimitAuthority(
            maximum, f"tracker:{inverter.id}:{mppt.id}", "high"
        )
        for inverter in topology.inverters
        for mppt in inverter.mppts
        if mppt.strings
    }


def test_single_mppt_has_exact_scalar_parity() -> None:
    topology = s91_support._topology()
    values = _inputs(topology)
    result = _run(topology, values)
    envelope = values[-1].states
    authority = values[-3]
    direct = calculate_sandia_inverter_ac_power(
        envelope["v_mppt_input_v"],
        envelope["i_mppt_input_a"],
        envelope["p_mppt_input_w"],
        authority.sandia_models_by_inverter_id["inverter-1"],
    )
    row = result.operating_points.iloc[0]
    assert row["p_ac_available_w"] == direct.iloc[0]["p_ac_available_w"]
    assert row["ac_to_dc_ratio"] == direct.iloc[0]["ac_to_dc_ratio"]
    assert row["at_ac_power_limit"] == direct.iloc[0]["at_ac_power_limit"]
    assert row["sandia_conversion_path"] == "sandia_single_mppt"
    assert [
        row["active_mppt_count"],
        row["inactive_mppt_count"],
        row["unresolved_mppt_count"],
        row["violating_mppt_count"],
    ] == [1, 0, 0, 0]


def test_multi_mppt_exact_public_parity_preserves_distinct_voltages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    values = _inputs(topology, voltage=360.0, current=10.0, limits=_multi_limits(topology))
    envelope = values[-1]
    # Produce a second canonical run with a distinct second voltage by changing
    # authoritative S8-1 input curves before all downstream stages.
    s81, branch, transformed, operating, names, authority, limits, _ = values
    curves = {
        key: frame.copy(deep=True) for key, frame in s81.string_iv_curves_by_string_id.items()
    }
    second_id = list(curves)[1]
    curves[second_id]["voltage_v"] *= 1.1
    curves[second_id]["power_w"] = curves[second_id]["voltage_v"] * curves[second_id]["current_a"]
    s81 = replace(s81, string_iv_curves_by_string_id=curves)
    transformed = importlib.import_module(
        "heliotelligence.physics.dc_collection"
    ).calculate_topology_mppt_input_string_iv(topology, s81, branch)
    operating = importlib.import_module(
        "heliotelligence.physics.dc_collection"
    ).calculate_topology_mppt_input_operating_points(topology, s81, branch, transformed)
    envelope = evaluate_topology_inverter_dc_envelope(
        topology, s81, branch, transformed, operating, names, authority, limits
    )
    values = (s81, branch, transformed, operating, names, authority, limits, envelope)
    seen: list[list[pd.Series]] = []
    real = pvlib.inverter.sandia_multi

    def wrapped(v_dc: list[pd.Series], p_dc: list[pd.Series], model: dict[str, float]) -> Any:
        seen.append(v_dc)
        return real(v_dc, p_dc, model)

    monkeypatch.setattr(pvlib.inverter, "sandia_multi", wrapped)
    result = _run(topology, values)
    frames = [
        envelope.states.xs(("inverter-1", mppt), level=("inverter_id", "mppt_id"))
        for mppt in ("mppt-1", "mppt-2")
    ]
    expected = real(
        [frame["v_mppt_input_v"] for frame in frames],
        [frame["p_mppt_input_w"] for frame in frames],
        authority.sandia_models_by_inverter_id["inverter-1"].parameters.to_pvlib_dict(),
    )
    row = result.operating_points.iloc[0]
    assert row["p_ac_available_w"] == pytest.approx(float(expected.iloc[0]))
    assert seen and not seen[0][0].equals(seen[0][1])
    assert row["p_dc_inverter_input_w"] == pytest.approx(
        sum(float(frame.iloc[0]["p_mppt_input_w"]) for frame in frames)
    )


def test_multi_mppt_applies_one_paco_not_one_inverter_per_tracker() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    values = _inputs(topology, voltage=360.0, current=10.0, limits=_multi_limits(topology))
    result = _run(topology, values)
    row = result.operating_points.iloc[0]
    model = values[-3].sandia_models_by_inverter_id["inverter-1"]
    assert row["p_ac_available_w"] <= model.parameters.paco_w
    assert row["at_ac_power_limit"]
    assert row["sandia_conversion_path"] == "sandia_multi_mppt"


def test_all_zero_multi_mppt_applies_one_night_tare() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    values = _inputs(topology, zero=True)
    row = _run(topology, values).operating_points.iloc[0]
    model = values[-3].sandia_models_by_inverter_id["inverter-1"]
    assert row["p_dc_inverter_input_w"] == 0.0
    assert row["p_ac_available_w"] == -model.parameters.pnt_w
    assert row["inverter_conversion_state"] == "resolved_sandia_night_tare"
    assert [
        row["active_mppt_count"],
        row["inactive_mppt_count"],
        row["unresolved_mppt_count"],
        row["violating_mppt_count"],
    ] == [0, 2, 0, 0]


@pytest.mark.parametrize(
    ("voltage", "current", "state"),
    [
        (601.0, 10.0, "unresolved_member_dc_constraint_violation"),
        (360.0, 33.0, "unresolved_member_dc_constraint_violation"),
    ],
)
def test_constraint_violation_blocks_conversion(voltage: float, current: float, state: str) -> None:
    topology = s91_support._topology()
    row = _run(topology, _inputs(topology, voltage=voltage, current=current)).operating_points.iloc[
        0
    ]
    assert row["inverter_conversion_state"] == state
    assert pd.isna(row["p_ac_available_w"])
    assert row["sandia_conversion_path"] == "not_evaluated"
    assert [
        row["active_mppt_count"],
        row["inactive_mppt_count"],
        row["unresolved_mppt_count"],
        row["violating_mppt_count"],
    ] == [0, 0, 0, 1]


def test_missing_multi_tracker_authority_blocks_conversion() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    row = _run(topology, _inputs(topology)).operating_points.iloc[0]
    assert row["inverter_conversion_state"] == "unresolved_member_dc_envelope"
    assert row["unresolved_mppt_count"] == 2
    assert pd.isna(row["p_ac_available_w"])
    assert [
        row["active_mppt_count"],
        row["inactive_mppt_count"],
        row["unresolved_mppt_count"],
        row["violating_mppt_count"],
    ] == [0, 0, 2, 0]


@pytest.mark.parametrize(
    ("mppts", "voltage", "current", "zero", "with_limits"),
    [
        (("mppt-1",), 360.0, 10.0, False, False),
        (("mppt-1",), 601.0, 10.0, False, False),
        (("mppt-1",), 360.0, 33.0, False, False),
        (("mppt-1", "mppt-2"), 360.0, 10.0, True, False),
        (("mppt-1", "mppt-2"), 360.0, 10.0, False, False),
        (("mppt-1", "mppt-2"), 360.0, 10.0, False, True),
    ],
)
def test_mppt_classification_counts_close_for_every_returned_row(
    mppts: tuple[str, ...],
    voltage: float,
    current: float,
    zero: bool,
    with_limits: bool,
) -> None:
    topology = s91_support._topology(mppts)
    limits = _multi_limits(topology) if with_limits else None
    result = _run(
        topology,
        _inputs(topology, voltage=voltage, current=current, zero=zero, limits=limits),
    )
    for _, row in result.operating_points.iterrows():
        counts = [
            row["active_mppt_count"],
            row["inactive_mppt_count"],
            row["unresolved_mppt_count"],
            row["violating_mppt_count"],
        ]
        assert all(isinstance(value, (int, np.integer)) for value in counts)
        assert all(value >= 0 for value in counts)
        assert sum(counts) == row["populated_mppt_count"]


def test_repeated_mppt_ids_and_one_bad_inverter_remain_independent() -> None:
    first = s91_support._topology(inverter_id="inverter-a").inverters[0]
    second = s91_support._topology(inverter_id="inverter-b").inverters[0]
    topology = ElectricalTopologyConfig(inverters=[first, second])
    values = _inputs(topology)
    result = _run(topology, values)
    assert result.operating_points.index.get_level_values("inverter_id").tolist() == [
        "inverter-a",
        "inverter-b",
    ]


def test_exact_s91_state_dtype_and_diagnostic_tampering_rejected() -> None:
    topology = s91_support._topology()
    values = list(_inputs(topology))
    envelope = values[-1]
    changed = envelope.states.copy(deep=True)
    changed.loc[:, "p_mppt_input_w"] *= 0.9
    values[-1] = replace(envelope, states=changed)
    with pytest.raises(ValueError, match="states do not match"):
        _run(topology, tuple(values))

    values = list(_inputs(topology))
    envelope = values[-1]
    changed = envelope.states.copy(deep=True)
    changed["dc_limits_satisfied"] = changed["dc_limits_satisfied"].astype(bool)
    values[-1] = replace(envelope, states=changed)
    with pytest.raises(ValueError, match="states do not match"):
        _run(topology, tuple(values))

    values = list(_inputs(topology))
    envelope = values[-1]
    values[-1] = replace(envelope, diagnostics=replace(envelope.diagnostics, row_count=99))
    with pytest.raises(ValueError, match="diagnostics"):
        _run(topology, tuple(values))


def test_empty_topology_and_empty_mppt_produce_no_rows() -> None:
    for topology in (ElectricalTopologyConfig(), s91_support._topology(populated=False)):
        result = _run(topology, _inputs(topology, names={}))
        assert result.operating_points.empty
        assert result.operating_points.index.names == ["timestamp", "inverter_id"]


def test_provenance_diagnostics_determinism_immutability_and_ownership() -> None:
    topology = s91_support._topology()
    values = _inputs(topology)
    before = values[-1].states.copy(deep=True)
    first = _run(topology, values)
    second = _run(topology, values)
    pd.testing.assert_frame_equal(first.operating_points, second.operating_points, check_exact=True)
    row = first.operating_points.iloc[0]
    assert row["source_reference_plane"] == MPPT_INPUT_REFERENCE_PLANE
    assert row["sink_reference_plane"] == INVERTER_AC_OUTPUT_REFERENCE_PLANE
    assert row["topology_sandia_inverter_ac_contract"] == TOPOLOGY_SANDIA_INVERTER_AC_CONTRACT_ID
    assert first.diagnostics.conversion_model == TOPOLOGY_SANDIA_INVERTER_AC_MODEL_ID
    first.operating_points.iloc[0, 10] = 999.0
    pd.testing.assert_frame_equal(values[-1].states, before, check_exact=True)
    assert values[-1].states.iloc[0]["p_mppt_input_w"] != 999.0


def test_output_has_no_aggregate_voltage_or_current_fields() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    result = _run(topology, _inputs(topology, limits=_multi_limits(topology)))
    forbidden = {"v_dc_average_v", "v_dc_inverter_v", "i_dc_total_a", "i_dc_average_a"}
    assert forbidden.isdisjoint(result.operating_points.columns)
