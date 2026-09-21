"""Tests for PVsyst-preferred far-horizon comparison and authority."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.geometry import PVReceiver, ReceiverKind, TriangleMesh
from heliotelligence.physics.pvsyst_far_horizon import (
    PVsystFarHorizonProfile,
    PVsystFarHorizonResult,
    evaluate_pvsyst_far_horizon,
)
from heliotelligence.physics.pvsyst_horizon_authority import (
    PVSYST_HORIZON_AUTHORITY_CONTRACT_ID,
    PVsystFarHorizonAuthorityResult,
    PVsystHorizonActivation,
    _select,
    compare_and_select_pvsyst_far_horizon,
)
from heliotelligence.physics.terrain_horizon import COVERAGE_SCOPE, MODEL_ID


def _receiver(
    identifier: str, *, area: float = 1.0, kind: ReceiverKind = ReceiverKind.FIXED_TABLE
) -> PVReceiver:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 0.0), (2.0 * area, 0.0, 0.0), (0.0, 1.0, 0.0))),
        np.asarray(((0, 1, 2),)),
    )
    return PVReceiver(identifier, mesh, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), kind)


def _terrain(
    ids: tuple[str, ...],
    *,
    factors: tuple[float, ...] | None = None,
    raw: tuple[float, ...] | None = None,
    zenith: float = 30.0,
    periods: int = 1,
) -> pd.DataFrame:
    times = pd.date_range("2026-06-01 12:00", periods=periods, freq="h", tz="UTC", name="time")
    index = pd.MultiIndex.from_product((times, ids), names=("time", "receiver_id"))
    count = len(index)
    values = factors or (1.0,) * count
    night = zenith >= 90.0
    return pd.DataFrame(
        {
            "poa_direct_raw_wm2": raw or (100.0,) * count,
            "apparent_solar_zenith_deg": (zenith,) * count,
            "solar_azimuth_deg": (180.0,) * count,
            "terrain_horizon_beam_visible_factor": (np.nan,) * count if night else values,
            "blocking_terrain_id": (None,) * count,
            "blocking_distance_m": (np.inf,) * count,
            "terrain_horizon_visibility_resolved": (False,) * count if night else (True,) * count,
            "terrain_horizon_state": ("no_above_horizon_direct_beam",) * count
            if night
            else ("resolved",) * count,
            "terrain_horizon_model": (MODEL_ID,) * count,
            "terrain_horizon_coverage_scope": (COVERAGE_SCOPE,) * count,
        },
        index=index,
    )


def _pvsyst(terrain: pd.DataFrame, *, horizon: float = 50.0) -> PVsystFarHorizonResult:
    times = pd.DatetimeIndex(terrain.index.get_level_values(0).unique())
    zenith = float(terrain["apparent_solar_zenith_deg"].iloc[0]) if len(terrain) else 30.0
    profile = PVsystFarHorizonProfile(
        "profile",
        (-180.0, 0.0, 180.0),
        (horizon, horizon, horizon),
        "full_azimuth_periodic",
        "PVsyst project",
        "fixture",
        "8.0",
    )
    return evaluate_pvsyst_far_horizon(
        profile,
        pd.Series((90.0 - zenith,) * len(times), index=times),
        pd.Series((180.0,) * len(times), index=times),
        hemisphere="north",
    )


def _activation(state: str = "enabled", **changes: object) -> PVsystHorizonActivation:
    values: dict[str, object] = {
        "profile_id": "profile",
        "project_variant_id": "variant-a",
        "activation_state": state,
        "source_label": "project handoff",
        "source_reference": "variant report",
        "evidence_note": "explicit setting",
    }
    values.update(changes)
    return PVsystHorizonActivation(**values)  # type: ignore[arg-type]


def _calculate(
    receivers: list[PVReceiver],
    terrain: pd.DataFrame,
    pvsyst: PVsystFarHorizonResult,
    *,
    state: str = "enabled",
    fallback: str = "no_fallback",
) -> PVsystFarHorizonAuthorityResult:
    return compare_and_select_pvsyst_far_horizon(
        receivers,
        terrain,
        pvsyst,
        activation=_activation(state),
        fallback_policy=fallback,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("profile_horizon", "helio", "delta", "comparison_state"),
    [
        (50.0, 1.0, 0.0, "agreement_visible"),
        (70.0, 0.0, 0.0, "agreement_blocked"),
        (50.0, 0.0, -1.0, "disagreement_pvsyst_visible_helio_blocked"),
        (70.0, 1.0, 1.0, "disagreement_pvsyst_blocked_helio_visible"),
    ],
)
def test_receiver_profile_comparison_states(
    profile_horizon: float, helio: float, delta: float, comparison_state: str
) -> None:
    terrain = _terrain(("r",), factors=(helio,))
    row = _calculate(
        [_receiver("r")], terrain, _pvsyst(terrain, horizon=profile_horizon)
    ).receiver_authority.iloc[0]
    assert row["helio_minus_pvsyst_profile_visibility_delta"] == delta
    assert row["profile_geometry_comparison_state"] == comparison_state


def test_receiver_heterogeneity_area_weighting_and_direct_impact() -> None:
    receivers = [_receiver("a", area=1.0), _receiver("b", area=3.0)]
    terrain = _terrain(("a", "b"), factors=(0.0, 1.0), raw=(100.0, 200.0))
    result = _calculate(receivers, terrain, _pvsyst(terrain, horizon=50.0))
    assert tuple(result.receiver_authority["helio_minus_pvsyst_profile_visibility_delta"]) == (
        -1.0,
        0.0,
    )
    site = result.site_comparison.iloc[0]
    assert site["helio_horizon_area_weighted_visible_fraction"] == pytest.approx(0.75)
    assert site["pvsyst_profile_direct_after_horizon_area_weighted_wm2"] == 175.0
    assert site["helio_direct_after_horizon_area_weighted_wm2"] == 150.0
    assert site["direct_irradiance_delta_helio_minus_pvsyst_wm2"] == -25.0


def test_enabled_authority_prefers_pvsyst_profile() -> None:
    terrain = _terrain(("r",), factors=(1.0,))
    row = _calculate(
        [_receiver("r")], terrain, _pvsyst(terrain, horizon=70.0)
    ).receiver_authority.iloc[0]
    assert row["selected_horizon_beam_visible_factor"] == 0.0
    assert row["selected_horizon_source"] == "pvsyst"


@pytest.mark.parametrize("fallback", ["no_fallback", "heliotelligence_if_pvsyst_unresolved"])
def test_disabled_authority_is_clear_and_preserves_blocked_profile(fallback: str) -> None:
    terrain = _terrain(("r",), factors=(0.0,))
    row = _calculate(
        [_receiver("r")],
        terrain,
        _pvsyst(terrain, horizon=70.0),
        state="disabled",
        fallback=fallback,
    ).receiver_authority.iloc[0]
    assert row["pvsyst_profile_horizon_beam_visible_factor"] == 0.0
    assert row["pvsyst_horizon_authority_factor"] == 1.0
    assert row["selected_horizon_beam_visible_factor"] == 1.0
    assert row["selected_horizon_source"] == "pvsyst_project_horizon_disabled"


def test_unknown_activation_no_fallback_and_helio_fallback() -> None:
    terrain = _terrain(("r",), factors=(0.0,))
    pvsyst = _pvsyst(terrain, horizon=50.0)
    refused = _calculate(
        [_receiver("r")], terrain, pvsyst, state="unknown"
    ).receiver_authority.iloc[0]
    fallback = _calculate(
        [_receiver("r")],
        terrain,
        pvsyst,
        state="unknown",
        fallback="heliotelligence_if_pvsyst_unresolved",
    ).receiver_authority.iloc[0]
    assert pd.isna(refused["selected_horizon_beam_visible_factor"])
    assert refused["selected_horizon_state"] == "unresolved_pvsyst_authority"
    assert fallback["selected_horizon_beam_visible_factor"] == 0.0
    assert fallback["selected_horizon_source"] == "heliotelligence_fallback"


@pytest.mark.parametrize("fallback", ["no_fallback", "heliotelligence_if_pvsyst_unresolved"])
def test_both_unresolved_selection_precedes_policy_refusal(fallback: str) -> None:
    selected = _select(30.0, np.nan, False, "none", np.nan, False, fallback)
    assert pd.isna(selected[0]) and selected[1:] == (False, "none", "unresolved_both_sources")


@pytest.mark.parametrize("state", ["enabled", "disabled", "unknown"])
def test_night_overrides_activation(state: str) -> None:
    terrain = _terrain(("r",), zenith=90.0)
    row = _calculate(
        [_receiver("r")], terrain, _pvsyst(terrain), state=state
    ).receiver_authority.iloc[0]
    assert pd.isna(row["selected_horizon_beam_visible_factor"])
    assert row["selected_horizon_state"] == "not_applicable_no_above_horizon_beam"


def test_zero_raw_direct_and_nan_raw_semantics() -> None:
    receivers = [_receiver("a"), _receiver("b")]
    zero = _terrain(("a", "b"), raw=(0.0, 0.0))
    zero_row = _calculate(receivers, zero, _pvsyst(zero)).site_comparison.iloc[0]
    assert zero_row["irradiance_impact_state"] == "resolved_zero_raw_direct"
    assert zero_row["direct_irradiance_delta_helio_minus_pvsyst_wm2"] == 0.0
    missing = _terrain(("a", "b"), raw=(np.nan, 1.0))
    missing_row = _calculate(receivers, missing, _pvsyst(missing)).site_comparison.iloc[0]
    assert missing_row["irradiance_impact_state"] == "unresolved_raw_direct_irradiance"


def test_mixed_zero_positive_does_not_require_zero_receiver_factor_for_impact() -> None:
    raw = np.asarray((0.0, 100.0))
    weights = np.asarray((1.0, 1.0))
    from heliotelligence.physics.pvsyst_horizon_authority import _impact

    result = _impact(raw, weights, 1.0, True, np.asarray((np.nan, 1.0)), np.asarray((False, True)))
    assert result[4] and result[2] == 50.0


def test_profile_binding_solar_state_and_receiver_solar_integrity() -> None:
    receivers = [_receiver("a"), _receiver("b")]
    terrain = _terrain(("a", "b"))
    with pytest.raises(ValueError, match="binding"):
        compare_and_select_pvsyst_far_horizon(
            receivers,
            terrain,
            _pvsyst(terrain),
            activation=_activation(profile_id="other"),
            fallback_policy="no_fallback",
        )
    altered = _pvsyst(terrain)
    altered.horizon.loc[:, "solar_azimuth_deg"] = 181.0
    with pytest.raises(ValueError, match="solar states"):
        _calculate(receivers, terrain, altered)
    terrain_bad = terrain.copy()
    terrain_bad.iloc[1, terrain_bad.columns.get_loc("solar_azimuth_deg")] = 181.0
    with pytest.raises(ValueError, match="solar states"):
        _calculate(receivers, terrain_bad, _pvsyst(terrain))


@pytest.mark.parametrize("column", ["terrain_horizon_model", "terrain_horizon_coverage_scope"])
def test_terrain_provenance_tampering_rejected(column: str) -> None:
    terrain = _terrain(("r",))
    terrain.loc[:, column] = "wrong"
    with pytest.raises(ValueError, match="provenance"):
        _calculate([_receiver("r")], terrain, _pvsyst(terrain))


@pytest.mark.parametrize(
    "column",
    [
        "pvsyst_far_horizon_contract",
        "pvsyst_far_horizon_model",
        "pvsyst_far_horizon_scope",
        "pvsyst_far_horizon_coverage_scope",
        "pvsyst_far_horizon_azimuth_reference",
        "pvsyst_horizon_profile_id",
    ],
)
def test_pvsyst_provenance_tampering_rejected(column: str) -> None:
    terrain = _terrain(("r",))
    pvsyst = _pvsyst(terrain)
    pvsyst.horizon.loc[:, column] = "wrong"
    with pytest.raises(ValueError):
        _calculate([_receiver("r")], terrain, pvsyst)


def test_pvsyst_diagnostics_tampering_rejected() -> None:
    terrain = _terrain(("r",))
    pvsyst = _pvsyst(terrain)
    forged = PVsystFarHorizonResult(pvsyst.horizon, replace(pvsyst.diagnostics, model="wrong"))
    with pytest.raises(ValueError):
        _calculate([_receiver("r")], terrain, forged)


@pytest.mark.parametrize("fallback", [None, "", "other", True])
def test_fallback_policy_is_explicit(fallback: object) -> None:
    terrain = _terrain(("r",))
    with pytest.raises(ValueError, match="fallback_policy"):
        _calculate([_receiver("r")], terrain, _pvsyst(terrain), fallback=fallback)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("activation_state", "other"),
        ("activation_state", True),
        ("profile_id", ""),
        ("project_variant_id", " "),
        ("source_label", None),
        ("source_reference", ""),
        ("evidence_note", " "),
    ],
)
def test_activation_validation(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _activation(**{field: value})  # type: ignore[arg-type]


def test_receiver_and_grid_admission() -> None:
    terrain = _terrain(("r",))
    pvsyst = _pvsyst(terrain)
    invalid_receivers = [
        [],
        [_receiver("r"), _receiver("r")],
        [_receiver("r", kind=ReceiverKind.TRACKER_TABLE)],
    ]
    for receivers in invalid_receivers:
        with pytest.raises(ValueError):
            _calculate(receivers, terrain, pvsyst)
    duplicate = pd.concat((terrain, terrain.iloc[[0]]))
    with pytest.raises(ValueError):
        _calculate([_receiver("r")], duplicate, pvsyst)
    naive = terrain.copy()
    naive.index = pd.MultiIndex.from_arrays(
        [terrain.index.get_level_values(0).tz_localize(None), terrain.index.get_level_values(1)],
        names=terrain.index.names,
    )
    with pytest.raises(ValueError):
        _calculate([_receiver("r")], naive, pvsyst)


def test_empty_determinism_reordering_and_immutability() -> None:
    receivers = [_receiver("b", area=2.0), _receiver("a")]
    terrain = _terrain(("a", "b"), periods=0)
    pvsyst = _pvsyst(terrain)
    activation = _activation()
    originals = (
        deepcopy(receivers),
        terrain.copy(deep=True),
        pvsyst.horizon.copy(deep=True),
        activation,
    )
    first = compare_and_select_pvsyst_far_horizon(
        receivers, terrain, pvsyst, activation=activation, fallback_policy="no_fallback"
    )
    second = compare_and_select_pvsyst_far_horizon(
        list(reversed(receivers)),
        terrain.iloc[::-1],
        pvsyst,
        activation=activation,
        fallback_policy="no_fallback",
    )
    pd.testing.assert_frame_equal(first.receiver_authority, second.receiver_authority)
    pd.testing.assert_frame_equal(first.site_comparison, second.site_comparison)
    assert first.receiver_authority.empty and first.site_comparison.empty
    assert first.diagnostics.receiver_count == 2 and first.diagnostics.timestamp_count == 0
    assert receivers == originals[0]
    pd.testing.assert_frame_equal(terrain, originals[1])
    pd.testing.assert_frame_equal(pvsyst.horizon, originals[2])
    assert activation == originals[3]


def test_output_contract_and_no_pipeline_leakage() -> None:
    terrain = _terrain(("r",))
    result = _calculate([_receiver("r")], terrain, _pvsyst(terrain))
    assert set(result.receiver_authority["pvsyst_horizon_authority_contract"]) == {
        PVSYST_HORIZON_AUTHORITY_CONTRACT_ID
    }
    forbidden = (
        "near_shading",
        "iam",
        "diffuse",
        "rear",
        "electrical",
        "thermal",
        "front_direct_geometric",
    )
    assert not any(
        token in column.lower() for token in forbidden for column in result.receiver_authority
    )
