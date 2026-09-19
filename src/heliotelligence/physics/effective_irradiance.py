"""Component-resolved fixed-table front optical effective irradiance."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pvlib.atmosphere  # type: ignore[import-untyped]
import pvlib.irradiance  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.diffuse_iam import (
    DiffuseIAMResult,
    calculate_diffuse_iam,
)
from heliotelligence.physics.diffuse_sky_visibility import (
    DIFFUSE_JOINT_OPTICAL_MODEL_ID,
    DiffuseComponentOpticalTransmission,
)
from heliotelligence.physics.iam import BeamIAMModel, calculate_beam_iam
from heliotelligence.physics.optical_state import STATE_CONTRACT_ID, OpticalStateResult

EFFECTIVE_IRRADIANCE_MODEL_ID = "component_resolved_front_optical_effective_irradiance_v1"
DIFFUSE_COMPONENT_MODEL_ID = "pvlib_perez_component_reconstruction_v1"
EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE = "fixed_table_front_surface_only"
EFFECTIVE_IRRADIANCE_SCOPE = "front_surface_only"
_TOLERANCE = 1e-9

_OUTPUT_COLUMNS = [
    "surface_tilt_deg",
    "surface_azimuth_deg",
    "poa_front_direct_raw_wm2",
    "poa_front_circumsolar_raw_wm2",
    "poa_front_isotropic_raw_wm2",
    "poa_front_horizon_raw_wm2",
    "poa_front_ground_diffuse_raw_wm2",
    "poa_front_sky_diffuse_raw_wm2",
    "poa_front_global_raw_wm2",
    "transposition_model",
    "diffuse_component_model",
    "front_direct_geometric_visible_fraction",
    "diffuse_sky_visible_fraction",
    "diffuse_horizon_visible_fraction",
    "diffuse_ground_visible_fraction",
    "poa_front_direct_after_geometry_wm2",
    "poa_front_circumsolar_after_geometry_wm2",
    "poa_front_isotropic_after_geometry_wm2",
    "poa_front_horizon_after_geometry_wm2",
    "poa_front_ground_diffuse_after_geometry_wm2",
    "beam_iam_factor",
    "diffuse_sky_marion_unobstructed_iam_reference",
    "diffuse_horizon_marion_unobstructed_iam_reference",
    "diffuse_ground_marion_unobstructed_iam_reference",
    "diffuse_sky_visible_region_iam_factor",
    "diffuse_horizon_visible_region_iam_factor",
    "diffuse_ground_visible_region_iam_factor",
    "diffuse_sky_joint_optical_transmission_factor",
    "diffuse_horizon_joint_optical_transmission_factor",
    "diffuse_ground_joint_optical_transmission_factor",
    "diffuse_joint_optical_model",
    "diffuse_iam_model",
    "iam_parameter_resolution_method",
    "iam_parameter_source_label",
    "iam_parameter_source_reference",
    "iam_parameter_is_fallback",
    "poa_front_direct_effective_wm2",
    "poa_front_circumsolar_effective_wm2",
    "poa_front_isotropic_effective_wm2",
    "poa_front_horizon_effective_wm2",
    "poa_front_ground_diffuse_effective_wm2",
    "poa_front_sky_diffuse_effective_wm2",
    "poa_front_diffuse_effective_wm2",
    "poa_front_effective_optical_wm2",
    "front_direct_effective_resolved",
    "front_circumsolar_effective_resolved",
    "front_isotropic_effective_resolved",
    "front_horizon_effective_resolved",
    "front_ground_diffuse_effective_resolved",
    "front_effective_irradiance_resolved",
    "front_effective_irradiance_state",
    "rear_mode",
    "effective_irradiance_model",
    "effective_irradiance_coverage_scope",
    "effective_irradiance_scope",
]

_GEOMETRY_COLUMNS = (
    "poa_front_direct_after_geometry_wm2",
    "poa_front_circumsolar_after_geometry_wm2",
    "poa_front_isotropic_after_geometry_wm2",
    "poa_front_horizon_after_geometry_wm2",
    "poa_front_ground_diffuse_after_geometry_wm2",
)
_EFFECTIVE_COMPONENT_COLUMNS = (
    "poa_front_direct_effective_wm2",
    "poa_front_circumsolar_effective_wm2",
    "poa_front_isotropic_effective_wm2",
    "poa_front_horizon_effective_wm2",
    "poa_front_ground_diffuse_effective_wm2",
)
_RESOLVED_COMPONENT_COLUMNS = (
    "front_direct_effective_resolved",
    "front_circumsolar_effective_resolved",
    "front_isotropic_effective_resolved",
    "front_horizon_effective_resolved",
    "front_ground_diffuse_effective_resolved",
)
_TOTAL_COLUMNS = (
    "poa_front_sky_diffuse_effective_wm2",
    "poa_front_diffuse_effective_wm2",
    "poa_front_effective_optical_wm2",
)


@dataclass(frozen=True)
class FrontEffectiveIrradianceDiagnostics:
    receiver_count: int
    timestamp_count: int
    row_count: int
    resolved_row_count: int
    unresolved_row_count: int
    transposition_model: str | None
    effective_irradiance_model: str


@dataclass(frozen=True)
class FrontEffectiveIrradianceResult:
    irradiance: pd.DataFrame
    diagnostics: FrontEffectiveIrradianceDiagnostics


def calculate_front_effective_irradiance(
    receivers: Sequence[PVReceiver],
    optical_state: OpticalStateResult,
    diffuse_component_visibility: DiffuseComponentOpticalTransmission,
    *,
    beam_iam_parameters_by_receiver: Mapping[str, Mapping[str, object]],
) -> FrontEffectiveIrradianceResult:
    """Apply validated front geometry and IAM component by component."""
    receiver_values = _validated_receivers(receivers)
    receiver_ids = tuple(sorted(receiver.id for receiver in receiver_values))
    receivers_by_id = {receiver.id: receiver for receiver in receiver_values}
    if not isinstance(optical_state, OpticalStateResult):
        raise ValueError("optical_state must be an OpticalStateResult")
    state = _validated_state(optical_state.state, receiver_ids)
    visibility = _validated_component_visibility(
        diffuse_component_visibility, receiver_ids, receivers_by_id, state
    )
    if not isinstance(beam_iam_parameters_by_receiver, Mapping) or set(
        beam_iam_parameters_by_receiver
    ) != set(receiver_ids):
        raise ValueError("beam IAM parameter keys must exactly match receiver IDs")

    resolved_models = set(
        state.loc[state["poa_transposition_resolved"].astype(bool), "transposition_model"]
    )
    if not resolved_models.issubset({"perez", "perez-driesse"}):
        raise ValueError("resolved transposition model must be perez or perez-driesse")
    if len(resolved_models) > 1:
        raise ValueError("resolved transposition model must be common across optical state")
    common_model = str(next(iter(resolved_models))) if resolved_models else None

    receiver_context: dict[str, tuple[float, float, DiffuseIAMResult, Mapping[str, object]]] = {}
    timestamp_index = state.index.get_level_values(0).unique()
    for receiver_id in receiver_ids:
        receiver = receivers_by_id[receiver_id]
        tilt, azimuth = _orientation(receiver)
        parameters = _validated_parameter_resolution(beam_iam_parameters_by_receiver[receiver_id])
        receiver_state = _receiver_state(state, receiver_id)
        model = cast(BeamIAMModel, parameters["model"])
        visibility_row = visibility.loc[receiver_id]
        if visibility_row["diffuse_joint_beam_iam_model"] != model or visibility_row[
            "diffuse_joint_beam_iam_parameter_signature"
        ] != _parameter_signature(cast(Mapping[str, object], parameters["model_parameters"])):
            raise ValueError(
                "joint diffuse optical IAM parameters do not match beam IAM parameters"
            )
        reproduced = calculate_beam_iam(
            pd.Series(
                receiver_state["aoi_deg"].to_numpy(dtype=np.float64),
                index=timestamp_index,
                dtype=float,
            ),
            model=model,
            model_parameters=cast(Mapping[str, object], parameters["model_parameters"]),
        )
        _validate_reproduced_iam(receiver_state, reproduced, model)
        diffuse_iam = calculate_diffuse_iam(
            surface_tilt_deg=tilt,
            beam_iam_model=model,
            model_parameters=cast(Mapping[str, object], parameters["model_parameters"]),
        )
        receiver_context[receiver_id] = (tilt, azimuth, diffuse_iam, parameters)

    component_frames: dict[str, pd.DataFrame] = {}
    for receiver_id in receiver_ids:
        receiver_state = _receiver_state(state, receiver_id)
        tilt, azimuth, _, _ = receiver_context[receiver_id]
        component_frames[receiver_id] = _reconstruct_components(receiver_state, tilt, azimuth)

    rows: list[dict[str, object]] = []
    for key, source in state.iterrows():
        timestamp, receiver_id = key
        receiver_id = str(receiver_id)
        tilt, azimuth, diffuse_iam, parameters = receiver_context[receiver_id]
        component = component_frames[receiver_id].loc[timestamp]
        visibility_row = visibility.loc[receiver_id]
        rows.append(
            _effective_row(
                source,
                component,
                visibility_row,
                tilt,
                azimuth,
                diffuse_iam,
                parameters,
            )
        )
    output = _typed_result(pd.DataFrame(rows, index=state.index, columns=_OUTPUT_COLUMNS))
    resolved_count = int(output["front_effective_irradiance_resolved"].sum())
    return FrontEffectiveIrradianceResult(
        output,
        FrontEffectiveIrradianceDiagnostics(
            receiver_count=len(receiver_ids),
            timestamp_count=len(timestamp_index),
            row_count=len(output),
            resolved_row_count=resolved_count,
            unresolved_row_count=len(output) - resolved_count,
            transposition_model=common_model,
            effective_irradiance_model=EFFECTIVE_IRRADIANCE_MODEL_ID,
        ),
    )


def _validated_receivers(value: object) -> tuple[PVReceiver, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ValueError("receivers must be a non-empty sequence")
    receivers = tuple(value)
    if any(not isinstance(receiver, PVReceiver) for receiver in receivers):
        raise ValueError("receivers must contain only PVReceiver values")
    _require_unique((receiver.id for receiver in receivers), "receiver IDs")
    for receiver in receivers:
        if receiver.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError(
                "S6C runtime tracker pose is required before tracker optical composition"
            )
        if receiver.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("S7B-2 accepts only FIXED_TABLE receivers")
    return receivers


def _validated_state(frame: pd.DataFrame, receiver_ids: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("optical state must use a timestamp/receiver MultiIndex")
    if frame.index.names[1] != "receiver_id":
        raise ValueError("optical state receiver index level must be named receiver_id")
    timestamps = frame.index.get_level_values(0)
    if not isinstance(timestamps, pd.DatetimeIndex) or timestamps.tz is None:
        raise ValueError("optical state timestamps must be timezone-aware")
    if timestamps.hasnans or frame.index.has_duplicates:
        raise ValueError("optical state timestamps/receiver rows must be unique and contain no NaT")
    if len(frame) and set(frame.index.get_level_values("receiver_id")) != set(receiver_ids):
        raise ValueError("optical state receiver IDs must exactly match canonical receivers")
    if not (frame["optical_state_contract"] == STATE_CONTRACT_ID).all():
        raise ValueError("optical state contract is not receiver_optical_state_v1")
    expected = pd.MultiIndex.from_product(
        [timestamps.unique(), receiver_ids], names=frame.index.names
    )
    if not frame.index.equals(expected):
        raise ValueError("optical state must use deterministic timestamp/receiver ordering")
    return frame


def _validated_component_visibility(
    value: object,
    receiver_ids: tuple[str, ...],
    receivers_by_id: Mapping[str, PVReceiver],
    state: pd.DataFrame,
) -> pd.DataFrame:
    if not isinstance(value, DiffuseComponentOpticalTransmission):
        raise ValueError(
            "diffuse_component_visibility must be DiffuseComponentOpticalTransmission"
        )
    frame = value.receivers
    required = {
        "receiver_id",
        "receiver_normal_east",
        "receiver_normal_north",
        "receiver_normal_up",
        "diffuse_sky_visible_fraction",
        "diffuse_sky_blocked_fraction",
        "diffuse_sky_visibility_resolved",
        "diffuse_sky_state",
        "diffuse_sky_model",
        "diffuse_sky_coverage_scope",
        "diffuse_horizon_visible_fraction",
        "diffuse_horizon_blocked_fraction",
        "diffuse_horizon_visibility_resolved",
        "diffuse_horizon_state",
        "diffuse_horizon_model",
        "diffuse_horizon_coverage_scope",
        "diffuse_ground_visible_fraction",
        "diffuse_ground_blocked_fraction",
        "diffuse_ground_visibility_resolved",
        "diffuse_ground_state",
        "diffuse_ground_model",
        "diffuse_ground_coverage_scope",
        "ground_plane_z_m",
        "diffuse_joint_optical_model",
        "diffuse_joint_beam_iam_model",
        "diffuse_joint_beam_iam_parameter_signature",
    }
    for component in ("sky", "horizon", "ground"):
        required.update(
            {
                f"diffuse_{component}_unobstructed_iam_factor",
                f"diffuse_{component}_visible_region_iam_factor",
                f"diffuse_{component}_joint_optical_transmission_factor",
                f"diffuse_{component}_joint_optical_resolved",
                f"diffuse_{component}_joint_optical_state",
            }
        )
    if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
        raise ValueError("diffuse component visibility is missing required columns")
    if frame["receiver_id"].duplicated().any() or set(frame["receiver_id"]) != set(receiver_ids):
        raise ValueError("diffuse component visibility requires exactly one row per receiver")
    ordered = frame.set_index("receiver_id").reindex(receiver_ids)
    for receiver_id in receiver_ids:
        row = ordered.loc[receiver_id]
        normal = np.asarray(
            [row["receiver_normal_east"], row["receiver_normal_north"], row["receiver_normal_up"]],
            dtype=np.float64,
        )
        if not np.allclose(
            normal,
            np.asarray(receivers_by_id[receiver_id].normal_enu),
            rtol=1e-12,
            atol=_TOLERANCE,
        ):
            raise ValueError("diffuse component receiver normal conflicts with canonical receiver")
        receiver_state = _receiver_state(state, receiver_id)
        for column in (
            "diffuse_sky_visible_fraction",
            "diffuse_sky_blocked_fraction",
        ):
            if not _series_matches(receiver_state[column], row[column]):
                raise ValueError("S7B-1 sky visibility does not match admitted S7A S6D state")
        for column in (
            "diffuse_sky_visibility_resolved",
            "diffuse_sky_state",
            "diffuse_sky_model",
            "diffuse_sky_coverage_scope",
        ):
            if not (receiver_state[column] == row[column]).all():
                raise ValueError("S7B-1 sky provenance does not match admitted S7A S6D state")
        for component in ("sky", "horizon", "ground"):
            _validate_visibility_factor(row, component)
            _validate_joint_factor(row, component)
        if row["diffuse_joint_optical_model"] != DIFFUSE_JOINT_OPTICAL_MODEL_ID:
            raise ValueError("diffuse joint optical model is not supported")
    return ordered


def _validate_joint_factor(row: pd.Series, component: str) -> None:
    if not bool(row[f"diffuse_{component}_joint_optical_resolved"]):
        return
    factor = row[f"diffuse_{component}_joint_optical_transmission_factor"]
    if isinstance(factor, (bool, np.bool_)) or pd.isna(factor):
        raise ValueError(f"resolved diffuse {component} joint optical factor is invalid")
    value = float(cast(Any, factor))
    if not np.isfinite(value) or value < -_TOLERANCE or value > 1.0 + _TOLERANCE:
        raise ValueError(f"resolved diffuse {component} joint optical factor is invalid")


def _validated_parameter_resolution(value: object) -> Mapping[str, object]:
    required = {
        "model",
        "model_parameters",
        "resolution_method",
        "source_label",
        "source_reference",
        "is_fallback",
    }
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise ValueError("beam IAM parameter resolution is missing required provenance")
    if value["model"] not in ("physical", "martin-ruiz", "ashrae"):
        raise ValueError("beam IAM parameter resolution has an invalid model")
    if value["resolution_method"] not in ("direct", "measured_fit", "explicit_fallback"):
        raise ValueError("beam IAM parameter resolution has an invalid method")
    if not isinstance(value["source_label"], str) or not value["source_label"].strip():
        raise ValueError("beam IAM parameter source_label must be non-empty")
    if value["source_reference"] is not None and not isinstance(value["source_reference"], str):
        raise ValueError("beam IAM parameter source_reference is invalid")
    if isinstance(value["source_reference"], str) and not value["source_reference"].strip():
        raise ValueError("beam IAM parameter source_reference is invalid")
    if not isinstance(value["is_fallback"], bool):
        raise ValueError("beam IAM parameter is_fallback must be Boolean")
    return value


def _parameter_signature(parameters: Mapping[str, object]) -> str:
    return repr(tuple(sorted(parameters.items())))


def _receiver_state(state: pd.DataFrame, receiver_id: str) -> pd.DataFrame:
    if state.empty:
        return state.iloc[:0].droplevel("receiver_id")
    return state.xs(receiver_id, level="receiver_id")


def _validate_reproduced_iam(
    state: pd.DataFrame, reproduced: pd.DataFrame, model: BeamIAMModel
) -> None:
    if not (state.loc[state["beam_iam_resolved"].astype(bool), "beam_iam_model"] == model).all():
        raise ValueError("beam IAM parameter model does not match S7A beam IAM model")
    expected_resolved = state["beam_iam_resolved"].to_numpy(dtype=bool)
    actual_resolved = reproduced["beam_iam_resolved"].to_numpy(dtype=bool)
    if not np.array_equal(expected_resolved, actual_resolved):
        raise ValueError("beam IAM parameter resolution does not reproduce S7A resolution state")
    if np.any(expected_resolved) and not np.allclose(
        state.loc[expected_resolved, "beam_iam_factor"],
        reproduced.loc[expected_resolved, "beam_iam_factor"],
        rtol=1e-12,
        atol=_TOLERANCE,
    ):
        raise ValueError("beam IAM parameters do not reproduce S7A beam IAM factors")


def _validate_visibility_factor(row: pd.Series, component: str) -> None:
    if not bool(row[f"diffuse_{component}_visibility_resolved"]):
        return
    factor = row[f"diffuse_{component}_visible_fraction"]
    if isinstance(factor, (bool, np.bool_)) or pd.isna(factor):
        raise ValueError(f"resolved diffuse {component} visibility factor is invalid")
    value = float(cast(Any, factor))
    if not np.isfinite(value) or value < -_TOLERANCE or value > 1.0 + _TOLERANCE:
        raise ValueError(f"resolved diffuse {component} visibility factor is invalid")
    blocked = row[f"diffuse_{component}_blocked_fraction"]
    if isinstance(blocked, (bool, np.bool_)) or pd.isna(blocked):
        raise ValueError(f"resolved diffuse {component} visibility factor is invalid")
    blocked_value = float(cast(Any, blocked))
    if (
        not np.isfinite(blocked_value)
        or blocked_value < -_TOLERANCE
        or blocked_value > 1.0 + _TOLERANCE
        or not np.isclose(value + blocked_value, 1.0, rtol=1e-12, atol=_TOLERANCE)
    ):
        raise ValueError(f"resolved diffuse {component} visibility factor is invalid")


def _orientation(receiver: PVReceiver) -> tuple[float, float]:
    normal = np.asarray(receiver.normal_enu, dtype=np.float64)
    tilt = float(np.degrees(np.arccos(np.clip(normal[2], -1.0, 1.0))))
    azimuth = (
        180.0
        if np.isclose(tilt, 0.0, rtol=0.0, atol=1e-12)
        else float(np.degrees(np.arctan2(normal[0], normal[1])) % 360.0)
    )
    return tilt, azimuth


def _reconstruct_components(state: pd.DataFrame, tilt: float, azimuth: float) -> pd.DataFrame:
    output = pd.DataFrame(
        np.nan,
        index=state.index,
        columns=["poa_sky_diffuse", "poa_isotropic", "poa_circumsolar", "poa_horizon"],
        dtype=float,
    )
    resolved = state["poa_transposition_resolved"].astype(bool)
    if not resolved.any():
        return output
    selected = state.loc[resolved]
    models = set(selected["transposition_model"])
    if len(models) != 1:
        raise ValueError("resolved transposition model must be common per receiver")
    model = str(next(iter(models)))
    if model == "perez":
        components = pvlib.irradiance.perez(
            tilt,
            azimuth,
            selected["dhi_wm2"],
            selected["dni_wm2"],
            selected["dni_extra_wm2"],
            selected["apparent_solar_zenith_deg"],
            selected["solar_azimuth_deg"],
            pvlib.atmosphere.get_relative_airmass(selected["apparent_solar_zenith_deg"]),
            model="allsitescomposite1990",
            return_components=True,
        )
    elif model == "perez-driesse":
        components = pvlib.irradiance.perez_driesse(
            tilt,
            azimuth,
            selected["dhi_wm2"],
            selected["dni_wm2"],
            selected["dni_extra_wm2"],
            selected["apparent_solar_zenith_deg"],
            selected["solar_azimuth_deg"],
            return_components=True,
        )
    else:
        raise ValueError("resolved transposition model must be perez or perez-driesse")
    required = {"poa_sky_diffuse", "poa_isotropic", "poa_circumsolar", "poa_horizon"}
    if not isinstance(components, pd.DataFrame) or not required.issubset(components.columns):
        raise RuntimeError("pvlib Perez component output is incomplete")
    if not np.isfinite(components[list(required)].to_numpy(dtype=np.float64)).all():
        raise RuntimeError("pvlib Perez component output is non-finite")
    if not np.allclose(
        components["poa_sky_diffuse"],
        selected["poa_sky_diffuse_raw_wm2"],
        rtol=1e-12,
        atol=_TOLERANCE,
    ):
        raise RuntimeError("reconstructed Perez sky diffuse does not match raw front POA")
    if not np.allclose(
        components["poa_isotropic"] + components["poa_circumsolar"] + components["poa_horizon"],
        components["poa_sky_diffuse"],
        rtol=1e-12,
        atol=_TOLERANCE,
    ):
        raise RuntimeError("Perez diffuse components do not close")
    output.loc[resolved, list(required)] = components[list(required)]
    return output


def _effective_row(
    source: pd.Series,
    components: pd.Series,
    visibility: pd.Series,
    tilt: float,
    azimuth: float,
    diffuse_iam: DiffuseIAMResult,
    parameters: Mapping[str, object],
) -> dict[str, object]:
    row = _base_row(source, components, visibility, tilt, azimuth, diffuse_iam, parameters)
    if not bool(source["poa_transposition_resolved"]):
        row.update(_unresolved_effective("unresolved_upstream_irradiance"))
        return row
    direct = float(source["poa_direct_raw_wm2"])
    circumsolar = float(components["poa_circumsolar"])
    isotropic = float(components["poa_isotropic"])
    horizon = float(components["poa_horizon"])
    ground = float(source["poa_ground_diffuse_raw_wm2"])
    direct_geometry = _apply_factor(
        direct,
        source["front_direct_geometric_visible_fraction"],
        bool(source["front_direct_geometric_composition_resolved"]),
    )
    circumsolar_geometry = _apply_factor(
        circumsolar,
        source["front_direct_geometric_visible_fraction"],
        bool(source["front_direct_geometric_composition_resolved"]),
    )
    isotropic_geometry = _apply_factor(
        isotropic,
        visibility["diffuse_sky_visible_fraction"],
        bool(visibility["diffuse_sky_visibility_resolved"]),
    )
    horizon_geometry = _apply_factor(
        horizon,
        visibility["diffuse_horizon_visible_fraction"],
        bool(visibility["diffuse_horizon_visibility_resolved"]),
    )
    ground_geometry = _apply_factor(
        ground,
        visibility["diffuse_ground_visible_fraction"],
        bool(visibility["diffuse_ground_visibility_resolved"]),
    )
    geometry = (
        direct_geometry,
        circumsolar_geometry,
        isotropic_geometry,
        horizon_geometry,
        ground_geometry,
    )
    for column, result in zip(_GEOMETRY_COLUMNS, geometry, strict=True):
        row[column] = result[0]
    direct_iam_values = (
        (source["beam_iam_factor"], bool(source["beam_iam_resolved"])),
        (source["beam_iam_factor"], bool(source["beam_iam_resolved"])),
    )
    direct_effective = tuple(
        _apply_factor(geometry_result[0], factor, geometry_result[1] and resolved)
        for geometry_result, (factor, resolved) in zip(
            geometry[:2], direct_iam_values, strict=True
        )
    )
    diffuse_effective = tuple(
        _apply_factor(
            raw,
            visibility[f"diffuse_{component}_joint_optical_transmission_factor"],
            bool(visibility[f"diffuse_{component}_joint_optical_resolved"]),
        )
        for raw, component in (
            (isotropic, "sky"),
            (horizon, "horizon"),
            (ground, "ground"),
        )
    )
    effective = direct_effective + diffuse_effective
    for column, resolved_column, result in zip(
        _EFFECTIVE_COMPONENT_COLUMNS, _RESOLVED_COMPONENT_COLUMNS, effective, strict=True
    ):
        row[column] = result[0]
        row[resolved_column] = result[1]
    if not all(result[1] for result in effective):
        row.update(_unresolved_totals("unresolved_component_dependency"))
        return row
    direct_eff, circumsolar_eff, isotropic_eff, horizon_eff, ground_eff = (
        result[0] for result in effective
    )
    sky_eff = circumsolar_eff + isotropic_eff + horizon_eff
    diffuse_eff = sky_eff + ground_eff
    total = direct_eff + diffuse_eff
    if total < -_TOLERANCE:
        raise RuntimeError("front optical effective irradiance is materially negative")
    total = max(0.0, total)
    if (
        not np.isclose(sky_eff, circumsolar_eff + isotropic_eff + horizon_eff, atol=_TOLERANCE)
        or not np.isclose(diffuse_eff, sky_eff + ground_eff, atol=_TOLERANCE)
        or not np.isclose(total, direct_eff + diffuse_eff, atol=_TOLERANCE)
    ):
        raise RuntimeError("front effective irradiance component closure failed")
    row.update(
        {
            "poa_front_sky_diffuse_effective_wm2": sky_eff,
            "poa_front_diffuse_effective_wm2": diffuse_eff,
            "poa_front_effective_optical_wm2": total,
            "front_effective_irradiance_resolved": True,
            "front_effective_irradiance_state": "resolved",
        }
    )
    return row


def _base_row(
    source: pd.Series,
    components: pd.Series,
    visibility: pd.Series,
    tilt: float,
    azimuth: float,
    diffuse_iam: DiffuseIAMResult,
    parameters: Mapping[str, object],
) -> dict[str, object]:
    return {
        "surface_tilt_deg": tilt,
        "surface_azimuth_deg": azimuth,
        "poa_front_direct_raw_wm2": source["poa_direct_raw_wm2"],
        "poa_front_circumsolar_raw_wm2": components["poa_circumsolar"],
        "poa_front_isotropic_raw_wm2": components["poa_isotropic"],
        "poa_front_horizon_raw_wm2": components["poa_horizon"],
        "poa_front_ground_diffuse_raw_wm2": source["poa_ground_diffuse_raw_wm2"],
        "poa_front_sky_diffuse_raw_wm2": source["poa_sky_diffuse_raw_wm2"],
        "poa_front_global_raw_wm2": source["poa_global_raw_wm2"],
        "transposition_model": source["transposition_model"],
        "diffuse_component_model": DIFFUSE_COMPONENT_MODEL_ID,
        "front_direct_geometric_visible_fraction": source[
            "front_direct_geometric_visible_fraction"
        ],
        "diffuse_sky_visible_fraction": visibility["diffuse_sky_visible_fraction"],
        "diffuse_horizon_visible_fraction": visibility["diffuse_horizon_visible_fraction"],
        "diffuse_ground_visible_fraction": visibility["diffuse_ground_visible_fraction"],
        "poa_front_direct_after_geometry_wm2": np.nan,
        "poa_front_circumsolar_after_geometry_wm2": np.nan,
        "poa_front_isotropic_after_geometry_wm2": np.nan,
        "poa_front_horizon_after_geometry_wm2": np.nan,
        "poa_front_ground_diffuse_after_geometry_wm2": np.nan,
        "beam_iam_factor": source["beam_iam_factor"],
        "diffuse_sky_marion_unobstructed_iam_reference": diffuse_iam.diffuse_sky_iam_factor,
        "diffuse_horizon_marion_unobstructed_iam_reference": (
            diffuse_iam.diffuse_horizon_iam_factor
        ),
        "diffuse_ground_marion_unobstructed_iam_reference": (
            diffuse_iam.diffuse_ground_iam_factor
        ),
        "diffuse_sky_visible_region_iam_factor": visibility[
            "diffuse_sky_visible_region_iam_factor"
        ],
        "diffuse_horizon_visible_region_iam_factor": visibility[
            "diffuse_horizon_visible_region_iam_factor"
        ],
        "diffuse_ground_visible_region_iam_factor": visibility[
            "diffuse_ground_visible_region_iam_factor"
        ],
        "diffuse_sky_joint_optical_transmission_factor": visibility[
            "diffuse_sky_joint_optical_transmission_factor"
        ],
        "diffuse_horizon_joint_optical_transmission_factor": visibility[
            "diffuse_horizon_joint_optical_transmission_factor"
        ],
        "diffuse_ground_joint_optical_transmission_factor": visibility[
            "diffuse_ground_joint_optical_transmission_factor"
        ],
        "diffuse_joint_optical_model": visibility["diffuse_joint_optical_model"],
        "diffuse_iam_model": diffuse_iam.model,
        "iam_parameter_resolution_method": parameters["resolution_method"],
        "iam_parameter_source_label": parameters["source_label"],
        "iam_parameter_source_reference": parameters["source_reference"],
        "iam_parameter_is_fallback": parameters["is_fallback"],
        "rear_mode": source["rear_mode"],
        "effective_irradiance_model": EFFECTIVE_IRRADIANCE_MODEL_ID,
        "effective_irradiance_coverage_scope": EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
        "effective_irradiance_scope": EFFECTIVE_IRRADIANCE_SCOPE,
    }


def _apply_factor(raw: object, factor: object, resolved: bool) -> tuple[float, bool]:
    value = float(cast(Any, raw))
    if abs(value) <= _TOLERANCE:
        return 0.0, True
    if not resolved or pd.isna(factor):
        return np.nan, False
    return value * float(cast(Any, factor)), True


def _unresolved_effective(state: str) -> dict[str, object]:
    values: dict[str, object] = {
        column: np.nan
        for column in _GEOMETRY_COLUMNS + _EFFECTIVE_COMPONENT_COLUMNS + _TOTAL_COLUMNS
    }
    values.update({column: False for column in _RESOLVED_COMPONENT_COLUMNS})
    values["front_effective_irradiance_resolved"] = False
    values["front_effective_irradiance_state"] = state
    return values


def _unresolved_totals(state: str) -> dict[str, object]:
    return {
        "poa_front_sky_diffuse_effective_wm2": np.nan,
        "poa_front_diffuse_effective_wm2": np.nan,
        "poa_front_effective_optical_wm2": np.nan,
        "front_effective_irradiance_resolved": False,
        "front_effective_irradiance_state": state,
    }


def _series_matches(series: pd.Series, scalar: object) -> bool:
    if pd.isna(scalar):
        return bool(series.isna().all())
    return bool(
        np.allclose(
            series.to_numpy(dtype=np.float64),
            float(cast(Any, scalar)),
            rtol=1e-12,
            atol=_TOLERANCE,
        )
    )


def _require_unique(values: Iterable[object], label: str) -> None:
    if any(count > 1 for count in Counter(values).values()):
        raise ValueError(f"{label} must be unique")


def _typed_result(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [column for column in frame if column.endswith("_resolved")]
    bool_columns.append("iam_parameter_is_fallback")
    string_columns = [
        column
        for column in frame
        if column.endswith("_model")
        or column.endswith("_state")
        or column.endswith("_scope")
        or column
        in (
            "iam_parameter_resolution_method",
            "iam_parameter_source_label",
            "iam_parameter_source_reference",
            "rear_mode",
        )
    ]
    for column in bool_columns:
        frame[column] = frame[column].astype("bool")
    for column in string_columns:
        frame[column] = frame[column].astype("string")
    numeric = set(frame.columns) - set(bool_columns) - set(string_columns)
    for column in numeric:
        frame[column] = frame[column].astype("float64")
    return frame
