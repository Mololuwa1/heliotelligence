"""Row-conditioned rear IAM factors relative to the S6E infinite-sheds baseline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral
from typing import cast

import numpy as np
import numpy.typing as npt
import pandas as pd  # type: ignore[import-untyped]
from pvlib.bifacial.utils import (  # type: ignore[import-untyped]
    vf_row_ground_2d_integ,
    vf_row_sky_2d_integ,
)

from heliotelligence.physics.fixed_bifacial_rear import (
    COVERAGE_SCOPE as S6E_COVERAGE_SCOPE,
)
from heliotelligence.physics.fixed_bifacial_rear import MODEL_ID as S6E_MODEL_ID
from heliotelligence.physics.fixed_bifacial_rear import (
    FixedBifacialRearArrayOpticalGeometry,
    FixedBifacialRearScene,
)
from heliotelligence.physics.iam import BeamIAMModel, calculate_beam_iam
from heliotelligence.physics.rear_optical_state import (
    REAR_OPTICAL_STATE_CONTRACT_ID,
    REAR_OPTICAL_STATE_COVERAGE_SCOPE,
    REAR_OPTICAL_STATE_MODEL_ID,
    RearOpticalStateResult,
)

REAR_ROW_OPTICAL_CONTRACT_ID = "rear_row_conditioned_optical_transmission_v1"
REAR_ROW_OPTICAL_MODEL_ID = "infinite_sheds_row_conditioned_rear_iam_v1"
REAR_ROW_OPTICAL_COVERAGE_SCOPE = "regular_parallel_fixed_rows_level_ground_rear_iam_only"
_MIN_ROW_POSITIONS = 32
_MIN_DIRECTIONS = 2048
_VF_TOLERANCE = 1e-3
_TOLERANCE = 1e-9
_GOLDEN_ANGLE = np.pi * (3.0 - np.sqrt(5.0))
_OUTPUT_COLUMNS = (
    "fixed_row_array_id",
    "rear_surface_tilt_deg",
    "rear_surface_azimuth_deg",
    "gcr",
    "row_position_count",
    "sky_direction_count",
    "ground_direction_count",
    "rear_sky_analytic_row_view_factor",
    "rear_sky_numerical_row_view_factor",
    "rear_sky_view_factor_abs_error",
    "rear_ground_analytic_row_view_factor",
    "rear_ground_numerical_row_view_factor",
    "rear_ground_view_factor_abs_error",
    "rear_sky_unobstructed_iam_reference",
    "rear_ground_unobstructed_iam_reference",
    "rear_sky_row_conditioned_iam_factor",
    "rear_sky_row_conditioned_iam_resolved",
    "rear_sky_row_conditioned_iam_state",
    "rear_ground_row_conditioned_iam_factor",
    "rear_ground_row_conditioned_iam_resolved",
    "rear_ground_row_conditioned_iam_state",
    "rear_direct_s6e_relative_optical_factor",
    "rear_direct_s6e_relative_optical_resolved",
    "rear_direct_s6e_relative_optical_state",
    "rear_circumsolar_s6e_relative_optical_factor",
    "rear_circumsolar_s6e_relative_optical_resolved",
    "rear_circumsolar_s6e_relative_optical_state",
    "rear_isotropic_sky_s6e_relative_optical_factor",
    "rear_isotropic_sky_s6e_relative_optical_resolved",
    "rear_isotropic_sky_s6e_relative_optical_state",
    "rear_ground_s6e_relative_optical_factor",
    "rear_ground_s6e_relative_optical_resolved",
    "rear_ground_s6e_relative_optical_state",
    "rear_beam_iam_model",
    "rear_iam_parameter_resolution_method",
    "rear_iam_parameter_source_label",
    "rear_iam_parameter_source_reference",
    "rear_iam_parameter_is_fallback",
    "rear_row_geometry_already_embedded",
    "rear_row_optical_contract",
    "rear_row_optical_model",
    "rear_row_optical_coverage_scope",
)


@dataclass(frozen=True)
class RearRowOpticalTransmissionDiagnostics:
    receiver_count: int
    array_count: int
    source_state_row_count: int
    row_position_count: int
    sky_direction_count: int
    ground_direction_count: int
    maximum_sky_view_factor_abs_error: float
    maximum_ground_view_factor_abs_error: float
    rear_row_optical_model: str
    rear_row_optical_coverage_scope: str


@dataclass(frozen=True)
class RearRowOpticalTransmissionResult:
    transmission: pd.DataFrame
    diagnostics: RearRowOpticalTransmissionDiagnostics


@dataclass(frozen=True)
class _FieldGeometry:
    normal: npt.NDArray[np.float64]
    directions: npt.NDArray[np.float64]
    weights: npt.NDArray[np.float64]
    visible_counts: npt.NDArray[np.float64]
    analytic_vf: float
    numerical_vf: float
    vf_error: float


def calculate_rear_row_optical_transmission(
    rear_optical_state: RearOpticalStateResult,
    *,
    scene: FixedBifacialRearScene,
    rear_beam_iam_parameters_by_receiver: Mapping[str, Mapping[str, object]],
    row_position_count: int,
    sky_direction_count: int,
    ground_direction_count: int,
) -> RearRowOpticalTransmissionResult:
    """Calculate component-resolved IAM factors without applying irradiance."""
    if not isinstance(scene, FixedBifacialRearScene):
        raise ValueError("scene must be FixedBifacialRearScene")
    if not isinstance(rear_optical_state, RearOpticalStateResult):
        raise ValueError("rear_optical_state must be RearOpticalStateResult")
    nx = _count(row_position_count, "row_position_count", _MIN_ROW_POSITIONS)
    nsky = _count(sky_direction_count, "sky_direction_count", _MIN_DIRECTIONS)
    nground = _count(ground_direction_count, "ground_direction_count", _MIN_DIRECTIONS)
    receiver_ids = tuple(sorted(scene.receiver_ids))
    if not isinstance(rear_beam_iam_parameters_by_receiver, Mapping) or set(
        rear_beam_iam_parameters_by_receiver
    ) != set(receiver_ids):
        raise ValueError("rear beam IAM parameter keys must exactly match scene receiver IDs")
    state = _validated_state(rear_optical_state.state, receiver_ids)
    geometries = scene.optical_geometry
    geometry_by_receiver = {
        receiver_id: geometry for geometry in geometries for receiver_id in geometry.receiver_ids
    }
    if set(geometry_by_receiver) != set(receiver_ids):
        raise ValueError("scene optical geometry receiver IDs are inconsistent")
    _validate_state_geometry(state, geometry_by_receiver)

    sky_directions = _hemisphere(nsky, upper=True)
    ground_directions = _hemisphere(nground, upper=False)
    field_cache: dict[str, tuple[_FieldGeometry, _FieldGeometry]] = {}
    for geometry in geometries:
        rear_normal, axis, cross_axis, tangent = _basis(geometry)
        sky = _field_geometry(
            geometry,
            rear_normal,
            axis,
            cross_axis,
            tangent,
            sky_directions,
            nx,
            sky=True,
        )
        ground = _field_geometry(
            geometry,
            rear_normal,
            axis,
            cross_axis,
            tangent,
            ground_directions,
            nx,
            sky=False,
        )
        field_cache[geometry.array_id] = (sky, ground)

    static_by_receiver: dict[str, dict[str, object]] = {}
    for receiver_id in receiver_ids:
        parameters = _validated_parameters(rear_beam_iam_parameters_by_receiver[receiver_id])
        receiver_state = _receiver_state(state, receiver_id)
        _validate_parameter_parity(receiver_state, parameters)
        geometry = geometry_by_receiver[receiver_id]
        sky, ground = field_cache[geometry.array_id]
        sky_iam = _conditioned_iam(sky, parameters)
        ground_iam = _conditioned_iam(ground, parameters)
        static_by_receiver[receiver_id] = {
            "parameters": parameters,
            "geometry": geometry,
            "sky": sky,
            "ground": ground,
            "sky_iam": sky_iam,
            "ground_iam": ground_iam,
        }

    rows: list[dict[str, object]] = []
    for (_timestamp, receiver_value), source in state.iterrows():
        receiver_id = str(receiver_value)
        static = static_by_receiver[receiver_id]
        geometry = cast(FixedBifacialRearArrayOpticalGeometry, static["geometry"])
        sky = cast(_FieldGeometry, static["sky"])
        ground = cast(_FieldGeometry, static["ground"])
        sky_iam = cast(tuple[float, float, bool, str], static["sky_iam"])
        ground_iam = cast(tuple[float, float, bool, str], static["ground_iam"])
        parameters = cast(Mapping[str, object], static["parameters"])
        direct_resolved = bool(source["rear_beam_iam_resolved"])
        direct_factor = source["rear_beam_iam_factor"] if direct_resolved else np.nan
        rows.append(
            {
                "fixed_row_array_id": geometry.array_id,
                "rear_surface_tilt_deg": geometry.rear_surface_tilt_deg,
                "rear_surface_azimuth_deg": geometry.rear_surface_azimuth_deg,
                "gcr": geometry.gcr,
                "row_position_count": nx,
                "sky_direction_count": nsky,
                "ground_direction_count": nground,
                "rear_sky_analytic_row_view_factor": sky.analytic_vf,
                "rear_sky_numerical_row_view_factor": sky.numerical_vf,
                "rear_sky_view_factor_abs_error": sky.vf_error,
                "rear_ground_analytic_row_view_factor": ground.analytic_vf,
                "rear_ground_numerical_row_view_factor": ground.numerical_vf,
                "rear_ground_view_factor_abs_error": ground.vf_error,
                "rear_sky_unobstructed_iam_reference": sky_iam[0],
                "rear_ground_unobstructed_iam_reference": ground_iam[0],
                "rear_sky_row_conditioned_iam_factor": sky_iam[1],
                "rear_sky_row_conditioned_iam_resolved": sky_iam[2],
                "rear_sky_row_conditioned_iam_state": sky_iam[3],
                "rear_ground_row_conditioned_iam_factor": ground_iam[1],
                "rear_ground_row_conditioned_iam_resolved": ground_iam[2],
                "rear_ground_row_conditioned_iam_state": ground_iam[3],
                "rear_direct_s6e_relative_optical_factor": direct_factor,
                "rear_direct_s6e_relative_optical_resolved": direct_resolved,
                "rear_direct_s6e_relative_optical_state": source["rear_beam_iam_state"],
                "rear_circumsolar_s6e_relative_optical_factor": direct_factor,
                "rear_circumsolar_s6e_relative_optical_resolved": direct_resolved,
                "rear_circumsolar_s6e_relative_optical_state": source["rear_beam_iam_state"],
                "rear_isotropic_sky_s6e_relative_optical_factor": sky_iam[1],
                "rear_isotropic_sky_s6e_relative_optical_resolved": sky_iam[2],
                "rear_isotropic_sky_s6e_relative_optical_state": sky_iam[3],
                "rear_ground_s6e_relative_optical_factor": ground_iam[1],
                "rear_ground_s6e_relative_optical_resolved": ground_iam[2],
                "rear_ground_s6e_relative_optical_state": ground_iam[3],
                "rear_beam_iam_model": source["rear_beam_iam_model"],
                "rear_iam_parameter_resolution_method": parameters["resolution_method"],
                "rear_iam_parameter_source_label": parameters["source_label"],
                "rear_iam_parameter_source_reference": parameters["source_reference"],
                "rear_iam_parameter_is_fallback": parameters["is_fallback"],
                "rear_row_geometry_already_embedded": True,
                "rear_row_optical_contract": REAR_ROW_OPTICAL_CONTRACT_ID,
                "rear_row_optical_model": REAR_ROW_OPTICAL_MODEL_ID,
                "rear_row_optical_coverage_scope": REAR_ROW_OPTICAL_COVERAGE_SCOPE,
            }
        )
    output = _typed(pd.DataFrame(rows, index=state.index, columns=_OUTPUT_COLUMNS))
    sky_errors = [fields[0].vf_error for fields in field_cache.values()]
    ground_errors = [fields[1].vf_error for fields in field_cache.values()]
    return RearRowOpticalTransmissionResult(
        output,
        RearRowOpticalTransmissionDiagnostics(
            len(receiver_ids),
            len(geometries),
            len(state),
            nx,
            nsky,
            nground,
            max(sky_errors, default=0.0),
            max(ground_errors, default=0.0),
            REAR_ROW_OPTICAL_MODEL_ID,
            REAR_ROW_OPTICAL_COVERAGE_SCOPE,
        ),
    )


def _basis(
    geometry: FixedBifacialRearArrayOpticalGeometry,
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    axis_azimuth = np.radians(geometry.axis_azimuth_deg)
    axis = np.asarray((np.sin(axis_azimuth), np.cos(axis_azimuth), 0.0))
    cross_axis = np.cross(axis, np.asarray((0.0, 0.0, 1.0)))
    front_tilt = np.radians(geometry.surface_tilt_deg)
    front_azimuth = np.radians(geometry.surface_azimuth_deg)
    front_normal = np.asarray(
        (
            np.sin(front_tilt) * np.sin(front_azimuth),
            np.sin(front_tilt) * np.cos(front_azimuth),
            np.cos(front_tilt),
        )
    )
    rear_normal = -front_normal
    tangent = np.cross(axis, front_normal)
    tangent /= np.linalg.norm(tangent)
    if any(
        abs(value) > 1e-10
        for value in (
            np.dot(axis, front_normal),
            np.dot(axis, tangent),
            np.dot(front_normal, tangent),
        )
    ):
        raise ValueError("S6E row geometry does not form an orthogonal basis")
    return rear_normal, axis, cross_axis, tangent


def _field_geometry(
    geometry: FixedBifacialRearArrayOpticalGeometry,
    rear_normal: npt.NDArray[np.float64],
    axis: npt.NDArray[np.float64],
    cross_axis: npt.NDArray[np.float64],
    tangent: npt.NDArray[np.float64],
    directions: npt.NDArray[np.float64],
    position_count: int,
    *,
    sky: bool,
) -> _FieldGeometry:
    del axis
    weights = np.maximum(0.0, directions @ rear_normal)
    positions = (np.arange(position_count, dtype=float) + 0.5) / position_count
    visible_counts = np.zeros(len(directions), dtype=float)
    for position in positions:
        origin = (position - 0.5) * geometry.collector_width_m * tangent
        blocked = np.zeros(len(directions), dtype=bool)
        for sign in (-1.0, 1.0):
            centre = sign * geometry.pitch_m * cross_axis
            start = centre - 0.5 * geometry.collector_width_m * tangent
            end = centre + 0.5 * geometry.collector_width_m * tangent
            blocked |= _ray_segment_hits(origin, directions, start, end, cross_axis)
        visible_counts += (~blocked).astype(float)
    numerical = float(2.0 * np.sum(weights * visible_counts) / (len(directions) * position_count))
    analytic = float(
        vf_row_sky_2d_integ(geometry.rear_surface_tilt_deg, geometry.gcr)
        if sky
        else vf_row_ground_2d_integ(geometry.rear_surface_tilt_deg, geometry.gcr)
    )
    error = abs(numerical - analytic)
    if error > _VF_TOLERANCE:
        raise ValueError(
            "row/angular quadrature resolution is insufficient for analytic view-factor parity"
        )
    return _FieldGeometry(
        rear_normal, directions, weights, visible_counts, analytic, numerical, error
    )


def _ray_segment_hits(
    origin: npt.NDArray[np.float64],
    directions: npt.NDArray[np.float64],
    start: npt.NDArray[np.float64],
    end: npt.NDArray[np.float64],
    cross_axis: npt.NDArray[np.float64],
) -> npt.NDArray[np.bool_]:
    o = np.asarray((np.dot(origin, cross_axis), origin[2]))
    d = np.column_stack((directions @ cross_axis, directions[:, 2]))
    a = np.asarray((np.dot(start, cross_axis), start[2]))
    b = np.asarray((np.dot(end, cross_axis), end[2]))
    segment = b - a
    denominator = d[:, 0] * segment[1] - d[:, 1] * segment[0]
    offset = a - o
    valid = np.abs(denominator) > 1e-12
    t = np.full(len(directions), np.inf)
    u = np.full(len(directions), np.inf)
    t[valid] = (offset[0] * segment[1] - offset[1] * segment[0]) / denominator[valid]
    u[valid] = (offset[0] * d[valid, 1] - offset[1] * d[valid, 0]) / denominator[valid]
    return np.asarray(
        valid & (t > 1e-10) & (u >= -1e-12) & (u <= 1.0 + 1e-12),
        dtype=np.bool_,
    )


def _conditioned_iam(
    field: _FieldGeometry, parameters: Mapping[str, object]
) -> tuple[float, float, bool, str]:
    model = cast(BeamIAMModel, parameters["model"])
    contributing = field.weights > 0.0
    total_weight = float(np.sum(field.weights[contributing]))
    if total_weight <= _TOLERANCE:
        return np.nan, np.nan, False, "not_applicable_no_row_visible_field"
    aoi = np.degrees(np.arccos(np.clip(field.directions[contributing] @ field.normal, -1.0, 1.0)))
    index = pd.date_range("2000-01-01", periods=len(aoi), freq="s", tz="UTC")
    iam_frame = calculate_beam_iam(
        pd.Series(aoi, index=index),
        model=model,
        model_parameters=cast(Mapping[str, object], parameters["model_parameters"]),
    )
    if not iam_frame["beam_iam_resolved"].all():
        raise RuntimeError("rear directional IAM is unresolved")
    iam = iam_frame["beam_iam_factor"].to_numpy(float)
    if not np.isfinite(iam).all() or (iam < -_TOLERANCE).any() or (iam > 1.0 + _TOLERANCE).any():
        raise RuntimeError("rear directional IAM is outside [0, 1]")
    iam = np.clip(iam, 0.0, 1.0)
    weights = field.weights[contributing]
    counts = field.visible_counts[contributing]
    unobstructed = float(np.sum(weights * iam) / total_weight)
    denominator = float(np.sum(weights * counts))
    if denominator <= _TOLERANCE:
        return unobstructed, np.nan, False, "not_applicable_no_row_visible_field"
    conditioned = float(np.sum(weights * counts * iam) / denominator)
    if not 0.0 - _TOLERANCE <= conditioned <= 1.0 + _TOLERANCE:
        raise RuntimeError("row-conditioned IAM is outside [0, 1]")
    return unobstructed, float(np.clip(conditioned, 0, 1)), True, "resolved"


def _hemisphere(count: int, *, upper: bool) -> npt.NDArray[np.float64]:
    index = np.arange(count, dtype=float)
    z = (index + 0.5) / count
    if not upper:
        z = -z
    radius = np.sqrt(1.0 - z * z)
    azimuth = index * _GOLDEN_ANGLE
    return np.column_stack((radius * np.sin(azimuth), radius * np.cos(azimuth), z))


def _validated_state(frame: pd.DataFrame, receiver_ids: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("rear optical state must use a MultiIndex")
    result = frame.copy()
    if len(result) and set(result.index.get_level_values("receiver_id")) != set(receiver_ids):
        raise ValueError("rear optical state receiver IDs must exactly match scene receiver IDs")
    required_values = {
        "rear_optical_state_contract": REAR_OPTICAL_STATE_CONTRACT_ID,
        "rear_optical_state_model": REAR_OPTICAL_STATE_MODEL_ID,
        "rear_optical_state_coverage_scope": REAR_OPTICAL_STATE_COVERAGE_SCOPE,
        "rear_irradiance_model": S6E_MODEL_ID,
        "rear_coverage_scope": S6E_COVERAGE_SCOPE,
        "rear_row_geometry_model": S6E_MODEL_ID,
    }
    for column, expected in required_values.items():
        if column not in result or not (result[column] == expected).all():
            raise ValueError(f"rear optical state {column} is incompatible")
    for _, row in result.iterrows():
        if bool(row["rear_irradiance_resolved"]):
            for flag in (
                "rear_row_direct_shading_embedded",
                "rear_row_sky_view_factor_embedded",
                "rear_ground_row_shadowing_embedded",
                "rear_row_ground_view_factor_embedded",
            ):
                if not bool(row[flag]):
                    raise ValueError("resolved rear state must preserve embedded row physics")
    return result


def _validate_state_geometry(
    state: pd.DataFrame,
    geometry_by_receiver: Mapping[str, FixedBifacialRearArrayOpticalGeometry],
) -> None:
    for (_, receiver_value), row in state.iterrows():
        geometry = geometry_by_receiver[str(receiver_value)]
        if row["fixed_row_array_id"] != geometry.array_id:
            raise ValueError("rear state array ID conflicts with scene geometry")
        for column in ("surface_tilt_deg", "rear_surface_tilt_deg"):
            if not np.isclose(float(row[column]), getattr(geometry, column), atol=1e-10):
                raise ValueError("rear state tilt conflicts with scene geometry")
        for column in ("surface_azimuth_deg", "rear_surface_azimuth_deg"):
            delta = ((float(row[column]) - getattr(geometry, column) + 180) % 360) - 180
            if abs(delta) > 1e-10:
                raise ValueError("rear state azimuth conflicts with scene geometry")


def _validated_parameters(value: object) -> Mapping[str, object]:
    required = {
        "model",
        "model_parameters",
        "resolution_method",
        "source_label",
        "source_reference",
        "is_fallback",
    }
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise ValueError("rear IAM parameters are missing required provenance")
    if value["model"] not in ("physical", "ashrae", "martin-ruiz"):
        raise ValueError("rear IAM model is invalid")
    if (value["resolution_method"] == "explicit_fallback") != value["is_fallback"]:
        raise ValueError("rear IAM fallback provenance is inconsistent")
    # Empty evaluation invokes the canonical model-parameter validator.
    calculate_beam_iam(
        pd.Series(index=pd.DatetimeIndex([], tz="UTC"), dtype=float),
        model=cast(BeamIAMModel, value["model"]),
        model_parameters=cast(Mapping[str, object], value["model_parameters"]),
    )
    return value


def _validate_parameter_parity(state: pd.DataFrame, parameters: Mapping[str, object]) -> None:
    provenance = {
        "rear_beam_iam_model": "model",
        "rear_iam_parameter_resolution_method": "resolution_method",
        "rear_iam_parameter_source_label": "source_label",
        "rear_iam_parameter_source_reference": "source_reference",
        "rear_iam_parameter_is_fallback": "is_fallback",
    }
    for state_column, parameter_key in provenance.items():
        if len(state) and not (state[state_column] == parameters[parameter_key]).all():
            raise ValueError("rear IAM parameter provenance does not match S7C-0")
    if state.empty:
        return
    reproduced = calculate_beam_iam(
        state["rear_aoi_deg"],
        model=cast(BeamIAMModel, parameters["model"]),
        model_parameters=cast(Mapping[str, object], parameters["model_parameters"]),
    )
    if not np.array_equal(
        reproduced["beam_iam_resolved"], state["rear_beam_iam_resolved"]
    ) or not np.allclose(
        reproduced.loc[reproduced["beam_iam_resolved"], "beam_iam_factor"],
        state.loc[state["rear_beam_iam_resolved"], "rear_beam_iam_factor"],
        rtol=1e-12,
        atol=_TOLERANCE,
    ):
        raise ValueError("rear IAM parameters do not reproduce S7C-0 beam IAM")


def _receiver_state(state: pd.DataFrame, receiver_id: str) -> pd.DataFrame:
    return state.xs(receiver_id, level="receiver_id") if len(state) else state.iloc[:0]


def _count(value: object, name: str, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [column for column in frame if column.endswith("_resolved")]
    bool_columns.extend(("rear_iam_parameter_is_fallback", "rear_row_geometry_already_embedded"))
    string_columns = [
        column
        for column in frame
        if column.endswith("_state")
        or column.endswith("_model")
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
        frame[column] = frame[column].astype(bool)
    for column in string_columns:
        frame[column] = frame[column].astype("string")
    for column in set(frame) - set(bool_columns) - set(string_columns):
        frame[column] = frame[column].astype(float)
    return frame
