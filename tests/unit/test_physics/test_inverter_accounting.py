"""Tests for S9-3B Sandia inverter power accounting."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter_accounting import (
    TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_CONTRACT_ID,
    TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_MODEL_ID,
    calculate_topology_sandia_inverter_power_accounting,
)

conversion_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_inverter_conversion"
)
potential_support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_potential")
s91_support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_topology")
MODEL = conversion_support.MODEL


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


def _inputs(
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
    potential = potential_support._call(topology, values, ac)
    return values, ac, potential


def _call(
    topology: ElectricalTopologyConfig,
    values: tuple[Any, ...],
    ac: Any,
    potential: Any,
) -> Any:
    (
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        authority,
        limits,
        envelope,
    ) = values
    return calculate_topology_sandia_inverter_power_accounting(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        authority,
        limits,
        envelope,
        ac,
        potential,
    )


def test_producing_accounting_closes_without_clipping() -> None:
    topology = s91_support._topology()
    values, ac, potential = _inputs(topology, current=5.0)
    result = _call(topology, values, ac, potential)
    row = result.accounting.iloc[0]
    assert row["accounting_state"] == "resolved_sandia_conversion_power_accounting"
    assert row["conversion_clipping_accounting_applicable"]
    assert not row["tare_accounting_applicable"]
    assert row["conversion_loss_w"] >= 0.0
    assert row["conversion_gain_w"] == 0.0
    assert row["clipping_loss_w"] == pytest.approx(0.0)
    assert row["p_dc_inverter_input_w"] + row["conversion_gain_w"] - row["conversion_loss_w"] - row[
        "clipping_loss_w"
    ] == pytest.approx(row["p_ac_available_w"])


def test_clipping_is_strictly_above_paco() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    values, ac, potential = _inputs(topology, limits=conversion_support._multi_limits(topology))
    row = _call(topology, values, ac, potential).accounting.iloc[0]
    assert row["p_ac_pre_limit_w"] > row["paco_w"]
    assert row["clipping_active"]
    assert row["would_hit_paco"]
    assert row["clipping_loss_w"] == pytest.approx(
        row["p_ac_pre_limit_w"] - row["p_ac_available_w"]
    )


def test_below_startup_and_all_zero_use_tare_only() -> None:
    topology = s91_support._topology()
    for current, zero in ((0.05, False), (10.0, True)):
        values, ac, potential = _inputs(topology, current=current, zero=zero)
        row = _call(topology, values, ac, potential).accounting.iloc[0]
        assert row["accounting_state"] == "resolved_sandia_below_startup_tare_accounting"
        assert row["tare_accounting_applicable"]
        assert not row["conversion_clipping_accounting_applicable"]
        assert row["sandia_tare_ac_consumption_w"] == row["pnt_w"]
        assert pd.isna(row["conversion_loss_w"])
        assert pd.isna(row["clipping_active"])
        assert row["net_dc_to_available_ac_delta_w"] == pytest.approx(
            row["p_dc_inverter_input_w"] - row["p_ac_available_w"]
        )


def test_exact_startup_uses_conversion_accounting() -> None:
    topology = s91_support._topology()
    values, ac, potential = _inputs(topology, voltage=360.0, current=0.1)
    row = _call(topology, values, ac, potential).accounting.iloc[0]
    assert row["p_dc_inverter_input_w"] == row["pso_w"]
    assert row["conversion_clipping_accounting_applicable"]
    assert not row["tare_accounting_applicable"]


def test_negative_above_startup_is_conversion_not_tare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def strong_database() -> pd.DataFrame:
        data = conversion_support._database()
        data.loc["C2", MODEL] = 0.01
        return data

    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", strong_database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", strong_database)
    topology = s91_support._topology()
    values, ac, potential = _inputs(topology, voltage=400.0, current=0.1)
    row = _call(topology, values, ac, potential).accounting.iloc[0]
    assert row["p_ac_pre_limit_w"] < -row["pnt_w"]
    assert row["pre_limit_ac_negative"]
    assert not row["tare_accounting_applicable"]
    assert row["sandia_tare_ac_consumption_w"] == 0.0
    assert row["conversion_loss_w"] == pytest.approx(
        row["p_dc_inverter_input_w"] - row["p_ac_pre_limit_w"]
    )
    assert row["conversion_loss_w"] > row["p_dc_inverter_input_w"]
    assert row["conversion_gain_w"] == 0.0
    assert row["clipping_loss_w"] == 0.0


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("p_dc_inverter_input_w", 123.0),
        ("p_ac_pre_limit_w", 123.0),
        ("p_ac_available_w", 123.0),
        ("paco_w", 123.0),
        ("pso_w", 123.0),
        ("pnt_w", 123.0),
        ("pre_limit_ac_applicable", False),
        ("pre_limit_ac_resolved", False),
        ("would_hit_paco", True),
        ("pre_limit_ac_exceeds_dc_input", True),
        ("pre_limit_ac_state", "forged"),
    ],
)
def test_exact_s93a_replay_rejects_tampering(column: str, value: object) -> None:
    topology = s91_support._topology()
    values, ac, potential = _inputs(topology)
    changed = potential.operating_points.copy(deep=True)
    changed.loc[:, column] = value
    with pytest.raises(ValueError, match="canonical replay"):
        _call(topology, values, ac, replace(potential, operating_points=changed))


def test_s93a_diagnostics_tamper_rejected() -> None:
    topology = s91_support._topology()
    values, ac, potential = _inputs(topology)
    changed = replace(potential, diagnostics=replace(potential.diagnostics, row_count=99))
    with pytest.raises(ValueError, match="diagnostics"):
        _call(topology, values, ac, changed)


def test_unresolved_upstream_remains_unresolved() -> None:
    topology = s91_support._topology(("mppt-1", "mppt-2"))
    values, ac, potential = _inputs(topology)
    row = _call(topology, values, ac, potential).accounting.iloc[0]
    assert not row["accounting_resolved"]
    assert row["accounting_state"] == "unresolved_upstream_sandia_power_accounting"
    assert pd.isna(row["conversion_loss_w"])
    assert pd.isna(row["net_dc_to_available_ac_delta_w"])


def test_empty_topology_and_empty_inverter() -> None:
    for topology in (ElectricalTopologyConfig(), s91_support._topology(populated=False)):
        values = conversion_support._inputs(topology, names={})
        ac = conversion_support._run(topology, values)
        potential = potential_support._call(topology, values, ac)
        result = _call(topology, values, ac, potential)
        assert result.accounting.empty
        assert result.accounting.index.names == ["timestamp", "inverter_id"]


def test_provenance_diagnostics_ownership_and_no_forbidden_fields() -> None:
    topology = s91_support._topology()
    values, ac, potential = _inputs(topology)
    result = _call(topology, values, ac, potential)
    row = result.accounting.iloc[0]
    assert row["topology_sandia_inverter_accounting_contract"] == (
        TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_CONTRACT_ID
    )
    assert result.diagnostics.model == TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_MODEL_ID
    assert result.diagnostics.row_count == (
        result.diagnostics.resolved_count + result.diagnostics.unresolved_count
    )
    assert {"total_inverter_loss_w", "energy_wh", "v_dc_inverter_v", "i_dc_total_a"}.isdisjoint(
        result.accounting.columns
    )
    result.accounting.iloc[0, 0] = 999.0
    assert potential.operating_points.iloc[0]["p_dc_inverter_input_w"] != 999.0


def test_production_module_has_no_pvlib_or_sandia_polynomial() -> None:
    module = importlib.import_module("heliotelligence.physics.inverter_accounting")
    source = inspect.getsource(module)
    assert "import pvlib" not in source
    assert "_sandia_eff" not in source
    assert "sandia_multi" not in source
    assert "pdco_w" not in source
