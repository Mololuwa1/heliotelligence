"""PVsyst-preferred far-horizon comparison and authority selection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from numpy.typing import NDArray

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.pvsyst_far_horizon import (
    PVSYST_FAR_HORIZON_AZIMUTH_REFERENCE,
    PVSYST_FAR_HORIZON_CONTRACT_ID,
    PVSYST_FAR_HORIZON_COVERAGE_SCOPE,
    PVSYST_FAR_HORIZON_MODEL_ID,
    PVSYST_FAR_HORIZON_SCOPE,
    PVsystFarHorizonResult,
)
from heliotelligence.physics.terrain_horizon import COVERAGE_SCOPE, MODEL_ID

PVSYST_HORIZON_AUTHORITY_CONTRACT_ID = "pvsyst_helio_far_horizon_authority_v1"
PVSYST_HORIZON_COMPARISON_MODEL_ID = "receiver_area_weighted_far_horizon_visibility_comparison_v1"
PVSYST_HORIZON_PREFERRED_POLICY_ID = "pvsyst_preferred_far_horizon_v1"
PVSYST_HORIZON_AUTHORITY_SCOPE = "fixed_table_far_horizon_beam_geometry_only"
HORIZON_COMPARISON_WEIGHTING = "canonical_receiver_surface_area_m2"

PVsystHorizonActivationState = Literal["enabled", "disabled", "unknown"]
PVsystHorizonFallbackPolicy = Literal["no_fallback", "heliotelligence_if_pvsyst_unresolved"]

_ATOL = 1e-9
_RTOL = 1e-12
_HELIO_REQUIRED = {
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "terrain_horizon_beam_visible_factor",
    "blocking_terrain_id",
    "blocking_distance_m",
    "terrain_horizon_visibility_resolved",
    "terrain_horizon_state",
    "terrain_horizon_model",
    "terrain_horizon_coverage_scope",
}
_PVSYST_REQUIRED = {
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
}
_RECEIVER_COLUMNS = (
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "receiver_surface_area_m2",
    "terrain_horizon_beam_visible_factor",
    "terrain_horizon_visibility_resolved",
    "terrain_horizon_state",
    "blocking_terrain_id",
    "blocking_distance_m",
    "pvsyst_horizon_profile_id",
    "pvsyst_horizon_elevation_deg",
    "pvsyst_horizon_clearance_deg",
    "pvsyst_profile_horizon_beam_visible_factor",
    "pvsyst_profile_horizon_visibility_resolved",
    "pvsyst_profile_horizon_state",
    "profile_geometry_comparison_resolved",
    "profile_geometry_comparison_state",
    "helio_minus_pvsyst_profile_visibility_delta",
    "absolute_profile_visibility_delta",
    "pvsyst_horizon_activation_state",
    "pvsyst_project_variant_id",
    "pvsyst_activation_source_label",
    "pvsyst_activation_source_reference",
    "pvsyst_activation_evidence_note",
    "pvsyst_horizon_authority_factor",
    "pvsyst_horizon_authority_resolved",
    "pvsyst_horizon_authority_source",
    "pvsyst_horizon_authority_state",
    "selected_horizon_beam_visible_factor",
    "selected_horizon_visibility_resolved",
    "selected_horizon_source",
    "selected_horizon_state",
    "fallback_policy",
    "pvsyst_version",
    "pvsyst_source_label",
    "pvsyst_source_reference",
    "comparison_weighting",
    "pvsyst_horizon_authority_contract",
    "pvsyst_horizon_comparison_model",
    "pvsyst_horizon_authority_policy",
    "pvsyst_horizon_authority_scope",
)
_SITE_COLUMNS = (
    "pvsyst_horizon_profile_id",
    "receiver_count",
    "helio_resolved_receiver_count",
    "receiver_surface_area_total_m2",
    "pvsyst_profile_horizon_beam_visible_factor",
    "pvsyst_profile_horizon_visibility_resolved",
    "helio_horizon_area_weighted_visible_fraction",
    "helio_horizon_site_resolved",
    "profile_geometry_comparison_resolved",
    "profile_geometry_comparison_state",
    "helio_minus_pvsyst_profile_visibility_delta",
    "absolute_profile_visibility_delta",
    "raw_direct_area_weighted_wm2",
    "pvsyst_profile_direct_after_horizon_area_weighted_wm2",
    "helio_direct_after_horizon_area_weighted_wm2",
    "direct_irradiance_delta_helio_minus_pvsyst_wm2",
    "irradiance_impact_resolved",
    "irradiance_impact_state",
    "comparison_weighting",
    "pvsyst_horizon_authority_contract",
    "pvsyst_horizon_comparison_model",
)


@dataclass(frozen=True)
class PVsystHorizonActivation:
    profile_id: str
    project_variant_id: str
    activation_state: PVsystHorizonActivationState
    source_label: str
    source_reference: str | None = None
    evidence_note: str | None = None

    def __post_init__(self) -> None:
        _text(self.profile_id, "profile_id")
        _text(self.project_variant_id, "project_variant_id")
        _text(self.source_label, "source_label")
        _optional_text(self.source_reference, "source_reference")
        _optional_text(self.evidence_note, "evidence_note")
        if self.activation_state not in ("enabled", "disabled", "unknown"):
            raise ValueError("activation_state must be enabled, disabled, or unknown")


@dataclass(frozen=True)
class PVsystFarHorizonAuthorityDiagnostics:
    receiver_count: int
    timestamp_count: int
    receiver_row_count: int
    site_comparison_row_count: int
    pvsyst_enabled_selected_count: int
    pvsyst_disabled_clear_selected_count: int
    helio_fallback_selected_count: int
    unresolved_selection_count: int
    not_applicable_count: int
    profile_comparable_receiver_row_count: int
    profile_agreement_count: int
    profile_disagreement_count: int
    pvsyst_visible_helio_blocked_count: int
    pvsyst_blocked_helio_visible_count: int
    site_comparable_timestamp_count: int
    area_weighted_bias: float
    area_weighted_mae: float
    max_abs_visibility_delta: float
    irradiance_impact_comparable_timestamp_count: int
    irradiance_weighted_mae: float
    activation_state: str
    project_variant_id: str
    contract: str
    comparison_model: str
    authority_policy: str


@dataclass(frozen=True)
class PVsystFarHorizonAuthorityResult:
    receiver_authority: pd.DataFrame
    site_comparison: pd.DataFrame
    diagnostics: PVsystFarHorizonAuthorityDiagnostics


def compare_and_select_pvsyst_far_horizon(
    receivers: Sequence[PVReceiver],
    helio_terrain_horizon: pd.DataFrame,
    pvsyst_horizon: PVsystFarHorizonResult,
    *,
    activation: PVsystHorizonActivation,
    fallback_policy: PVsystHorizonFallbackPolicy,
) -> PVsystFarHorizonAuthorityResult:
    """Compare profile/terrain visibility and select project horizon authority."""
    if fallback_policy not in ("no_fallback", "heliotelligence_if_pvsyst_unresolved"):
        raise ValueError("fallback_policy must be explicitly supported")
    if not isinstance(activation, PVsystHorizonActivation):
        raise ValueError("activation must be PVsystHorizonActivation")
    receiver_map, areas = _receivers(receivers)
    helio = _helio_frame(helio_terrain_horizon, tuple(receiver_map))
    pvsyst = _pvsyst_frame(pvsyst_horizon, helio, activation)
    rows: list[dict[str, object]] = []
    for index in helio.index:
        rows.append(
            _receiver_row(
                helio.loc[index],
                pvsyst.loc[index[0]],
                areas[str(index[1])],
                activation,
                fallback_policy,
            )
        )
    authority = _typed(pd.DataFrame(rows, index=helio.index, columns=_RECEIVER_COLUMNS))
    site = _site_comparison(authority)
    if tuple(authority.columns) != _RECEIVER_COLUMNS or tuple(site.columns) != _SITE_COLUMNS:
        raise RuntimeError("PVsyst horizon authority output schema changed unexpectedly")
    diagnostics = _diagnostics(authority, site, len(receiver_map), activation)
    return PVsystFarHorizonAuthorityResult(authority, site, diagnostics)


def _receivers(receivers: object) -> tuple[dict[str, PVReceiver], dict[str, float]]:
    if not isinstance(receivers, Sequence) or isinstance(receivers, (str, bytes)):
        raise ValueError("receivers must be a sequence")
    values: dict[str, PVReceiver] = {}
    for receiver in receivers:
        if not isinstance(receiver, PVReceiver):
            raise ValueError("receivers must contain PVReceiver values")
        if receiver.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError("S6C runtime tracker pose is required before horizon authority")
        if receiver.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("horizon authority supports FIXED_TABLE receivers only")
        if receiver.id in values:
            raise ValueError("receiver IDs must be unique")
        values[receiver.id] = receiver
    if not values:
        raise ValueError("receivers must be non-empty")
    ordered = {key: values[key] for key in sorted(values)}
    return ordered, {key: _area(value) for key, value in ordered.items()}


def _area(receiver: PVReceiver) -> float:
    vertices, faces = receiver.mesh.vertices_enu_m, receiver.mesh.faces
    triangles = vertices[faces]
    area = float(
        np.sum(
            0.5
            * np.linalg.norm(
                np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
                axis=1,
            )
        )
    )
    if not np.isfinite(area) or area <= 0.0:
        raise ValueError("receiver mesh surface area must be finite and positive")
    return area


def _helio_frame(value: object, receiver_ids: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame) or not isinstance(value.index, pd.MultiIndex):
        raise ValueError("Helio terrain horizon must use a MultiIndex")
    if value.index.nlevels != 2 or value.index.names[1] != "receiver_id":
        raise ValueError("Helio index must be timestamp/receiver_id")
    if not _HELIO_REQUIRED.issubset(value.columns):
        raise ValueError("Helio terrain horizon is missing required columns")
    timestamps = value.index.get_level_values(0)
    if not isinstance(timestamps, pd.DatetimeIndex) or timestamps.tz is None:
        raise ValueError("Helio timestamps must be timezone-aware")
    if timestamps.hasnans or value.index.has_duplicates:
        raise ValueError("Helio index contains NaT or duplicates")
    result = value.copy()
    if len(result):
        if set(result.index.get_level_values("receiver_id")) != set(receiver_ids):
            raise ValueError("Helio receiver IDs do not match")
        times = pd.DatetimeIndex(timestamps.unique()).sort_values()
        expected = pd.MultiIndex.from_product((times, receiver_ids), names=result.index.names)
        if set(result.index) != set(expected):
            raise ValueError("Helio receiver/timestamp grid is incomplete")
        result = result.reindex(expected)
    _validate_helio(result)
    return result


def _validate_helio(frame: pd.DataFrame) -> None:
    for timestamp in frame.index.get_level_values(0).unique():
        group = frame.loc[timestamp]
        zeniths = [
            _bounded(v, "solar zenith", 0.0, 180.0) for v in group["apparent_solar_zenith_deg"]
        ]
        azimuths = [
            _bounded(v, "solar azimuth", 0.0, 360.0, upper_open=True)
            for v in group["solar_azimuth_deg"]
        ]
        if any(not np.isclose(v, zeniths[0], atol=_ATOL, rtol=0.0) for v in zeniths[1:]) or any(
            not np.isclose(v, azimuths[0], atol=_ATOL, rtol=0.0) for v in azimuths[1:]
        ):
            raise ValueError("Helio receiver solar states must agree per timestamp")
    for _, row in frame.iterrows():
        _raw(row["poa_direct_raw_wm2"])
        if (
            row["terrain_horizon_model"] != MODEL_ID
            or row["terrain_horizon_coverage_scope"] != COVERAGE_SCOPE
        ):
            raise ValueError("Helio terrain provenance is invalid")
        zenith = _bounded(row["apparent_solar_zenith_deg"], "solar zenith", 0.0, 180.0)
        resolved = _boolean(row["terrain_horizon_visibility_resolved"], "Helio resolved")
        factor = row["terrain_horizon_beam_visible_factor"]
        if zenith < 90.0:
            if not resolved or _binary(factor, "Helio terrain factor") not in (0.0, 1.0):
                raise ValueError("Helio above-horizon visibility is invalid")
        elif resolved or not pd.isna(factor):
            raise ValueError("Helio night visibility is invalid")


def _pvsyst_frame(
    value: object, helio: pd.DataFrame, activation: PVsystHorizonActivation
) -> pd.DataFrame:
    if not isinstance(value, PVsystFarHorizonResult):
        raise ValueError("pvsyst_horizon must be PVsystFarHorizonResult")
    frame = value.horizon.copy()
    timestamps = pd.DatetimeIndex(helio.index.get_level_values(0).unique()).sort_values()
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or frame.index.tz is None
        or frame.index.hasnans
        or frame.index.has_duplicates
        or frame.index.name != timestamps.name
        or frame.index.tz != timestamps.tz
        or not frame.index.equals(timestamps)
    ):
        raise ValueError("PVsyst timestamps must exactly match Helio timestamps")
    if (
        not _PVSYST_REQUIRED.issubset(frame.columns)
        or value.diagnostics.model != PVSYST_FAR_HORIZON_MODEL_ID
        or activation.profile_id != value.diagnostics.profile_id
    ):
        raise ValueError("PVsyst result contract or profile binding is invalid")
    exact = {
        "pvsyst_horizon_profile_id": value.diagnostics.profile_id,
        "pvsyst_far_horizon_azimuth_reference": PVSYST_FAR_HORIZON_AZIMUTH_REFERENCE,
        "pvsyst_far_horizon_contract": PVSYST_FAR_HORIZON_CONTRACT_ID,
        "pvsyst_far_horizon_model": PVSYST_FAR_HORIZON_MODEL_ID,
        "pvsyst_far_horizon_coverage_scope": PVSYST_FAR_HORIZON_COVERAGE_SCOPE,
        "pvsyst_far_horizon_scope": PVSYST_FAR_HORIZON_SCOPE,
    }
    for column, expected in exact.items():
        if any(not isinstance(item, str) or item != expected for item in frame[column].array):
            raise ValueError(f"PVsyst {column} provenance is invalid")
    _pvsyst_provenance(frame)
    visible = blocked = not_applicable = 0
    for _, row in frame.iterrows():
        elevation = _bounded(row["solar_elevation_deg"], "PVsyst elevation", -90.0, 90.0)
        _bounded(row["solar_azimuth_deg"], "PVsyst azimuth", 0.0, 360.0, upper_open=True)
        horizon = _bounded(row["pvsyst_horizon_elevation_deg"], "horizon elevation", -90.0, 90.0)
        clearance = _real(row["pvsyst_horizon_clearance_deg"], "horizon clearance")
        if not np.isclose(clearance, elevation - horizon, atol=_ATOL, rtol=_RTOL):
            raise ValueError("PVsyst horizon clearance is invalid")
        resolved = _boolean(row["pvsyst_horizon_visibility_resolved"], "PVsyst resolved")
        factor, state = row["pvsyst_horizon_beam_visible_factor"], row["pvsyst_horizon_state"]
        if elevation <= 0.0:
            if resolved or not pd.isna(factor) or state != "not_applicable_no_above_horizon_beam":
                raise ValueError("PVsyst night state is invalid")
            not_applicable += 1
        else:
            expected_factor = 1.0 if clearance > 1e-12 else 0.0
            expected_state = (
                "resolved_visible_above_far_horizon"
                if expected_factor
                else "resolved_blocked_by_far_horizon"
            )
            if (
                not resolved
                or _binary(factor, "PVsyst profile factor") != expected_factor
                or state != expected_state
            ):
                raise ValueError("PVsyst resolved state is invalid")
            visible += int(expected_factor == 1.0)
            blocked += int(expected_factor == 0.0)
    d = value.diagnostics
    if (
        d.timestamp_count != len(frame)
        or d.resolved_count != visible + blocked
        or d.visible_count != visible
        or d.blocked_count != blocked
        or d.not_applicable_count != not_applicable
    ):
        raise ValueError("PVsyst diagnostics are inconsistent")
    return frame


def _pvsyst_provenance(frame: pd.DataFrame) -> None:
    for column in ("pvsyst_source_label",):
        values = list(frame[column].array)
        if any(not isinstance(v, str) or not v.strip() for v in values) or len(set(values)) > 1:
            raise ValueError(f"PVsyst {column} provenance is invalid")
    for column in ("pvsyst_version", "pvsyst_source_reference"):
        optional_values: list[str | None] = []
        for value in frame[column].array:
            if pd.isna(value):
                optional_values.append(None)
            elif isinstance(value, str) and value.strip():
                optional_values.append(value)
            else:
                raise ValueError(f"PVsyst {column} provenance is invalid")
        if len(set(optional_values)) > 1:
            raise ValueError(f"PVsyst {column} provenance is mixed")


def _receiver_row(
    helio: pd.Series,
    pvsyst: pd.Series,
    area: float,
    activation: PVsystHorizonActivation,
    fallback_policy: str,
) -> dict[str, object]:
    raw = _raw(helio["poa_direct_raw_wm2"])
    zenith = _bounded(helio["apparent_solar_zenith_deg"], "solar zenith", 0.0, 180.0)
    azimuth = _bounded(helio["solar_azimuth_deg"], "solar azimuth", 0.0, 360.0, upper_open=True)
    elevation = _bounded(pvsyst["solar_elevation_deg"], "PVsyst elevation", -90.0, 90.0)
    if not np.isclose(elevation, 90.0 - zenith, atol=_ATOL, rtol=0.0) or not np.isclose(
        _real(pvsyst["solar_azimuth_deg"], "PVsyst azimuth"), azimuth, atol=_ATOL, rtol=0.0
    ):
        raise ValueError("PVsyst and Helio solar states do not match")
    helio_resolved = _boolean(helio["terrain_horizon_visibility_resolved"], "Helio resolved")
    helio_factor = (
        _binary(helio["terrain_horizon_beam_visible_factor"], "Helio factor")
        if helio_resolved
        else np.nan
    )
    profile_resolved = _boolean(pvsyst["pvsyst_horizon_visibility_resolved"], "PVsyst resolved")
    profile_factor = (
        _binary(pvsyst["pvsyst_horizon_beam_visible_factor"], "PVsyst factor")
        if profile_resolved
        else np.nan
    )
    comparable = zenith < 90.0 and helio_resolved and profile_resolved
    delta = helio_factor - profile_factor if comparable else np.nan
    comparison_state = _comparison_state(zenith, comparable, profile_factor, helio_factor)
    authority_factor, authority_resolved, authority_source, authority_state = _project_authority(
        zenith, profile_factor, profile_resolved, activation.activation_state
    )
    selected, selected_resolved, selected_source, selected_state = _select(
        zenith,
        authority_factor,
        authority_resolved,
        authority_source,
        helio_factor,
        helio_resolved,
        fallback_policy,
    )
    return {
        "poa_direct_raw_wm2": raw,
        "apparent_solar_zenith_deg": zenith,
        "solar_azimuth_deg": azimuth,
        "receiver_surface_area_m2": area,
        "terrain_horizon_beam_visible_factor": helio_factor,
        "terrain_horizon_visibility_resolved": helio_resolved,
        "terrain_horizon_state": helio["terrain_horizon_state"],
        "blocking_terrain_id": helio["blocking_terrain_id"],
        "blocking_distance_m": helio["blocking_distance_m"],
        "pvsyst_horizon_profile_id": pvsyst["pvsyst_horizon_profile_id"],
        "pvsyst_horizon_elevation_deg": pvsyst["pvsyst_horizon_elevation_deg"],
        "pvsyst_horizon_clearance_deg": pvsyst["pvsyst_horizon_clearance_deg"],
        "pvsyst_profile_horizon_beam_visible_factor": profile_factor,
        "pvsyst_profile_horizon_visibility_resolved": profile_resolved,
        "pvsyst_profile_horizon_state": pvsyst["pvsyst_horizon_state"],
        "profile_geometry_comparison_resolved": comparable,
        "profile_geometry_comparison_state": comparison_state,
        "helio_minus_pvsyst_profile_visibility_delta": delta,
        "absolute_profile_visibility_delta": abs(delta) if comparable else np.nan,
        "pvsyst_horizon_activation_state": activation.activation_state,
        "pvsyst_project_variant_id": activation.project_variant_id,
        "pvsyst_activation_source_label": activation.source_label,
        "pvsyst_activation_source_reference": activation.source_reference,
        "pvsyst_activation_evidence_note": activation.evidence_note,
        "pvsyst_horizon_authority_factor": authority_factor,
        "pvsyst_horizon_authority_resolved": authority_resolved,
        "pvsyst_horizon_authority_source": authority_source,
        "pvsyst_horizon_authority_state": authority_state,
        "selected_horizon_beam_visible_factor": selected,
        "selected_horizon_visibility_resolved": selected_resolved,
        "selected_horizon_source": selected_source,
        "selected_horizon_state": selected_state,
        "fallback_policy": fallback_policy,
        "pvsyst_version": pvsyst["pvsyst_version"],
        "pvsyst_source_label": pvsyst["pvsyst_source_label"],
        "pvsyst_source_reference": pvsyst["pvsyst_source_reference"],
        "comparison_weighting": HORIZON_COMPARISON_WEIGHTING,
        "pvsyst_horizon_authority_contract": PVSYST_HORIZON_AUTHORITY_CONTRACT_ID,
        "pvsyst_horizon_comparison_model": PVSYST_HORIZON_COMPARISON_MODEL_ID,
        "pvsyst_horizon_authority_policy": PVSYST_HORIZON_PREFERRED_POLICY_ID,
        "pvsyst_horizon_authority_scope": PVSYST_HORIZON_AUTHORITY_SCOPE,
    }


def _comparison_state(zenith: float, comparable: bool, pvsyst: float, helio: float) -> str:
    if zenith >= 90.0:
        return "not_applicable_no_above_horizon_beam"
    if not comparable:
        return "unresolved_profile_geometry_comparison"
    if pvsyst == helio:
        return "agreement_visible" if pvsyst == 1.0 else "agreement_blocked"
    return (
        "disagreement_pvsyst_visible_helio_blocked"
        if pvsyst == 1.0
        else "disagreement_pvsyst_blocked_helio_visible"
    )


def _project_authority(
    zenith: float, profile: float, resolved: bool, activation: str
) -> tuple[float, bool, str, str]:
    if zenith >= 90.0:
        return np.nan, False, "none", "not_applicable_no_above_horizon_beam"
    if activation == "disabled":
        return (
            1.0,
            True,
            "pvsyst_project_horizon_disabled",
            "resolved_project_horizon_disabled_clear",
        )
    if activation == "unknown":
        return np.nan, False, "none", "unresolved_project_horizon_activation_unknown"
    if resolved:
        return profile, True, "pvsyst", "resolved_pvsyst_horizon_authority"
    return np.nan, False, "none", "unresolved_pvsyst_profile_visibility"


def _select(
    zenith: float,
    authority: float,
    authority_resolved: bool,
    authority_source: str,
    helio: float,
    helio_resolved: bool,
    fallback_policy: str,
) -> tuple[float, bool, str, str]:
    if zenith >= 90.0:
        return np.nan, False, "none", "not_applicable_no_above_horizon_beam"
    if authority_resolved:
        state = (
            "resolved_pvsyst_project_horizon_disabled_clear"
            if authority_source == "pvsyst_project_horizon_disabled"
            else "resolved_pvsyst_horizon_authority"
        )
        return authority, True, authority_source, state
    if not helio_resolved:
        return np.nan, False, "none", "unresolved_both_sources"
    if fallback_policy == "heliotelligence_if_pvsyst_unresolved":
        return helio, True, "heliotelligence_fallback", "resolved_heliotelligence_fallback"
    return np.nan, False, "none", "unresolved_pvsyst_authority"


def _site_comparison(authority: pd.DataFrame) -> pd.DataFrame:
    timestamps = pd.DatetimeIndex(authority.index.get_level_values(0).unique()).sort_values()
    rows = [_site_row(authority.loc[timestamp]) for timestamp in timestamps]
    frame = pd.DataFrame(rows, index=timestamps, columns=_SITE_COLUMNS)
    frame.index.name = authority.index.names[0]
    return _typed(frame)


def _site_row(group: pd.DataFrame) -> dict[str, object]:
    weights = group["receiver_surface_area_m2"].to_numpy(dtype=float)
    total = float(weights.sum())
    helio_resolved = group["terrain_horizon_visibility_resolved"].to_numpy(dtype=bool)
    profile_resolved = bool(group["pvsyst_profile_horizon_visibility_resolved"].iloc[0])
    helio_site_resolved = bool(helio_resolved.all())
    helio = (
        float(
            np.dot(weights, group["terrain_horizon_beam_visible_factor"].to_numpy(dtype=float))
            / total
        )
        if helio_site_resolved
        else np.nan
    )
    profile = (
        float(group["pvsyst_profile_horizon_beam_visible_factor"].iloc[0])
        if profile_resolved
        else np.nan
    )
    comparable = profile_resolved and helio_site_resolved
    delta = helio - profile if comparable else np.nan
    raw = group["poa_direct_raw_wm2"].to_numpy(dtype=float)
    raw_avg, p_after, h_after, impact_delta, impact_resolved, impact_state = _impact(
        raw,
        weights,
        profile,
        profile_resolved,
        group["terrain_horizon_beam_visible_factor"].to_numpy(dtype=float),
        helio_resolved,
    )
    return {
        "pvsyst_horizon_profile_id": group["pvsyst_horizon_profile_id"].iloc[0],
        "receiver_count": len(group),
        "helio_resolved_receiver_count": int(helio_resolved.sum()),
        "receiver_surface_area_total_m2": total,
        "pvsyst_profile_horizon_beam_visible_factor": profile,
        "pvsyst_profile_horizon_visibility_resolved": profile_resolved,
        "helio_horizon_area_weighted_visible_fraction": helio,
        "helio_horizon_site_resolved": helio_site_resolved,
        "profile_geometry_comparison_resolved": comparable,
        "profile_geometry_comparison_state": "resolved"
        if comparable
        else "unresolved_source_dependency",
        "helio_minus_pvsyst_profile_visibility_delta": delta,
        "absolute_profile_visibility_delta": abs(delta) if comparable else np.nan,
        "raw_direct_area_weighted_wm2": raw_avg,
        "pvsyst_profile_direct_after_horizon_area_weighted_wm2": p_after,
        "helio_direct_after_horizon_area_weighted_wm2": h_after,
        "direct_irradiance_delta_helio_minus_pvsyst_wm2": impact_delta,
        "irradiance_impact_resolved": impact_resolved,
        "irradiance_impact_state": impact_state,
        "comparison_weighting": HORIZON_COMPARISON_WEIGHTING,
        "pvsyst_horizon_authority_contract": PVSYST_HORIZON_AUTHORITY_CONTRACT_ID,
        "pvsyst_horizon_comparison_model": PVSYST_HORIZON_COMPARISON_MODEL_ID,
    }


def _impact(
    raw: NDArray[np.float64],
    weights: NDArray[np.float64],
    profile: float,
    profile_resolved: bool,
    helio: NDArray[np.float64],
    helio_resolved: NDArray[np.bool_],
) -> tuple[float, float, float, float, bool, str]:
    if np.isnan(raw).any():
        return np.nan, np.nan, np.nan, np.nan, False, "unresolved_raw_direct_irradiance"
    raw_avg = float(np.dot(weights, raw) / weights.sum())
    positive = raw > _ATOL
    if not positive.any():
        return raw_avg, 0.0, 0.0, 0.0, True, "resolved_zero_raw_direct"
    if not profile_resolved:
        return raw_avg, np.nan, np.nan, np.nan, False, "unresolved_pvsyst_profile_visibility"
    if not helio_resolved[positive].all():
        return raw_avg, np.nan, np.nan, np.nan, False, "unresolved_helio_terrain_visibility"
    p_after = float(np.dot(weights, raw * profile) / weights.sum())
    h_after = float(np.dot(weights, np.where(positive, raw * helio, 0.0)) / weights.sum())
    return raw_avg, p_after, h_after, h_after - p_after, True, "resolved"


def _diagnostics(
    authority: pd.DataFrame,
    site: pd.DataFrame,
    receiver_count: int,
    activation: PVsystHorizonActivation,
) -> PVsystFarHorizonAuthorityDiagnostics:
    comparable = authority[authority["profile_geometry_comparison_resolved"]]
    if len(comparable):
        weights = comparable["receiver_surface_area_m2"].to_numpy(dtype=float)
        delta = comparable["helio_minus_pvsyst_profile_visibility_delta"].to_numpy(dtype=float)
        bias = float(np.dot(weights, delta) / weights.sum())
        mae = float(np.dot(weights, np.abs(delta)) / weights.sum())
        maximum = float(np.max(np.abs(delta)))
        raw = comparable["poa_direct_raw_wm2"].to_numpy(dtype=float)
        positive = np.isfinite(raw) & (raw > _ATOL)
        denominator = float(np.dot(weights[positive], raw[positive]))
        irradiance_mae = (
            float(np.dot(weights[positive] * raw[positive], np.abs(delta[positive])) / denominator)
            if denominator > 0
            else np.nan
        )
    else:
        bias = mae = maximum = irradiance_mae = np.nan
    sources, states = authority["selected_horizon_source"], authority["selected_horizon_state"]
    return PVsystFarHorizonAuthorityDiagnostics(
        receiver_count,
        authority.index.get_level_values(0).nunique(),
        len(authority),
        len(site),
        int((sources == "pvsyst").sum()),
        int((sources == "pvsyst_project_horizon_disabled").sum()),
        int((sources == "heliotelligence_fallback").sum()),
        int((~authority["selected_horizon_visibility_resolved"]).sum()),
        int((states == "not_applicable_no_above_horizon_beam").sum()),
        len(comparable),
        int((comparable["helio_minus_pvsyst_profile_visibility_delta"] == 0).sum()),
        int((comparable["helio_minus_pvsyst_profile_visibility_delta"] != 0).sum()),
        int((comparable["helio_minus_pvsyst_profile_visibility_delta"] == -1).sum()),
        int((comparable["helio_minus_pvsyst_profile_visibility_delta"] == 1).sum()),
        int(site["profile_geometry_comparison_resolved"].sum()),
        bias,
        mae,
        maximum,
        int(site["irradiance_impact_resolved"].sum()),
        irradiance_mae,
        activation.activation_state,
        activation.project_variant_id,
        PVSYST_HORIZON_AUTHORITY_CONTRACT_ID,
        PVSYST_HORIZON_COMPARISON_MODEL_ID,
        PVSYST_HORIZON_PREFERRED_POLICY_ID,
    )


def _raw(value: object) -> float:
    if pd.isna(value):
        return np.nan
    return _bounded(value, "raw direct irradiance", 0.0, np.inf)


def _real(value: object, name: str) -> float:
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, Real)
        or not np.isfinite(float(value))
    ):
        raise ValueError(f"{name} must be a finite non-Boolean real")
    return float(value)


def _bounded(
    value: object, name: str, lower: float, upper: float, *, upper_open: bool = False
) -> float:
    result = _real(value, name)
    if result < lower or result > upper or (upper_open and result >= upper):
        raise ValueError(f"{name} is outside its valid range")
    return result


def _binary(value: object, name: str) -> float:
    result = _bounded(value, name, 0.0, 1.0)
    if result not in (0.0, 1.0):
        raise ValueError(f"{name} must be exactly binary")
    return result


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a Boolean")
    return bool(value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [c for c in frame if c.endswith("_resolved")]
    integer_columns = [c for c in frame if c.endswith("_count")]
    string_columns = [
        c
        for c in frame
        if c.endswith(
            ("_id", "_state", "_model", "_policy", "_scope", "_source", "_reference", "_note")
        )
        or c
        in {
            "fallback_policy",
            "pvsyst_version",
            "pvsyst_source_label",
            "pvsyst_activation_source_label",
            "comparison_weighting",
            "pvsyst_horizon_authority_contract",
        }
    ]
    object_columns = [c for c in frame if c == "blocking_terrain_id"]
    for c in bool_columns:
        frame[c] = frame[c].astype(bool)
    for c in integer_columns:
        frame[c] = frame[c].astype("int64")
    for c in string_columns:
        frame[c] = frame[c].astype("string")
    for c in (
        set(frame)
        - set(bool_columns)
        - set(integer_columns)
        - set(string_columns)
        - set(object_columns)
    ):
        frame[c] = frame[c].astype(float)
    return frame
