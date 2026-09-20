"""PVsyst-preferred comparison and authority for fixed-table near shading."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.pvsyst_linear_shading import (
    PVSYST_LINEAR_SHADING_CONTRACT_ID,
    PVSYST_LINEAR_SHADING_COVERAGE_SCOPE,
    PVSYST_LINEAR_SHADING_MODEL_ID,
    PVSYST_LINEAR_SHADING_SCOPE,
    PVsystLinearShadingResult,
)

PVSYST_SHADING_AUTHORITY_CONTRACT_ID = "pvsyst_helio_near_shading_authority_v1"
PVSYST_HELIO_COMPARISON_MODEL_ID = "surface_area_weighted_near_shading_comparison_v1"
PVSYST_PREFERRED_POLICY_ID = "pvsyst_preferred_near_shading_v1"
PVSYST_SHADING_AUTHORITY_SCOPE = "fixed_table_near_shading_beam_geometry_only"
PVsystFallbackPolicy = Literal["no_fallback", "heliotelligence_if_pvsyst_unresolved"]

_WEIGHTING = "canonical_receiver_surface_area_m2"
_ATOL = 1e-9
_RTOL = 1e-12
_FIXED_REQUIRED = {
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "fixed_inter_row_beam_visible_fraction",
    "fixed_inter_row_beam_shaded_fraction",
    "fixed_inter_row_visibility_resolved",
    "fixed_inter_row_state",
    "fixed_inter_row_model",
}
_NEAR_REQUIRED = {
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "near_object_beam_visible_fraction",
    "near_object_beam_shaded_fraction",
    "near_object_visibility_resolved",
    "near_object_shading_state",
    "near_object_shading_model",
}
_PVSYST_REQUIRED = {
    "solar_elevation_deg",
    "solar_azimuth_deg",
    "pvsyst_beam_transmission_fraction",
    "pvsyst_beam_shaded_fraction",
    "pvsyst_linear_shading_resolved",
    "pvsyst_linear_shading_state",
    "pvsyst_table_id",
    "pvsyst_orientation_id",
    "pvsyst_zone_id",
    "pvsyst_version",
    "pvsyst_source_label",
    "pvsyst_source_reference",
    "pvsyst_linear_shading_contract",
    "pvsyst_linear_shading_model",
    "pvsyst_linear_shading_coverage_scope",
    "pvsyst_linear_shading_scope",
}
_RECEIVER_COLUMNS = (
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "pvsyst_scope_id",
    "pvsyst_table_id",
    "pvsyst_orientation_id",
    "pvsyst_zone_id",
    "receiver_surface_area_m2",
    "fixed_inter_row_beam_visible_fraction",
    "fixed_inter_row_visibility_resolved",
    "near_object_beam_visible_fraction",
    "near_object_visibility_resolved",
    "helio_near_shading_beam_transmission_fraction",
    "helio_near_shading_beam_shaded_fraction",
    "helio_near_shading_resolved",
    "helio_near_shading_state",
    "pvsyst_near_shading_beam_transmission_fraction",
    "pvsyst_near_shading_beam_shaded_fraction",
    "pvsyst_near_shading_resolved",
    "pvsyst_near_shading_state",
    "selected_near_shading_beam_transmission_fraction",
    "selected_near_shading_beam_shaded_fraction",
    "selected_near_shading_resolved",
    "selected_near_shading_source",
    "selected_near_shading_state",
    "fallback_policy",
    "pvsyst_version",
    "pvsyst_source_label",
    "pvsyst_source_reference",
    "comparison_weighting",
    "pvsyst_shading_authority_contract",
    "pvsyst_helio_comparison_model",
    "pvsyst_shading_authority_policy",
    "pvsyst_shading_authority_scope",
)
_COMPARISON_COLUMNS = (
    "pvsyst_scope_id",
    "pvsyst_table_id",
    "pvsyst_orientation_id",
    "pvsyst_zone_id",
    "receiver_count",
    "helio_resolved_receiver_count",
    "receiver_surface_area_total_m2",
    "pvsyst_near_shading_beam_transmission_fraction",
    "pvsyst_near_shading_resolved",
    "pvsyst_near_shading_state",
    "helio_near_shading_area_weighted_transmission_fraction",
    "helio_near_shading_scope_resolved",
    "helio_near_shading_scope_state",
    "geometry_comparison_resolved",
    "geometry_comparison_state",
    "helio_minus_pvsyst_transmission_delta",
    "absolute_transmission_delta",
    "raw_direct_area_weighted_wm2",
    "pvsyst_direct_after_near_shading_area_weighted_wm2",
    "helio_direct_after_near_shading_area_weighted_wm2",
    "direct_irradiance_delta_helio_minus_pvsyst_wm2",
    "irradiance_impact_resolved",
    "irradiance_impact_state",
    "comparison_weighting",
    "pvsyst_shading_authority_contract",
    "pvsyst_helio_comparison_model",
)


@dataclass(frozen=True)
class PVsystNearShadingScope:
    scope_id: str
    table_id: str
    receiver_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.scope_id, "scope_id")
        _text(self.table_id, "table_id")
        if not isinstance(self.receiver_ids, tuple) or not self.receiver_ids:
            raise ValueError("receiver_ids must be a non-empty tuple")
        for receiver_id in self.receiver_ids:
            _text(receiver_id, "receiver_id")
        if len(set(self.receiver_ids)) != len(self.receiver_ids):
            raise ValueError("scope receiver IDs must be unique")


@dataclass(frozen=True)
class PVsystNearShadingAuthorityDiagnostics:
    receiver_count: int
    scope_count: int
    timestamp_count: int
    receiver_row_count: int
    comparison_row_count: int
    pvsyst_selected_count: int
    helio_fallback_selected_count: int
    unresolved_selection_count: int
    not_applicable_count: int
    geometry_comparable_scope_row_count: int
    area_weighted_bias: float
    area_weighted_mae: float
    area_weighted_rmse: float
    max_abs_transmission_delta: float
    irradiance_impact_comparable_row_count: int
    irradiance_weighted_mae: float
    contract: str
    comparison_model: str
    authority_policy: str


@dataclass(frozen=True)
class PVsystNearShadingAuthorityResult:
    receiver_authority: pd.DataFrame
    scope_comparison: pd.DataFrame
    diagnostics: PVsystNearShadingAuthorityDiagnostics


def compare_and_select_pvsyst_near_shading(
    receivers: Sequence[PVReceiver],
    fixed_inter_row: pd.DataFrame,
    near_object: pd.DataFrame,
    pvsyst_by_table_id: Mapping[str, PVsystLinearShadingResult],
    scopes: Sequence[PVsystNearShadingScope],
    *,
    fallback_policy: PVsystFallbackPolicy,
) -> PVsystNearShadingAuthorityResult:
    """Compare scope-level near shading and select PVsyst-preferred authority."""
    if fallback_policy not in ("no_fallback", "heliotelligence_if_pvsyst_unresolved"):
        raise ValueError("fallback_policy must be explicitly supported")
    receiver_map, areas = _receivers(receivers)
    scope_map, receiver_scope = _scopes(scopes, receiver_map)
    fixed = _frame(fixed_inter_row, tuple(receiver_map), _FIXED_REQUIRED, "fixed inter-row")
    near = _frame(near_object, tuple(receiver_map), _NEAR_REQUIRED, "near object")
    if fixed.index.names != near.index.names or not fixed.index.equals(near.index):
        raise ValueError("fixed inter-row and near-object row sets must match")
    _cross_mechanism(fixed, near)
    pvsyst = _pvsyst_mapping(pvsyst_by_table_id, scope_map, fixed.index)
    authority_rows: list[dict[str, object]] = []
    for index in fixed.index:
        receiver_id = str(index[1])
        scope = receiver_scope[receiver_id]
        pvsyst_row = pvsyst[scope.table_id].loc[index[0]]
        authority_rows.append(
            _receiver_row(
                fixed.loc[index],
                near.loc[index],
                pvsyst_row,
                scope,
                areas[receiver_id],
                fallback_policy,
            )
        )
    authority = pd.DataFrame(authority_rows, index=fixed.index, columns=_RECEIVER_COLUMNS)
    authority = _typed(authority)
    comparison = _scope_comparison(authority, scope_map, areas)
    diagnostics = _diagnostics(authority, comparison, len(receiver_map), len(scope_map))
    return PVsystNearShadingAuthorityResult(authority, comparison, diagnostics)


def _receivers(receivers: object) -> tuple[dict[str, PVReceiver], dict[str, float]]:
    if not isinstance(receivers, Sequence) or isinstance(receivers, (str, bytes)):
        raise ValueError("receivers must be a sequence")
    receiver_map: dict[str, PVReceiver] = {}
    for receiver in receivers:
        if not isinstance(receiver, PVReceiver):
            raise ValueError("receivers must contain PVReceiver values")
        if receiver.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError("S6C runtime tracker pose is required before shading authority")
        if receiver.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("shading authority supports FIXED_TABLE receivers only")
        if receiver.id in receiver_map:
            raise ValueError("receiver IDs must be unique")
        receiver_map[receiver.id] = receiver
    if not receiver_map:
        raise ValueError("receivers must be non-empty")
    ordered = {key: receiver_map[key] for key in sorted(receiver_map)}
    return ordered, {
        key: _area(receiver.mesh.vertices_enu_m, receiver.mesh.faces)
        for key, receiver in ordered.items()
    }


def _area(vertices: np.ndarray, faces: np.ndarray) -> float:  # type: ignore[type-arg]
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


def _scopes(
    scopes: object, receivers: Mapping[str, PVReceiver]
) -> tuple[dict[str, PVsystNearShadingScope], dict[str, PVsystNearShadingScope]]:
    if not isinstance(scopes, Sequence) or isinstance(scopes, (str, bytes)) or not scopes:
        raise ValueError("scopes must be a non-empty sequence")
    by_id: dict[str, PVsystNearShadingScope] = {}
    by_receiver: dict[str, PVsystNearShadingScope] = {}
    for scope in scopes:
        if not isinstance(scope, PVsystNearShadingScope):
            raise ValueError("scopes must contain PVsystNearShadingScope values")
        if scope.scope_id in by_id:
            raise ValueError("scope IDs must be unique")
        by_id[scope.scope_id] = scope
        normals = []
        for receiver_id in scope.receiver_ids:
            if receiver_id not in receivers:
                raise ValueError("scope contains an unknown receiver")
            if receiver_id in by_receiver:
                raise ValueError("receiver is assigned to multiple scopes")
            by_receiver[receiver_id] = scope
            normals.append(receivers[receiver_id].normal_enu)
        if any(not np.allclose(normals[0], normal, atol=1e-9, rtol=0.0) for normal in normals[1:]):
            raise ValueError("receivers in a scope must share one front orientation")
    if set(by_receiver) != set(receivers):
        raise ValueError("every receiver must be assigned to exactly one scope")
    return {key: by_id[key] for key in sorted(by_id)}, by_receiver


def _frame(
    value: object, receiver_ids: tuple[str, ...], required: set[str], label: str
) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame) or not isinstance(value.index, pd.MultiIndex):
        raise ValueError(f"{label} must use a MultiIndex")
    if value.index.nlevels != 2 or value.index.names[1] != "receiver_id":
        raise ValueError(f"{label} index must be timestamp/receiver_id")
    if not required.issubset(value.columns):
        raise ValueError(f"{label} is missing required columns")
    timestamps = value.index.get_level_values(0)
    if not isinstance(timestamps, pd.DatetimeIndex) or timestamps.tz is None:
        raise ValueError(f"{label} timestamps must be timezone-aware")
    if timestamps.hasnans or value.index.has_duplicates:
        raise ValueError(f"{label} index contains NaT or duplicates")
    result = value.copy()
    if len(result):
        if set(result.index.get_level_values("receiver_id")) != set(receiver_ids):
            raise ValueError(f"{label} receiver IDs do not match")
        times = pd.DatetimeIndex(timestamps.unique()).sort_values()
        expected = pd.MultiIndex.from_product((times, receiver_ids), names=result.index.names)
        if set(result.index) != set(expected):
            raise ValueError(f"{label} receiver/timestamp grid is incomplete")
        result = result.reindex(expected)
    return result


def _cross_mechanism(fixed: pd.DataFrame, near: pd.DataFrame) -> None:
    for index in fixed.index:
        for column in ("poa_direct_raw_wm2", "apparent_solar_zenith_deg", "solar_azimuth_deg"):
            left, right = fixed.loc[index, column], near.loc[index, column]
            if pd.isna(left) or pd.isna(right):
                if not (pd.isna(left) and pd.isna(right) and column == "poa_direct_raw_wm2"):
                    raise ValueError(f"fixed/near {column} provenance mismatch")
            elif not np.isclose(_real(left, column), _real(right, column), atol=_ATOL, rtol=_RTOL):
                raise ValueError(f"fixed/near {column} provenance mismatch")


def _pvsyst_mapping(
    mapping: object,
    scopes: Mapping[str, PVsystNearShadingScope],
    canonical_index: pd.MultiIndex,
) -> dict[str, pd.DataFrame]:
    table_ids = {scope.table_id for scope in scopes.values()}
    if not isinstance(mapping, Mapping) or set(mapping) != table_ids:
        raise ValueError("PVsyst table mappings must exactly match referenced table IDs")
    timestamps = pd.DatetimeIndex(canonical_index.get_level_values(0).unique()).sort_values()
    result: dict[str, pd.DataFrame] = {}
    for table_id in sorted(table_ids):
        item = mapping[table_id]
        if not isinstance(item, PVsystLinearShadingResult):
            raise ValueError("PVsyst mappings must contain PVsystLinearShadingResult")
        frame = item.shading.copy()
        if (
            not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.name != timestamps.name
            or not frame.index.equals(timestamps)
        ):
            raise ValueError("PVsyst timestamps must exactly match Helio timestamps")
        if (
            not _PVSYST_REQUIRED.issubset(frame.columns)
            or item.diagnostics.table_id != table_id
            or item.diagnostics.model != PVSYST_LINEAR_SHADING_MODEL_ID
        ):
            raise ValueError("PVsyst result contract or table identity is invalid")
        exact = {
            "pvsyst_table_id": table_id,
            "pvsyst_linear_shading_contract": PVSYST_LINEAR_SHADING_CONTRACT_ID,
            "pvsyst_linear_shading_model": PVSYST_LINEAR_SHADING_MODEL_ID,
            "pvsyst_linear_shading_coverage_scope": PVSYST_LINEAR_SHADING_COVERAGE_SCOPE,
            "pvsyst_linear_shading_scope": PVSYST_LINEAR_SHADING_SCOPE,
        }
        for column, expected in exact.items():
            if any(
                not isinstance(value, str) or value != expected for value in frame[column].array
            ):
                raise ValueError(f"PVsyst {column} provenance is invalid")
        _pvsyst_provenance(frame)
        result[table_id] = frame
    return result


def _receiver_row(
    fixed: pd.Series,
    near: pd.Series,
    pvsyst: pd.Series,
    scope: PVsystNearShadingScope,
    area: float,
    fallback_policy: str,
) -> dict[str, object]:
    raw = _raw(fixed["poa_direct_raw_wm2"])
    zenith = _bounded(fixed["apparent_solar_zenith_deg"], "solar zenith", 0.0, 180.0)
    azimuth = _bounded(fixed["solar_azimuth_deg"], "solar azimuth", 0.0, 360.0, upper_open=True)
    if not np.isclose(
        _real(pvsyst["solar_elevation_deg"], "PVsyst elevation"),
        90.0 - zenith,
        atol=_ATOL,
        rtol=0.0,
    ) or not np.isclose(
        _real(pvsyst["solar_azimuth_deg"], "PVsyst azimuth"), azimuth, atol=_ATOL, rtol=0.0
    ):
        raise ValueError("PVsyst and Helio solar states do not match")
    fixed_factor, fixed_resolved = _mechanism(fixed, "fixed_inter_row")
    near_factor, near_resolved = _mechanism(near, "near_object")
    helio_factor, helio_resolved, helio_state = _helio(
        zenith, fixed_factor, fixed_resolved, near_factor, near_resolved
    )
    pvsyst_factor, pvsyst_resolved, pvsyst_state = _pvsyst_factor(pvsyst, zenith)
    selected, selected_resolved, source, selected_state = _select(
        zenith,
        pvsyst_factor,
        pvsyst_resolved,
        helio_factor,
        helio_resolved,
        fallback_policy,
    )
    return {
        "poa_direct_raw_wm2": raw,
        "apparent_solar_zenith_deg": zenith,
        "solar_azimuth_deg": azimuth,
        "pvsyst_scope_id": scope.scope_id,
        "pvsyst_table_id": scope.table_id,
        "pvsyst_orientation_id": pvsyst["pvsyst_orientation_id"],
        "pvsyst_zone_id": pvsyst["pvsyst_zone_id"],
        "receiver_surface_area_m2": area,
        "fixed_inter_row_beam_visible_fraction": fixed_factor,
        "fixed_inter_row_visibility_resolved": fixed_resolved,
        "near_object_beam_visible_fraction": near_factor,
        "near_object_visibility_resolved": near_resolved,
        "helio_near_shading_beam_transmission_fraction": helio_factor,
        "helio_near_shading_beam_shaded_fraction": 1.0 - helio_factor if helio_resolved else np.nan,
        "helio_near_shading_resolved": helio_resolved,
        "helio_near_shading_state": helio_state,
        "pvsyst_near_shading_beam_transmission_fraction": pvsyst_factor,
        "pvsyst_near_shading_beam_shaded_fraction": 1.0 - pvsyst_factor
        if pvsyst_resolved
        else np.nan,
        "pvsyst_near_shading_resolved": pvsyst_resolved,
        "pvsyst_near_shading_state": pvsyst_state,
        "selected_near_shading_beam_transmission_fraction": selected,
        "selected_near_shading_beam_shaded_fraction": 1.0 - selected
        if selected_resolved
        else np.nan,
        "selected_near_shading_resolved": selected_resolved,
        "selected_near_shading_source": source,
        "selected_near_shading_state": selected_state,
        "fallback_policy": fallback_policy,
        "pvsyst_version": pvsyst["pvsyst_version"],
        "pvsyst_source_label": pvsyst["pvsyst_source_label"],
        "pvsyst_source_reference": pvsyst["pvsyst_source_reference"],
        "comparison_weighting": _WEIGHTING,
        "pvsyst_shading_authority_contract": PVSYST_SHADING_AUTHORITY_CONTRACT_ID,
        "pvsyst_helio_comparison_model": PVSYST_HELIO_COMPARISON_MODEL_ID,
        "pvsyst_shading_authority_policy": PVSYST_PREFERRED_POLICY_ID,
        "pvsyst_shading_authority_scope": PVSYST_SHADING_AUTHORITY_SCOPE,
    }


def _pvsyst_provenance(frame: pd.DataFrame) -> None:
    required = ("pvsyst_orientation_id", "pvsyst_source_label")
    optional = (
        "pvsyst_zone_id",
        "pvsyst_version",
        "pvsyst_source_reference",
    )
    for column in required:
        values = list(frame[column].array)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"PVsyst {column} provenance is invalid")
        if len(set(values)) > 1:
            raise ValueError(f"PVsyst {column} provenance is mixed")
    for column in optional:
        normalized: list[str | None] = []
        for value in frame[column].array:
            if pd.isna(value):
                normalized.append(None)
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"PVsyst {column} provenance is invalid")
            else:
                normalized.append(value)
        if len(set(normalized)) > 1:
            raise ValueError(f"PVsyst {column} provenance is mixed")


def _mechanism(row: pd.Series, prefix: str) -> tuple[float, bool]:
    factor_column = f"{prefix}_beam_visible_fraction"
    shaded_column = f"{prefix}_beam_shaded_fraction"
    resolved = _boolean(row[f"{prefix}_visibility_resolved"], f"{prefix} resolved")
    if not isinstance(
        row[f"{prefix}_model" if prefix == "fixed_inter_row" else f"{prefix}_shading_model"], str
    ):
        raise ValueError(f"{prefix} model provenance is invalid")
    if not resolved:
        if not pd.isna(row[factor_column]) or not pd.isna(row[shaded_column]):
            raise ValueError(f"unresolved {prefix} factors must be NaN")
        return np.nan, False
    factor = _fraction(row[factor_column], factor_column)
    shaded = _fraction(row[shaded_column], shaded_column)
    if not np.isclose(factor + shaded, 1.0, atol=_ATOL, rtol=_RTOL):
        raise ValueError(f"{prefix} visible/shaded closure failed")
    return _edge(factor), True


def _helio(
    zenith: float, fixed: float, fixed_resolved: bool, near: float, near_resolved: bool
) -> tuple[float, bool, str]:
    if zenith >= 90.0:
        return np.nan, False, "not_applicable_no_above_horizon_beam"
    if not fixed_resolved or not near_resolved:
        return np.nan, False, "unresolved_mechanism_visibility"
    if fixed == 0.0 or near == 0.0:
        return 0.0, True, "resolved"
    if fixed == 1.0:
        return near, True, "resolved"
    if near == 1.0:
        return fixed, True, "resolved"
    return np.nan, False, "unresolved_fixed_near_partial_overlap"


def _pvsyst_factor(row: pd.Series, zenith: float) -> tuple[float, bool, str]:
    resolved = _boolean(row["pvsyst_linear_shading_resolved"], "PVsyst resolved")
    state = row["pvsyst_linear_shading_state"]
    if not isinstance(state, str) or not state:
        raise ValueError("PVsyst state is invalid")
    if zenith >= 90.0:
        if (
            resolved
            or not pd.isna(row["pvsyst_beam_transmission_fraction"])
            or not pd.isna(row["pvsyst_beam_shaded_fraction"])
        ):
            raise ValueError("PVsyst night state is inconsistent")
        return np.nan, False, "not_applicable_no_above_horizon_beam"
    if resolved:
        factor = _fraction(row["pvsyst_beam_transmission_fraction"], "PVsyst factor")
        shaded = _fraction(row["pvsyst_beam_shaded_fraction"], "PVsyst shaded factor")
        if state != "resolved" or not np.isclose(factor + shaded, 1.0, atol=_ATOL, rtol=_RTOL):
            raise ValueError("PVsyst resolved state is inconsistent")
        return _edge(factor), True, state
    if not pd.isna(row["pvsyst_beam_transmission_fraction"]) or not pd.isna(
        row["pvsyst_beam_shaded_fraction"]
    ):
        raise ValueError("unresolved PVsyst factors must be NaN")
    return np.nan, False, state


def _select(
    zenith: float,
    pvsyst: float,
    pvsyst_resolved: bool,
    helio: float,
    helio_resolved: bool,
    fallback_policy: str,
) -> tuple[float, bool, str, str]:
    if zenith >= 90.0:
        return np.nan, False, "none", "not_applicable_no_above_horizon_beam"
    if pvsyst_resolved:
        return pvsyst, True, "pvsyst", "resolved_pvsyst_authority"
    if fallback_policy == "heliotelligence_if_pvsyst_unresolved" and helio_resolved:
        return helio, True, "heliotelligence_fallback", "resolved_heliotelligence_fallback"
    if fallback_policy == "no_fallback":
        return np.nan, False, "none", "unresolved_pvsyst_authority"
    return np.nan, False, "none", "unresolved_both_sources"


def _scope_comparison(
    authority: pd.DataFrame,
    scopes: Mapping[str, PVsystNearShadingScope],
    areas: Mapping[str, float],
) -> pd.DataFrame:
    timestamps = pd.DatetimeIndex(authority.index.get_level_values(0).unique()).sort_values()
    rows: list[dict[str, object]] = []
    for timestamp in timestamps:
        for scope in scopes.values():
            group = authority.loc[(timestamp, list(scope.receiver_ids)), :]
            rows.append(_comparison_row(group, scope, areas))
    result_index = pd.MultiIndex.from_product(
        (timestamps, tuple(scopes)), names=(authority.index.names[0], "pvsyst_scope_id")
    )
    frame = pd.DataFrame(rows, index=result_index, columns=_COMPARISON_COLUMNS)
    return _typed(frame)


def _comparison_row(
    group: pd.DataFrame, scope: PVsystNearShadingScope, areas: Mapping[str, float]
) -> dict[str, object]:
    receiver_ids = [str(value) for value in group.index.get_level_values("receiver_id")]
    weights = np.asarray([areas[value] for value in receiver_ids])
    total_area = float(weights.sum())
    helio_resolved = group["helio_near_shading_resolved"].to_numpy(dtype=bool)
    pvsyst_resolved = bool(group["pvsyst_near_shading_resolved"].iloc[0])
    helio_count = int(helio_resolved.sum())
    helio_scope_resolved = bool(helio_resolved.all())
    helio_scope = (
        float(
            np.dot(
                weights,
                group["helio_near_shading_beam_transmission_fraction"].to_numpy(dtype=float),
            )
            / total_area
        )
        if helio_scope_resolved
        else np.nan
    )
    pvsyst_factor = (
        float(group["pvsyst_near_shading_beam_transmission_fraction"].iloc[0])
        if pvsyst_resolved
        else np.nan
    )
    comparable = pvsyst_resolved and helio_scope_resolved
    delta = helio_scope - pvsyst_factor if comparable else np.nan
    raw = group["poa_direct_raw_wm2"].to_numpy(dtype=float)
    raw_average, pvsyst_after, helio_after, impact_delta, impact_resolved, impact_state = _impact(
        raw,
        weights,
        pvsyst_factor,
        pvsyst_resolved,
        group["helio_near_shading_beam_transmission_fraction"].to_numpy(dtype=float),
        helio_resolved,
    )
    first = group.iloc[0]
    return {
        "pvsyst_scope_id": scope.scope_id,
        "pvsyst_table_id": scope.table_id,
        "pvsyst_orientation_id": first["pvsyst_orientation_id"],
        "pvsyst_zone_id": first["pvsyst_zone_id"],
        "receiver_count": len(group),
        "helio_resolved_receiver_count": helio_count,
        "receiver_surface_area_total_m2": total_area,
        "pvsyst_near_shading_beam_transmission_fraction": pvsyst_factor,
        "pvsyst_near_shading_resolved": pvsyst_resolved,
        "pvsyst_near_shading_state": first["pvsyst_near_shading_state"],
        "helio_near_shading_area_weighted_transmission_fraction": helio_scope,
        "helio_near_shading_scope_resolved": helio_scope_resolved,
        "helio_near_shading_scope_state": "resolved"
        if helio_scope_resolved
        else "unresolved_receiver_dependency",
        "geometry_comparison_resolved": comparable,
        "geometry_comparison_state": "resolved" if comparable else "unresolved_source_dependency",
        "helio_minus_pvsyst_transmission_delta": delta,
        "absolute_transmission_delta": abs(delta) if comparable else np.nan,
        "raw_direct_area_weighted_wm2": raw_average,
        "pvsyst_direct_after_near_shading_area_weighted_wm2": pvsyst_after,
        "helio_direct_after_near_shading_area_weighted_wm2": helio_after,
        "direct_irradiance_delta_helio_minus_pvsyst_wm2": impact_delta,
        "irradiance_impact_resolved": impact_resolved,
        "irradiance_impact_state": impact_state,
        "comparison_weighting": _WEIGHTING,
        "pvsyst_shading_authority_contract": PVSYST_SHADING_AUTHORITY_CONTRACT_ID,
        "pvsyst_helio_comparison_model": PVSYST_HELIO_COMPARISON_MODEL_ID,
    }


def _impact(
    raw: np.ndarray,  # type: ignore[type-arg]
    weights: np.ndarray,  # type: ignore[type-arg]
    pvsyst_factor: float,
    pvsyst_resolved: bool,
    helio_factors: np.ndarray,  # type: ignore[type-arg]
    helio_resolved: np.ndarray,  # type: ignore[type-arg]
) -> tuple[float, float, float, float, bool, str]:
    if np.isnan(raw).any():
        return np.nan, np.nan, np.nan, np.nan, False, "unresolved_raw_direct_irradiance"
    raw_average = float(np.dot(weights, raw) / weights.sum())
    positive = raw > _ATOL
    if not positive.any():
        return raw_average, 0.0, 0.0, 0.0, True, "resolved_zero_raw_direct"
    if not pvsyst_resolved:
        return raw_average, np.nan, np.nan, np.nan, False, "unresolved_pvsyst_near_shading"
    if not helio_resolved[positive].all():
        return raw_average, np.nan, np.nan, np.nan, False, "unresolved_helio_near_shading"
    pvsyst_after = float(np.dot(weights, raw * pvsyst_factor) / weights.sum())
    helio_contributions = np.where(positive, raw * helio_factors, 0.0)
    helio_after = float(np.dot(weights, helio_contributions) / weights.sum())
    return raw_average, pvsyst_after, helio_after, helio_after - pvsyst_after, True, "resolved"


def _diagnostics(
    authority: pd.DataFrame, comparison: pd.DataFrame, receiver_count: int, scope_count: int
) -> PVsystNearShadingAuthorityDiagnostics:
    comparable = comparison[comparison["geometry_comparison_resolved"]]
    if len(comparable):
        weights = comparable["receiver_surface_area_total_m2"].to_numpy(dtype=float)
        delta = comparable["helio_minus_pvsyst_transmission_delta"].to_numpy(dtype=float)
        denominator = float(weights.sum())
        bias = float(np.dot(weights, delta) / denominator)
        mae = float(np.dot(weights, np.abs(delta)) / denominator)
        rmse = float(np.sqrt(np.dot(weights, delta**2) / denominator))
        maximum = float(np.max(np.abs(delta)))
        raw = comparable["raw_direct_area_weighted_wm2"].to_numpy(dtype=float)
        positive = np.isfinite(raw) & (raw > _ATOL)
        irradiance_denominator = float(np.dot(weights[positive], raw[positive]))
        irradiance_mae = (
            float(
                np.dot(weights[positive] * raw[positive], np.abs(delta[positive]))
                / irradiance_denominator
            )
            if irradiance_denominator > 0.0
            else np.nan
        )
    else:
        bias = mae = rmse = maximum = irradiance_mae = np.nan
    timestamps = authority.index.get_level_values(0).nunique()
    sources = authority["selected_near_shading_source"]
    states = authority["selected_near_shading_state"]
    return PVsystNearShadingAuthorityDiagnostics(
        receiver_count,
        scope_count,
        timestamps,
        len(authority),
        len(comparison),
        int((sources == "pvsyst").sum()),
        int((sources == "heliotelligence_fallback").sum()),
        int((~authority["selected_near_shading_resolved"]).sum()),
        int((states == "not_applicable_no_above_horizon_beam").sum()),
        len(comparable),
        bias,
        mae,
        rmse,
        maximum,
        int(comparison["irradiance_impact_resolved"].sum()),
        irradiance_mae,
        PVSYST_SHADING_AUTHORITY_CONTRACT_ID,
        PVSYST_HELIO_COMPARISON_MODEL_ID,
        PVSYST_PREFERRED_POLICY_ID,
    )


def _raw(value: object) -> float:
    if pd.isna(value):
        return np.nan
    return _bounded(value, "raw direct irradiance", 0.0, np.inf)


def _real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite non-Boolean real")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be a finite non-Boolean real")
    return result


def _bounded(
    value: object, name: str, lower: float, upper: float, *, upper_open: bool = False
) -> float:
    result = _real(value, name)
    if result < lower or result > upper or (upper_open and result >= upper):
        raise ValueError(f"{name} is outside its valid range")
    return result


def _fraction(value: object, name: str) -> float:
    return _bounded(value, name, 0.0, 1.0)


def _edge(value: float) -> float:
    if abs(value) <= _ATOL:
        return 0.0
    if abs(value - 1.0) <= _ATOL:
        return 1.0
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a Boolean")
    return bool(value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [column for column in frame if column.endswith("_resolved")]
    integer_columns = [column for column in frame if column.endswith("_count")]
    string_columns = [
        column
        for column in frame
        if column.endswith(("_id", "_state", "_model", "_policy", "_scope"))
        or column
        in {
            "pvsyst_zone_id",
            "selected_near_shading_source",
            "fallback_policy",
            "pvsyst_version",
            "pvsyst_source_label",
            "pvsyst_source_reference",
            "comparison_weighting",
            "pvsyst_shading_authority_contract",
        }
    ]
    for column in bool_columns:
        frame[column] = frame[column].astype(bool)
    for column in integer_columns:
        frame[column] = frame[column].astype("int64")
    for column in string_columns:
        frame[column] = frame[column].astype("string")
    for column in set(frame) - set(bool_columns) - set(integer_columns) - set(string_columns):
        frame[column] = frame[column].astype(float)
    return frame
