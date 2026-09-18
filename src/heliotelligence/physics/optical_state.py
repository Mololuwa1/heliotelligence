"""Canonical receiver/time optical-state assembly with guarded composition.

S7A validates and joins mechanism-isolated optical states. It does not apply
IAM, attenuate anisotropic diffuse irradiance, calculate effective irradiance,
or compose front and rear energy.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any, Literal, TypeVar, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.diffuse_sky_visibility import DiffuseSkyVisibility
from heliotelligence.physics.shading import solar_direction_enu

STATE_CONTRACT_ID = "receiver_optical_state_v1"
DIRECT_COMPOSITION_ID = "exact_scalar_direct_visibility_guard_v1"
DIFFUSE_SKY_ROLE = "geometric_visibility_only_not_scalar_perez_attenuation"
RearOpticalMode = Literal["not_applicable", "fixed_bifacial_rear"]
_TOLERANCE = 1e-9
_ANGULAR_TOLERANCE_DEG = 1e-8
_COMMON_FRONT_COLUMNS = (
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "dni_extra_wm2",
)
_T = TypeVar("_T")

_FRONT_COLUMNS = [
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "dni_extra_wm2",
    "aoi_deg",
    "poa_direct_raw_wm2",
    "poa_sky_diffuse_raw_wm2",
    "poa_ground_diffuse_raw_wm2",
    "poa_diffuse_raw_wm2",
    "poa_global_raw_wm2",
    "poa_transposition_resolved",
    "transposition_applied",
    "transposition_state",
    "transposition_model",
]
_IAM_COLUMNS = [
    "aoi_deg",
    "beam_iam_factor",
    "beam_iam_resolved",
    "beam_iam_state",
    "beam_iam_model",
]
_TERRAIN_COLUMNS = [
    "terrain_horizon_beam_visible_factor",
    "blocking_terrain_id",
    "blocking_terrain_distance_m",
    "terrain_horizon_visibility_resolved",
    "terrain_horizon_shading_resolved",
    "terrain_horizon_state",
    "terrain_horizon_model",
    "terrain_horizon_coverage_scope",
]
_FIXED_COLUMNS = [
    "fixed_inter_row_beam_visible_fraction",
    "fixed_inter_row_beam_shaded_fraction",
    "shading_row_id",
    "shading_pitch_m",
    "cross_axis_slope_deg",
    "fixed_row_id",
    "fixed_row_array_id",
    "fixed_inter_row_visibility_resolved",
    "fixed_inter_row_shading_resolved",
    "fixed_inter_row_state",
    "fixed_inter_row_model",
]
_NEAR_COLUMNS = [
    "near_object_beam_visible_fraction",
    "near_object_beam_shaded_fraction",
    "near_object_sample_count",
    "near_object_shaded_sample_count",
    "near_object_visibility_resolved",
    "near_object_shading_resolved",
    "near_object_state",
    "near_object_model",
]
_DIFFUSE_COLUMNS = [
    "diffuse_sky_visible_fraction",
    "diffuse_sky_blocked_fraction",
    "diffuse_sky_visibility_resolved",
    "diffuse_sky_state",
    "diffuse_sky_model",
    "diffuse_sky_coverage_scope",
    "surface_sample_count",
    "sky_direction_count",
    "diffuse_sky_application_role",
]
_DIRECT_COLUMNS = [
    "front_direct_geometric_visible_fraction",
    "front_direct_geometric_shaded_fraction",
    "front_direct_geometric_composition_resolved",
    "front_direct_geometric_state",
    "front_direct_overlap_state",
    "front_direct_composition_model",
]
_REAR_COMPONENTS = [
    "poa_rear_direct_raw_wm2",
    "poa_rear_circumsolar_diffuse_raw_wm2",
    "poa_rear_sky_diffuse_raw_wm2",
    "poa_rear_ground_diffuse_raw_wm2",
    "poa_rear_diffuse_raw_wm2",
    "poa_rear_global_raw_wm2",
    "rear_direct_shaded_fraction",
]
_REAR_PROVENANCE = [
    "rear_irradiance_resolved",
    "rear_irradiance_state",
    "rear_irradiance_model",
    "rear_diffuse_model",
    "rear_coverage_scope",
    "rear_fixed_row_array_id",
    "rear_surface_tilt_deg",
    "rear_surface_azimuth_deg",
    "rear_collector_width_m",
    "rear_pitch_m",
    "rear_gcr",
    "rear_row_center_height_m",
    "rear_albedo",
]
_OUTPUT_COLUMNS = (
    _FRONT_COLUMNS
    + _IAM_COLUMNS[1:]
    + _TERRAIN_COLUMNS
    + _FIXED_COLUMNS
    + _NEAR_COLUMNS
    + _DIFFUSE_COLUMNS
    + _DIRECT_COLUMNS
    + ["rear_mode"]
    + _REAR_COMPONENTS
    + _REAR_PROVENANCE
    + ["optical_state_contract"]
)


@dataclass(frozen=True)
class OpticalStateDiagnostics:
    receiver_count: int
    timestamp_count: int
    row_count: int
    rear_receiver_count: int
    direct_overlap_unresolved_count: int
    state_contract: str


@dataclass(frozen=True)
class OpticalStateResult:
    state: pd.DataFrame
    diagnostics: OpticalStateDiagnostics


def assemble_receiver_optical_state(
    receivers: Sequence[PVReceiver],
    front_poa_by_receiver: Mapping[str, pd.DataFrame],
    beam_iam_by_receiver: Mapping[str, pd.DataFrame],
    terrain_horizon: pd.DataFrame,
    fixed_inter_row: pd.DataFrame,
    near_object: pd.DataFrame,
    diffuse_sky_visibility: DiffuseSkyVisibility,
    *,
    rear_mode_by_receiver: Mapping[str, RearOpticalMode],
    rear_irradiance: pd.DataFrame | None = None,
) -> OpticalStateResult:
    """Validate and assemble canonical optical state without applying modifiers."""
    receiver_values = _validated_receivers(receivers)
    receiver_ids = tuple(sorted(item.id for item in receiver_values))
    receivers_by_id = {item.id: item for item in receiver_values}
    _require_mapping_keys(front_poa_by_receiver, receiver_ids, "front POA")
    _require_mapping_keys(beam_iam_by_receiver, receiver_ids, "beam IAM")
    _require_mapping_keys(rear_mode_by_receiver, receiver_ids, "rear mode")
    for mode in rear_mode_by_receiver.values():
        if mode not in ("not_applicable", "fixed_bifacial_rear"):
            raise ValueError("rear mode must be 'not_applicable' or 'fixed_bifacial_rear'")

    timestamp_index = _validated_front_frames(front_poa_by_receiver, receiver_ids)
    canonical_index = _canonical_index(timestamp_index, receiver_ids)
    terrain = _validated_mechanism_frame(terrain_horizon, canonical_index, "terrain_horizon")
    fixed = _validated_mechanism_frame(fixed_inter_row, canonical_index, "fixed_inter_row")
    near = _validated_mechanism_frame(near_object, canonical_index, "near_object")
    diffuse = _validated_diffuse(diffuse_sky_visibility, receiver_ids, receivers_by_id)
    rear_ids = tuple(
        identifier
        for identifier in receiver_ids
        if rear_mode_by_receiver[identifier] == "fixed_bifacial_rear"
    )
    rear = _validated_rear(rear_irradiance, timestamp_index, rear_ids)

    rows: list[dict[str, object]] = []
    overlap_count = 0
    for timestamp in timestamp_index:
        for receiver_id in receiver_ids:
            receiver = receivers_by_id[receiver_id]
            front = front_poa_by_receiver[receiver_id].loc[timestamp]
            iam = _validated_iam_row(
                beam_iam_by_receiver[receiver_id], timestamp_index, timestamp, front
            )
            _validate_front_row(receiver, front)
            mechanism_key = (timestamp, receiver_id)
            terrain_row = terrain.loc[mechanism_key]
            fixed_row = fixed.loc[mechanism_key]
            near_row = near.loc[mechanism_key]
            for name, mechanism in (
                ("terrain_horizon", terrain_row),
                ("fixed_inter_row", fixed_row),
                ("near_object", near_row),
            ):
                _validate_direct_provenance(name, mechanism, front)
            _validate_factors(terrain_row, fixed_row, near_row)
            direct = _compose_direct(front, terrain_row, fixed_row, near_row)
            if direct["front_direct_overlap_state"] == "unresolved_fixed_near_partial_overlap":
                overlap_count += 1
            diffuse_row = diffuse.loc[receiver_id]
            row = {name: front[name] for name in _FRONT_COLUMNS}
            row.update({name: iam[name] for name in _IAM_COLUMNS[1:]})
            row.update(_terrain_values(terrain_row))
            row.update(_fixed_values(fixed_row))
            row.update(_near_values(near_row))
            row.update({name: diffuse_row[name] for name in _DIFFUSE_COLUMNS[:-1]})
            row["diffuse_sky_application_role"] = DIFFUSE_SKY_ROLE
            row.update(direct)
            mode = rear_mode_by_receiver[receiver_id]
            row["rear_mode"] = mode
            row.update(_rear_values(mode, rear, mechanism_key, front))
            row["optical_state_contract"] = STATE_CONTRACT_ID
            rows.append(row)
    state = _typed_state(pd.DataFrame(rows, columns=_OUTPUT_COLUMNS, index=canonical_index))
    return OpticalStateResult(
        state,
        OpticalStateDiagnostics(
            receiver_count=len(receiver_ids),
            timestamp_count=len(timestamp_index),
            row_count=len(state),
            rear_receiver_count=len(rear_ids),
            direct_overlap_unresolved_count=overlap_count,
            state_contract=STATE_CONTRACT_ID,
        ),
    )


def _validated_receivers(value: object) -> tuple[PVReceiver, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ValueError("receivers must be a non-empty sequence")
    receivers = tuple(value)
    if any(not isinstance(item, PVReceiver) for item in receivers):
        raise ValueError("receivers must contain only PVReceiver values")
    _require_unique((item.id for item in receivers), "receiver IDs")
    for receiver in receivers:
        if receiver.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError(
                "TRACKER_TABLE runtime pose belongs to S6C; S7A v1 cannot assemble "
                "static tracker geometry as operational optical state"
            )
        if receiver.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("S7A v1 accepts only FIXED_TABLE receivers")
    return receivers


def _validated_front_frames(
    frames: Mapping[str, pd.DataFrame], receiver_ids: tuple[str, ...]
) -> pd.DatetimeIndex:
    reference: pd.DatetimeIndex | None = None
    for receiver_id in receiver_ids:
        frame = frames[receiver_id]
        _require_columns(frame, _FRONT_COLUMNS, "front POA")
        index = _validated_time_index(frame.index, "front POA")
        if reference is None:
            reference = index
        elif not index.equals(reference) or index.name != reference.name:
            raise ValueError("all front POA frames must use the exact same timestamp index")
    assert reference is not None
    reference_frame = frames[receiver_ids[0]]
    for receiver_id in receiver_ids[1:]:
        candidate = frames[receiver_id]
        for column in _COMMON_FRONT_COLUMNS:
            reference_values = reference_frame[column].to_numpy(dtype=np.float64)
            candidate_values = candidate[column].to_numpy(dtype=np.float64)
            if column in ("ghi_wm2", "dhi_wm2", "dni_wm2"):
                valid = np.isnan(reference_values) == np.isnan(candidate_values)
                finite = np.isfinite(reference_values) | np.isnan(reference_values)
                candidate_finite = np.isfinite(candidate_values) | np.isnan(candidate_values)
            else:
                valid = np.ones(len(reference_values), dtype=bool)
                finite = np.isfinite(reference_values)
                candidate_finite = np.isfinite(candidate_values)
            equal = np.isclose(
                reference_values,
                candidate_values,
                rtol=1e-12,
                atol=_TOLERANCE,
                equal_nan=True,
            )
            if not np.all(valid & finite & candidate_finite & equal):
                raise ValueError(
                    "inconsistent receiver front meteorology/solar state: "
                    f"{column} differs for receiver {receiver_id!r}"
                )
    return reference


def _validated_iam_row(
    frame: pd.DataFrame,
    index: pd.DatetimeIndex,
    timestamp: pd.Timestamp,
    front: pd.Series,
) -> pd.Series:
    _require_columns(frame, _IAM_COLUMNS, "beam IAM")
    iam_index = _validated_time_index(frame.index, "beam IAM")
    if not iam_index.equals(index) or iam_index.name != index.name:
        raise ValueError("beam IAM index must exactly match front POA")
    row = frame.loc[timestamp]
    if not _same_number(row["aoi_deg"], front["aoi_deg"], _ANGULAR_TOLERANCE_DEG):
        raise ValueError("beam IAM AOI must match front POA AOI")
    if bool(row["beam_iam_resolved"]):
        factor = row["beam_iam_factor"]
        if isinstance(factor, (bool, np.bool_)) or not isinstance(factor, Real):
            raise ValueError("resolved beam IAM factor must be a finite real in [0, 1]")
        factor_value = float(factor)
        if not np.isfinite(factor_value) or not (-_TOLERANCE <= factor_value <= 1.0 + _TOLERANCE):
            raise ValueError("resolved beam IAM factor must be a finite real in [0, 1]")
    return row


def _validate_front_row(receiver: PVReceiver, row: pd.Series) -> None:
    if bool(row["poa_transposition_resolved"]) and (
        not np.isclose(
            float(row["poa_diffuse_raw_wm2"]),
            float(row["poa_sky_diffuse_raw_wm2"]) + float(row["poa_ground_diffuse_raw_wm2"]),
            rtol=1e-12,
            atol=_TOLERANCE,
        )
        or not np.isclose(
            float(row["poa_global_raw_wm2"]),
            float(row["poa_direct_raw_wm2"]) + float(row["poa_diffuse_raw_wm2"]),
            rtol=1e-12,
            atol=_TOLERANCE,
        )
    ):
        raise ValueError("resolved front POA components do not close")
    zenith = float(row["apparent_solar_zenith_deg"])
    azimuth = float(row["solar_azimuth_deg"])
    if zenith < 90.0:
        direction = np.asarray(solar_direction_enu(zenith, azimuth))
    else:
        zenith_rad = np.radians(zenith)
        azimuth_rad = np.radians(azimuth)
        direction = np.asarray(
            (
                np.sin(zenith_rad) * np.sin(azimuth_rad),
                np.sin(zenith_rad) * np.cos(azimuth_rad),
                np.cos(zenith_rad),
            )
        )
    expected = np.degrees(np.arccos(np.clip(np.dot(receiver.normal_enu, direction), -1.0, 1.0)))
    if not _same_number(row["aoi_deg"], expected, _ANGULAR_TOLERANCE_DEG):
        raise ValueError("front POA AOI conflicts with canonical receiver orientation")


def _validated_mechanism_frame(
    frame: pd.DataFrame, canonical: pd.MultiIndex, label: str
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.MultiIndex):
        raise ValueError(f"{label} must use a receiver/time MultiIndex")
    if frame.index.names != canonical.names:
        raise ValueError(f"{label} index names must match canonical receiver/time names")
    if frame.index.has_duplicates:
        raise ValueError(f"{label} contains duplicate receiver/time rows")
    if set(frame.index) != set(canonical) or len(frame) != len(canonical):
        raise ValueError(f"{label} must contain exactly one row per receiver/timestamp")
    return frame.reindex(canonical)


def _validated_diffuse(
    value: object,
    receiver_ids: tuple[str, ...],
    receivers_by_id: Mapping[str, PVReceiver],
) -> pd.DataFrame:
    if not isinstance(value, DiffuseSkyVisibility):
        raise ValueError("diffuse_sky_visibility must be a DiffuseSkyVisibility")
    frame = value.receivers
    normal_columns = (
        "receiver_normal_east",
        "receiver_normal_north",
        "receiver_normal_up",
    )
    required = [*_DIFFUSE_COLUMNS[:-1], *normal_columns]
    _require_columns(frame, required, "diffuse sky visibility")
    if frame["receiver_id"].duplicated().any() or set(frame["receiver_id"]) != set(receiver_ids):
        raise ValueError("diffuse sky visibility requires exactly one row per receiver")
    ordered = frame.set_index("receiver_id").reindex(receiver_ids)
    for receiver_id in receiver_ids:
        supplied = ordered.loc[receiver_id, list(normal_columns)].to_numpy(dtype=np.float64)
        expected = np.asarray(receivers_by_id[receiver_id].normal_enu, dtype=np.float64)
        if not np.all(np.isfinite(supplied)) or not np.allclose(
            supplied, expected, rtol=1e-12, atol=_TOLERANCE
        ):
            raise ValueError("diffuse sky receiver normal does not match canonical PVReceiver")
    return ordered


def _validated_rear(
    frame: pd.DataFrame | None,
    timestamps: pd.DatetimeIndex,
    receiver_ids: tuple[str, ...],
) -> pd.DataFrame | None:
    if not receiver_ids:
        if frame is not None and len(frame):
            raise ValueError("rear data was supplied but all receivers are not_applicable")
        return None
    if frame is None:
        raise ValueError("fixed_bifacial_rear receivers require rear_irradiance")
    required = [
        "ghi_wm2",
        "dhi_wm2",
        "dni_wm2",
        "apparent_solar_zenith_deg",
        "solar_azimuth_deg",
        *_REAR_COMPONENTS,
        "rear_irradiance_resolved",
        "rear_irradiance_state",
        "rear_irradiance_model",
        "rear_diffuse_model",
        "rear_coverage_scope",
        "fixed_row_array_id",
        "rear_surface_tilt_deg",
        "rear_surface_azimuth_deg",
        "collector_width_m",
        "pitch_m",
        "gcr",
        "row_center_height_m",
        "albedo",
    ]
    _require_columns(frame, required, "rear irradiance")
    expected = _canonical_index(timestamps, receiver_ids)
    if not isinstance(frame.index, pd.MultiIndex) or frame.index.has_duplicates:
        raise ValueError("rear irradiance requires unique receiver/time rows")
    if frame.index.names != expected.names:
        raise ValueError("rear irradiance index names must match canonical receiver/time names")
    if set(frame.index) != set(expected) or len(frame) != len(expected):
        raise ValueError("rear irradiance rows must exactly match fixed rear receivers")
    rear = frame.reindex(expected)
    resolved = rear["rear_irradiance_resolved"].astype(bool)
    if resolved.any():
        values = rear.loc[resolved]
        if not np.allclose(
            values["poa_rear_diffuse_raw_wm2"],
            values["poa_rear_sky_diffuse_raw_wm2"] + values["poa_rear_ground_diffuse_raw_wm2"],
            rtol=1e-12,
            atol=_TOLERANCE,
        ) or not np.allclose(
            values["poa_rear_global_raw_wm2"],
            values["poa_rear_direct_raw_wm2"] + values["poa_rear_diffuse_raw_wm2"],
            rtol=1e-12,
            atol=_TOLERANCE,
        ):
            raise ValueError("resolved rear irradiance components do not close")
    return rear


def _validate_direct_provenance(label: str, mechanism: pd.Series, front: pd.Series) -> None:
    for column in ("poa_direct_raw_wm2", "apparent_solar_zenith_deg", "solar_azimuth_deg"):
        if column not in mechanism or not _same_number(
            mechanism[column], front[column], _TOLERANCE
        ):
            raise ValueError(f"{label} {column} does not match canonical front POA")


def _validate_factors(terrain: pd.Series, fixed: pd.Series, near: pd.Series) -> None:
    if bool(terrain["terrain_horizon_visibility_resolved"]):
        value = float(terrain["terrain_horizon_beam_visible_factor"])
        if not (np.isclose(value, 0.0, atol=_TOLERANCE) or np.isclose(value, 1.0, atol=_TOLERANCE)):
            raise ValueError("resolved terrain visibility factor must be binary")
    for label, row, visible, shaded, resolved in (
        (
            "fixed inter-row",
            fixed,
            "fixed_inter_row_beam_visible_fraction",
            "fixed_inter_row_beam_shaded_fraction",
            "fixed_inter_row_visibility_resolved",
        ),
        (
            "near-object",
            near,
            "near_object_beam_visible_fraction",
            "near_object_beam_shaded_fraction",
            "near_object_visibility_resolved",
        ),
    ):
        if bool(row[resolved]):
            left, right = float(row[visible]), float(row[shaded])
            if (
                not (-_TOLERANCE <= left <= 1 + _TOLERANCE)
                or not (-_TOLERANCE <= right <= 1 + _TOLERANCE)
                or not np.isclose(left + right, 1.0, atol=_TOLERANCE)
            ):
                raise ValueError(f"resolved {label} fractions are invalid")


def _compose_direct(
    front: pd.Series, terrain: pd.Series, fixed: pd.Series, near: pd.Series
) -> dict[str, object]:
    base: dict[str, object] = {
        "front_direct_geometric_visible_fraction": np.nan,
        "front_direct_geometric_shaded_fraction": np.nan,
        "front_direct_geometric_composition_resolved": False,
        "front_direct_geometric_state": "unresolved_geometry",
        "front_direct_overlap_state": "not_evaluated",
        "front_direct_composition_model": DIRECT_COMPOSITION_ID,
    }
    zenith = float(front["apparent_solar_zenith_deg"])
    raw = front["poa_direct_raw_wm2"]
    if zenith >= 90.0:
        base["front_direct_geometric_state"] = (
            "not_evaluated_no_above_horizon_direct_beam"
            if _same_number(raw, 0.0, _TOLERANCE)
            else "unresolved_below_horizon_direct_state"
        )
        return base
    if pd.isna(raw):
        base["front_direct_geometric_state"] = "unresolved_upstream_direct_irradiance"
        return base
    if not all(
        bool(value)
        for value in (
            terrain["terrain_horizon_visibility_resolved"],
            fixed["fixed_inter_row_visibility_resolved"],
            near["near_object_visibility_resolved"],
        )
    ):
        return base
    t = _boundary(float(terrain["terrain_horizon_beam_visible_factor"]))
    f = _boundary(float(fixed["fixed_inter_row_beam_visible_fraction"]))
    n = _boundary(float(near["near_object_beam_visible_fraction"]))
    visible: float | None
    overlap = "exact_no_partial_overlap_ambiguity"
    if t == 0.0 or f == 0.0 or n == 0.0:
        visible = 0.0
    elif f == 1.0:
        visible = n
    elif n == 1.0:
        visible = f
    else:
        visible = None
        overlap = "unresolved_fixed_near_partial_overlap"
    if visible is None:
        base["front_direct_geometric_state"] = "unresolved_spatial_overlap"
        base["front_direct_overlap_state"] = overlap
        return base
    base.update(
        {
            "front_direct_geometric_visible_fraction": visible,
            "front_direct_geometric_shaded_fraction": 1.0 - visible,
            "front_direct_geometric_composition_resolved": True,
            "front_direct_geometric_state": "resolved",
            "front_direct_overlap_state": overlap,
        }
    )
    return base


def _terrain_values(row: pd.Series) -> dict[str, object]:
    return {
        "terrain_horizon_beam_visible_factor": row["terrain_horizon_beam_visible_factor"],
        "blocking_terrain_id": row["blocking_terrain_id"],
        "blocking_terrain_distance_m": row["blocking_distance_m"],
        "terrain_horizon_visibility_resolved": row["terrain_horizon_visibility_resolved"],
        "terrain_horizon_shading_resolved": row["terrain_horizon_shading_resolved"],
        "terrain_horizon_state": row["terrain_horizon_state"],
        "terrain_horizon_model": row["terrain_horizon_model"],
        "terrain_horizon_coverage_scope": row["terrain_horizon_coverage_scope"],
    }


def _fixed_values(row: pd.Series) -> dict[str, object]:
    return {name: row[name] for name in _FIXED_COLUMNS}


def _near_values(row: pd.Series) -> dict[str, object]:
    mapping = {
        "near_object_beam_visible_fraction": "near_object_beam_visible_fraction",
        "near_object_beam_shaded_fraction": "near_object_beam_shaded_fraction",
        "near_object_sample_count": "sample_count",
        "near_object_shaded_sample_count": "shaded_sample_count",
        "near_object_visibility_resolved": "near_object_visibility_resolved",
        "near_object_shading_resolved": "near_object_shading_resolved",
        "near_object_state": "near_object_shading_state",
        "near_object_model": "near_object_shading_model",
    }
    return {target: row[source] for target, source in mapping.items()}


def _rear_values(
    mode: RearOpticalMode,
    rear: pd.DataFrame | None,
    key: tuple[pd.Timestamp, str],
    front: pd.Series,
) -> dict[str, object]:
    if mode == "not_applicable":
        output: dict[str, object] = {name: np.nan for name in _REAR_COMPONENTS}
        output.update({name: np.nan for name in _REAR_PROVENANCE})
        output["rear_irradiance_resolved"] = False
        output["rear_irradiance_state"] = "not_applicable"
        return output
    assert rear is not None
    row = rear.loc[key]
    for column in (
        "ghi_wm2",
        "dhi_wm2",
        "dni_wm2",
        "apparent_solar_zenith_deg",
        "solar_azimuth_deg",
    ):
        if not _same_number(row[column], front[column], _TOLERANCE):
            raise ValueError(f"rear irradiance {column} does not match canonical front POA")
    rear_output: dict[str, object] = {name: row[name] for name in _REAR_COMPONENTS}
    rear_output.update(
        {
            "rear_irradiance_resolved": row["rear_irradiance_resolved"],
            "rear_irradiance_state": row["rear_irradiance_state"],
            "rear_irradiance_model": row["rear_irradiance_model"],
            "rear_diffuse_model": row["rear_diffuse_model"],
            "rear_coverage_scope": row["rear_coverage_scope"],
            "rear_fixed_row_array_id": row["fixed_row_array_id"],
            "rear_surface_tilt_deg": row["rear_surface_tilt_deg"],
            "rear_surface_azimuth_deg": row["rear_surface_azimuth_deg"],
            "rear_collector_width_m": row["collector_width_m"],
            "rear_pitch_m": row["pitch_m"],
            "rear_gcr": row["gcr"],
            "rear_row_center_height_m": row["row_center_height_m"],
            "rear_albedo": row["albedo"],
        }
    )
    return rear_output


def _canonical_index(index: pd.DatetimeIndex, receiver_ids: tuple[str, ...]) -> pd.MultiIndex:
    return pd.MultiIndex.from_product([index, receiver_ids], names=[index.name, "receiver_id"])


def _validated_time_index(value: object, label: str) -> pd.DatetimeIndex:
    if not isinstance(value, pd.DatetimeIndex) or value.tz is None:
        raise ValueError(f"{label} requires a timezone-aware DatetimeIndex")
    if value.has_duplicates or value.hasnans:
        raise ValueError(f"{label} timestamps must be unique and contain no NaT")
    return value


def _require_mapping_keys(value: object, receiver_ids: tuple[str, ...], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != set(receiver_ids):
        raise ValueError(f"{label} mapping keys must exactly match receiver IDs")


def _require_columns(frame: object, columns: Sequence[str], label: str) -> None:
    if not isinstance(frame, pd.DataFrame) or not set(columns).issubset(frame.columns):
        raise ValueError(f"{label} is missing required columns")


def _same_number(left: object, right: object, tolerance: float) -> bool:
    if pd.isna(left) or pd.isna(right):
        return bool(pd.isna(left) and pd.isna(right))
    try:
        return bool(
            np.isclose(
                float(cast(Any, left)),
                float(cast(Any, right)),
                rtol=1e-12,
                atol=tolerance,
            )
        )
    except (TypeError, ValueError):
        return False


def _boundary(value: float) -> float:
    if np.isclose(value, 0.0, rtol=0.0, atol=_TOLERANCE):
        return 0.0
    if np.isclose(value, 1.0, rtol=0.0, atol=_TOLERANCE):
        return 1.0
    return value


def _typed_state(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [
        column for column in frame if column.endswith("_resolved") or column.endswith("_applied")
    ]
    integer_columns = [
        "near_object_sample_count",
        "near_object_shaded_sample_count",
        "surface_sample_count",
        "sky_direction_count",
    ]
    string_columns = [
        column
        for column in frame
        if column.endswith("_state")
        or column.endswith("_model")
        or column.endswith("_scope")
        or column.endswith("_role")
        or column
        in (
            "blocking_terrain_id",
            "shading_row_id",
            "fixed_row_id",
            "fixed_row_array_id",
            "rear_mode",
            "rear_fixed_row_array_id",
            "optical_state_contract",
        )
    ]
    for column in bool_columns:
        frame[column] = frame[column].astype("bool")
    for column in integer_columns:
        frame[column] = frame[column].astype("Int64")
    for column in string_columns:
        frame[column] = frame[column].astype("string")
    numeric = set(frame.columns) - set(bool_columns) - set(string_columns) - set(integer_columns)
    for column in numeric:
        frame[column] = frame[column].astype("float64")
    return frame


def _require_unique(values: Iterable[object], label: str) -> None:
    items = tuple(values)
    if any(count > 1 for count in Counter(items).values()):
        raise ValueError(f"{label} must be unique")
