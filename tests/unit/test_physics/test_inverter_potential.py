"""Tests for S9-3A model-native Sandia pre-limit AC potential."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pvlib.inverter  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter import SandiaInverterParameters
from heliotelligence.physics.inverter_potential import (
    INVERTER_AC_PRE_PACO_LIMIT_REFERENCE_PLANE,
    TOPOLOGY_SANDIA_PRE_LIMIT_AC_CONTRACT_ID,
    TOPOLOGY_SANDIA_PRE_LIMIT_AC_MODEL_ID,
    calculate_sandia_pre_limit_ac_power,
    calculate_topology_sandia_pre_limit_ac,
)

conversion_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_inverter_conversion"
)
s91_support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_topology")
MODEL = conversion_support.MODEL


def _call(
    topology: ElectricalTopologyConfig,
    values: tuple[Any, ...],
    inverter_ac: Any,
) -> Any:
    (
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        cec_sam_name_by_inverter_id,
        inverter_authority,
        mppt_current_limit_by_key,
        inverter_dc_envelope,
    ) = values
    return calculate_topology_sandia_pre_limit_ac(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        cec_sam_name_by_inverter_id,
        inverter_authority,
        mppt_current_limit_by_key,
        inverter_dc_envelope,
        inverter_ac,
    )


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        inverter_lookup, "_load_cec_inverter_database", conversion_support._database
    )
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        conversion_support._database,
    )


def _evaluate(
    topology: ElectricalTopologyConfig,
    *,
    voltage: float = 360.0,
    current: float = 10.0,
    zero: bool = False,
    limits: Any = None,
) -> tuple[tuple[Any, ...], Any, Any]:
    values = conversion_support._inputs(
        topology, voltage=voltage, current=current, zero=zero, limits=limits
    )
    ac = conversion_support._run(topology, values)
    result = _call(topology, values, ac)
    return values, ac, result


def test_single_primitive_matches_pinned_private_oracle() -> None:
    parameters = SandiaInverterParameters(
        paco_w=6000.0,
        pdco_w=6158.0,
        vdco_v=360.0,
        pso_w=36.0,
        c0_per_w=-1e-5,
        c1_per_v=0.0002,
        c2_per_v=0.0001,
        c3_per_v=0.0001,
        pnt_w=1.8,
    )
    index = pd.date_range("2025-01-01", periods=4, tz="UTC")
    voltage = pd.Series([300.0, 360.0, 420.0, 500.0], index=index)
    power = pd.Series([40.0, 1000.0, 5000.0, 8000.0], index=index)
    actual = calculate_sandia_pre_limit_ac_power(voltage, power, parameters)
    expected = pvlib.inverter._sandia_eff(voltage, power, parameters.to_pvlib_dict())
    pd.testing.assert_series_equal(actual, expected, check_exact=True)


def test_single_topology_raw_potential_closes_to_s92() -> None:
    topology = s91_support._topology()
    values, ac, result = _evaluate(topology, current=10.0)
    row = result.operating_points.iloc[0]
    envelope = values[-1].states.iloc[0]
    model = values[-3].sandia_models_by_inverter_id["inverter-1"]
    oracle = pvlib.inverter._sandia_eff(
        envelope["v_mppt_input_v"],
        envelope["p_mppt_input_w"],
        model.parameters.to_pvlib_dict(),
    )
    assert row["p_ac_pre_limit_w"] == pytest.approx(float(oracle))
    assert row["p_ac_available_w"] == ac.operating_points.iloc[0]["p_ac_available_w"]
    assert row["pre_limit_ac_state"] == "resolved_sandia_pre_limit_potential"


def test_multi_input_matches_power_weighted_private_oracle_without_voltage_average() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    limits = conversion_support._multi_limits(topology)
    values, _, result = _evaluate(topology, limits=limits)
    envelope = values[-1].states
    model = values[-3].sandia_models_by_inverter_id["inverter-1"]
    rows = [
        envelope.xs(("inverter-1", mppt), level=("inverter_id", "mppt_id")).iloc[0]
        for mppt in ("mppt-1", "mppt-2")
    ]
    total = sum(float(row["p_mppt_input_w"]) for row in rows)
    expected = sum(
        float(row["p_mppt_input_w"])
        / total
        * float(
            pvlib.inverter._sandia_eff(
                row["v_mppt_input_v"], total, model.parameters.to_pvlib_dict()
            )
        )
        for row in rows
    )
    output = result.operating_points.iloc[0]
    assert output["p_ac_pre_limit_w"] == pytest.approx(expected)
    assert output["sandia_pre_limit_path"] == "sandia_pre_limit_multi_mppt"
    assert not any(
        "voltage" in column or "current" in column for column in result.operating_points.columns
    )


def test_clipping_preserves_raw_above_paco_and_available_at_paco() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    _, ac, result = _evaluate(
        topology, current=10.0, limits=conversion_support._multi_limits(topology)
    )
    row = result.operating_points.iloc[0]
    assert row["would_hit_paco"]
    assert row["p_ac_pre_limit_w"] >= row["paco_w"]
    assert row["p_ac_available_w"] == row["paco_w"]
    assert ac.operating_points.iloc[0]["at_ac_power_limit"]


def test_all_zero_is_resolved_not_applicable_without_raw_evaluation() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    _, _, result = _evaluate(topology, zero=True)
    row = result.operating_points.iloc[0]
    assert row["pre_limit_ac_state"] == ("resolved_pre_limit_not_applicable_below_startup")
    assert not row["pre_limit_ac_applicable"]
    assert row["pre_limit_ac_resolved"]
    assert pd.isna(row["p_ac_pre_limit_w"])
    assert pd.isna(row["would_hit_paco"])


def test_unresolved_s92_propagates_without_counterfactual() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    _, _, result = _evaluate(topology)
    row = result.operating_points.iloc[0]
    assert row["pre_limit_ac_state"] == "unresolved_upstream_sandia_conversion"
    assert not row["pre_limit_ac_resolved"]
    assert pd.isna(row["p_ac_pre_limit_w"])


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("p_ac_available_w", 123.0),
        ("p_dc_inverter_input_w", 123.0),
        ("inverter_conversion_state", "forged"),
        ("at_ac_power_limit", False),
        ("pvlib_version", "forged"),
    ],
)
def test_exact_s92_replay_rejects_tampering(column: str, value: object) -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    limits = conversion_support._multi_limits(topology)
    values = conversion_support._inputs(topology, limits=limits)
    ac = conversion_support._run(topology, values)
    changed = ac.operating_points.copy(deep=True)
    changed.loc[:, column] = value
    with pytest.raises(ValueError, match="do not match canonical replay"):
        _call(topology, values, replace(ac, operating_points=changed))


def test_s92_diagnostics_tamper_rejected() -> None:
    topology = s91_support._topology()
    values = conversion_support._inputs(topology)
    ac = conversion_support._run(topology, values)
    stale = replace(ac, diagnostics=replace(ac.diagnostics, row_count=99))
    with pytest.raises(ValueError, match="diagnostics"):
        _call(topology, values, stale)


def test_empty_topology_and_empty_inverter_are_deterministic() -> None:
    for topology in (ElectricalTopologyConfig(), s91_support._topology(populated=False)):
        values = conversion_support._inputs(topology, names={})
        ac = conversion_support._run(topology, values)
        result = _call(topology, values, ac)
        assert result.operating_points.empty
        assert result.operating_points.index.names == ["timestamp", "inverter_id"]


def test_provenance_diagnostics_ownership_and_no_loss_fields() -> None:
    topology = s91_support._topology()
    values, ac, result = _evaluate(topology)
    row = result.operating_points.iloc[0]
    assert row["potential_reference_plane"] == INVERTER_AC_PRE_PACO_LIMIT_REFERENCE_PLANE
    assert row["topology_sandia_pre_limit_ac_contract"] == TOPOLOGY_SANDIA_PRE_LIMIT_AC_CONTRACT_ID
    assert result.diagnostics.model == TOPOLOGY_SANDIA_PRE_LIMIT_AC_MODEL_ID
    assert result.diagnostics.row_count == (
        result.diagnostics.resolved_count + result.diagnostics.unresolved_count
    )
    assert {"conversion_loss_w", "clipping_loss_w", "total_inverter_loss_w"}.isdisjoint(
        result.operating_points.columns
    )
    result.operating_points.iloc[0, 0] = 999.0
    assert ac.operating_points.iloc[0]["p_dc_inverter_input_w"] != 999.0
    assert values[-1].states.iloc[0]["p_mppt_input_w"] != 999.0


def test_production_source_does_not_reference_pvlib_private_helpers() -> None:
    module = importlib.import_module("heliotelligence.physics.inverter_potential")
    source = inspect.getsource(module)
    assert "._sandia_eff" not in source
    assert "._sandia_limits" not in source
