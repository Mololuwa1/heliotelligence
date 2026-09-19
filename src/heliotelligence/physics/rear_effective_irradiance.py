"""Component-resolved rear optical-effective irradiance composition."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.fixed_bifacial_rear import (
    COVERAGE_SCOPE as S6E_COVERAGE_SCOPE,
)
from heliotelligence.physics.fixed_bifacial_rear import MODEL_ID as S6E_MODEL_ID
from heliotelligence.physics.rear_optical_state import (
    REAR_OPTICAL_STATE_CONTRACT_ID,
    REAR_OPTICAL_STATE_COVERAGE_SCOPE,
    REAR_OPTICAL_STATE_MODEL_ID,
    RearOpticalStateResult,
)
from heliotelligence.physics.rear_row_optical_transmission import (
    REAR_ROW_OPTICAL_CONTRACT_ID,
    REAR_ROW_OPTICAL_COVERAGE_SCOPE,
    REAR_ROW_OPTICAL_MODEL_ID,
    RearRowOpticalTransmissionResult,
)

REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID = "rear_effective_irradiance_v1"
REAR_EFFECTIVE_IRRADIANCE_MODEL_ID = "component_resolved_rear_optical_effective_irradiance_v1"
REAR_EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE = (
    "regular_parallel_fixed_rows_level_ground_rear_surface_only"
)
REAR_EFFECTIVE_IRRADIANCE_SCOPE = "rear_surface_only"
_ATOL = 1e-9
_RTOL = 1e-12

_RAW = {
    "direct": "poa_rear_direct_raw_wm2",
    "circumsolar": "poa_rear_circumsolar_diffuse_raw_wm2",
    "isotropic_sky": "poa_rear_isotropic_sky_raw_wm2",
    "ground": "poa_rear_ground_diffuse_raw_wm2",
}
_FACTORS = {
    "direct": "rear_direct_s6e_relative_optical",
    "circumsolar": "rear_circumsolar_s6e_relative_optical",
    "isotropic_sky": "rear_isotropic_sky_s6e_relative_optical",
    "ground": "rear_ground_s6e_relative_optical",
}
_EFFECTIVE = {
    "direct": "poa_rear_direct_effective_wm2",
    "circumsolar": "poa_rear_circumsolar_diffuse_effective_wm2",
    "isotropic_sky": "poa_rear_isotropic_sky_effective_wm2",
    "ground": "poa_rear_ground_diffuse_effective_wm2",
}
_RESOLVED = {
    "direct": "rear_direct_effective_resolved",
    "circumsolar": "rear_circumsolar_effective_resolved",
    "isotropic_sky": "rear_isotropic_sky_effective_resolved",
    "ground": "rear_ground_diffuse_effective_resolved",
}
_STATE_REQUIRED = {
    "fixed_row_array_id",
    "rear_surface_tilt_deg",
    "rear_surface_azimuth_deg",
    *tuple(_RAW.values()),
    "poa_rear_sky_diffuse_raw_wm2",
    "poa_rear_diffuse_raw_wm2",
    "poa_rear_global_raw_wm2",
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
    "rear_diffuse_model",
    "rear_irradiance_model",
    "rear_coverage_scope",
    "rear_optical_admission_state",
    "rear_optical_state_contract",
    "rear_optical_state_model",
    "rear_optical_state_coverage_scope",
}
_TRANSMISSION_REQUIRED = {
    "fixed_row_array_id",
    "rear_surface_tilt_deg",
    "rear_surface_azimuth_deg",
    *tuple(
        f"{base}_{suffix}"
        for base in _FACTORS.values()
        for suffix in ("factor", "resolved", "state")
    ),
    "rear_sky_row_conditioned_iam_factor",
    "rear_sky_row_conditioned_iam_resolved",
    "rear_sky_row_conditioned_iam_state",
    "rear_ground_row_conditioned_iam_factor",
    "rear_ground_row_conditioned_iam_resolved",
    "rear_ground_row_conditioned_iam_state",
    "rear_beam_iam_model",
    "rear_iam_parameter_resolution_method",
    "rear_iam_parameter_source_label",
    "rear_iam_parameter_source_reference",
    "rear_iam_parameter_is_fallback",
    "rear_row_geometry_already_embedded",
    "rear_row_optical_contract",
    "rear_row_optical_model",
    "rear_row_optical_coverage_scope",
}
_OUTPUT_COLUMNS = (
    "fixed_row_array_id",
    "rear_surface_tilt_deg",
    "rear_surface_azimuth_deg",
    "rear_diffuse_model",
    *_RAW.values(),
    "poa_rear_sky_diffuse_raw_wm2",
    "poa_rear_diffuse_raw_wm2",
    "poa_rear_global_raw_wm2",
    *tuple(
        f"{base}_{suffix}"
        for base in _FACTORS.values()
        for suffix in ("factor", "resolved", "state")
    ),
    "rear_beam_iam_model",
    "rear_iam_parameter_resolution_method",
    "rear_iam_parameter_source_label",
    "rear_iam_parameter_source_reference",
    "rear_iam_parameter_is_fallback",
    *_EFFECTIVE.values(),
    "poa_rear_sky_diffuse_effective_wm2",
    "poa_rear_diffuse_effective_wm2",
    "poa_rear_effective_optical_wm2",
    *_RESOLVED.values(),
    "rear_effective_irradiance_resolved",
    "rear_effective_irradiance_state",
    "rear_irradiance_model",
    "rear_coverage_scope",
    "rear_optical_state_contract",
    "rear_optical_state_model",
    "rear_optical_state_coverage_scope",
    "rear_row_optical_contract",
    "rear_row_optical_model",
    "rear_row_optical_coverage_scope",
    "rear_row_geometry_already_embedded",
    "rear_effective_irradiance_contract",
    "rear_effective_irradiance_model",
    "rear_effective_irradiance_coverage_scope",
    "rear_effective_irradiance_scope",
)


@dataclass(frozen=True)
class RearEffectiveIrradianceDiagnostics:
    receiver_count: int
    timestamp_count: int
    row_count: int
    resolved_row_count: int
    unresolved_row_count: int
    rear_diffuse_model: str | None
    rear_effective_irradiance_model: str


@dataclass(frozen=True)
class RearEffectiveIrradianceResult:
    irradiance: pd.DataFrame
    diagnostics: RearEffectiveIrradianceDiagnostics


def calculate_rear_effective_irradiance(
    receivers: Sequence[PVReceiver],
    rear_optical_state: RearOpticalStateResult,
    rear_row_optical_transmission: RearRowOpticalTransmissionResult,
) -> RearEffectiveIrradianceResult:
    """Apply validated S6E-relative factors without adding optical physics."""
    receiver_ids = _receiver_ids(receivers)
    if not isinstance(rear_optical_state, RearOpticalStateResult):
        raise ValueError("rear_optical_state must be RearOpticalStateResult")
    if not isinstance(rear_row_optical_transmission, RearRowOpticalTransmissionResult):
        raise ValueError("rear_row_optical_transmission must be RearRowOpticalTransmissionResult")
    state = _frame(rear_optical_state.state, receiver_ids, _STATE_REQUIRED, "S7C-0")
    transmission = _frame(
        rear_row_optical_transmission.transmission,
        receiver_ids,
        _TRANSMISSION_REQUIRED,
        "S7C-1",
    )
    if not state.index.equals(transmission.index):
        raise ValueError("S7C-0 and S7C-1 must contain exactly the same row keys")
    diffuse_model = _validate_state(state)
    _validate_transmission(state, transmission)
    rows = [
        _compose(s, t)
        for (_, s), (_, t) in zip(state.iterrows(), transmission.iterrows(), strict=True)
    ]
    output = _typed(pd.DataFrame(rows, index=state.index, columns=_OUTPUT_COLUMNS))
    resolved_count = int(output["rear_effective_irradiance_resolved"].sum()) if len(output) else 0
    timestamps = state.index.get_level_values(0).unique()
    return RearEffectiveIrradianceResult(
        output,
        RearEffectiveIrradianceDiagnostics(
            len(receiver_ids),
            len(timestamps),
            len(output),
            resolved_count,
            len(output) - resolved_count,
            diffuse_model,
            REAR_EFFECTIVE_IRRADIANCE_MODEL_ID,
        ),
    )


def _receiver_ids(receivers: object) -> tuple[str, ...]:
    if not isinstance(receivers, Sequence) or isinstance(receivers, (str, bytes)):
        raise ValueError("receivers must be a sequence of PVReceiver")
    values = tuple(receivers)
    if any(not isinstance(item, PVReceiver) for item in values):
        raise ValueError("receivers must contain only PVReceiver")
    identifiers = tuple(item.id for item in values)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("receiver IDs must be unique")
    for item in values:
        if item.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError("S6C runtime tracker pose is required before rear optical composition")
        if item.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("rear effective irradiance supports FIXED_TABLE receivers only")
    return tuple(sorted(identifiers))


def _frame(
    value: object, receiver_ids: tuple[str, ...], required: set[str], label: str
) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame) or not isinstance(value.index, pd.MultiIndex):
        raise ValueError(f"{label} must use a two-level MultiIndex")
    if value.index.nlevels != 2 or value.index.names[1] != "receiver_id":
        raise ValueError(f"{label} must use timestamp/receiver_id index levels")
    missing = required - set(value.columns)
    if missing:
        raise ValueError(f"{label} is missing required columns: {sorted(missing)}")
    timestamps = value.index.get_level_values(0)
    if not isinstance(timestamps, pd.DatetimeIndex) or timestamps.tz is None:
        raise ValueError(f"{label} timestamps must be timezone-aware")
    if timestamps.hasnans or value.index.has_duplicates:
        raise ValueError(f"{label} index must not contain NaT or duplicates")
    result = value.copy()
    if len(result):
        ids = result.index.get_level_values("receiver_id")
        if set(ids) != set(receiver_ids):
            raise ValueError(f"{label} receiver IDs must exactly match canonical receivers")
        ordered_times = pd.DatetimeIndex(timestamps.unique()).sort_values()
        expected = pd.MultiIndex.from_product(
            (ordered_times, receiver_ids), names=result.index.names
        )
        if set(result.index) != set(expected):
            raise ValueError(f"{label} must contain every timestamp/receiver combination")
        result = result.reindex(expected)
    elif (
        not isinstance(result.index.levels[0], pd.DatetimeIndex)
        or result.index.levels[0].tz is None
    ):
        raise ValueError(f"empty {label} timestamps must be timezone-aware")
    return result


def _validate_state(state: pd.DataFrame) -> str | None:
    exact = {
        "rear_optical_state_contract": REAR_OPTICAL_STATE_CONTRACT_ID,
        "rear_optical_state_model": REAR_OPTICAL_STATE_MODEL_ID,
        "rear_optical_state_coverage_scope": REAR_OPTICAL_STATE_COVERAGE_SCOPE,
        "rear_irradiance_model": S6E_MODEL_ID,
        "rear_coverage_scope": S6E_COVERAGE_SCOPE,
        "rear_row_geometry_model": S6E_MODEL_ID,
    }
    for column, expected in exact.items():
        if any(not isinstance(value, str) or value != expected for value in state[column].array):
            raise ValueError(f"S7C-0 {column} is incompatible")
    models: set[str] = set()
    for _, row in state.iterrows():
        _provenance(row)
        array_id = row["fixed_row_array_id"]
        if not isinstance(array_id, str) or not array_id.strip():
            raise ValueError("fixed_row_array_id must be a non-empty string")
        model = row["rear_diffuse_model"]
        if not isinstance(model, str) or model not in ("isotropic", "haydavies"):
            raise ValueError("rear diffuse model is invalid")
        models.add(model)
        resolved = _boolean(row["rear_irradiance_resolved"], "rear_irradiance_resolved")
        if row["rear_irradiance_state"] != (
            "resolved" if resolved else "unresolved_missing_irradiance"
        ):
            raise ValueError("rear irradiance state contradicts resolution")
        admission = "resolved" if resolved else "unresolved_upstream_rear_irradiance"
        if row["rear_optical_admission_state"] != admission:
            raise ValueError("rear optical admission state contradicts resolution")
        for flag in (
            "rear_row_direct_shading_embedded",
            "rear_row_sky_view_factor_embedded",
            "rear_ground_row_shadowing_embedded",
            "rear_row_ground_view_factor_embedded",
        ):
            if _boolean(row[flag], flag) is not resolved:
                raise ValueError("embedded row physics flags contradict resolution")
        raw = {name: row[column] for name, column in _RAW.items()}
        extra = {
            "sky": row["poa_rear_sky_diffuse_raw_wm2"],
            "diffuse": row["poa_rear_diffuse_raw_wm2"],
            "global": row["poa_rear_global_raw_wm2"],
        }
        if resolved:
            values = {name: _nonnegative(value, name) for name, value in {**raw, **extra}.items()}
            _close(values["sky"], values["circumsolar"] + values["isotropic_sky"], "raw sky")
            _close(values["diffuse"], values["sky"] + values["ground"], "raw diffuse")
            _close(values["global"], values["direct"] + values["diffuse"], "raw global")
            if model == "isotropic" and abs(values["circumsolar"]) > _ATOL:
                raise ValueError("isotropic rear model must have zero circumsolar irradiance")
        elif any(not pd.isna(value) for value in (*raw.values(), *extra.values())):
            raise ValueError("unresolved rear raw components must be NaN")
    if len(models) > 1:
        raise ValueError("rear state must use one common diffuse model")
    return next(iter(models), None)


def _validate_transmission(state: pd.DataFrame, transmission: pd.DataFrame) -> None:
    exact = {
        "rear_row_optical_contract": REAR_ROW_OPTICAL_CONTRACT_ID,
        "rear_row_optical_model": REAR_ROW_OPTICAL_MODEL_ID,
        "rear_row_optical_coverage_scope": REAR_ROW_OPTICAL_COVERAGE_SCOPE,
    }
    for column, expected in exact.items():
        if any(
            not isinstance(value, str) or value != expected for value in transmission[column].array
        ):
            raise ValueError(f"S7C-1 {column} is incompatible")
    for (_, source), (_, optical) in zip(state.iterrows(), transmission.iterrows(), strict=True):
        _provenance(optical)
        if (
            _boolean(optical["rear_row_geometry_already_embedded"], "row geometry embedded")
            is not True
        ):
            raise ValueError("S7C-1 must confirm row geometry is already embedded")
        if source["fixed_row_array_id"] != optical["fixed_row_array_id"]:
            raise ValueError("S7C-0/S7C-1 array identity mismatch")
        for column in ("rear_surface_tilt_deg", "rear_surface_azimuth_deg"):
            left = _geometry(source[column], column, azimuth=column.endswith("azimuth_deg"))
            right = _geometry(optical[column], column, azimuth=column.endswith("azimuth_deg"))
            delta = (
                ((left - right + 180) % 360) - 180
                if column.endswith("azimuth_deg")
                else left - right
            )
            if abs(delta) > _ATOL:
                raise ValueError("S7C-0/S7C-1 rear geometry mismatch")
        for column in (
            "rear_beam_iam_model",
            "rear_iam_parameter_resolution_method",
            "rear_iam_parameter_source_label",
            "rear_iam_parameter_source_reference",
            "rear_iam_parameter_is_fallback",
        ):
            if not _same(source[column], optical[column]):
                raise ValueError("S7C-0/S7C-1 IAM provenance mismatch")
        factors = {
            name: _factor(optical, base, directional=name in ("direct", "circumsolar"))
            for name, base in _FACTORS.items()
        }
        beam = (
            source["rear_beam_iam_factor"],
            _boolean(source["rear_beam_iam_resolved"], "rear_beam_iam_resolved"),
            source["rear_beam_iam_state"],
        )
        if not _triple_same(factors["direct"], beam):
            raise ValueError("direct factor does not match S7C-0 beam IAM")
        if not _triple_same(factors["circumsolar"], factors["direct"]):
            raise ValueError("circumsolar factor does not match direct factor")
        sky = _factor(optical, "rear_sky_row_conditioned_iam", directional=False)
        ground = _factor(optical, "rear_ground_row_conditioned_iam", directional=False)
        if not _triple_same(factors["isotropic_sky"], sky):
            raise ValueError("isotropic production factor does not match sky diagnostic")
        if not _triple_same(factors["ground"], ground):
            raise ValueError("ground production factor does not match ground diagnostic")


def _factor(row: pd.Series, base: str, *, directional: bool) -> tuple[object, bool, object]:
    factor, resolved, state = (
        row[f"{base}_factor"],
        _boolean(row[f"{base}_resolved"], f"{base}_resolved"),
        row[f"{base}_state"],
    )
    expected_unresolved = (
        "model_output_unresolved" if directional else "not_applicable_no_row_visible_field"
    )
    if resolved:
        _bounded_factor(factor, f"{base}_factor")
        if state != "resolved":
            raise ValueError(f"{base} resolved state is inconsistent")
    elif not pd.isna(factor) or state != expected_unresolved:
        raise ValueError(f"{base} unresolved representation is inconsistent")
    return factor, resolved, state


def _compose(source: pd.Series, optical: pd.Series) -> dict[str, object]:
    row: dict[str, object] = {}
    for column in _OUTPUT_COLUMNS:
        if column in source:
            row[column] = source[column]
        elif column in optical:
            row[column] = optical[column]
    upstream = bool(source["rear_irradiance_resolved"])
    component_values: dict[str, float] = {}
    component_resolved: dict[str, bool] = {}
    for name in _RAW:
        raw = source[_RAW[name]]
        factor = optical[f"{_FACTORS[name]}_factor"]
        factor_resolved = bool(optical[f"{_FACTORS[name]}_resolved"])
        if not upstream:
            value, resolved = np.nan, False
        elif abs(float(raw)) <= _ATOL:
            value, resolved = 0.0, True
        elif factor_resolved:
            value, resolved = float(raw) * float(factor), True
        else:
            value, resolved = np.nan, False
        component_values[name], component_resolved[name] = value, resolved
        row[_EFFECTIVE[name]], row[_RESOLVED[name]] = value, resolved
    sky_resolved = component_resolved["circumsolar"] and component_resolved["isotropic_sky"]
    diffuse_resolved = sky_resolved and component_resolved["ground"]
    total_resolved = diffuse_resolved and component_resolved["direct"]
    sky = (
        component_values["circumsolar"] + component_values["isotropic_sky"]
        if sky_resolved
        else np.nan
    )
    diffuse = sky + component_values["ground"] if diffuse_resolved else np.nan
    total = component_values["direct"] + diffuse if total_resolved else np.nan
    row["poa_rear_sky_diffuse_effective_wm2"] = sky
    row["poa_rear_diffuse_effective_wm2"] = diffuse
    row["poa_rear_effective_optical_wm2"] = total
    row["rear_effective_irradiance_resolved"] = total_resolved
    row["rear_effective_irradiance_state"] = (
        "resolved"
        if total_resolved
        else "unresolved_upstream_rear_irradiance"
        if not upstream
        else "unresolved_component_dependency"
    )
    if total_resolved:
        _validate_output(source, component_values, sky, diffuse, total)
    row.update(
        {
            "rear_effective_irradiance_contract": REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID,
            "rear_effective_irradiance_model": REAR_EFFECTIVE_IRRADIANCE_MODEL_ID,
            "rear_effective_irradiance_coverage_scope": REAR_EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
            "rear_effective_irradiance_scope": REAR_EFFECTIVE_IRRADIANCE_SCOPE,
        }
    )
    return row


def _validate_output(
    source: pd.Series, values: dict[str, float], sky: float, diffuse: float, total: float
) -> None:
    for name, value in values.items():
        raw = float(source[_RAW[name]])
        if not np.isfinite(value) or value < -_ATOL or value > raw + _ATOL:
            raise RuntimeError("rear effective component violates physical bounds")
    _close_runtime(sky, values["circumsolar"] + values["isotropic_sky"], "effective sky")
    _close_runtime(diffuse, sky + values["ground"], "effective diffuse")
    _close_runtime(total, values["direct"] + diffuse, "effective total")
    if total > float(source["poa_rear_global_raw_wm2"]) + _ATOL:
        raise RuntimeError("rear effective total exceeds raw rear global irradiance")


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a Boolean")
    return bool(value)


def _provenance(row: pd.Series) -> None:
    model = row["rear_beam_iam_model"]
    method = row["rear_iam_parameter_resolution_method"]
    label = row["rear_iam_parameter_source_label"]
    reference = row["rear_iam_parameter_source_reference"]
    fallback = _boolean(row["rear_iam_parameter_is_fallback"], "rear IAM fallback")
    if not isinstance(model, str) or model not in ("physical", "ashrae", "martin-ruiz"):
        raise ValueError("rear beam IAM model is invalid")
    if not isinstance(method, str) or method not in (
        "direct",
        "measured_fit",
        "explicit_fallback",
    ):
        raise ValueError("rear IAM resolution method is invalid")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("rear IAM source label is invalid")
    if not pd.isna(reference) and (not isinstance(reference, str) or not reference.strip()):
        raise ValueError("rear IAM source reference is invalid")
    if (method == "explicit_fallback") is not fallback:
        raise ValueError("rear IAM fallback provenance is inconsistent")


def _nonnegative(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite non-negative real")
    result = float(value)
    if not np.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative real")
    return result


def _bounded_factor(value: object, name: str) -> float:
    result = _nonnegative(value, name)
    if result > 1.0:
        raise ValueError(f"{name} must be within [0, 1]")
    return result


def _geometry(value: object, name: str, *, azimuth: bool) -> float:
    result = _nonnegative(value, name)
    if result > 180.0 if not azimuth else result >= 360.0:
        raise ValueError(f"{name} is outside its valid range")
    return result


def _same(left: object, right: object) -> bool:
    if pd.isna(left) or pd.isna(right):
        return bool(pd.isna(left) and pd.isna(right))
    if isinstance(left, (bool, np.bool_)) or isinstance(right, (bool, np.bool_)):
        return (
            isinstance(left, (bool, np.bool_))
            and isinstance(right, (bool, np.bool_))
            and bool(left) is bool(right)
        )
    return type(left) is type(right) and bool(left == right)


def _triple_same(left: tuple[object, bool, object], right: tuple[object, bool, object]) -> bool:
    return left[1] is right[1] and _same(left[0], right[0]) and _same(left[2], right[2])


def _close(actual: float, expected: float, name: str) -> None:
    if not np.isclose(actual, expected, atol=_ATOL, rtol=_RTOL):
        raise ValueError(f"{name} component closure failed")


def _close_runtime(actual: float, expected: float, name: str) -> None:
    if not np.isclose(actual, expected, atol=_ATOL, rtol=_RTOL):
        raise RuntimeError(f"{name} component closure failed")


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [column for column in frame if column.endswith("_resolved")]
    bool_columns.extend(("rear_iam_parameter_is_fallback", "rear_row_geometry_already_embedded"))
    string_columns = [
        column
        for column in frame
        if column.endswith(("_state", "_model", "_scope", "_contract"))
        or column
        in (
            "fixed_row_array_id",
            "rear_diffuse_model",
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
