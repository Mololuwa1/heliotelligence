"""Tests for PVsyst-preferred near-shading comparison and authority."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.geometry import PVReceiver, ReceiverKind, TriangleMesh
from heliotelligence.physics.pvsyst_linear_shading import (
    PVsystLinearShadingResult,
    PVsystLinearShadingTable,
    evaluate_pvsyst_linear_beam_shading,
)
from heliotelligence.physics.pvsyst_shading_authority import (
    PVSYST_SHADING_AUTHORITY_CONTRACT_ID,
    PVsystNearShadingAuthorityResult,
    PVsystNearShadingScope,
    compare_and_select_pvsyst_near_shading,
)


def _receiver(
    identifier: str,
    *,
    area: float = 1.0,
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> PVReceiver:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 0.0), (2.0 * area, 0.0, 0.0), (0.0, 1.0, 0.0))),
        np.asarray(((0, 1, 2),)),
    )
    return PVReceiver(identifier, mesh, (0.0, 0.0, 0.0), normal, ReceiverKind.FIXED_TABLE)


def _index(ids: tuple[str, ...], *, periods: int = 1) -> pd.MultiIndex:
    times = pd.date_range("2026-06-01 12:00", periods=periods, freq="h", tz="UTC", name="time")
    return pd.MultiIndex.from_product((times, ids), names=("time", "receiver_id"))


def _frames(
    ids: tuple[str, ...],
    *,
    fixed: tuple[float, ...] | None = None,
    near: tuple[float, ...] | None = None,
    raw: tuple[float, ...] | None = None,
    zenith: float = 30.0,
    periods: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = _index(ids, periods=periods)
    count = len(index)
    fixed_values = fixed or (1.0,) * count
    near_values = near or (1.0,) * count
    raw_values = raw or (100.0,) * count
    fixed_frame = pd.DataFrame(
        {
            "poa_direct_raw_wm2": raw_values,
            "apparent_solar_zenith_deg": (zenith,) * count,
            "solar_azimuth_deg": (180.0,) * count,
            "fixed_inter_row_beam_visible_fraction": fixed_values,
            "fixed_inter_row_beam_shaded_fraction": tuple(1.0 - value for value in fixed_values),
            "fixed_inter_row_visibility_resolved": (True,) * count,
            "fixed_inter_row_state": ("resolved",) * count,
            "fixed_inter_row_model": ("fixed-row-model",) * count,
        },
        index=index,
    )
    near_frame = pd.DataFrame(
        {
            "poa_direct_raw_wm2": raw_values,
            "apparent_solar_zenith_deg": (zenith,) * count,
            "solar_azimuth_deg": (180.0,) * count,
            "near_object_beam_visible_fraction": near_values,
            "near_object_beam_shaded_fraction": tuple(1.0 - value for value in near_values),
            "near_object_visibility_resolved": (True,) * count,
            "near_object_shading_state": ("resolved",) * count,
            "near_object_shading_model": ("near-object-model",) * count,
        },
        index=index,
    )
    return fixed_frame, near_frame


def _pvsyst(
    timestamps: pd.DatetimeIndex,
    *,
    factor: float = 0.8,
    elevation: float = 60.0,
    table_id: str = "table",
    minimum_height: float = 10.0,
) -> PVsystLinearShadingResult:
    table = PVsystLinearShadingTable(
        table_id,
        "orientation",
        "zone",
        (minimum_height, 80.0),
        (-180.0, 180.0),
        ((factor, factor), (factor, factor)),
        "transmission_fraction",
        "PVsyst export",
        "fixture",
        "8.0",
    )
    return evaluate_pvsyst_linear_beam_shading(
        table,
        pd.Series((elevation,) * len(timestamps), index=timestamps),
        pd.Series((180.0,) * len(timestamps), index=timestamps),
        hemisphere="north",
    )


def _calculate(
    receivers: list[PVReceiver],
    fixed: pd.DataFrame,
    near: pd.DataFrame,
    pvsyst: PVsystLinearShadingResult,
    *,
    fallback: str = "no_fallback",
    scopes: list[PVsystNearShadingScope] | None = None,
) -> PVsystNearShadingAuthorityResult:
    selected_scopes = scopes or [
        PVsystNearShadingScope("scope", "table", tuple(receiver.id for receiver in receivers))
    ]
    return compare_and_select_pvsyst_near_shading(
        receivers,
        fixed,
        near,
        {"table": pvsyst},
        selected_scopes,
        fallback_policy=fallback,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("pvsyst_factor", "helio_factor", "expected_delta"),
    [(0.8, 0.8, 0.0), (0.7, 0.82, 0.12), (0.9, 0.76, -0.14)],
)
def test_comparison_sign_and_pvsyst_authority(
    pvsyst_factor: float, helio_factor: float, expected_delta: float
) -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",), fixed=(1.0,), near=(helio_factor,))
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique(), factor=pvsyst_factor)
    result = _calculate(receivers, fixed, near, pvsyst)
    comparison = result.scope_comparison.iloc[0]
    authority = result.receiver_authority.iloc[0]
    assert comparison["helio_minus_pvsyst_transmission_delta"] == pytest.approx(expected_delta)
    assert comparison["absolute_transmission_delta"] == pytest.approx(abs(expected_delta))
    assert comparison["geometry_comparison_resolved"]
    assert authority["selected_near_shading_beam_transmission_fraction"] == pvsyst_factor
    assert authority["selected_near_shading_source"] == "pvsyst"


def test_surface_area_weighting_and_direct_irradiance_delta() -> None:
    receivers = [_receiver("a", area=1.0), _receiver("b", area=3.0)]
    fixed, near = _frames(("a", "b"), fixed=(1.0, 1.0), near=(0.5, 1.0), raw=(100.0, 200.0))
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique(), factor=0.75)
    row = _calculate(receivers, fixed, near, pvsyst).scope_comparison.iloc[0]
    assert row["receiver_surface_area_total_m2"] == pytest.approx(4.0)
    assert row["helio_near_shading_area_weighted_transmission_fraction"] == pytest.approx(0.875)
    assert row["raw_direct_area_weighted_wm2"] == pytest.approx(175.0)
    assert row["pvsyst_direct_after_near_shading_area_weighted_wm2"] == pytest.approx(131.25)
    assert row["helio_direct_after_near_shading_area_weighted_wm2"] == pytest.approx(162.5)
    assert row["direct_irradiance_delta_helio_minus_pvsyst_wm2"] == pytest.approx(31.25)


@pytest.mark.parametrize(
    ("fixed_factor", "near_factor", "expected"),
    [(1.0, 0.75, 0.75), (0.6, 1.0, 0.6), (0.0, 0.8, 0.0), (0.8, 0.0, 0.0), (1.0, 1.0, 1.0)],
)
def test_guarded_helio_exact_composition(
    fixed_factor: float, near_factor: float, expected: float
) -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",), fixed=(fixed_factor,), near=(near_factor,))
    result = _calculate(receivers, fixed, near, _pvsyst(fixed.index.get_level_values(0).unique()))
    row = result.receiver_authority.iloc[0]
    assert row["helio_near_shading_beam_transmission_fraction"] == pytest.approx(expected)
    assert row["helio_near_shading_resolved"]


def test_partial_overlap_unresolved_but_pvsyst_wins() -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",), fixed=(0.8,), near=(0.7,))
    row = _calculate(
        receivers, fixed, near, _pvsyst(fixed.index.get_level_values(0).unique(), factor=0.65)
    ).receiver_authority.iloc[0]
    assert np.isnan(row["helio_near_shading_beam_transmission_fraction"])
    assert row["helio_near_shading_state"] == "unresolved_fixed_near_partial_overlap"
    assert row["selected_near_shading_beam_transmission_fraction"] == 0.65
    assert row["selected_near_shading_source"] == "pvsyst"


@pytest.mark.parametrize(
    ("fallback", "expected_source", "resolved"),
    [
        ("no_fallback", "none", False),
        ("heliotelligence_if_pvsyst_unresolved", "heliotelligence_fallback", True),
    ],
)
def test_outside_domain_fallback_policy(
    fallback: str, expected_source: str, resolved: bool
) -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",), fixed=(1.0,), near=(0.9,), zenith=80.0)
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique(), elevation=10.0, minimum_height=20.0)
    row = _calculate(receivers, fixed, near, pvsyst, fallback=fallback).receiver_authority.iloc[0]
    assert row["selected_near_shading_source"] == expected_source
    assert bool(row["selected_near_shading_resolved"]) is resolved
    if resolved:
        assert row["selected_near_shading_beam_transmission_fraction"] == 0.9
    else:
        assert np.isnan(row["selected_near_shading_beam_transmission_fraction"])
        assert np.isnan(row["selected_near_shading_beam_shaded_fraction"])
        assert row["selected_near_shading_state"] == "unresolved_pvsyst_authority"


def test_both_unresolved_and_night_states() -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",), fixed=(0.8,), near=(0.7,), zenith=80.0)
    outside = _pvsyst(fixed.index.get_level_values(0).unique(), elevation=10.0, minimum_height=20.0)
    row = _calculate(
        receivers, fixed, near, outside, fallback="heliotelligence_if_pvsyst_unresolved"
    ).receiver_authority.iloc[0]
    assert row["selected_near_shading_state"] == "unresolved_both_sources"
    no_fallback_row = _calculate(
        receivers, fixed, near, outside, fallback="no_fallback"
    ).receiver_authority.iloc[0]
    assert np.isnan(no_fallback_row["selected_near_shading_beam_transmission_fraction"])
    assert np.isnan(no_fallback_row["selected_near_shading_beam_shaded_fraction"])
    assert not no_fallback_row["selected_near_shading_resolved"]
    assert no_fallback_row["selected_near_shading_source"] == "none"
    assert no_fallback_row["selected_near_shading_state"] == "unresolved_both_sources"
    night_fixed, night_near = _frames(("r",), zenith=90.0)
    night = _pvsyst(night_fixed.index.get_level_values(0).unique(), elevation=0.0)
    night_row = _calculate(receivers, night_fixed, night_near, night).receiver_authority.iloc[0]
    for column in (
        "helio_near_shading_beam_transmission_fraction",
        "pvsyst_near_shading_beam_transmission_fraction",
        "selected_near_shading_beam_transmission_fraction",
    ):
        assert np.isnan(night_row[column])
    assert night_row["selected_near_shading_state"] == "not_applicable_no_above_horizon_beam"


def test_strict_scope_comparison_and_zero_direct_semantics() -> None:
    receivers = [_receiver("a"), _receiver("b")]
    fixed, near = _frames(("a", "b"), fixed=(1.0, 0.8), near=(0.9, 0.7), raw=(0.0, 0.0))
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique(), factor=0.8)
    row = _calculate(receivers, fixed, near, pvsyst).scope_comparison.iloc[0]
    assert not row["geometry_comparison_resolved"]
    assert row["helio_resolved_receiver_count"] == 1
    assert row["pvsyst_direct_after_near_shading_area_weighted_wm2"] == 0.0
    assert row["helio_direct_after_near_shading_area_weighted_wm2"] == 0.0
    assert row["direct_irradiance_delta_helio_minus_pvsyst_wm2"] == 0.0
    assert row["irradiance_impact_state"] == "resolved_zero_raw_direct"


def test_mixed_zero_positive_direct_ignores_unresolved_zero_factor() -> None:
    receivers = [_receiver("a"), _receiver("b")]
    fixed, near = _frames(("a", "b"), fixed=(0.8, 1.0), near=(0.7, 0.9), raw=(0.0, 100.0))
    row = _calculate(
        receivers, fixed, near, _pvsyst(fixed.index.get_level_values(0).unique(), factor=0.8)
    ).scope_comparison.iloc[0]
    assert row["irradiance_impact_resolved"]
    assert row["helio_direct_after_near_shading_area_weighted_wm2"] == pytest.approx(45.0)
    assert row["pvsyst_direct_after_near_shading_area_weighted_wm2"] == pytest.approx(40.0)


def test_nan_raw_direct_keeps_impact_unresolved() -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",), raw=(np.nan,))
    row = _calculate(
        receivers, fixed, near, _pvsyst(fixed.index.get_level_values(0).unique())
    ).scope_comparison.iloc[0]
    assert not row["irradiance_impact_resolved"]
    assert row["irradiance_impact_state"] == "unresolved_raw_direct_irradiance"


def test_scope_and_orientation_integrity() -> None:
    receivers = [_receiver("a"), _receiver("b")]
    fixed, near = _frames(("a", "b"))
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique())
    invalid_scopes = [
        [PVsystNearShadingScope("s", "table", ("a",))],
        [PVsystNearShadingScope("s", "table", ("a", "unknown"))],
        [
            PVsystNearShadingScope("s1", "table", ("a",)),
            PVsystNearShadingScope("s2", "table", ("a", "b")),
        ],
        [
            PVsystNearShadingScope("s", "table", ("a",)),
            PVsystNearShadingScope("s", "table", ("b",)),
        ],
    ]
    for scopes in invalid_scopes:
        with pytest.raises(ValueError):
            _calculate(receivers, fixed, near, pvsyst, scopes=scopes)
    different = [_receiver("a"), _receiver("b", normal=(0.0, 1.0, 0.0))]
    with pytest.raises(ValueError, match="orientation"):
        _calculate(different, fixed, near, pvsyst)
    with pytest.raises(ValueError):
        PVsystNearShadingScope("s", "table", ())


def test_table_mapping_and_provenance_tampering() -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",))
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique())
    scope = [PVsystNearShadingScope("scope", "table", ("r",))]
    with pytest.raises(ValueError, match="mappings"):
        compare_and_select_pvsyst_near_shading(
            receivers, fixed, near, {}, scope, fallback_policy="no_fallback"
        )
    with pytest.raises(ValueError, match="mappings"):
        compare_and_select_pvsyst_near_shading(
            receivers,
            fixed,
            near,
            {"table": pvsyst, "extra": pvsyst},
            scope,
            fallback_policy="no_fallback",
        )
    broken = pvsyst.shading.copy()
    broken["pvsyst_linear_shading_model"] = "wrong"
    tampered = PVsystLinearShadingResult(broken, pvsyst.diagnostics)
    with pytest.raises(ValueError, match="provenance"):
        _calculate(receivers, fixed, near, tampered)


def test_solar_and_cross_mechanism_provenance_mismatch() -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",))
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique())
    for column in ("poa_direct_raw_wm2", "apparent_solar_zenith_deg", "solar_azimuth_deg"):
        changed = near.copy()
        changed.loc[changed.index[0], column] += 1.0
        with pytest.raises(ValueError, match="mismatch"):
            _calculate(receivers, fixed, changed, pvsyst)
    solar = pvsyst.shading.copy()
    solar["solar_elevation_deg"] += 1.0
    with pytest.raises(ValueError, match="solar states"):
        _calculate(receivers, fixed, near, PVsystLinearShadingResult(solar, pvsyst.diagnostics))


def test_same_table_reused_by_scopes_and_metrics() -> None:
    receivers = [_receiver("a"), _receiver("b", area=2.0)]
    fixed, near = _frames(("a", "b"), fixed=(1.0, 1.0), near=(0.7, 0.9), raw=(100.0, 200.0))
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique(), factor=0.8)
    scopes = [
        PVsystNearShadingScope("east", "table", ("a",)),
        PVsystNearShadingScope("west", "table", ("b",)),
    ]
    result = _calculate(receivers, fixed, near, pvsyst, scopes=scopes)
    assert tuple(result.scope_comparison.index.get_level_values("pvsyst_scope_id")) == (
        "east",
        "west",
    )
    assert result.diagnostics.area_weighted_bias == pytest.approx(1.0 / 30.0)
    assert result.diagnostics.area_weighted_mae == pytest.approx(0.1)
    assert result.diagnostics.area_weighted_rmse == pytest.approx(0.1)
    assert result.diagnostics.max_abs_transmission_delta == pytest.approx(0.1)
    assert result.diagnostics.irradiance_weighted_mae == pytest.approx(0.1)


def test_empty_determinism_no_mutation_and_no_forbidden_outputs() -> None:
    receivers = [_receiver("a"), _receiver("b")]
    fixed, near = _frames(("a", "b"), periods=0)
    pvsyst = _pvsyst(fixed.index.get_level_values(0).unique())
    scopes = [PVsystNearShadingScope("scope", "table", ("a", "b"))]
    originals = (deepcopy(receivers), fixed.copy(), near.copy(), deepcopy(pvsyst), deepcopy(scopes))
    first = _calculate(receivers, fixed, near, pvsyst, scopes=scopes)
    second = _calculate(
        receivers[::-1], fixed.iloc[::-1], near.iloc[::-1], pvsyst, scopes=scopes[::-1]
    )
    pd.testing.assert_frame_equal(first.receiver_authority, second.receiver_authority)
    pd.testing.assert_frame_equal(first.scope_comparison, second.scope_comparison)
    assert first.receiver_authority.empty and first.scope_comparison.empty
    assert first.diagnostics.receiver_row_count == first.diagnostics.comparison_row_count == 0
    assert np.isnan(first.diagnostics.area_weighted_mae)
    assert all("terrain" not in column for column in first.receiver_authority)
    assert "pvsyst_direct_after_near_shading_area_weighted_wm2" not in first.receiver_authority
    assert all("iam" not in column.lower() for column in first.receiver_authority)
    assert first.receiver_authority.columns[-4] == "pvsyst_shading_authority_contract"
    assert first.diagnostics.contract == PVSYST_SHADING_AUTHORITY_CONTRACT_ID
    assert receivers == originals[0] and scopes == originals[4]
    pd.testing.assert_frame_equal(fixed, originals[1])
    pd.testing.assert_frame_equal(near, originals[2])
    assert pvsyst.diagnostics == originals[3].diagnostics


@pytest.mark.parametrize("fallback", [None, "", "helio", True])
def test_fallback_policy_is_required_and_explicit(fallback: object) -> None:
    receivers = [_receiver("r")]
    fixed, near = _frames(("r",))
    with pytest.raises(ValueError, match="fallback_policy"):
        _calculate(
            receivers,
            fixed,
            near,
            _pvsyst(fixed.index.get_level_values(0).unique()),
            fallback=fallback,  # type: ignore[arg-type]
        )
