"""Tests for S9-4C explicit inverter thermal-derating authority."""

from __future__ import annotations

import importlib
import inspect
import math
from dataclasses import FrozenInstanceError, dataclass

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import (
    ElectricalTopologyConfig,
    InverterUnitConfig,
    MPPTConfig,
    StringConfig,
)
from heliotelligence.physics.inverter_thermal_authority import (
    TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_MODEL_ID,
    TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_SCOPE,
    InverterThermalDeratingAuthority,
    resolve_topology_inverter_thermal_derating_authority,
)


def _topology(*ids: str) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inverter_id,
                group_id="misleading-group",
                model_ref="misleading-model",
                mppts=[
                    MPPTConfig(
                        id="mppt-1",
                        strings=[StringConfig(id=f"string-{inverter_id}", modules_per_string=24)],
                    )
                ],
            )
            for inverter_id in ids
        ]
    )


def _authority(**changes: object) -> InverterThermalDeratingAuthority:
    values: dict[str, object] = {
        "temperature_quantity": "ambient_air",
        "derating_mode": "piecewise_linear_limits",
        "temperature_points_c": (40.0, 45.0, 50.0),
        "active_power_limit_w": (100000.0, 95000.0, 85000.0),
        "parameter_source": "manufacturer_datasheet",
        "confidence": "high",
    }
    values.update(changes)
    return InverterThermalDeratingAuthority(**values)  # type: ignore[arg-type]


def test_explicit_no_derating_is_resolved_and_distinct_from_missing() -> None:
    authority = InverterThermalDeratingAuthority(
        temperature_quantity="ambient_air",
        derating_mode="explicit_no_derating",
        temperature_points_c=(-20.0, 45.0),
        parameter_source="manufacturer_datasheet",
        confidence="high",
    )
    result = resolve_topology_inverter_thermal_derating_authority(
        _topology("resolved", "missing"), {"resolved": authority}
    )
    resolved = result.states.loc["resolved"]
    missing = result.states.loc["missing"]
    assert resolved["thermal_derating_authority_state"] == (
        "resolved_explicit_no_thermal_derating_authority"
    )
    assert resolved["temperature_points_c"] == (-20.0, 45.0)
    assert resolved["interpolation_model"] == "not_applicable"
    assert all(
        resolved[column] == ()
        for column in (
            "active_power_limit_w_curve",
            "apparent_power_limit_va_curve",
            "reactive_power_min_var_curve",
            "reactive_power_max_var_curve",
        )
    )
    assert not resolved["active_power_thermal_limit_resolved"]
    assert missing["thermal_derating_authority_state"] == (
        "unresolved_no_explicit_inverter_thermal_derating_authority"
    )
    assert not missing["thermal_derating_authority_resolved"]
    assert math.isnan(missing["temperature_min_c"])


@pytest.mark.parametrize(
    ("curves", "flags"),
    [
        ({"active_power_limit_w": (10.0, 8.0)}, (True, False, False)),
        (
            {"active_power_limit_w": None, "apparent_power_limit_va": (12.0, 9.0)},
            (False, True, False),
        ),
        (
            {
                "active_power_limit_w": None,
                "reactive_power_min_var": (-4.0, -2.0),
                "reactive_power_max_var": (3.0, 1.0),
            },
            (False, False, True),
        ),
    ],
)
def test_partial_channel_authorities_resolve(
    curves: dict[str, object], flags: tuple[bool, bool, bool]
) -> None:
    authority = _authority(temperature_points_c=(0.0, 60.0), **curves)
    row = resolve_topology_inverter_thermal_derating_authority(
        _topology("i"), {"i": authority}
    ).states.iloc[0]
    assert tuple(
        bool(row[column])
        for column in (
            "active_power_thermal_limit_resolved",
            "apparent_power_thermal_limit_resolved",
            "reactive_power_thermal_limits_resolved",
        )
    ) == flags


def test_multichannel_exact_replay_and_provenance() -> None:
    authority = _authority(
        apparent_power_limit_va=(110000.0, 105000.0, 90000.0),
        reactive_power_min_var=(-40000.0, -35000.0, -20000.0),
        reactive_power_max_var=(40000.0, 35000.0, 20000.0),
    )
    result = resolve_topology_inverter_thermal_derating_authority(
        _topology("i"), {"i": authority}
    )
    row = result.states.iloc[0]
    assert row["active_power_limit_w_curve"] == authority.active_power_limit_w
    assert row["apparent_power_limit_va_curve"] == authority.apparent_power_limit_va
    assert row["reactive_power_min_var_curve"] == authority.reactive_power_min_var
    assert row["reactive_power_max_var_curve"] == authority.reactive_power_max_var
    assert row["temperature_min_c"] == 40.0
    assert row["temperature_max_c"] == 50.0
    assert row["temperature_point_count"] == 3
    assert row["interpolation_model"] == "linear"
    assert row["outside_domain_policy"] == "unresolved"
    assert row["topology_inverter_thermal_derating_authority_contract"] == (
        TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_CONTRACT_ID
    )
    assert row["topology_inverter_thermal_derating_authority_model"] == (
        TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_MODEL_ID
    )
    assert row["topology_inverter_thermal_derating_authority_scope"] == (
        TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_SCOPE
    )
    assert row["topology_inverter_thermal_derating_authority_coverage_scope"] == (
        TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_COVERAGE_SCOPE
    )


def test_zero_limits_asymmetric_q_flat_and_nonmonotonic_are_valid() -> None:
    assert _authority(active_power_limit_w=(0.0, 8.0, 0.0))
    assert _authority(
        active_power_limit_w=None,
        apparent_power_limit_va=(0.0, 0.0, 0.0),
        reactive_power_min_var=(0.0, 0.0, 0.0),
        reactive_power_max_var=(0.0, 0.0, 0.0),
    )
    assert _authority(active_power_limit_w=(10.0, 10.0, 10.0))
    assert _authority(active_power_limit_w=(10.0, 8.0, 9.0))


@pytest.mark.parametrize(
    "points",
    [
        (1.0,),
        (1.0, 1.0),
        (2.0, 1.0),
        (0.0, float("nan")),
        (0.0, float("inf")),
        (False, 1.0),
        [0.0, 1.0],
    ],
)
def test_invalid_temperature_grids_are_rejected(points: object) -> None:
    with pytest.raises(ValueError):
        _authority(temperature_points_c=points, active_power_limit_w=(1.0, 1.0))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"active_power_limit_w": (1.0,)}, "align"),
        ({"active_power_limit_w": (True, 1.0, 1.0)}, "non-Boolean"),
        ({"active_power_limit_w": (1.0, float("nan"), 1.0)}, "finite"),
        ({"active_power_limit_w": (1.0, float("inf"), 1.0)}, "finite"),
        ({"active_power_limit_w": (1.0, -1.0, 1.0)}, "non-negative"),
        (
            {"active_power_limit_w": None, "apparent_power_limit_va": (1.0, -1.0, 1.0)},
            "non-negative",
        ),
        ({"reactive_power_min_var": (-1.0, -1.0, -1.0)}, "both"),
        (
            {
                "active_power_limit_w": None,
                "reactive_power_min_var": (1.0, 1.0, 1.0),
                "reactive_power_max_var": (0.0, 0.0, 0.0),
            },
            "minimum",
        ),
        (
            {
                "active_power_limit_w": (2.0, 2.0, 2.0),
                "apparent_power_limit_va": (1.0, 1.0, 1.0),
            },
            "active-power",
        ),
        (
            {
                "active_power_limit_w": None,
                "apparent_power_limit_va": (1.0, 1.0, 1.0),
                "reactive_power_min_var": (-2.0, 0.0, 0.0),
                "reactive_power_max_var": (0.0, 0.0, 0.0),
            },
            "magnitude",
        ),
    ],
)
def test_invalid_curves_are_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _authority(**changes)


def test_modes_and_string_metadata_are_validated() -> None:
    with pytest.raises(ValueError, match="temperature_quantity"):
        _authority(temperature_quantity=" ")
    with pytest.raises(ValueError, match="parameter_source"):
        _authority(parameter_source="")
    with pytest.raises(ValueError, match="confidence"):
        _authority(confidence="certain")
    with pytest.raises(ValueError, match="derating_mode"):
        _authority(derating_mode="quadratic")
    with pytest.raises(ValueError, match="at least one"):
        _authority(active_power_limit_w=None)
    with pytest.raises(ValueError, match="exactly two"):
        _authority(derating_mode="explicit_no_derating", active_power_limit_w=None)
    with pytest.raises(ValueError, match="must not contain"):
        _authority(
            derating_mode="explicit_no_derating",
            temperature_points_c=(0.0, 1.0),
            active_power_limit_w=(1.0, 1.0),
        )


def test_topology_and_mapping_order_are_canonical() -> None:
    topology = _topology("b", "a")
    mapping = {"a": _authority(), "b": _authority(temperature_quantity="heatsink")}
    first = resolve_topology_inverter_thermal_derating_authority(topology, mapping)
    second = resolve_topology_inverter_thermal_derating_authority(
        topology, dict(reversed(list(mapping.items())))
    )
    assert first.states.index.tolist() == ["b", "a"]
    pd.testing.assert_frame_equal(first.states, second.states, check_exact=True)
    assert first.diagnostics == second.diagnostics


def test_unexpected_and_nonexact_authorities_are_rejected() -> None:
    with pytest.raises(ValueError, match="unexpected"):
        resolve_topology_inverter_thermal_derating_authority(_topology("a"), {"z": _authority()})
    with pytest.raises(TypeError, match="exact authority type"):
        resolve_topology_inverter_thermal_derating_authority(
            _topology("a"), {"a": {"temperature_quantity": "ambient_air"}}  # type: ignore[dict-item]
        )

    @dataclass(frozen=True)
    class Lookalike:
        temperature_quantity: str = "ambient_air"

    with pytest.raises(TypeError, match="exact authority type"):
        resolve_topology_inverter_thermal_derating_authority(
            _topology("a"), {"a": Lookalike()}  # type: ignore[dict-item]
        )

    @dataclass(frozen=True)
    class AuthoritySubclass(InverterThermalDeratingAuthority):
        pass

    subclass = AuthoritySubclass(
        temperature_quantity="ambient_air",
        derating_mode="piecewise_linear_limits",
        temperature_points_c=(0.0, 1.0),
        active_power_limit_w=(1.0, 1.0),
        parameter_source="datasheet",
    )
    with pytest.raises(TypeError, match="exact authority type"):
        resolve_topology_inverter_thermal_derating_authority(
            _topology("a"), {"a": subclass}
        )


def test_empty_schema_dtypes_diagnostics_and_ownership() -> None:
    empty = resolve_topology_inverter_thermal_derating_authority(
        ElectricalTopologyConfig(), {}
    )
    populated = resolve_topology_inverter_thermal_derating_authority(
        _topology("i"), {"i": _authority()}
    )
    assert empty.states.index.names == ["inverter_id"]
    assert empty.states.dtypes.to_dict() == populated.states.dtypes.to_dict()
    assert empty.diagnostics.inverter_count == 0
    assert empty.diagnostics.resolved_inverter_count == 0
    with pytest.raises(TypeError):
        empty.authorities_by_inverter_id["i"] = _authority()  # type: ignore[index]

    authority = _authority()
    first = resolve_topology_inverter_thermal_derating_authority(
        _topology("i"), {"i": authority}
    )
    second = resolve_topology_inverter_thermal_derating_authority(
        _topology("i"), {"i": authority}
    )
    first.states.loc["i", "temperature_quantity"] = "mutated"
    assert second.states.loc["i", "temperature_quantity"] == "ambient_air"
    assert authority.temperature_quantity == "ambient_air"
    with pytest.raises(FrozenInstanceError):
        authority.temperature_quantity = "mutated"  # type: ignore[misc]


def test_diagnostics_close_without_overlapping_channel_assumption() -> None:
    no_derating = InverterThermalDeratingAuthority(
        temperature_quantity="ambient_air",
        derating_mode="explicit_no_derating",
        temperature_points_c=(-40.0, 85.0),
        parameter_source="datasheet",
    )
    result = resolve_topology_inverter_thermal_derating_authority(
        _topology("all", "none", "missing"),
        {
            "all": _authority(
                apparent_power_limit_va=(110000.0, 105000.0, 90000.0),
                reactive_power_min_var=(-1000.0, -1000.0, -1000.0),
                reactive_power_max_var=(1000.0, 1000.0, 1000.0),
            ),
            "none": no_derating,
        },
    )
    d = result.diagnostics
    assert d.resolved_inverter_count + d.unresolved_inverter_count == d.inverter_count == 3
    assert d.explicit_no_derating_authority_count + d.piecewise_derating_authority_count == 2
    assert d.active_power_limit_authority_count == 1
    assert d.apparent_power_limit_authority_count == 1
    assert d.reactive_power_limit_authority_count == 1


def test_no_inference_or_operating_physics_dependencies() -> None:
    result = resolve_topology_inverter_thermal_derating_authority(_topology("i"), {})
    assert not result.states.iloc[0]["thermal_derating_authority_resolved"]
    module = importlib.import_module("heliotelligence.physics.inverter_thermal_authority")
    source = inspect.getsource(module)
    assert "heliotelligence.physics.thermal" not in source
    assert "import pvlib" not in source
    assert "np.interp" not in source
    for forbidden in ("calculate_cell_temp", "retrieve_sam", "limit_at_temperature"):
        assert forbidden not in source
    columns = " ".join(result.states.columns)
    for forbidden in ("timestamp", "thermal_loss", "ac_current", "dispatch"):
        assert forbidden not in columns
