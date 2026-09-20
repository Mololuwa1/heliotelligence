"""Front-referenced bifacial electrical-equivalent irradiance composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.bifacial_response import resolve_bifacial_response_parameters
from heliotelligence.physics.effective_irradiance import (
    EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
    EFFECTIVE_IRRADIANCE_MODEL_ID,
    FrontEffectiveIrradianceResult,
)
from heliotelligence.physics.rear_effective_irradiance import (
    REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID,
    REAR_EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
    REAR_EFFECTIVE_IRRADIANCE_MODEL_ID,
    REAR_EFFECTIVE_IRRADIANCE_SCOPE,
    RearEffectiveIrradianceResult,
)

BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID = "bifacial_electrical_equivalent_irradiance_v1"
BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID = "iec_phi_isc_front_rear_composition_v1"
BIFACIAL_EQUIVALENT_IRRADIANCE_COVERAGE_SCOPE = (
    "fixed_table_front_rear_electrical_equivalent_irradiance"
)
BIFACIAL_EQUIVALENT_IRRADIANCE_SCOPE = "electrical_equivalent_irradiance_only"
_FRONT_SCOPE = "front_surface_only"
_ATOL = 1e-9
_RTOL = 1e-12
_PARAMETER_KEYS = {
    "bifacial_enabled",
    "isc_bifaciality_factor",
    "bifaciality_coefficient_kind",
    "resolution_method",
    "source_label",
    "source_reference",
    "is_fallback",
    "front_isc_stc_a",
    "rear_isc_stc_a",
    "derivation_note",
    "equivalent_irradiance_formula",
    "bifacial_response_contract",
    "bifacial_response_model",
    "bifacial_response_standard_basis",
    "bifacial_response_scope",
}
_FRONT_COMPONENTS = {
    "direct": ("poa_front_direct_effective_wm2", "front_direct_effective_resolved"),
    "circumsolar": ("poa_front_circumsolar_effective_wm2", "front_circumsolar_effective_resolved"),
    "isotropic": ("poa_front_isotropic_effective_wm2", "front_isotropic_effective_resolved"),
    "horizon": ("poa_front_horizon_effective_wm2", "front_horizon_effective_resolved"),
    "ground": ("poa_front_ground_diffuse_effective_wm2", "front_ground_diffuse_effective_resolved"),
}
_REAR_COMPONENTS = {
    "direct": ("poa_rear_direct_effective_wm2", "rear_direct_effective_resolved"),
    "circumsolar": (
        "poa_rear_circumsolar_diffuse_effective_wm2",
        "rear_circumsolar_effective_resolved",
    ),
    "isotropic": ("poa_rear_isotropic_sky_effective_wm2", "rear_isotropic_sky_effective_resolved"),
    "ground": ("poa_rear_ground_diffuse_effective_wm2", "rear_ground_diffuse_effective_resolved"),
}
_FRONT_REQUIRED = {
    "surface_tilt_deg",
    "surface_azimuth_deg",
    *tuple(value for pair in _FRONT_COMPONENTS.values() for value in pair),
    "poa_front_sky_diffuse_effective_wm2",
    "poa_front_diffuse_effective_wm2",
    "poa_front_effective_optical_wm2",
    "front_effective_irradiance_resolved",
    "front_effective_irradiance_state",
    "effective_irradiance_model",
    "effective_irradiance_coverage_scope",
    "effective_irradiance_scope",
}
_REAR_REQUIRED = {
    *tuple(value for pair in _REAR_COMPONENTS.values() for value in pair),
    "poa_rear_sky_diffuse_effective_wm2",
    "poa_rear_diffuse_effective_wm2",
    "poa_rear_effective_optical_wm2",
    "rear_effective_irradiance_resolved",
    "rear_effective_irradiance_state",
    "rear_effective_irradiance_contract",
    "rear_effective_irradiance_model",
    "rear_effective_irradiance_coverage_scope",
    "rear_effective_irradiance_scope",
}
_OUTPUT_COLUMNS = (
    "surface_tilt_deg",
    "surface_azimuth_deg",
    "poa_front_effective_optical_wm2",
    "poa_rear_effective_optical_wm2",
    *_PARAMETER_KEYS,
    "rear_electrical_equivalent_irradiance_wm2",
    "rear_electrical_equivalent_resolved",
    "rear_electrical_equivalent_state",
    "bifacial_electrical_equivalent_irradiance_wm2",
    "bifacial_electrical_equivalent_resolved",
    "bifacial_electrical_equivalent_state",
    "front_effective_irradiance_model",
    "front_effective_irradiance_coverage_scope",
    "front_effective_irradiance_scope",
    "rear_effective_irradiance_contract",
    "rear_effective_irradiance_model",
    "rear_effective_irradiance_coverage_scope",
    "rear_effective_irradiance_scope",
    "rear_effective_input_present",
    "bifacial_equivalent_irradiance_contract",
    "bifacial_equivalent_irradiance_model",
    "bifacial_equivalent_irradiance_coverage_scope",
    "bifacial_equivalent_irradiance_scope",
)


@dataclass(frozen=True)
class BifacialEquivalentIrradianceDiagnostics:
    receiver_count: int
    bifacial_receiver_count: int
    monofacial_receiver_count: int
    timestamp_count: int
    row_count: int
    resolved_row_count: int
    unresolved_row_count: int
    bifacial_equivalent_irradiance_model: str


@dataclass(frozen=True)
class BifacialEquivalentIrradianceResult:
    irradiance: pd.DataFrame
    diagnostics: BifacialEquivalentIrradianceDiagnostics


def calculate_bifacial_electrical_equivalent_irradiance(
    receivers: Sequence[PVReceiver],
    front_effective_irradiance: FrontEffectiveIrradianceResult,
    *,
    bifacial_response_parameters_by_receiver: Mapping[str, Mapping[str, object]],
    rear_effective_irradiance: RearEffectiveIrradianceResult | None = None,
) -> BifacialEquivalentIrradianceResult:
    """Compose front and phi_Isc-weighted rear optical-effective irradiance."""
    receiver_ids = _receivers(receivers)
    if not isinstance(front_effective_irradiance, FrontEffectiveIrradianceResult):
        raise ValueError("front_effective_irradiance must be FrontEffectiveIrradianceResult")
    if not isinstance(bifacial_response_parameters_by_receiver, Mapping) or set(
        bifacial_response_parameters_by_receiver
    ) != set(receiver_ids):
        raise ValueError("bifacial response parameter keys must exactly match receivers")
    parameters = {
        receiver_id: _parameters(bifacial_response_parameters_by_receiver[receiver_id])
        for receiver_id in receiver_ids
    }
    bifacial_ids = {key for key, value in parameters.items() if value["bifacial_enabled"] is True}
    front = _frame(front_effective_irradiance.irradiance, receiver_ids, _FRONT_REQUIRED, "front")
    _front(front)
    rear: pd.DataFrame | None = None
    if bifacial_ids:
        if not isinstance(rear_effective_irradiance, RearEffectiveIrradianceResult):
            raise ValueError("a canonical rear result is required for bifacial receivers")
        rear = _frame(rear_effective_irradiance.irradiance, receiver_ids, _REAR_REQUIRED, "rear")
        if not front.index.equals(rear.index):
            raise ValueError("front and rear row keys must match exactly")
        _rear(rear)
    elif rear_effective_irradiance is not None:
        raise ValueError("all-monofacial composition must not receive rear irradiance")
    rows = []
    for index, front_row in front.iterrows():
        receiver_id = str(index[1])
        rear_row = rear.loc[index] if rear is not None else None
        rows.append(_compose(front_row, rear_row, parameters[receiver_id], rear is not None))
    output = _typed(pd.DataFrame(rows, index=front.index, columns=_OUTPUT_COLUMNS))
    resolved = int(output["bifacial_electrical_equivalent_resolved"].sum()) if len(output) else 0
    return BifacialEquivalentIrradianceResult(
        output,
        BifacialEquivalentIrradianceDiagnostics(
            len(receiver_ids),
            len(bifacial_ids),
            len(receiver_ids) - len(bifacial_ids),
            len(front.index.get_level_values(0).unique()),
            len(output),
            resolved,
            len(output) - resolved,
            BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID,
        ),
    )


def _receivers(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise ValueError("receivers must be a non-empty sequence")
    if any(not isinstance(item, PVReceiver) for item in value):
        raise ValueError("receivers must contain PVReceiver")
    ids = tuple(item.id for item in value)
    if len(ids) != len(set(ids)):
        raise ValueError("receiver IDs must be unique")
    for item in value:
        if item.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError("S6C runtime tracker pose is required before bifacial composition")
        if item.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("bifacial composition supports FIXED_TABLE receivers only")
    return tuple(sorted(ids))


def _parameters(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _PARAMETER_KEYS:
        raise ValueError("response parameter mapping must contain exactly the canonical 15 keys")
    method = value["resolution_method"]
    kwargs: dict[str, object] = {
        "bifacial_enabled": value["bifacial_enabled"],
        "method": method,
        "source_label": value["source_label"],
        "source_reference": value["source_reference"],
    }
    if method in ("direct", "explicit_fallback"):
        kwargs["isc_bifaciality_factor"] = value["isc_bifaciality_factor"]
    elif method == "derived_stc_isc_ratio":
        kwargs["front_isc_stc_a"] = value["front_isc_stc_a"]
        kwargs["rear_isc_stc_a"] = value["rear_isc_stc_a"]
    replayed = resolve_bifacial_response_parameters(**kwargs)  # type: ignore[arg-type]
    if dict(value) != replayed:
        raise ValueError("response parameter mapping does not match canonical S7D-0 replay")
    return replayed


def _frame(value: object, ids: tuple[str, ...], required: set[str], label: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame) or not isinstance(value.index, pd.MultiIndex):
        raise ValueError(f"{label} result must use a MultiIndex")
    if value.index.nlevels != 2 or value.index.names[1] != "receiver_id":
        raise ValueError(f"{label} index must be timestamp/receiver_id")
    if not required.issubset(value.columns):
        raise ValueError(f"{label} result is missing required columns")
    times = value.index.get_level_values(0)
    if not isinstance(times, pd.DatetimeIndex) or times.tz is None:
        raise ValueError(f"{label} timestamps must be timezone-aware")
    if times.hasnans or value.index.has_duplicates:
        raise ValueError(f"{label} index contains NaT or duplicates")
    result = value.copy()
    if len(result):
        if set(result.index.get_level_values("receiver_id")) != set(ids):
            raise ValueError(f"{label} receiver IDs do not match")
        expected = pd.MultiIndex.from_product(
            (pd.DatetimeIndex(times.unique()).sort_values(), ids), names=result.index.names
        )
        if set(result.index) != set(expected):
            raise ValueError(f"{label} grid is incomplete")
        result = result.reindex(expected)
    return result


def _front(frame: pd.DataFrame) -> None:
    exact = {
        "effective_irradiance_model": EFFECTIVE_IRRADIANCE_MODEL_ID,
        "effective_irradiance_coverage_scope": EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
        "effective_irradiance_scope": _FRONT_SCOPE,
    }
    _exact(frame, exact, "front")
    for _, row in frame.iterrows():
        values = _components(row, _FRONT_COMPONENTS)
        resolved = _bool(row["front_effective_irradiance_resolved"], "front total resolved")
        total = row["poa_front_effective_optical_wm2"]
        if resolved:
            if (
                not all(value[1] for value in values.values())
                or row["front_effective_irradiance_state"] != "resolved"
            ):
                raise ValueError("front resolution state is inconsistent")
            total_value = _number(total, "front total")
            sky = _number(row["poa_front_sky_diffuse_effective_wm2"], "front sky")
            diffuse = _number(row["poa_front_diffuse_effective_wm2"], "front diffuse")
            _close(
                sky,
                values["circumsolar"][0] + values["isotropic"][0] + values["horizon"][0],
                "front sky",
            )
            _close(diffuse, sky + values["ground"][0], "front diffuse")
            _close(total_value, values["direct"][0] + diffuse, "front total")
            if (
                "poa_front_global_raw_wm2" in row
                and total_value > float(row["poa_front_global_raw_wm2"]) + _ATOL
            ):
                raise ValueError("front effective total exceeds raw global")
        elif row["front_effective_irradiance_state"] not in (
            "unresolved_upstream_irradiance",
            "unresolved_component_dependency",
        ) or any(
            not pd.isna(row[column])
            for column in (
                "poa_front_effective_optical_wm2",
                "poa_front_sky_diffuse_effective_wm2",
                "poa_front_diffuse_effective_wm2",
            )
        ):
            raise ValueError("unresolved front total representation is invalid")


def _rear(frame: pd.DataFrame) -> None:
    _exact(
        frame,
        {
            "rear_effective_irradiance_contract": REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID,
            "rear_effective_irradiance_model": REAR_EFFECTIVE_IRRADIANCE_MODEL_ID,
            "rear_effective_irradiance_coverage_scope": REAR_EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
            "rear_effective_irradiance_scope": REAR_EFFECTIVE_IRRADIANCE_SCOPE,
        },
        "rear",
    )
    for _, row in frame.iterrows():
        values = _components(row, _REAR_COMPONENTS)
        resolved = _bool(row["rear_effective_irradiance_resolved"], "rear total resolved")
        if resolved:
            if (
                not all(value[1] for value in values.values())
                or row["rear_effective_irradiance_state"] != "resolved"
            ):
                raise ValueError("rear resolution state is inconsistent")
            total = _number(row["poa_rear_effective_optical_wm2"], "rear total")
            sky = _number(row["poa_rear_sky_diffuse_effective_wm2"], "rear sky")
            diffuse = _number(row["poa_rear_diffuse_effective_wm2"], "rear diffuse")
            _close(sky, values["circumsolar"][0] + values["isotropic"][0], "rear sky")
            _close(diffuse, sky + values["ground"][0], "rear diffuse")
            _close(total, values["direct"][0] + diffuse, "rear total")
            if (
                "poa_rear_global_raw_wm2" in row
                and total > float(row["poa_rear_global_raw_wm2"]) + _ATOL
            ):
                raise ValueError("rear effective total exceeds raw global")
        elif row["rear_effective_irradiance_state"] not in (
            "unresolved_upstream_rear_irradiance",
            "unresolved_component_dependency",
        ) or not pd.isna(row["poa_rear_effective_optical_wm2"]):
            raise ValueError("unresolved rear total representation is invalid")


def _components(
    row: pd.Series, fields: Mapping[str, tuple[str, str]]
) -> dict[str, tuple[float, bool]]:
    result = {}
    for name, (column, flag) in fields.items():
        resolved = _bool(row[flag], flag)
        if resolved:
            result[name] = (_number(row[column], column), True)
        elif not pd.isna(row[column]):
            raise ValueError(f"unresolved {column} must be NaN")
        else:
            result[name] = (np.nan, False)
    return result


def _compose(
    front: pd.Series, rear: pd.Series | None, parameters: Mapping[str, object], rear_present: bool
) -> dict[str, object]:
    bifacial = parameters["bifacial_enabled"] is True
    front_resolved = bool(front["front_effective_irradiance_resolved"])
    front_value = float(front["poa_front_effective_optical_wm2"]) if front_resolved else np.nan
    rear_optical = (
        float(rear["poa_rear_effective_optical_wm2"])
        if rear is not None and bool(rear["rear_effective_irradiance_resolved"])
        else np.nan
    )
    if not bifacial:
        rear_eq, rear_resolved, rear_state = 0.0, True, "resolved_monofacial_zero"
    elif rear is not None and bool(rear["rear_effective_irradiance_resolved"]):
        rear_eq = _number(parameters["isc_bifaciality_factor"], "phi_Isc") * rear_optical
        rear_resolved, rear_state = True, "resolved"
    else:
        rear_eq, rear_resolved, rear_state = np.nan, False, "unresolved_rear_effective_irradiance"
    total_resolved = front_resolved and rear_resolved
    total = front_value + rear_eq if total_resolved else np.nan
    total_state = (
        "resolved"
        if total_resolved
        else "unresolved_front_and_rear_effective_irradiance"
        if not front_resolved and not rear_resolved
        else "unresolved_front_effective_irradiance"
        if not front_resolved
        else "unresolved_rear_effective_irradiance"
    )
    if total_resolved:
        if rear_eq < -_ATOL or (bifacial and rear_eq > rear_optical + _ATOL):
            raise RuntimeError("rear electrical equivalent violates bounds")
        upper = front_value + (rear_optical if bifacial else 0.0)
        if total < front_value - _ATOL or total > upper + _ATOL:
            raise RuntimeError("bifacial electrical equivalent violates bounds")
    row = {
        "surface_tilt_deg": front["surface_tilt_deg"],
        "surface_azimuth_deg": front["surface_azimuth_deg"],
        "poa_front_effective_optical_wm2": front_value,
        "poa_rear_effective_optical_wm2": rear_optical,
        **parameters,
        "rear_electrical_equivalent_irradiance_wm2": rear_eq,
        "rear_electrical_equivalent_resolved": rear_resolved,
        "rear_electrical_equivalent_state": rear_state,
        "bifacial_electrical_equivalent_irradiance_wm2": total,
        "bifacial_electrical_equivalent_resolved": total_resolved,
        "bifacial_electrical_equivalent_state": total_state,
        "front_effective_irradiance_model": front["effective_irradiance_model"],
        "front_effective_irradiance_coverage_scope": front["effective_irradiance_coverage_scope"],
        "front_effective_irradiance_scope": front["effective_irradiance_scope"],
        "rear_effective_irradiance_contract": rear["rear_effective_irradiance_contract"]
        if rear is not None
        else pd.NA,
        "rear_effective_irradiance_model": rear["rear_effective_irradiance_model"]
        if rear is not None
        else pd.NA,
        "rear_effective_irradiance_coverage_scope": rear["rear_effective_irradiance_coverage_scope"]
        if rear is not None
        else pd.NA,
        "rear_effective_irradiance_scope": rear["rear_effective_irradiance_scope"]
        if rear is not None
        else pd.NA,
        "rear_effective_input_present": rear_present,
        "bifacial_equivalent_irradiance_contract": BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID,
        "bifacial_equivalent_irradiance_model": BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID,
        "bifacial_equivalent_irradiance_coverage_scope": (
            BIFACIAL_EQUIVALENT_IRRADIANCE_COVERAGE_SCOPE
        ),
        "bifacial_equivalent_irradiance_scope": BIFACIAL_EQUIVALENT_IRRADIANCE_SCOPE,
    }
    return row


def _exact(frame: pd.DataFrame, expected: Mapping[str, str], label: str) -> None:
    for column, target in expected.items():
        if any(not isinstance(value, str) or value != target for value in frame[column].array):
            raise ValueError(f"{label} {column} is incompatible")


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a Boolean")
    return bool(value)


def _number(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite non-negative real")
    result = float(value)
    if not np.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative real")
    return result


def _close(actual: float, expected: float, name: str) -> None:
    if not np.isclose(actual, expected, atol=_ATOL, rtol=_RTOL):
        raise ValueError(f"{name} closure failed")


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [column for column in frame if column.endswith("_resolved")]
    bool_columns.extend(("bifacial_enabled", "is_fallback", "rear_effective_input_present"))
    string_columns = [
        column
        for column in frame
        if column.endswith(("_state", "_model", "_scope", "_contract"))
        or column
        in (
            "bifaciality_coefficient_kind",
            "resolution_method",
            "source_label",
            "source_reference",
            "derivation_note",
            "equivalent_irradiance_formula",
            "bifacial_response_standard_basis",
            "front_effective_irradiance_coverage_scope",
            "rear_effective_irradiance_coverage_scope",
            "bifacial_equivalent_irradiance_coverage_scope",
        )
    ]
    for column in bool_columns:
        frame[column] = frame[column].astype(bool)
    for column in string_columns:
        frame[column] = frame[column].astype("string")
    for column in set(frame) - set(bool_columns) - set(string_columns):
        frame[column] = frame[column].astype(float)
    return frame
