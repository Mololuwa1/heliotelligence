"""Tests for explicit string states and independent-MPP aggregation."""

from __future__ import annotations

import pandas as pd
import pytest

from heliotelligence.config.site import (
    ElectricalTopologyConfig,
    InverterConfig,
    InverterUnitConfig,
    ModuleConfig,
    MPPTConfig,
    SiteConfig,
    StringConfig,
)
from heliotelligence.physics.electrical import (
    aggregate_independent_string_mppt_power,
    calculate_string_operating_points,
    scale_module_to_string,
)


STRING_STATE_COLUMNS = [
    "timestamp",
    "inverter_id",
    "mppt_id",
    "string_id",
    "zone_id",
    "modules_per_string",
    "p_mp_w",
    "v_mp_v",
    "i_mp_a",
    "effective_irradiance_wm2",
    "tier_used",
    "fit_quality",
]


def _module_point(n: int = 2) -> pd.DataFrame:
    index = pd.date_range("2024-06-21 12:00", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "p_mp_w": [500.0] * n,
            "v_mp_v": [40.0] * n,
            "i_mp_a": [12.5] * n,
            "effective_irradiance_wm2": [900.0] * n,
            "tier_used": [3] * n,
            "fit_quality": ["high"] * n,
        },
        index=index,
    )


def _topology() -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="INV-01",
                mppts=[
                    MPPTConfig(
                        id="MPPT-01",
                        strings=[
                            StringConfig(
                                id="STR-001",
                                modules_per_string=20,
                                zone_id="ZONE-A",
                            ),
                            StringConfig(
                                id="STR-002",
                                modules_per_string=24,
                                zone_id="ZONE-B",
                            ),
                        ],
                    ),
                    MPPTConfig(
                        id="MPPT-02",
                        strings=[
                            StringConfig(id="STR-003", modules_per_string=22),
                        ],
                    ),
                ],
            ),
            InverterUnitConfig(
                id="INV-02",
                mppts=[
                    MPPTConfig(
                        id="MPPT-01",
                        strings=[
                            StringConfig(id="STR-004", modules_per_string=24),
                            StringConfig(id="STR-005", modules_per_string=24),
                        ],
                    ),
                ],
            ),
        ]
    )


def _site(
    topology: ElectricalTopologyConfig | None = None,
) -> SiteConfig:
    return SiteConfig(
        id="string-test",
        name="String Test",
        latitude=52.56,
        longitude=1.21,
        timezone="Europe/London",
        capacity_kwp=1000.0,
        solcast_resource_id="test",
        module=ModuleConfig(pnom_wp=500.0, gamma_pmp=-0.3),
        inverter=InverterConfig(),
        electrical_topology=topology,
    )


def test_module_to_string_scaling_remains_ideal_series_algebra() -> None:
    string_point = scale_module_to_string(_module_point(n=1), modules_per_string=24)

    assert string_point["v_mp_v"].iloc[0] == pytest.approx(24 * 40.0)
    assert string_point["i_mp_a"].iloc[0] == pytest.approx(12.5)
    assert string_point["p_mp_w"].iloc[0] == pytest.approx(24 * 500.0)


def test_string_states_preserve_hierarchy_and_metadata() -> None:
    states = calculate_string_operating_points(_site(_topology()), _module_point())
    first = states.loc[states["string_id"] == "STR-001"].iloc[0]

    assert first["inverter_id"] == "INV-01"
    assert first["mppt_id"] == "MPPT-01"
    assert first["zone_id"] == "ZONE-A"
    assert first["modules_per_string"] == 20
    assert first["effective_irradiance_wm2"] == pytest.approx(900.0)
    assert first["tier_used"] == 3
    assert first["fit_quality"] == "high"


def test_one_state_exists_per_physical_string_per_timestep() -> None:
    module_point = _module_point(n=3)
    states = calculate_string_operating_points(_site(_topology()), module_point)

    assert len(states) == 3 * 5
    assert states.groupby("timestamp")["string_id"].nunique().eq(5).all()
    assert set(states["string_id"]) == {
        "STR-001",
        "STR-002",
        "STR-003",
        "STR-004",
        "STR-005",
    }


def test_duplicate_module_timestamps_are_rejected_without_mutating_input() -> None:
    timestamp = pd.Timestamp("2024-06-21 12:00", tz="UTC")
    module_point = _module_point()
    module_point.index = pd.DatetimeIndex([timestamp, timestamp], name="time")
    original = module_point.copy(deep=True)
    original_index = module_point.index.copy()

    with pytest.raises(
        ValueError,
        match="module_operating_point index must contain unique timestamps",
    ):
        calculate_string_operating_points(_site(_topology()), module_point)

    pd.testing.assert_frame_equal(module_point, original)
    pd.testing.assert_index_equal(module_point.index, original_index)
    assert module_point.index.name == "time"


def test_empty_explicit_topology_returns_declared_schema() -> None:
    topology = ElectricalTopologyConfig(inverters=[])

    states = calculate_string_operating_points(_site(topology), _module_point())

    assert states.empty
    assert states.columns.tolist() == STRING_STATE_COLUMNS


def test_empty_mppt_returns_declared_schema() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="INV-EMPTY",
                mppts=[MPPTConfig(id="MPPT-EMPTY", strings=[])],
            )
        ]
    )

    states = calculate_string_operating_points(_site(topology), _module_point())

    assert states.empty
    assert states.columns.tolist() == STRING_STATE_COLUMNS


def test_empty_module_operating_point_creates_no_string_states() -> None:
    module_point = pd.DataFrame(columns=["p_mp_w", "v_mp_v", "i_mp_a"])

    states = calculate_string_operating_points(_site(_topology()), module_point)

    assert states.empty
    assert states.columns.tolist() == STRING_STATE_COLUMNS[:9]


def test_module_operating_point_and_index_are_not_mutated() -> None:
    module_point = _module_point()
    module_point.index.name = "module_timestamp"
    original = module_point.copy(deep=True)
    original_index = module_point.index.copy()

    calculate_string_operating_points(_site(_topology()), module_point)

    pd.testing.assert_frame_equal(module_point, original)
    pd.testing.assert_index_equal(module_point.index, original_index)
    assert module_point.index.name == "module_timestamp"


def test_string_state_timestamps_preserve_timezone_for_every_string() -> None:
    module_point = _module_point(n=3)
    module_point.index = pd.date_range(
        "2024-06-21 12:00",
        periods=3,
        freq="h",
        tz="Europe/London",
    )

    states = calculate_string_operating_points(_site(_topology()), module_point)

    assert str(states["timestamp"].dt.tz) == "Europe/London"
    for string_id in states["string_id"].unique():
        string_timestamps = states.loc[
            states["string_id"] == string_id,
            "timestamp",
        ]
        assert string_timestamps.tolist() == module_point.index.tolist()


def test_independent_mppt_power_is_sum_of_member_string_mpps() -> None:
    states = calculate_string_operating_points(_site(_topology()), _module_point())
    aggregate = aggregate_independent_string_mppt_power(states)
    expected = states.groupby(
        ["timestamp", "inverter_id", "mppt_id"],
        as_index=False,
        sort=False,
    )["p_mp_w"].sum()

    assert aggregate["p_independent_mp_w"].tolist() == pytest.approx(
        expected["p_mp_w"].tolist()
    )
    assert aggregate[
        ["timestamp", "inverter_id", "mppt_id"]
    ].equals(expected[["timestamp", "inverter_id", "mppt_id"]])


def test_empty_independent_mppt_input_returns_declared_schema() -> None:
    string_states = pd.DataFrame(
        columns=["timestamp", "inverter_id", "mppt_id", "p_mp_w"]
    )

    aggregate = aggregate_independent_string_mppt_power(string_states)

    assert aggregate.empty
    assert aggregate.columns.tolist() == [
        "timestamp",
        "inverter_id",
        "mppt_id",
        "p_independent_mp_w",
    ]


@pytest.mark.parametrize(
    "missing_column",
    ["timestamp", "inverter_id", "mppt_id", "p_mp_w"],
)
def test_independent_mppt_input_requires_complete_schema(
    missing_column: str,
) -> None:
    required_columns = ["timestamp", "inverter_id", "mppt_id", "p_mp_w"]
    string_states = pd.DataFrame(
        columns=[column for column in required_columns if column != missing_column]
    )

    with pytest.raises(ValueError, match=f"missing columns: {missing_column}"):
        aggregate_independent_string_mppt_power(string_states)


def test_uniform_topology_power_matches_total_configured_module_count() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="INV-01",
                mppts=[
                    MPPTConfig(
                        id="MPPT-01",
                        strings=[
                            StringConfig(id=f"STR-{number:03d}", modules_per_string=24)
                            for number in range(1, 5)
                        ],
                    )
                ],
            )
        ]
    )
    states = calculate_string_operating_points(_site(topology), _module_point())

    expected_per_timestep = 500.0 * (4 * 24)
    assert states.groupby("timestamp")["p_mp_w"].sum().tolist() == pytest.approx(
        [expected_per_timestep, expected_per_timestep]
    )


def test_mixed_string_lengths_do_not_invent_common_mppt_voltage_or_current() -> None:
    states = calculate_string_operating_points(_site(_topology()), _module_point(n=1))
    aggregate = aggregate_independent_string_mppt_power(states)
    first_mppt_states = states[
        (states["inverter_id"] == "INV-01") & (states["mppt_id"] == "MPPT-01")
    ]

    assert set(first_mppt_states["modules_per_string"]) == {20, 24}
    assert set(first_mppt_states["v_mp_v"]) == {800.0, 960.0}
    assert set(first_mppt_states["p_mp_w"]) == {10000.0, 12000.0}
    assert set(first_mppt_states["i_mp_a"]) == {12.5}
    assert aggregate.columns.tolist() == [
        "timestamp",
        "inverter_id",
        "mppt_id",
        "p_independent_mp_w",
    ]
    assert "v_mp_v" not in aggregate
    assert "i_mp_a" not in aggregate
    first_mppt_aggregate = aggregate[
        (aggregate["inverter_id"] == "INV-01")
        & (aggregate["mppt_id"] == "MPPT-01")
    ]
    assert first_mppt_aggregate["p_independent_mp_w"].iloc[0] == pytest.approx(
        22000.0
    )


def test_explicit_electrical_topology_is_required() -> None:
    with pytest.raises(ValueError, match="electrical_topology is required"):
        calculate_string_operating_points(_site(), _module_point())
