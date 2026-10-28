"""Dormant, per-timestamp module cell-temperature resolution for one thermal zone.

Thermal POA is supplied incident broadband irradiance, NOT automatically electrical
effective irradiance. This contract does not establish whether source weather is
instantaneous, interval-start, midpoint or interval-end. No filling, persistence,
thermal inertia, SiteConfig lookup or production integration is performed.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, fields
from numbers import Real
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pvlib.temperature  # type: ignore[import-untyped]

from heliotelligence.physics.module_thermal_authority import (
    MODULE_THERMAL_AUTHORITY_CONTRACT_ID,
    MODULE_THERMAL_AUTHORITY_MODEL_ID,
    FaimanThermalAuthority,
    ModuleBackSurfaceToCellTemperatureAuthority,
    ModuleTemperatureEvidence,
    ModuleThermalMeasurementState,
    PvsystCellThermalAuthority,
    ThermalModelAuthority,
    _revalidate,
    _text,
)

MODULE_THERMAL_STATE_CONTRACT_ID = (
    "admitted_module_temperature_evidence_and_explicit_thermal_model_authority_"
    "to_timestamped_cell_temperature_state_v1"
)
MODULE_THERMAL_STATE_MODEL_ID = (
    "per_timestamp_direct_cell_measurement_module_back_conversion_or_explicit_"
    "pvsyst_faiman_thermal_resolution_v1"
)
MODULE_THERMAL_STATE_SCOPE = (
    "module_cell_temperature_state_before_temperature_dependent_module_electrical_evaluation"
)
MODULE_THERMAL_STATE_COVERAGE_SCOPE = (
    "explicit_thermal_zone_timestamped_measurement_or_native_model_parameter_authority"
)
_FIDELITIES = (
    "direct_cell_temperature_evidence",
    "measured_module_back_to_cell_temperature",
    "pvsyst_cell_temperature",
    "faiman_cell_temperature",
    "faiman_module_back_to_cell_temperature",
)
_UNRESOLVED = (
    "unresolved_no_temperature_evidence_or_model_authority",
    "unresolved_missing_thermal_poa",
    "unresolved_missing_ambient_temperature",
    "unresolved_missing_wind_speed",
    "unresolved_missing_module_to_cell_conversion_authority",
    "unresolved_model_output_is_module_temperature_without_conversion",
    "unresolved_invalid_or_incomplete_model_inputs",
)
_STATES = tuple("resolved_" + value for value in _FIDELITIES) + _UNRESOLVED
_FIXED = MappingProxyType(
    {
        "module_thermal_authority_contract": MODULE_THERMAL_AUTHORITY_CONTRACT_ID,
        "module_thermal_authority_model": MODULE_THERMAL_AUTHORITY_MODEL_ID,
        "module_thermal_state_contract": MODULE_THERMAL_STATE_CONTRACT_ID,
        "module_thermal_state_model": MODULE_THERMAL_STATE_MODEL_ID,
        "module_thermal_state_scope": MODULE_THERMAL_STATE_SCOPE,
        "module_thermal_state_coverage_scope": MODULE_THERMAL_STATE_COVERAGE_SCOPE,
    }
)
_MODEL_FLOAT = (
    "u_c_w_per_m2k",
    "u_v_w_per_m2k_per_ms",
    "module_efficiency",
    "alpha_absorption",
    "u0_w_per_m2k",
    "u1_w_per_m2k_per_ms",
)
_MODEL_TEXT = ("parameter_source", "confidence", "method_reference", "wind_speed_basis_description")
_CONVERSION_FLOAT = ("delta_t_c_at_reference_irradiance", "reference_irradiance_wm2")
_CONVERSION_TEXT = ("parameter_source", "confidence", "method_reference")
_EVIDENCE_TEXT = (
    "temperature_quantity",
    "evidence_kind",
    "parameter_source",
    "confidence",
    "method_reference",
    "measurement_location_description",
    "aggregation_description",
)
_FLOAT_COLUMNS = (
    (
        "cell_temperature_c",
        "module_back_surface_temperature_c",
        "thermal_poa_global_wm2",
        "ambient_air_temperature_c",
        "wind_speed_m_per_s",
        "cell_evidence_temperature_c",
        "module_back_evidence_temperature_c",
    )
    + tuple("model_" + f for f in _MODEL_FLOAT)
    + tuple("conversion_" + f for f in _CONVERSION_FLOAT)
)
_BOOL_COLUMNS = (
    "cell_temperature_resolved",
    "module_back_surface_temperature_present",
    "measured_temperature_present",
    "direct_cell_temperature_used",
    "module_back_to_cell_conversion_applied",
    "model_temperature_used",
    "model_fallback_after_unusable_measurement",
    "temperature_interpolation_applied",
    "temperature_extrapolation_applied",
)
_TEXT_COLUMNS = (
    (
        "thermal_zone_id",
        "selected_thermal_fidelity",
        "selected_thermal_model_family",
        "selected_temperature_source",
        "parameter_source",
        "confidence",
        "module_thermal_state",
        "measurement_path_unusable_reason",
        "supplied_thermal_model_family",
        "model_output_quantity",
    )
    + tuple("model_" + f for f in _MODEL_TEXT)
    + tuple("conversion_" + f for f in _CONVERSION_TEXT)
    + tuple(
        prefix + f for prefix in ("cell_evidence_", "module_back_evidence_") for f in _EVIDENCE_TEXT
    )
    + tuple(_FIXED)
)
_COLUMNS = _FLOAT_COLUMNS + _BOOL_COLUMNS + _TEXT_COLUMNS


@dataclass(frozen=True)
class ModuleThermalDiagnostics:
    """Presence counts are evidence inventory, not simultaneous selected pathways.

    Missing-input counts refer to primary unresolved reasons, not irrelevant NaNs.
    """

    timestamp_count: int
    resolved_timestamp_count: int
    unresolved_timestamp_count: int
    direct_cell_measurement_count: int
    module_back_measurement_count: int
    module_back_conversion_count: int
    pvsyst_model_count: int
    faiman_cell_model_count: int
    faiman_module_conversion_count: int
    model_fallback_after_unusable_measurement_count: int
    missing_poa_count: int
    missing_ambient_count: int
    missing_required_wind_count: int
    missing_conversion_authority_count: int
    state_counts: Mapping[str, int]
    contract: str = MODULE_THERMAL_STATE_CONTRACT_ID
    model: str = MODULE_THERMAL_STATE_MODEL_ID
    scope: str = MODULE_THERMAL_STATE_SCOPE
    coverage_scope: str = MODULE_THERMAL_STATE_COVERAGE_SCOPE


@dataclass(frozen=True)
class ModuleThermalStateResult:
    """Frozen result envelope; tabular contents are checked by independent replay."""

    states: pd.DataFrame
    diagnostics: ModuleThermalDiagnostics


@dataclass(frozen=True)
class _Inputs:
    zone: str
    poa: pd.Series
    ambient: pd.Series
    wind: pd.Series
    measurements: Mapping[pd.Timestamp, ModuleThermalMeasurementState]
    model: ThermalModelAuthority | None
    conversion: ModuleBackSurfaceToCellTemperatureAuthority | None


def _admit_inputs(
    thermal_zone_id: str,
    poa_global_wm2: pd.Series,
    ambient_air_temperature_c: pd.Series,
    wind_speed_m_per_s: pd.Series,
    measurements: Mapping[pd.Timestamp, ModuleThermalMeasurementState] | None,
    model_authority: ThermalModelAuthority | None,
    conversion_authority: ModuleBackSurfaceToCellTemperatureAuthority | None,
) -> _Inputs:
    _text(thermal_zone_id, "thermal_zone_id")
    series = (poa_global_wm2, ambient_air_temperature_c, wind_speed_m_per_s)
    for value, name, lower in zip(
        series, ("thermal POA", "ambient", "wind"), (0.0, -273.15, 0.0), strict=True
    ):
        if type(value) is not pd.Series or type(value.index) is not pd.DatetimeIndex:
            raise TypeError("thermal inputs must be exact Series with DatetimeIndex")
        if value.index.tz is None or value.index.hasnans or not value.index.is_unique:
            raise ValueError("thermal input index must be timezone-aware, unique and without NaT")
        if not value.index.identical(poa_global_wm2.index):
            raise ValueError(
                "thermal input indexes must align exactly, including timezone and order"
            )
        for item in value:
            if isinstance(item, bool) or not isinstance(item, Real):
                raise ValueError(f"{name} must contain real non-Boolean values or NaN")
            number = float(item)
            if math.isnan(number):
                continue
            if (
                not math.isfinite(number)
                or number < lower
                or (name == "ambient" and number == lower)
            ):
                raise ValueError(f"{name} values are outside their physical domain")
    if model_authority is not None:
        if type(model_authority) not in (PvsystCellThermalAuthority, FaimanThermalAuthority):
            raise TypeError("model_authority must be an exact supported native thermal authority")
        model_authority = _revalidate(model_authority)
    if conversion_authority is not None:
        if type(conversion_authority) is not ModuleBackSurfaceToCellTemperatureAuthority:
            raise TypeError("conversion_authority must be exact module-back conversion authority")
        conversion_authority = _revalidate(conversion_authority)
    if measurements is not None and not isinstance(measurements, Mapping):
        raise TypeError("measurements must be an exact-timestamp mapping")
    admitted = {}
    for timestamp, state in measurements.items() if measurements is not None else ():
        if (
            type(timestamp) is not pd.Timestamp
            or pd.isna(timestamp)
            or timestamp.tz is None
            or str(timestamp.tz) != str(poa_global_wm2.index.tz)
            or timestamp not in poa_global_wm2.index
        ):
            raise ValueError("measurement timestamps must belong exactly to the input grid")
        if type(state) is not ModuleThermalMeasurementState:
            raise TypeError("measurement state must be exact ModuleThermalMeasurementState")
        admitted[timestamp] = ModuleThermalMeasurementState(
            _revalidate(state.cell_temperature) if state.cell_temperature is not None else None,
            _revalidate(state.module_back_surface_temperature)
            if state.module_back_surface_temperature is not None
            else None,
        )
    return _Inputs(
        thermal_zone_id,
        poa_global_wm2.copy(deep=True).astype(float),
        ambient_air_temperature_c.copy(deep=True).astype(float),
        wind_speed_m_per_s.copy(deep=True).astype(float),
        MappingProxyType(admitted),
        model_authority,
        conversion_authority,
    )


def _record(inputs: _Inputs, position: int) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(_FLOAT_COLUMNS, math.nan)
    row.update(dict.fromkeys(_BOOL_COLUMNS, False))
    row.update(dict.fromkeys(_TEXT_COLUMNS, ""))
    row.update(_FIXED)
    row.update(
        thermal_zone_id=inputs.zone,
        thermal_poa_global_wm2=inputs.poa.iloc[position],
        ambient_air_temperature_c=inputs.ambient.iloc[position],
        wind_speed_m_per_s=inputs.wind.iloc[position],
        selected_thermal_model_family="none",
        selected_thermal_fidelity="unresolved",
        selected_temperature_source="unresolved",
        module_thermal_state=_UNRESOLVED[0],
        supplied_thermal_model_family="none",
    )
    state = inputs.measurements.get(inputs.poa.index[position])
    for prefix, evidence in (
        ("cell_evidence_", state.cell_temperature if state else None),
        ("module_back_evidence_", state.module_back_surface_temperature if state else None),
    ):
        if evidence is not None:
            for field in fields(evidence):
                row[prefix + field.name] = getattr(evidence, field.name) or ""
            # Explicit zero degrees must remain numeric zero, not an empty string.
            row[prefix + "temperature_c"] = evidence.temperature_c
    row["measured_temperature_present"] = state is not None
    row["module_back_surface_temperature_c"] = row["module_back_evidence_temperature_c"]
    if inputs.model is not None:
        row["supplied_thermal_model_family"] = (
            "pvsyst" if isinstance(inputs.model, PvsystCellThermalAuthority) else "faiman"
        )
        row["model_output_quantity"] = (
            "cell_temperature"
            if isinstance(inputs.model, PvsystCellThermalAuthority)
            else inputs.model.output_temperature_quantity
        )
        for field in fields(inputs.model):
            if field.name != "output_temperature_quantity":
                row["model_" + field.name] = getattr(inputs.model, field.name)
    if inputs.conversion is not None:
        for field in fields(inputs.conversion):
            value = getattr(inputs.conversion, field.name)
            row["conversion_" + field.name] = value if value is not None else ""
    return row


def _convert(
    back: float, poa: float, authority: ModuleBackSurfaceToCellTemperatureAuthority
) -> float:
    return (
        back
        + poa / authority.reference_irradiance_wm2 * authority.delta_t_c_at_reference_irradiance
    )


def _native_model(model: ThermalModelAuthority, poa: float, ambient: float, wind: float) -> float:
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        if isinstance(model, PvsystCellThermalAuthority):
            return float(
                pvlib.temperature.pvsyst_cell(
                    poa_global=poa,
                    temp_air=ambient,
                    wind_speed=wind,
                    u_c=model.u_c_w_per_m2k,
                    u_v=model.u_v_w_per_m2k_per_ms,
                    module_efficiency=model.module_efficiency,
                    alpha_absorption=model.alpha_absorption,
                )
            )
        return float(
            pvlib.temperature.faiman(
                poa_global=poa,
                temp_air=ambient,
                wind_speed=wind,
                u0=model.u0_w_per_m2k,
                u1=model.u1_w_per_m2k_per_ms,
            )
        )


def _resolve_row(inputs: _Inputs, position: int) -> dict[str, Any]:
    row = _record(inputs, position)
    state = inputs.measurements.get(inputs.poa.index[position])
    cell = state.cell_temperature if state else None
    back = state.module_back_surface_temperature if state else None
    poa, ambient, wind = (
        float(s.iloc[position]) for s in (inputs.poa, inputs.ambient, inputs.wind)
    )
    conversion, model = inputs.conversion, inputs.model
    temperature = math.nan
    fidelity = ""
    selected: ModuleTemperatureEvidence | ThermalModelAuthority | None = None
    if cell is not None:
        temperature, fidelity, selected = cell.temperature_c, _FIDELITIES[0], cell
    elif back is not None:
        if conversion is None:
            row["measurement_path_unusable_reason"] = "missing_module_to_cell_conversion_authority"
        elif math.isnan(poa):
            row["measurement_path_unusable_reason"] = "missing_thermal_poa"
        else:
            temperature = _convert(back.temperature_c, poa, conversion)
            if math.isfinite(temperature) and temperature > -273.15:
                fidelity, selected = _FIDELITIES[1], back
            else:
                temperature = math.nan
                row["measurement_path_unusable_reason"] = "invalid_or_incomplete_model_inputs"
        if not fidelity:
            row["module_thermal_state"] = "unresolved_" + row["measurement_path_unusable_reason"]
    if not fidelity and model is not None:
        if math.isnan(poa):
            row["module_thermal_state"] = _UNRESOLVED[1]
        elif math.isnan(ambient):
            row["module_thermal_state"] = _UNRESOLVED[2]
        else:
            coefficient = (
                model.u_v_w_per_m2k_per_ms
                if isinstance(model, PvsystCellThermalAuthority)
                else model.u1_w_per_m2k_per_ms
            )
            base = (
                model.u_c_w_per_m2k
                if isinstance(model, PvsystCellThermalAuthority)
                else model.u0_w_per_m2k
            )
            if coefficient != 0 and math.isnan(wind):
                row["module_thermal_state"] = _UNRESOLVED[3]
            else:
                # A zero coefficient eliminates the wind term; no missing observation is filled.
                equation_wind = 0.0 if coefficient == 0 else wind
                denominator = base + coefficient * equation_wind
                value = (
                    _native_model(model, poa, ambient, equation_wind)
                    if math.isfinite(denominator)
                    else math.nan
                )
                if not math.isfinite(value) or value <= -273.15:
                    row["module_thermal_state"] = _UNRESOLVED[6]
                elif isinstance(model, PvsystCellThermalAuthority):
                    temperature, fidelity, selected = value, _FIDELITIES[2], model
                elif model.output_temperature_quantity == "cell_temperature":
                    temperature, fidelity, selected = value, _FIDELITIES[3], model
                else:
                    row["module_back_surface_temperature_c"] = value
                    if conversion is None:
                        row["module_thermal_state"] = _UNRESOLVED[5]
                    else:
                        value = _convert(value, poa, conversion)
                        if math.isfinite(value) and value > -273.15:
                            temperature, fidelity, selected = value, _FIDELITIES[4], model
                        else:
                            row["module_thermal_state"] = _UNRESOLVED[6]
    if fidelity and selected is not None:
        row.update(
            cell_temperature_c=temperature,
            cell_temperature_resolved=True,
            selected_thermal_fidelity=fidelity,
            module_thermal_state="resolved_" + fidelity,
            parameter_source=selected.parameter_source,
            confidence=selected.confidence,
            direct_cell_temperature_used=fidelity == _FIDELITIES[0],
            module_back_to_cell_conversion_applied=fidelity in (_FIDELITIES[1], _FIDELITIES[4]),
            model_temperature_used=fidelity in _FIDELITIES[2:],
            selected_temperature_source=(
                "cell_temperature_evidence"
                if fidelity == _FIDELITIES[0]
                else "module_back_surface_evidence"
                if fidelity == _FIDELITIES[1]
                else "pvsyst_model"
                if fidelity == _FIDELITIES[2]
                else "faiman_model"
            ),
            selected_thermal_model_family=(
                "none"
                if fidelity in _FIDELITIES[:2]
                else "pvsyst"
                if fidelity == _FIDELITIES[2]
                else "faiman"
            ),
            model_fallback_after_unusable_measurement=(
                fidelity in _FIDELITIES[2:] and bool(row["measurement_path_unusable_reason"])
            ),
        )
    row["module_back_surface_temperature_present"] = math.isfinite(
        row["module_back_surface_temperature_c"]
    )
    return row


def _frame(records: list[dict[str, Any]], index: pd.DatetimeIndex) -> pd.DataFrame:
    result = pd.DataFrame(records, index=index.copy(), columns=_COLUMNS)
    for column in _FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    for column in _BOOL_COLUMNS:
        result[column] = result[column].astype(bool)
    for column in _TEXT_COLUMNS:
        result[column] = result[column].astype(object)
    return result


def _diagnostics(frame: pd.DataFrame) -> ModuleThermalDiagnostics:
    counts = Counter(frame["module_thermal_state"])
    resolved = int(frame["cell_temperature_resolved"].sum())
    return ModuleThermalDiagnostics(
        len(frame),
        resolved,
        len(frame) - resolved,
        int(frame["direct_cell_temperature_used"].sum()),
        int(frame["module_back_evidence_temperature_c"].notna().sum()),
        int(frame["module_back_to_cell_conversion_applied"].sum()),
        counts["resolved_pvsyst_cell_temperature"],
        counts["resolved_faiman_cell_temperature"],
        counts["resolved_faiman_module_back_to_cell_temperature"],
        int(frame["model_fallback_after_unusable_measurement"].sum()),
        counts["unresolved_missing_thermal_poa"],
        counts["unresolved_missing_ambient_temperature"],
        counts["unresolved_missing_wind_speed"],
        counts[_UNRESOLVED[4]] + counts[_UNRESOLVED[5]],
        MappingProxyType({state: counts[state] for state in _STATES}),
    )


def resolve_module_thermal_state(
    *,
    thermal_zone_id: str,
    poa_global_wm2: pd.Series,
    ambient_air_temperature_c: pd.Series,
    wind_speed_m_per_s: pd.Series,
    measurements: Mapping[pd.Timestamp, ModuleThermalMeasurementState] | None = None,
    model_authority: ThermalModelAuthority | None = None,
    conversion_authority: ModuleBackSurfaceToCellTemperatureAuthority | None = None,
) -> ModuleThermalStateResult:
    """Resolve each supplied timestamp, preserving its own evidence/fidelity.

    No model is inferred. Native parameters and any external parameter conversion
    must be documented in the supplied authorities. Zone-to-module mapping and
    weather-time/thermal-irradiance admission remain outside this contract.
    """
    inputs = _admit_inputs(
        thermal_zone_id,
        poa_global_wm2,
        ambient_air_temperature_c,
        wind_speed_m_per_s,
        measurements,
        model_authority,
        conversion_authority,
    )
    frame = _frame([_resolve_row(inputs, i) for i in range(len(inputs.poa))], inputs.poa.index)
    result = ModuleThermalStateResult(frame, _diagnostics(frame))
    validate_module_thermal_state_result(
        result,
        thermal_zone_id=thermal_zone_id,
        poa_global_wm2=poa_global_wm2,
        ambient_air_temperature_c=ambient_air_temperature_c,
        wind_speed_m_per_s=wind_speed_m_per_s,
        measurements=measurements,
        model_authority=model_authority,
        conversion_authority=conversion_authority,
    )
    return result


def validate_module_thermal_state_result(
    result: ModuleThermalStateResult,
    *,
    thermal_zone_id: str,
    poa_global_wm2: pd.Series,
    ambient_air_temperature_c: pd.Series,
    wind_speed_m_per_s: pd.Series,
    measurements: Mapping[pd.Timestamp, ModuleThermalMeasurementState] | None = None,
    model_authority: ThermalModelAuthority | None = None,
    conversion_authority: ModuleBackSurfaceToCellTemperatureAuthority | None = None,
) -> None:
    """Independently reconstruct precedence, native equations, schema and diagnostics.

    Does not call production record/frame/selection/diagnostic builders, pvlib, or
    conversion/model helpers. Shared admission validates evidence, not the solve.
    """
    if (
        type(result) is not ModuleThermalStateResult
        or type(result.diagnostics) is not ModuleThermalDiagnostics
    ):
        raise ValueError("invalid module thermal result type")
    inputs = _admit_inputs(
        thermal_zone_id,
        poa_global_wm2,
        ambient_air_temperature_c,
        wind_speed_m_per_s,
        measurements,
        model_authority,
        conversion_authority,
    )
    records = []
    for timestamp, irradiance, air, speed in zip(
        inputs.poa.index, inputs.poa, inputs.ambient, inputs.wind, strict=True
    ):
        row: dict[str, Any] = {name: math.nan for name in _FLOAT_COLUMNS}
        row.update({name: False for name in _BOOL_COLUMNS})
        row.update({name: "" for name in _TEXT_COLUMNS})
        row.update(_FIXED)
        row.update(
            thermal_zone_id=inputs.zone,
            thermal_poa_global_wm2=irradiance,
            ambient_air_temperature_c=air,
            wind_speed_m_per_s=speed,
            selected_thermal_fidelity="unresolved",
            selected_thermal_model_family="none",
            selected_temperature_source="unresolved",
            supplied_thermal_model_family="none",
        )
        measurement = inputs.measurements.get(timestamp)
        cell = measurement.cell_temperature if measurement else None
        back = measurement.module_back_surface_temperature if measurement else None
        for prefix, evidence in (("cell_evidence_", cell), ("module_back_evidence_", back)):
            if evidence is not None:
                row[prefix + "temperature_c"] = evidence.temperature_c
                for name in _EVIDENCE_TEXT:
                    value = getattr(evidence, name)
                    row[prefix + name] = "" if value is None else value
        row["measured_temperature_present"] = measurement is not None
        row["module_back_surface_temperature_c"] = back.temperature_c if back else math.nan
        native, conversion = inputs.model, inputs.conversion
        if native is not None:
            is_pvsyst = isinstance(native, PvsystCellThermalAuthority)
            row["supplied_thermal_model_family"] = "pvsyst" if is_pvsyst else "faiman"
            row["model_output_quantity"] = (
                "cell_temperature"
                if isinstance(native, PvsystCellThermalAuthority)
                else native.output_temperature_quantity
            )
            for name in _MODEL_FLOAT + _MODEL_TEXT:
                if hasattr(native, name):
                    row["model_" + name] = getattr(native, name)
        if conversion is not None:
            for name in _CONVERSION_FLOAT + _CONVERSION_TEXT:
                value = getattr(conversion, name)
                row["conversion_" + name] = "" if value is None else value
        chosen = -1
        temperature = math.nan
        source = confidence = ""
        failure = "unresolved_no_temperature_evidence_or_model_authority"
        unusable = ""
        if cell is not None:
            chosen, temperature = 0, cell.temperature_c
            source, confidence = cell.parameter_source, cell.confidence
        elif back is not None:
            if conversion is None:
                unusable = "missing_module_to_cell_conversion_authority"
            elif math.isnan(irradiance):
                unusable = "missing_thermal_poa"
            else:
                corrected = (
                    back.temperature_c
                    + (irradiance / conversion.reference_irradiance_wm2)
                    * conversion.delta_t_c_at_reference_irradiance
                )
                if math.isfinite(corrected) and corrected > -273.15:
                    chosen, temperature = 1, corrected
                    source, confidence = back.parameter_source, back.confidence
                else:
                    unusable = "invalid_or_incomplete_model_inputs"
            if unusable:
                failure = "unresolved_" + unusable
        if chosen == -1 and native is not None:
            if math.isnan(irradiance):
                failure = "unresolved_missing_thermal_poa"
            elif math.isnan(air):
                failure = "unresolved_missing_ambient_temperature"
            else:
                if isinstance(native, PvsystCellThermalAuthority):
                    constant, slope = native.u_c_w_per_m2k, native.u_v_w_per_m2k_per_ms
                    heat = irradiance * native.alpha_absorption * (1 - native.module_efficiency)
                else:
                    constant, slope = native.u0_w_per_m2k, native.u1_w_per_m2k_per_ms
                    heat = irradiance
                if slope > 0 and math.isnan(speed):
                    failure = "unresolved_missing_wind_speed"
                else:
                    loss_coefficient = constant if slope == 0 else constant + slope * speed
                    model_temperature = (
                        air + heat / loss_coefficient
                        if math.isfinite(loss_coefficient)
                        else math.nan
                    )
                    if not math.isfinite(model_temperature) or model_temperature <= -273.15:
                        failure = "unresolved_invalid_or_incomplete_model_inputs"
                    elif isinstance(native, PvsystCellThermalAuthority):
                        chosen, temperature = 2, model_temperature
                    elif native.output_temperature_quantity == "cell_temperature":
                        chosen, temperature = 3, model_temperature
                    else:
                        row["module_back_surface_temperature_c"] = model_temperature
                        if conversion is None:
                            failure = (
                                "unresolved_model_output_is_module_temperature_without_conversion"
                            )
                        else:
                            corrected = (
                                model_temperature
                                + (irradiance / conversion.reference_irradiance_wm2)
                                * conversion.delta_t_c_at_reference_irradiance
                            )
                            if math.isfinite(corrected) and corrected > -273.15:
                                chosen, temperature = 4, corrected
                            else:
                                failure = "unresolved_invalid_or_incomplete_model_inputs"
                    if chosen >= 2:
                        source, confidence = native.parameter_source, native.confidence
        row["measurement_path_unusable_reason"] = unusable
        row["module_thermal_state"] = failure
        if chosen >= 0:
            fidelity = _FIDELITIES[chosen]
            row.update(
                cell_temperature_c=temperature,
                cell_temperature_resolved=True,
                direct_cell_temperature_used=chosen == 0,
                module_back_to_cell_conversion_applied=chosen in (1, 4),
                model_temperature_used=chosen >= 2,
                model_fallback_after_unusable_measurement=chosen >= 2 and bool(unusable),
                selected_thermal_fidelity=fidelity,
                selected_thermal_model_family=("none", "none", "pvsyst", "faiman", "faiman")[
                    chosen
                ],
                selected_temperature_source=(
                    "cell_temperature_evidence",
                    "module_back_surface_evidence",
                    "pvsyst_model",
                    "faiman_model",
                    "faiman_model",
                )[chosen],
                parameter_source=source,
                confidence=confidence,
                module_thermal_state="resolved_" + fidelity,
            )
        row["module_back_surface_temperature_present"] = math.isfinite(
            row["module_back_surface_temperature_c"]
        )
        records.append(row)
    expected = pd.DataFrame(records, index=inputs.poa.index.copy(), columns=_COLUMNS)
    for name in _COLUMNS:
        expected[name] = expected[name].astype(
            float if name in _FLOAT_COLUMNS else bool if name in _BOOL_COLUMNS else object
        )
    try:
        pd.testing.assert_frame_equal(
            result.states, expected, check_exact=False, atol=1e-12, rtol=1e-12
        )
    except (AssertionError, TypeError, ValueError) as exc:
        raise ValueError("module thermal states failed independent validation") from exc
    counts = {state: sum(r["module_thermal_state"] == state for r in records) for state in _STATES}
    selected_counts = [counts["resolved_" + f] for f in _FIDELITIES]
    resolved = sum(selected_counts)
    expected_diagnostics = ModuleThermalDiagnostics(
        len(records),
        resolved,
        len(records) - resolved,
        selected_counts[0],
        sum(not math.isnan(r["module_back_evidence_temperature_c"]) for r in records),
        selected_counts[1] + selected_counts[4],
        selected_counts[2],
        selected_counts[3],
        selected_counts[4],
        sum(r["model_fallback_after_unusable_measurement"] for r in records),
        counts["unresolved_missing_thermal_poa"],
        counts["unresolved_missing_ambient_temperature"],
        counts["unresolved_missing_wind_speed"],
        counts["unresolved_missing_module_to_cell_conversion_authority"]
        + counts["unresolved_model_output_is_module_temperature_without_conversion"],
        MappingProxyType(counts),
    )
    if result.diagnostics != expected_diagnostics:
        raise ValueError("module thermal diagnostics failed independent validation")
