"""Physics-contract tests for receiver-resolved direct-beam shading coupling."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

import heliotelligence.physics.direct_beam_shading as coupling
from heliotelligence.physics.direct_beam_shading import (
    calculate_direct_beam_shading,
)
from heliotelligence.physics.iam import calculate_beam_iam
from heliotelligence.physics.irradiance_components import (
    resolve_horizontal_irradiance_components,
)
from heliotelligence.physics.poa_transposition import calculate_raw_poa_transposition
from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility,
    solar_direction_enu,
)
from heliotelligence.physics.solar_geometry import calculate_solar_geometry

OUTPUT_COLUMNS = [
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "beam_visible_fraction",
    "beam_shaded_fraction",
    "poa_direct_visible_wm2",
    "poa_direct_shading_loss_wm2",
    "sample_count",
    "shaded_sample_count",
    "beam_visibility_resolved",
    "beam_shading_resolved",
    "beam_shading_applied",
    "beam_shading_state",
    "beam_shading_model",
]


def _horizontal(
    surface_id: str,
    *,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    span_u: float = 2.0,
    span_v: float = 2.0,
) -> RectangularSurface3D:
    return RectangularSurface3D(
        id=surface_id,
        center_enu_m=center,
        u_axis_enu=(1.0, 0.0, 0.0),
        v_axis_enu=(0.0, 1.0, 0.0),
        span_u_m=span_u,
        span_v_m=span_v,
    )


def _index(*times: str, name: str = "physical_time") -> pd.DatetimeIndex:
    values = times or ("2026-06-21 12:00",)
    return pd.DatetimeIndex(values, tz="Europe/London", name=name)


def _calculate(
    raw: pd.DataFrame | None = None,
    zenith: pd.Series | None = None,
    azimuth: pd.Series | None = None,
    *,
    surfaces: list[RectangularSurface3D] | None = None,
    samples_u: int = 10,
    samples_v: int = 2,
) -> pd.DataFrame:
    index = _index() if raw is None else raw.index
    raw = pd.DataFrame({"receiver": [800.0]}, index=index) if raw is None else raw
    zenith = pd.Series(0.0, index=index) if zenith is None else zenith
    azimuth = pd.Series(0.0, index=index) if azimuth is None else azimuth
    surfaces = [_horizontal("receiver")] if surfaces is None else surfaces
    return calculate_direct_beam_shading(
        raw,
        zenith,
        azimuth,
        surfaces=surfaces,
        samples_u=samples_u,
        samples_v=samples_v,
    )


def test_no_occluder_preserves_direct_beam() -> None:
    result = _calculate()
    row = result.iloc[0]
    assert row["beam_visible_fraction"] == 1.0
    assert row["beam_shaded_fraction"] == 0.0
    assert row["poa_direct_visible_wm2"] == 800.0
    assert row["poa_direct_shading_loss_wm2"] == 0.0
    assert bool(row["beam_visibility_resolved"])
    assert bool(row["beam_shading_resolved"])
    assert bool(row["beam_shading_applied"])
    assert row["beam_shading_state"] == "resolved"


def test_full_occluder_removes_all_direct_beam() -> None:
    result = _calculate(
        surfaces=[_horizontal("receiver"), _horizontal("cover", center=(0, 0, 1))]
    )
    row = result.iloc[0]
    assert row["beam_visible_fraction"] == 0.0
    assert row["beam_shaded_fraction"] == 1.0
    assert row["poa_direct_visible_wm2"] == 0.0
    assert row["poa_direct_shading_loss_wm2"] == 800.0


def test_half_occluder_couples_exact_cell_centre_fraction() -> None:
    result = _calculate(
        surfaces=[
            _horizontal("receiver"),
            _horizontal("half", center=(0.5, 0, 1), span_u=1.0),
        ]
    )
    row = result.iloc[0]
    assert row["sample_count"] == 20
    assert row["shaded_sample_count"] == 10
    assert row["beam_visible_fraction"] == 0.5
    assert row["beam_shaded_fraction"] == 0.5
    assert row["poa_direct_visible_wm2"] == 400.0
    assert row["poa_direct_shading_loss_wm2"] == 400.0


def test_receivers_can_have_different_geometry_and_raw_direct() -> None:
    index = _index()
    raw = pd.DataFrame({"clear": [900.0], "shaded": [600.0]}, index=index)
    surfaces = [
        _horizontal("clear", center=(4, 0, 0)),
        _horizontal("shaded"),
        _horizontal("cover", center=(0, 0, 1)),
    ]
    result = _calculate(raw, surfaces=surfaces)
    assert result.index.get_level_values("receiver_id").tolist() == ["clear", "shaded"]
    assert result.loc[(index[0], "clear"), "poa_direct_visible_wm2"] == 900.0
    assert result.loc[(index[0], "shaded"), "poa_direct_visible_wm2"] == 0.0


def test_receiver_specific_raw_direct_is_never_replicated() -> None:
    index = _index()
    raw = pd.DataFrame({"a": [700.0], "b": [350.0]}, index=index)
    result = _calculate(
        raw,
        surfaces=[_horizontal("a", center=(-3, 0, 0)), _horizontal("b", center=(3, 0, 0))],
    )
    assert result["beam_visible_fraction"].tolist() == [1.0, 1.0]
    assert result["poa_direct_visible_wm2"].tolist() == [700.0, 350.0]


def test_sun_direction_is_evaluated_independently_per_timestamp() -> None:
    index = _index("2026-06-21 09:00", "2026-06-21 15:00")
    raw = pd.DataFrame({"receiver": [500.0, 500.0]}, index=index)
    zenith = pd.Series([45.0, 45.0], index=index)
    azimuth = pd.Series([90.0, 270.0], index=index)
    surfaces = [_horizontal("receiver"), _horizontal("object", center=(1, 0, 1))]
    result = _calculate(raw, zenith, azimuth, surfaces=surfaces)
    assert result["beam_visible_fraction"].tolist() == [0.0, 1.0]
    assert result["poa_direct_visible_wm2"].tolist() == [0.0, 500.0]


@pytest.mark.parametrize("zenith_value", [90.0, 120.0])
def test_at_or_below_horizon_states_do_not_call_geometry(
    zenith_value: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = _index()

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("geometry must not run")

    monkeypatch.setattr(coupling, "calculate_direct_beam_visibility", unexpected)
    for raw_value, state, resolved, expected in (
        (0.0, "no_above_horizon_direct_beam", True, 0.0),
        (np.nan, "no_above_horizon_direct_beam_irradiance_unresolved", False, np.nan),
        (20.0, "inconsistent_below_horizon_direct_irradiance", False, np.nan),
    ):
        raw = pd.DataFrame({"receiver": [raw_value]}, index=index)
        result = _calculate(raw, pd.Series(zenith_value, index=index))
        row = result.iloc[0]
        assert row["beam_shading_state"] == state
        assert bool(row["beam_visibility_resolved"]) is False
        assert bool(row["beam_shading_resolved"]) is resolved
        assert bool(row["beam_shading_applied"]) is False
        assert pd.isna(row["beam_visible_fraction"])
        assert pd.isna(row["sample_count"])
        if np.isnan(expected):
            assert pd.isna(row["poa_direct_visible_wm2"])
            assert pd.isna(row["poa_direct_shading_loss_wm2"])
        else:
            assert row["poa_direct_visible_wm2"] == expected
            assert row["poa_direct_shading_loss_wm2"] == expected
        assert row["beam_shading_model"] == "not_applied"


def test_above_horizon_missing_irradiance_still_resolves_geometry() -> None:
    index = _index()
    raw = pd.DataFrame({"receiver": [np.nan]}, index=index)
    result = _calculate(
        raw,
        surfaces=[
            _horizontal("receiver"),
            _horizontal("half", center=(0.5, 0, 1), span_u=1),
        ],
    )
    row = result.iloc[0]
    assert row["beam_visible_fraction"] == 0.5
    assert row["beam_shaded_fraction"] == 0.5
    assert bool(row["beam_visibility_resolved"])
    assert not bool(row["beam_shading_resolved"])
    assert not bool(row["beam_shading_applied"])
    assert row["beam_shading_state"] == "geometry_resolved_irradiance_unresolved"
    assert pd.isna(row["poa_direct_visible_wm2"])


def test_reference_kernel_geometry_is_preserved_exactly() -> None:
    index = _index()
    receivers = ["clear", "half"]
    surfaces = [
        _horizontal("clear", center=(4, 0, 0)),
        _horizontal("half"),
        _horizontal("object", center=(0.5, 0, 1), span_u=1),
    ]
    raw = pd.DataFrame({"clear": [500.0], "half": [500.0]}, index=index)
    reference = calculate_direct_beam_visibility(
        surfaces,
        receivers,
        solar_zenith_deg=0.0,
        solar_azimuth_deg=0.0,
        samples_u=10,
        samples_v=2,
    )
    result = _calculate(raw, surfaces=surfaces)
    for position, receiver in enumerate(receivers):
        row = result.loc[(index[0], receiver)]
        expected = reference.iloc[position]
        assert row["beam_visible_fraction"] == expected["visible_fraction"]
        assert row["beam_shaded_fraction"] == expected["shaded_fraction"]
        assert row["sample_count"] == expected["sample_count"]
        assert row["shaded_sample_count"] == expected["shaded_sample_count"]


def test_fraction_and_energy_conservation() -> None:
    index = _index()
    raw = pd.DataFrame({"receiver": [0.0]}, index=index)
    result = _calculate(
        raw,
        surfaces=[
            _horizontal("receiver"),
            _horizontal("half", center=(0.5, 0, 1), span_u=1),
        ],
    )
    assert np.allclose(
        result["beam_visible_fraction"] + result["beam_shaded_fraction"], 1.0
    )
    assert np.allclose(
        result["poa_direct_visible_wm2"]
        + result["poa_direct_shading_loss_wm2"],
        result["poa_direct_raw_wm2"],
    )
    assert result["poa_direct_visible_wm2"].iloc[0] == 0.0
    assert result["poa_direct_shading_loss_wm2"].iloc[0] == 0.0
    assert (result["shaded_sample_count"] <= result["sample_count"]).all()


def test_irregular_unsorted_timestamps_and_receiver_order_are_preserved() -> None:
    index = _index("2026-06-21 14:17", "2026-06-21 09:03")
    raw = pd.DataFrame({"z-receiver": [1.0, 2.0], "a-receiver": [3.0, 4.0]}, index=index)
    result = _calculate(
        raw,
        surfaces=[_horizontal("z-receiver"), _horizontal("a-receiver", center=(4, 0, 0))],
    )
    expected = [
        (index[0], "z-receiver"),
        (index[0], "a-receiver"),
        (index[1], "z-receiver"),
        (index[1], "a-receiver"),
    ]
    assert result.index.tolist() == expected
    assert result.index.names == ["physical_time", "receiver_id"]
    assert result.index.levels[0].tz == index.tz
    assert result["poa_direct_raw_wm2"].tolist() == [1.0, 3.0, 2.0, 4.0]


def test_equal_indexes_with_different_frequency_metadata_are_accepted() -> None:
    canonical = pd.date_range("2026-06-21 10:00", periods=2, freq="h", tz="UTC", name="time")
    without_frequency = pd.DatetimeIndex(list(canonical), name="time")
    raw = pd.DataFrame({"receiver": [1.0, 2.0]}, index=canonical)
    result = _calculate(
        raw,
        pd.Series([20.0, 30.0], index=without_frequency),
        pd.Series([100.0, 120.0], index=without_frequency),
    )
    assert result.index.get_level_values(0).tolist() == list(canonical)


def test_empty_input_has_stable_typed_schema_and_does_not_call_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = pd.DatetimeIndex([], tz="UTC", name="physical_time")
    raw = pd.DataFrame({"b": pd.Series(dtype=float), "a": pd.Series(dtype=float)}, index=index)

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("geometry must not run")

    monkeypatch.setattr(coupling, "calculate_direct_beam_visibility", unexpected)
    result = _calculate(
        raw,
        pd.Series(dtype=float, index=index),
        pd.Series(dtype=float, index=index),
        surfaces=[_horizontal("b"), _horizontal("a")],
    )
    assert result.columns.tolist() == OUTPUT_COLUMNS
    assert result.empty
    assert result.index.names == ["physical_time", "receiver_id"]
    assert result.index.levels[0].tz == index.tz
    assert result.index.levels[1].tolist() == ["b", "a"]
    assert result.dtypes.iloc[:7].eq("float64").all()
    assert result.dtypes.iloc[7:9].astype(str).eq("Int64").all()
    assert result.dtypes.iloc[9:12].eq("bool").all()
    assert result.dtypes.iloc[12:].astype(str).eq("string").all()


@pytest.mark.parametrize("bad", [None, [], pd.Series([1.0])])
def test_raw_direct_requires_dataframe(bad: object) -> None:
    with pytest.raises(ValueError, match="pandas DataFrame"):
        calculate_direct_beam_shading(  # type: ignore[arg-type]
            bad,
            pd.Series(dtype=float),
            pd.Series(dtype=float),
            surfaces=[],
        )


def test_at_least_one_unique_nonempty_string_receiver_is_required() -> None:
    index = _index()
    for columns, message in (
        ([], "contain receivers"),
        ([1], "non-empty strings"),
        ([""], "non-empty strings"),
        (["receiver", "receiver"], "unique"),
    ):
        raw = pd.DataFrame([[1.0] * len(columns)], index=index, columns=columns)
        with pytest.raises(ValueError, match=message):
            _calculate(raw)


def test_scene_is_validated_for_empty_and_night_inputs() -> None:
    index = pd.DatetimeIndex([], tz="UTC", name="time")
    raw = pd.DataFrame({"receiver": pd.Series(dtype=float)}, index=index)
    empty_series = pd.Series(dtype=float, index=index)
    cases: list[tuple[object, str]] = [
        ("scene", "sequence"),
        ([object()], "RectangularSurface3D"),
        ([_horizontal("other")], "every receiver"),
        ([_horizontal("receiver"), _horizontal("receiver")], "unique IDs"),
    ]
    for surfaces, message in cases:
        with pytest.raises(ValueError, match=message):
            calculate_direct_beam_shading(
                raw,
                empty_series,
                empty_series,
                surfaces=surfaces,  # type: ignore[arg-type]
            )


@pytest.mark.parametrize("bad", [-1.0, True, "1", np.inf, -np.inf])
def test_invalid_present_raw_direct_is_rejected(bad: object) -> None:
    index = _index()
    with pytest.raises(ValueError, match="poa_direct_raw_wm2"):
        _calculate(pd.DataFrame({"receiver": [bad]}, index=index))


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("zenith", -0.1),
        ("zenith", 180.1),
        ("zenith", np.nan),
        ("zenith", np.inf),
        ("zenith", True),
        ("azimuth", -0.1),
        ("azimuth", 360.0),
        ("azimuth", np.nan),
        ("azimuth", np.inf),
        ("azimuth", False),
    ],
)
def test_invalid_geometry_values_are_rejected(field: str, bad: object) -> None:
    index = _index()
    zenith = pd.Series([bad if field == "zenith" else 30.0], index=index)
    azimuth = pd.Series([bad if field == "azimuth" else 180.0], index=index)
    with pytest.raises(ValueError, match="solar"):
        _calculate(zenith=zenith, azimuth=azimuth)


@pytest.mark.parametrize("field", ["zenith", "azimuth"])
def test_solar_inputs_require_series(field: str) -> None:
    index = _index()
    raw = pd.DataFrame({"receiver": [1.0]}, index=index)
    zenith: object = [30.0] if field == "zenith" else pd.Series([30.0], index=index)
    azimuth: object = [180.0] if field == "azimuth" else pd.Series([180.0], index=index)
    with pytest.raises(ValueError, match="pandas Series"):
        calculate_direct_beam_shading(
            raw,
            zenith,  # type: ignore[arg-type]
            azimuth,  # type: ignore[arg-type]
            surfaces=[_horizontal("receiver")],
        )


@pytest.mark.parametrize("series_name", ["zenith", "azimuth"])
@pytest.mark.parametrize(
    "defect", ["naive", "nat", "duplicate", "values", "name", "timezone"]
)
def test_index_contract_rejects_invalid_or_mismatched_indexes(
    defect: str, series_name: str
) -> None:
    canonical = _index("2026-06-21 10:00", "2026-06-21 11:00")
    raw_index = canonical
    other = canonical
    if defect == "naive":
        other = canonical.tz_localize(None)
    elif defect == "nat":
        other = pd.DatetimeIndex([canonical[0], pd.NaT], name=canonical.name)
    elif defect == "duplicate":
        other = pd.DatetimeIndex([canonical[0], canonical[0]], name=canonical.name)
    elif defect == "values":
        other = _index("2026-06-21 10:00", "2026-06-21 12:00")
    elif defect == "name":
        other = canonical.rename("different")
    elif defect == "timezone":
        other = canonical.tz_convert("UTC")
    raw = pd.DataFrame({"receiver": [1.0, 2.0]}, index=raw_index)
    zenith_index = other if series_name == "zenith" else canonical
    azimuth_index = other if series_name == "azimuth" else canonical
    with pytest.raises(ValueError, match="index"):
        _calculate(
            raw,
            pd.Series([20.0, 30.0], index=zenith_index),
            pd.Series([100.0, 120.0], index=azimuth_index),
        )


@pytest.mark.parametrize("defect", ["non_datetime", "naive", "nat", "duplicate"])
def test_raw_dataframe_index_is_validated(defect: str) -> None:
    if defect == "non_datetime":
        index: pd.Index = pd.Index([0, 1], name="time")
    elif defect == "naive":
        index = pd.DatetimeIndex(["2026-01-01", "2026-01-02"], name="time")
    elif defect == "nat":
        index = pd.DatetimeIndex(["2026-01-01", pd.NaT], tz="UTC", name="time")
    else:
        index = pd.DatetimeIndex(["2026-01-01", "2026-01-01"], tz="UTC", name="time")
    raw = pd.DataFrame({"receiver": [1.0, 2.0]}, index=index)
    with pytest.raises(ValueError, match="index|DatetimeIndex"):
        _calculate(raw)


@pytest.mark.parametrize(
    "samples_u,samples_v",
    [(0, 1), (-1, 1), (1, 0), (1, -1), (True, 1), (1, False), (1.5, 1), (1, 2.5)],
)
def test_sample_grid_validation(samples_u: object, samples_v: object) -> None:
    with pytest.raises(ValueError, match="samples"):
        _calculate(samples_u=samples_u, samples_v=samples_v)  # type: ignore[arg-type]


def test_reference_geometry_inconsistency_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def inconsistent(*args: object, **kwargs: object) -> pd.DataFrame:
        return pd.DataFrame(
            [{"receiver_id": "receiver", "visible_fraction": 0.8, "shaded_fraction": 0.5,
              "sample_count": 20, "shaded_sample_count": 10}]
        )

    monkeypatch.setattr(coupling, "calculate_direct_beam_visibility", inconsistent)
    with pytest.raises(ValueError, match="inconsistent geometry"):
        _calculate()


def test_inputs_scene_and_column_order_are_immutable_and_repeatable() -> None:
    index = _index("2026-06-21 12:00", "2026-06-21 12:07")
    raw = pd.DataFrame({"b": [100.0, np.nan], "a": [50.0, 0.0]}, index=index)
    zenith = pd.Series([10.0, 20.0], index=index, name="zenith")
    azimuth = pd.Series([180.0, 190.0], index=index, name="azimuth")
    surfaces = [_horizontal("b"), _horizontal("a", center=(4, 0, 0))]
    raw_before = raw.copy(deep=True)
    zenith_before = zenith.copy(deep=True)
    azimuth_before = azimuth.copy(deep=True)
    surfaces_before = deepcopy(surfaces)
    first = _calculate(raw, zenith, azimuth, surfaces=surfaces)
    second = _calculate(raw, zenith, azimuth, surfaces=surfaces)
    pdt.assert_frame_equal(first, second)
    pdt.assert_frame_equal(raw, raw_before)
    pdt.assert_series_equal(zenith, zenith_before)
    pdt.assert_series_equal(azimuth, azimuth_before)
    assert [asdict(surface) for surface in surfaces] == [
        asdict(surface) for surface in surfaces_before
    ]
    assert raw.columns.tolist() == ["b", "a"]


def test_r1a_r1b_r2_r4a_composition_uses_receiver_specific_visibility() -> None:
    index = _index("2026-06-21 12:00")
    geometry = calculate_solar_geometry(
        index, latitude_deg=52.5, longitude_deg=-1.2, altitude_m=100.0
    )
    missing = pd.Series(np.nan, index=index)
    r1b = resolve_horizontal_irradiance_components(
        pd.Series([800.0], index=index),
        missing.copy(),
        missing.copy(),
        geometry["solar_zenith_deg"],
    )
    r2 = calculate_raw_poa_transposition(
        r1b["ghi_wm2"],
        r1b["dhi_wm2"],
        r1b["dni_wm2"],
        geometry["apparent_solar_zenith_deg"],
        geometry["solar_azimuth_deg"],
        surface_tilt_deg=0.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model="perez-driesse",
    )
    raw_direct = r2["poa_direct_raw_wm2"]
    raw = pd.DataFrame({"clear": raw_direct, "shaded": raw_direct}, index=index)
    sun_direction = solar_direction_enu(
        geometry["apparent_solar_zenith_deg"].iloc[0],
        geometry["solar_azimuth_deg"].iloc[0],
    )
    surfaces = [
        _horizontal("clear", center=(4, 0, 0)),
        _horizontal("shaded"),
        _horizontal("cover", center=sun_direction),
    ]
    result = _calculate(
        raw,
        geometry["apparent_solar_zenith_deg"],
        geometry["solar_azimuth_deg"],
        surfaces=surfaces,
    )
    assert result.loc[(index[0], "clear"), "poa_direct_raw_wm2"] == raw_direct.iloc[0]
    for receiver in ("clear", "shaded"):
        row = result.loc[(index[0], receiver)]
        assert row["poa_direct_visible_wm2"] == pytest.approx(
            raw_direct.iloc[0] * row["beam_visible_fraction"]
        )
    assert result.loc[(index[0], "clear"), "beam_visible_fraction"] != result.loc[
        (index[0], "shaded"), "beam_visible_fraction"
    ]


def test_r4a_operates_on_finite_r2_direct_when_global_is_unresolved() -> None:
    index = _index()
    zero = pd.Series([0.0], index=index)
    r2 = calculate_raw_poa_transposition(
        zero,
        zero.copy(),
        zero.copy(),
        pd.Series([30.0], index=index),
        pd.Series([180.0], index=index),
        surface_tilt_deg=30.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model="perez",
    )
    assert not bool(r2["poa_transposition_resolved"].iloc[0])
    assert r2["poa_direct_raw_wm2"].iloc[0] == 0.0
    result = _calculate(
        pd.DataFrame({"receiver": r2["poa_direct_raw_wm2"]}, index=index),
        r2["apparent_solar_zenith_deg"],
        r2["solar_azimuth_deg"],
    )
    assert bool(result["beam_shading_resolved"].iloc[0])
    assert result["poa_direct_visible_wm2"].iloc[0] == 0.0


def test_r3a_future_composition_is_test_only() -> None:
    index = _index()
    raw = pd.DataFrame({"receiver": [800.0]}, index=index)
    r4a = _calculate(
        raw,
        surfaces=[
            _horizontal("receiver"),
            _horizontal("half", center=(0.5, 0, 1), span_u=1),
        ],
    )
    r3a = calculate_beam_iam(
        pd.Series([60.0], index=index),
        model="ashrae",
        model_parameters={"b": 0.05},
    )
    future_from_raw = (
        raw.iloc[0, 0]
        * r3a["beam_iam_factor"].iloc[0]
        * r4a["beam_visible_fraction"].iloc[0]
    )
    future_from_visible = (
        r4a["poa_direct_visible_wm2"].iloc[0]
        * r3a["beam_iam_factor"].iloc[0]
    )
    assert future_from_raw == pytest.approx(future_from_visible)
    assert "beam_iam_factor" not in r4a.columns
