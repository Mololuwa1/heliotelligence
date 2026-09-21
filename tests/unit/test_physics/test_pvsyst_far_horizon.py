"""Tests for the canonical PVsyst far-horizon profile evaluator."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics.pvsyst_far_horizon import (
    PVSYST_FAR_HORIZON_AZIMUTH_REFERENCE,
    PVSYST_FAR_HORIZON_CONTRACT_ID,
    PVSYST_FAR_HORIZON_COVERAGE_SCOPE,
    PVSYST_FAR_HORIZON_MODEL_ID,
    PVSYST_FAR_HORIZON_SCOPE,
    PVsystFarHorizonProfile,
    PVsystFarHorizonResult,
    evaluate_pvsyst_far_horizon,
)


def _profile(
    *,
    azimuths: tuple[float, ...] = (-180.0, -90.0, 0.0, 90.0, 180.0),
    elevations: tuple[float, ...] = (2.0, 4.0, 8.0, 6.0, 2.0),
    **changes: object,
) -> PVsystFarHorizonProfile:
    values: dict[str, object] = {
        "profile_id": "far-horizon-1",
        "pvsyst_solar_azimuth_deg": azimuths,
        "horizon_elevation_deg": elevations,
        "coverage_semantics": "full_azimuth_periodic",
        "source_label": "normalized PVsyst horizon",
        "source_reference": "project/site.HOR",
        "pvsyst_version": "8.0",
    }
    values.update(changes)
    return PVsystFarHorizonProfile(**values)  # type: ignore[arg-type]


def _series(
    elevations: tuple[float, ...], azimuths: tuple[float, ...]
) -> tuple[pd.Series, pd.Series]:
    index = pd.date_range(
        "2026-06-01", periods=len(elevations), freq="h", tz="UTC", name="time"
    )
    return pd.Series(elevations, index=index), pd.Series(azimuths, index=index)


def _evaluate(
    elevations: tuple[float, ...],
    azimuths: tuple[float, ...],
    *,
    profile: PVsystFarHorizonProfile | None = None,
    hemisphere: str = "north",
) -> PVsystFarHorizonResult:
    solar_elevation, solar_azimuth = _series(elevations, azimuths)
    return evaluate_pvsyst_far_horizon(
        _profile() if profile is None else profile,
        solar_elevation,
        solar_azimuth,
        hemisphere=hemisphere,  # type: ignore[arg-type]
    )


def test_constants_provenance_schema_and_diagnostics() -> None:
    result = _evaluate((10.0, 1.0, 0.0), (180.0, 0.0, 90.0))
    frame = result.horizon
    assert tuple(frame.columns) == (
        "solar_elevation_deg",
        "solar_azimuth_deg",
        "pvsyst_solar_azimuth_deg",
        "pvsyst_horizon_elevation_deg",
        "pvsyst_horizon_clearance_deg",
        "pvsyst_horizon_beam_visible_factor",
        "pvsyst_horizon_visibility_resolved",
        "pvsyst_horizon_state",
        "pvsyst_horizon_profile_id",
        "pvsyst_version",
        "pvsyst_source_label",
        "pvsyst_source_reference",
        "pvsyst_far_horizon_azimuth_reference",
        "pvsyst_far_horizon_contract",
        "pvsyst_far_horizon_model",
        "pvsyst_far_horizon_coverage_scope",
        "pvsyst_far_horizon_scope",
    )
    assert set(frame["pvsyst_far_horizon_contract"]) == {
        PVSYST_FAR_HORIZON_CONTRACT_ID
    }
    assert set(frame["pvsyst_far_horizon_model"]) == {PVSYST_FAR_HORIZON_MODEL_ID}
    assert set(frame["pvsyst_far_horizon_scope"]) == {PVSYST_FAR_HORIZON_SCOPE}
    assert set(frame["pvsyst_far_horizon_coverage_scope"]) == {
        PVSYST_FAR_HORIZON_COVERAGE_SCOPE
    }
    assert set(frame["pvsyst_far_horizon_azimuth_reference"]) == {
        PVSYST_FAR_HORIZON_AZIMUTH_REFERENCE
    }
    assert result.diagnostics.resolved_count == 2
    assert result.diagnostics.visible_count == 1
    assert result.diagnostics.blocked_count == 1
    assert result.diagnostics.not_applicable_count == 1


def test_northern_and_southern_conversion_reuses_shared_convention() -> None:
    flat = _profile(elevations=(1.0,) * 5)
    north = _evaluate((5.0,) * 4, (180.0, 90.0, 270.0, 0.0), profile=flat)
    south = _evaluate(
        (5.0,) * 4, (0.0, 90.0, 270.0, 180.0), profile=flat, hemisphere="south"
    )
    expected = (0.0, -90.0, 90.0, -180.0)
    assert tuple(north.horizon["pvsyst_solar_azimuth_deg"]) == expected
    assert tuple(south.horizon["pvsyst_solar_azimuth_deg"]) == expected


def test_exact_profile_points_and_variable_spacing_interpolation() -> None:
    profile = _profile(
        azimuths=(-180.0, -120.0, -35.0, 10.0, 73.0, 145.0, 180.0),
        elevations=(2.0, 5.0, 11.0, 7.0, 15.0, 4.0, 2.0),
    )
    pvlib = tuple((value + 180.0) % 360.0 for value in profile.pvsyst_solar_azimuth_deg)
    exact = _evaluate((30.0,) * len(pvlib), pvlib, profile=profile).horizon
    assert tuple(exact["pvsyst_horizon_elevation_deg"]) == pytest.approx(
        profile.horizon_elevation_deg
    )
    # -77.5 is halfway between -120 (5) and -35 (11).
    interpolated = _evaluate((30.0,), (102.5,), profile=profile).horizon.iloc[0]
    assert interpolated["pvsyst_horizon_elevation_deg"] == pytest.approx(8.0)


def test_periodic_seam_is_continuous_with_explicit_duplicate() -> None:
    result = _evaluate((10.0,) * 4, (359.0, 1.0, 359.999, 0.001)).horizon
    heights = result["pvsyst_horizon_elevation_deg"].to_numpy()
    assert abs(heights[2] - heights[3]) < abs(heights[0] - heights[1])
    assert heights[2] == pytest.approx(2.0, abs=5e-5)
    assert heights[3] == pytest.approx(2.0, abs=5e-5)


def test_periodic_profile_without_plus_180_spans_final_gap() -> None:
    profile = _profile(
        azimuths=(-180.0, -90.0, 0.0, 90.0),
        elevations=(2.0, 4.0, 8.0, 6.0),
    )
    # North-west-side query maps to +135, halfway from +90 (6) to +180/-180 (2).
    row = _evaluate((20.0,), (315.0,), profile=profile).horizon.iloc[0]
    assert row["pvsyst_horizon_elevation_deg"] == pytest.approx(4.0)


def test_periodic_profile_may_begin_away_from_minus_180() -> None:
    profile = _profile(
        azimuths=(-120.0, 0.0, 120.0), elevations=(3.0, 9.0, 6.0)
    )
    # -180 wraps to +180, halfway from +120 (6) to +240/-120 (3).
    row = _evaluate((20.0,), (0.0,), profile=profile).horizon.iloc[0]
    assert row["pvsyst_horizon_elevation_deg"] == pytest.approx(4.5)


def test_inconsistent_explicit_seam_is_rejected() -> None:
    with pytest.raises(ValueError, match="seam"):
        _profile(elevations=(2.0, 4.0, 8.0, 6.0, 2.01))


def test_visibility_tangency_clearance_and_binary_factors() -> None:
    flat = _profile(elevations=(6.0,) * 5)
    result = _evaluate((5.0, 6.0, 6.000001), (180.0,) * 3, profile=flat).horizon
    assert tuple(result["pvsyst_horizon_beam_visible_factor"]) == (0.0, 0.0, 1.0)
    assert tuple(result["pvsyst_horizon_state"]) == (
        "resolved_blocked_by_far_horizon",
        "resolved_blocked_by_far_horizon",
        "resolved_visible_above_far_horizon",
    )
    assert tuple(result["pvsyst_horizon_clearance_deg"]) == pytest.approx(
        (-1.0, 0.0, 0.000001)
    )


def test_sub_two_degree_profile_is_not_suppressed() -> None:
    profile = _profile(elevations=(1.5,) * 5)
    frame = _evaluate((1.0, 2.0), (180.0, 180.0), profile=profile).horizon
    assert tuple(frame["pvsyst_horizon_beam_visible_factor"]) == (0.0, 1.0)


def test_negative_horizon_is_not_clamped() -> None:
    profile = _profile(elevations=(-5.0,) * 5)
    row = _evaluate((1.0,), (180.0,), profile=profile).horizon.iloc[0]
    assert row["pvsyst_horizon_elevation_deg"] == -5.0
    assert row["pvsyst_horizon_beam_visible_factor"] == 1.0


def test_night_retains_geometry_but_has_no_visibility_factor() -> None:
    frame = _evaluate((0.0, -10.0), (180.0, 90.0)).horizon
    assert frame["pvsyst_horizon_elevation_deg"].notna().all()
    assert frame["pvsyst_horizon_clearance_deg"].notna().all()
    assert frame["pvsyst_horizon_beam_visible_factor"].isna().all()
    assert not frame["pvsyst_horizon_visibility_resolved"].any()
    assert set(frame["pvsyst_horizon_state"]) == {
        "not_applicable_no_above_horizon_beam"
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile_id", " "),
        ("profile_id", None),
        ("source_label", ""),
        ("source_label", 1),
        ("source_reference", " "),
        ("source_reference", np.nan),
        ("pvsyst_version", ""),
        ("coverage_semantics", None),
        ("coverage_semantics", "partial"),
    ],
)
def test_invalid_identity_provenance_and_coverage_are_rejected(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        _profile(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("azimuths", "elevations"),
    [
        ([-180.0, 0.0, 180.0], (2.0, 8.0, 2.0)),
        ((-180.0, 180.0), (2.0, 2.0)),
        ((-180.0, 0.0, 0.0), (2.0, 8.0, 8.0)),
        ((-180.0, 30.0, 0.0), (2.0, 6.0, 8.0)),
        ((-181.0, 0.0, 180.0), (2.0, 8.0, 2.0)),
        ((-180.0, True, 180.0), (2.0, 8.0, 2.0)),
        ((-180.0, np.nan, 180.0), (2.0, 8.0, 2.0)),
        ((-180.0, np.inf, 180.0), (2.0, 8.0, 2.0)),
        ((-180.0, 0.0, 180.0), (2.0, 8.0)),
        ((-180.0, 0.0, 180.0), (2.0, True, 2.0)),
        ((-180.0, 0.0, 180.0), (2.0, np.nan, 2.0)),
        ((-180.0, 0.0, 180.0), (2.0, np.inf, 2.0)),
        ((-180.0, 0.0, 180.0), (2.0, 91.0, 2.0)),
    ],
)
def test_invalid_profile_grids_are_rejected(
    azimuths: object, elevations: tuple[object, ...]
) -> None:
    with pytest.raises(ValueError):
        _profile(azimuths=azimuths, elevations=elevations)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("elevation", "azimuth"),
    [
        ((True,), (180.0,)),
        (("5",), (180.0,)),
        ((np.nan,), (180.0,)),
        ((np.inf,), (180.0,)),
        ((91.0,), (180.0,)),
        ((-91.0,), (180.0,)),
        ((5.0,), (True,)),
        ((5.0,), ("180",)),
        ((5.0,), (np.nan,)),
        ((5.0,), (np.inf,)),
        ((5.0,), (360.0,)),
        ((5.0,), (-1.0,)),
    ],
)
def test_invalid_solar_values_are_rejected(
    elevation: tuple[object, ...], azimuth: tuple[object, ...]
) -> None:
    solar_elevation, solar_azimuth = _series(elevation, azimuth)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        evaluate_pvsyst_far_horizon(
            _profile(), solar_elevation, solar_azimuth, hemisphere="north"
        )


def test_series_and_index_integrity_are_strict() -> None:
    elevation, azimuth = _series((5.0, 6.0), (180.0, 190.0))
    invalid_pairs: list[tuple[object, object]] = [
        (elevation.to_numpy(), azimuth),
        (elevation, azimuth.to_numpy()),
        (elevation.tz_localize(None), azimuth.tz_localize(None)),
        (elevation, azimuth.iloc[::-1]),
        (elevation, azimuth.rename_axis("timestamp")),
        (elevation, azimuth.tz_convert("Europe/London")),
    ]
    duplicate = pd.DatetimeIndex([elevation.index[0], elevation.index[0]], name="time")
    invalid_pairs.append(
        (pd.Series((5.0, 6.0), index=duplicate), pd.Series((180.0, 190.0), index=duplicate))
    )
    nat_index = pd.DatetimeIndex([elevation.index[0], pd.NaT], tz="UTC", name="time")
    invalid_pairs.append(
        (pd.Series((5.0, 6.0), index=nat_index), pd.Series((180.0, 190.0), index=nat_index))
    )
    for invalid_elevation, invalid_azimuth in invalid_pairs:
        with pytest.raises(ValueError):
            evaluate_pvsyst_far_horizon(
                _profile(),
                invalid_elevation,
                invalid_azimuth,
                hemisphere="north",
            )


def test_invalid_profile_object_and_hemisphere_are_rejected() -> None:
    elevation, azimuth = _series((5.0,), (180.0,))
    with pytest.raises(ValueError, match="profile"):
        evaluate_pvsyst_far_horizon(
            cast(PVsystFarHorizonProfile, object()),
            elevation,
            azimuth,
            hemisphere="north",
        )
    with pytest.raises(ValueError, match="hemisphere"):
        evaluate_pvsyst_far_horizon(
            _profile(), elevation, azimuth, hemisphere="equator"  # type: ignore[arg-type]
        )


def test_empty_input_is_stable_and_deterministic() -> None:
    index = pd.DatetimeIndex([], tz="UTC", name="time")
    elevation = pd.Series([], index=index, dtype=float)
    azimuth = pd.Series([], index=index, dtype=float)
    first = evaluate_pvsyst_far_horizon(
        _profile(), elevation, azimuth, hemisphere="north"
    )
    second = evaluate_pvsyst_far_horizon(
        _profile(), elevation, azimuth, hemisphere="north"
    )
    pd.testing.assert_frame_equal(first.horizon, second.horizon)
    assert first.diagnostics == second.diagnostics
    assert first.horizon.empty
    assert first.diagnostics.timestamp_count == 0
    assert first.diagnostics.resolved_count == 0


def test_determinism_and_input_immutability() -> None:
    profile = _profile()
    elevation, azimuth = _series((5.0, 10.0), (1.0, 225.0))
    originals = (deepcopy(profile), elevation.copy(deep=True), azimuth.copy(deep=True))
    first = evaluate_pvsyst_far_horizon(
        profile, elevation, azimuth, hemisphere="north"
    )
    second = evaluate_pvsyst_far_horizon(
        profile, elevation, azimuth, hemisphere="north"
    )
    pd.testing.assert_frame_equal(first.horizon, second.horizon)
    assert asdict(first.diagnostics) == asdict(second.diagnostics)
    assert profile == originals[0]
    pd.testing.assert_series_equal(elevation, originals[1])
    pd.testing.assert_series_equal(azimuth, originals[2])


def test_geometry_only_schema_and_api_boundaries() -> None:
    columns = tuple(column.lower() for column in _evaluate((5.0,), (180.0,)).horizon)
    forbidden = (
        "ghi",
        "dni",
        "dhi",
        "poa",
        "wm2",
        "effective_irradiance",
        "near_object",
        "fixed_inter_row",
        "terrain_horizon",
        "selected_horizon_source",
        "electrical",
    )
    assert not any(token in column for token in forbidden for column in columns)
