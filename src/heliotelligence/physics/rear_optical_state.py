"""Canonical fixed-table rear optical admission state built from S6E output."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.fixed_bifacial_rear import (
    COVERAGE_SCOPE as S6E_COVERAGE_SCOPE,
)
from heliotelligence.physics.fixed_bifacial_rear import MODEL_ID as S6E_MODEL_ID
from heliotelligence.physics.iam import BeamIAMModel, calculate_beam_iam
from heliotelligence.physics.shading import solar_direction_enu

REAR_OPTICAL_STATE_CONTRACT_ID = "rear_optical_state_v1"
REAR_OPTICAL_STATE_MODEL_ID = "s6e_fixed_rear_optical_admission_v1"
REAR_OPTICAL_STATE_COVERAGE_SCOPE = (
    "regular_parallel_fixed_rows_level_ground_rear_state_only"
)
_TOLERANCE = 1e-9
_GEOMETRY_TOLERANCE = 1e-10

_REQUIRED_S6E_COLUMNS = {
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "fixed_row_array_id",
    "surface_tilt_deg",
    "surface_azimuth_deg",
    "rear_surface_tilt_deg",
    "rear_surface_azimuth_deg",
    "poa_rear_direct_raw_wm2",
    "poa_rear_circumsolar_diffuse_raw_wm2",
    "poa_rear_sky_diffuse_raw_wm2",
    "poa_rear_ground_diffuse_raw_wm2",
    "poa_rear_diffuse_raw_wm2",
    "poa_rear_global_raw_wm2",
    "rear_direct_shaded_fraction",
    "rear_irradiance_resolved",
    "rear_irradiance_state",
    "rear_irradiance_model",
    "rear_diffuse_model",
    "rear_coverage_scope",
}
_OUTPUT_COLUMNS = [
    "fixed_row_array_id",
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "front_normal_east",
    "front_normal_north",
    "front_normal_up",
    "surface_tilt_deg",
    "surface_azimuth_deg",
    "rear_normal_east",
    "rear_normal_north",
    "rear_normal_up",
    "rear_surface_tilt_deg",
    "rear_surface_azimuth_deg",
    "rear_aoi_deg",
    "poa_rear_direct_raw_wm2",
    "poa_rear_circumsolar_diffuse_raw_wm2",
    "poa_rear_isotropic_sky_raw_wm2",
    "poa_rear_sky_diffuse_raw_wm2",
    "poa_rear_ground_diffuse_raw_wm2",
    "poa_rear_diffuse_raw_wm2",
    "poa_rear_global_raw_wm2",
    "rear_direct_shaded_fraction",
    "rear_direct_row_visible_fraction",
    "rear_row_direct_shading_embedded",
    "rear_row_sky_view_factor_embedded",
    "rear_ground_row_shadowing_embedded",
    "rear_row_ground_view_factor_embedded",
    "rear_row_geometry_model",
    "rear_beam_iam_factor",
    "rear_beam_iam_resolved",
    "rear_beam_iam_state",
    "rear_beam_iam_model",
    "rear_iam_parameter_resolution_method",
    "rear_iam_parameter_source_label",
    "rear_iam_parameter_source_reference",
    "rear_iam_parameter_is_fallback",
    "rear_irradiance_resolved",
    "rear_irradiance_state",
    "rear_irradiance_model",
    "rear_diffuse_model",
    "rear_coverage_scope",
    "rear_optical_admission_state",
    "rear_optical_state_contract",
    "rear_optical_state_model",
    "rear_optical_state_coverage_scope",
]


@dataclass(frozen=True)
class RearOpticalStateDiagnostics:
    receiver_count: int
    timestamp_count: int
    row_count: int
    resolved_rear_irradiance_row_count: int
    unresolved_rear_irradiance_row_count: int
    rear_diffuse_model: str | None
    rear_optical_state_model: str


@dataclass(frozen=True)
class RearOpticalStateResult:
    state: pd.DataFrame
    diagnostics: RearOpticalStateDiagnostics


def calculate_rear_optical_state(
    receivers: Sequence[PVReceiver],
    rear_irradiance: pd.DataFrame,
    *,
    rear_beam_iam_parameters_by_receiver: Mapping[str, Mapping[str, object]],
) -> RearOpticalStateResult:
    """Validate and admit S6E rear irradiance without applying optical loss."""
    receiver_values = _validated_receivers(receivers)
    receiver_ids = tuple(sorted(receiver.id for receiver in receiver_values))
    receivers_by_id = {receiver.id: receiver for receiver in receiver_values}
    frame = _validated_s6e_frame(rear_irradiance, receiver_ids)
    if not isinstance(rear_beam_iam_parameters_by_receiver, Mapping) or set(
        rear_beam_iam_parameters_by_receiver
    ) != set(receiver_ids):
        raise ValueError("rear beam IAM parameter keys must exactly match receiver IDs")

    models = set(frame["rear_diffuse_model"].dropna().astype(str))
    if not models.issubset({"isotropic", "haydavies"}) or len(models) > 1:
        raise ValueError("rear diffuse model must be one common isotropic or haydavies model")
    common_diffuse_model = next(iter(models)) if models else None
    receiver_context: dict[str, dict[str, object]] = {}
    timestamps = frame.index.get_level_values(0).unique()
    for receiver_id in receiver_ids:
        receiver = receivers_by_id[receiver_id]
        front_normal = np.asarray(receiver.normal_enu, dtype=np.float64)
        if not np.isclose(
            np.linalg.norm(front_normal), 1.0, rtol=0.0, atol=_GEOMETRY_TOLERANCE
        ):
            raise ValueError("canonical receiver normal must be a unit vector")
        rear_normal = -front_normal
        front_tilt, front_azimuth = _orientation(front_normal)
        rear_tilt, rear_azimuth = _orientation(rear_normal)
        receiver_frame = (
            frame.xs(receiver_id, level="receiver_id")
            if len(frame)
            else frame.iloc[:0].droplevel("receiver_id")
        )
        _validate_orientation(receiver_frame, front_tilt, front_azimuth, rear_tilt, rear_azimuth)
        parameters = _validated_parameter_resolution(
            rear_beam_iam_parameters_by_receiver[receiver_id]
        )
        rear_aoi = pd.Series(
            [
                _rear_aoi(rear_normal, float(zenith), float(azimuth))
                for zenith, azimuth in zip(
                    receiver_frame["apparent_solar_zenith_deg"],
                    receiver_frame["solar_azimuth_deg"],
                    strict=True,
                )
            ],
            index=timestamps,
            dtype=float,
        )
        model = cast(BeamIAMModel, parameters["model"])
        iam = calculate_beam_iam(
            rear_aoi,
            model=model,
            model_parameters=cast(Mapping[str, object], parameters["model_parameters"]),
        )
        receiver_context[receiver_id] = {
            "front_normal": front_normal,
            "rear_normal": rear_normal,
            "front_tilt": front_tilt,
            "front_azimuth": front_azimuth,
            "rear_tilt": rear_tilt,
            "rear_azimuth": rear_azimuth,
            "rear_aoi": rear_aoi,
            "iam": iam,
            "parameters": parameters,
        }

    rows: list[dict[str, object]] = []
    for (timestamp, receiver_id_value), source in frame.iterrows():
        receiver_id = str(receiver_id_value)
        context = receiver_context[receiver_id]
        resolved = bool(source["rear_irradiance_resolved"])
        admitted = _admitted_components(source, resolved)
        iam = cast(pd.DataFrame, context["iam"]).loc[timestamp]
        parameters = cast(Mapping[str, object], context["parameters"])
        front_normal = cast(npt.NDArray[np.float64], context["front_normal"])
        rear_normal = cast(npt.NDArray[np.float64], context["rear_normal"])
        rows.append(
            {
                "fixed_row_array_id": source["fixed_row_array_id"],
                "ghi_wm2": source["ghi_wm2"],
                "dhi_wm2": source["dhi_wm2"],
                "dni_wm2": source["dni_wm2"],
                "apparent_solar_zenith_deg": source["apparent_solar_zenith_deg"],
                "solar_azimuth_deg": source["solar_azimuth_deg"],
                "front_normal_east": front_normal[0],
                "front_normal_north": front_normal[1],
                "front_normal_up": front_normal[2],
                "surface_tilt_deg": context["front_tilt"],
                "surface_azimuth_deg": context["front_azimuth"],
                "rear_normal_east": rear_normal[0],
                "rear_normal_north": rear_normal[1],
                "rear_normal_up": rear_normal[2],
                "rear_surface_tilt_deg": context["rear_tilt"],
                "rear_surface_azimuth_deg": context["rear_azimuth"],
                "rear_aoi_deg": cast(pd.Series, context["rear_aoi"]).loc[timestamp],
                **admitted,
                "rear_direct_row_visible_fraction": (
                    1.0 - float(source["rear_direct_shaded_fraction"])
                    if resolved
                    else np.nan
                ),
                "rear_row_direct_shading_embedded": resolved,
                "rear_row_sky_view_factor_embedded": resolved,
                "rear_ground_row_shadowing_embedded": resolved,
                "rear_row_ground_view_factor_embedded": resolved,
                "rear_row_geometry_model": S6E_MODEL_ID,
                "rear_beam_iam_factor": iam["beam_iam_factor"],
                "rear_beam_iam_resolved": iam["beam_iam_resolved"],
                "rear_beam_iam_state": iam["beam_iam_state"],
                "rear_beam_iam_model": iam["beam_iam_model"],
                "rear_iam_parameter_resolution_method": parameters["resolution_method"],
                "rear_iam_parameter_source_label": parameters["source_label"],
                "rear_iam_parameter_source_reference": parameters["source_reference"],
                "rear_iam_parameter_is_fallback": parameters["is_fallback"],
                "rear_irradiance_resolved": resolved,
                "rear_irradiance_state": source["rear_irradiance_state"],
                "rear_irradiance_model": source["rear_irradiance_model"],
                "rear_diffuse_model": source["rear_diffuse_model"],
                "rear_coverage_scope": source["rear_coverage_scope"],
                "rear_optical_admission_state": (
                    "resolved"
                    if resolved
                    else "unresolved_upstream_rear_irradiance"
                ),
                "rear_optical_state_contract": REAR_OPTICAL_STATE_CONTRACT_ID,
                "rear_optical_state_model": REAR_OPTICAL_STATE_MODEL_ID,
                "rear_optical_state_coverage_scope": REAR_OPTICAL_STATE_COVERAGE_SCOPE,
            }
        )
    output = _typed_result(pd.DataFrame(rows, index=frame.index, columns=_OUTPUT_COLUMNS))
    resolved_count = int(output["rear_irradiance_resolved"].sum())
    return RearOpticalStateResult(
        output,
        RearOpticalStateDiagnostics(
            receiver_count=len(receiver_ids),
            timestamp_count=len(timestamps),
            row_count=len(output),
            resolved_rear_irradiance_row_count=resolved_count,
            unresolved_rear_irradiance_row_count=len(output) - resolved_count,
            rear_diffuse_model=common_diffuse_model,
            rear_optical_state_model=REAR_OPTICAL_STATE_MODEL_ID,
        ),
    )


def _validated_receivers(receivers: object) -> tuple[PVReceiver, ...]:
    if isinstance(receivers, (str, bytes)) or not isinstance(receivers, Sequence):
        raise ValueError("receivers must be a sequence")
    result = tuple(receivers)
    if any(not isinstance(receiver, PVReceiver) for receiver in result):
        raise ValueError("receivers must contain only PVReceiver values")
    _require_unique((receiver.id for receiver in result), "receiver IDs")
    for receiver in result:
        if receiver.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError(
                "S6C runtime tracker pose is required before rear tracker optical composition"
            )
        if receiver.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("rear optical state accepts only FIXED_TABLE receivers")
    return result


def _validated_s6e_frame(frame: object, receiver_ids: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("rear_irradiance must use a timestamp/receiver MultiIndex")
    if frame.index.nlevels != 2 or frame.index.names[1] != "receiver_id":
        raise ValueError("rear_irradiance index must be timestamp, receiver_id")
    if not _REQUIRED_S6E_COLUMNS.issubset(frame.columns):
        raise ValueError("rear_irradiance is missing required S6E columns")
    timestamps = frame.index.get_level_values(0)
    if not isinstance(timestamps, pd.DatetimeIndex) or timestamps.tz is None:
        raise ValueError("rear_irradiance timestamps must be timezone-aware")
    if timestamps.hasnans or frame.index.has_duplicates:
        raise ValueError("rear_irradiance index must be unique and contain no NaT")
    if len(frame) and set(frame.index.get_level_values("receiver_id")) != set(receiver_ids):
        raise ValueError("S6E receiver IDs must exactly match canonical receiver IDs")
    timestamp_values = timestamps.unique().sort_values()
    expected = pd.MultiIndex.from_product(
        [timestamp_values, receiver_ids], names=frame.index.names
    )
    if set(frame.index) != set(expected):
        raise ValueError("S6E requires exactly one row per timestamp and receiver")
    result = frame.reindex(expected).copy()
    if not (result["rear_irradiance_model"] == S6E_MODEL_ID).all():
        raise ValueError("rear irradiance model is not the admitted S6E model")
    if not (result["rear_coverage_scope"] == S6E_COVERAGE_SCOPE).all():
        raise ValueError("rear coverage scope is not the admitted S6E scope")
    return result


def _orientation(normal: npt.NDArray[np.float64]) -> tuple[float, float]:
    tilt = float(np.degrees(np.arccos(np.clip(normal[2], -1.0, 1.0))))
    horizontal = np.isclose(abs(normal[2]), 1.0, rtol=0.0, atol=_GEOMETRY_TOLERANCE)
    azimuth = 180.0 if horizontal else float(np.degrees(np.arctan2(normal[0], normal[1])) % 360)
    return tilt, azimuth


def _validate_orientation(
    frame: pd.DataFrame,
    front_tilt: float,
    front_azimuth: float,
    rear_tilt: float,
    rear_azimuth: float,
) -> None:
    for column, expected in (
        ("surface_tilt_deg", front_tilt),
        ("surface_azimuth_deg", front_azimuth),
        ("rear_surface_tilt_deg", rear_tilt),
        ("rear_surface_azimuth_deg", rear_azimuth),
    ):
        if not np.allclose(frame[column], expected, rtol=0.0, atol=_GEOMETRY_TOLERANCE):
            raise ValueError(f"S6E {column} conflicts with canonical receiver normal")


def _rear_aoi(
    rear_normal: npt.NDArray[np.float64], zenith: float, azimuth: float
) -> float:
    if zenith < 90.0:
        direction = np.asarray(solar_direction_enu(zenith, azimuth), dtype=np.float64)
    else:
        zenith_rad = np.radians(zenith)
        azimuth_rad = np.radians(azimuth)
        direction = np.asarray(
            (
                np.sin(zenith_rad) * np.sin(azimuth_rad),
                np.sin(zenith_rad) * np.cos(azimuth_rad),
                np.cos(zenith_rad),
            ),
            dtype=np.float64,
        )
    aoi = float(np.degrees(np.arccos(np.clip(np.dot(rear_normal, direction), -1.0, 1.0))))
    if not np.isfinite(aoi) or not 0.0 <= aoi <= 180.0:
        raise ValueError("rear AOI is outside [0, 180]")
    return aoi


def _admitted_components(source: pd.Series, resolved: bool) -> dict[str, object]:
    names = (
        "poa_rear_direct_raw_wm2",
        "poa_rear_circumsolar_diffuse_raw_wm2",
        "poa_rear_sky_diffuse_raw_wm2",
        "poa_rear_ground_diffuse_raw_wm2",
        "poa_rear_diffuse_raw_wm2",
        "poa_rear_global_raw_wm2",
        "rear_direct_shaded_fraction",
    )
    values = {name: source[name] for name in names}
    if not resolved:
        if any(not pd.isna(values[name]) for name in names):
            raise ValueError("unresolved S6E irradiance components must remain NaN")
        values["poa_rear_isotropic_sky_raw_wm2"] = np.nan
        return values
    numeric = {name: _finite_real(values[name], name) for name in names}
    shaded = numeric["rear_direct_shaded_fraction"]
    if not 0.0 <= shaded <= 1.0:
        raise ValueError("resolved rear direct shaded fraction must be within [0, 1]")
    isotropic = (
        numeric["poa_rear_sky_diffuse_raw_wm2"]
        - numeric["poa_rear_circumsolar_diffuse_raw_wm2"]
    )
    if isotropic < -_TOLERANCE:
        raise ValueError("rear circumsolar diffuse exceeds rear sky diffuse")
    isotropic = max(0.0, isotropic)
    if not np.isclose(
        numeric["poa_rear_sky_diffuse_raw_wm2"],
        isotropic + numeric["poa_rear_circumsolar_diffuse_raw_wm2"],
        rtol=1e-12,
        atol=_TOLERANCE,
    ) or not np.isclose(
        numeric["poa_rear_diffuse_raw_wm2"],
        numeric["poa_rear_sky_diffuse_raw_wm2"]
        + numeric["poa_rear_ground_diffuse_raw_wm2"],
        rtol=1e-12,
        atol=_TOLERANCE,
    ) or not np.isclose(
        numeric["poa_rear_global_raw_wm2"],
        numeric["poa_rear_direct_raw_wm2"] + numeric["poa_rear_diffuse_raw_wm2"],
        rtol=1e-12,
        atol=_TOLERANCE,
    ):
        raise ValueError("admitted S6E rear irradiance components do not close")
    values["poa_rear_isotropic_sky_raw_wm2"] = isotropic
    return values


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
        raise ValueError("rear beam IAM parameter resolution is missing required provenance")
    if value["model"] not in ("physical", "ashrae", "martin-ruiz"):
        raise ValueError("rear beam IAM parameter resolution has an invalid model")
    if value["resolution_method"] not in ("direct", "measured_fit", "explicit_fallback"):
        raise ValueError("rear beam IAM parameter resolution has an invalid method")
    if not isinstance(value["source_label"], str) or not value["source_label"].strip():
        raise ValueError("rear IAM parameter source_label must be non-empty")
    reference = value["source_reference"]
    if reference is not None and (not isinstance(reference, str) or not reference.strip()):
        raise ValueError("rear IAM parameter source_reference is invalid")
    if not isinstance(value["is_fallback"], bool):
        raise ValueError("rear IAM parameter is_fallback must be Boolean")
    return value


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or pd.isna(value):
        raise ValueError(f"{name} must be a finite real number")
    result = float(cast(Any, value))
    if not np.isfinite(result):
        raise ValueError(f"{name} must be a finite real number")
    return result


def _require_unique(values: Iterable[object], label: str) -> None:
    if any(count > 1 for count in Counter(values).values()):
        raise ValueError(f"{label} must be unique")


def _typed_result(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [column for column in frame if column.endswith("_embedded")]
    bool_columns.extend(
        ("rear_beam_iam_resolved", "rear_iam_parameter_is_fallback", "rear_irradiance_resolved")
    )
    string_columns = [
        column
        for column in frame
        if column.endswith("_model")
        or column.endswith("_state")
        or column.endswith("_scope")
        or column.endswith("_contract")
        or column
        in (
            "fixed_row_array_id",
            "rear_iam_parameter_resolution_method",
            "rear_iam_parameter_source_label",
            "rear_iam_parameter_source_reference",
        )
    ]
    for column in bool_columns:
        frame[column] = frame[column].astype("bool")
    for column in string_columns:
        frame[column] = frame[column].astype("string")
    for column in set(frame.columns) - set(bool_columns) - set(string_columns):
        frame[column] = frame[column].astype("float64")
    return frame
