"""Explicit native module thermal parameters and temperature evidence.

No SiteConfig lookup, model-family conversion, sensor-placement inference or
production activation occurs here. A thermal zone's site binding is external.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from numbers import Real
from typing import Literal, TypeVar

MODULE_THERMAL_AUTHORITY_CONTRACT_ID = (
    "explicit_native_module_thermal_model_and_module_back_to_cell_conversion_authority_v1"
)
MODULE_THERMAL_AUTHORITY_MODEL_ID = (
    "native_pvsyst_cell_faiman_declared_quantity_and_reference_irradiance_delta_t_authority_v1"
)
Confidence = Literal["high", "medium", "low", "unknown"]
TemperatureQuantity = Literal["cell_temperature", "module_back_surface_temperature"]
EvidenceKind = Literal[
    "direct_sensor_measurement",
    "aggregated_sensor_measurement",
    "documented_external_temperature_estimate",
]
_CONFIDENCES = frozenset({"high", "medium", "low", "unknown"})
_QUANTITIES = frozenset({"cell_temperature", "module_back_surface_temperature"})
_KINDS = frozenset(
    {
        "direct_sensor_measurement",
        "aggregated_sensor_measurement",
        "documented_external_temperature_estimate",
    }
)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be an exact non-empty string without padding")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite non-Boolean real number")
    return float(value)


def _provenance(source: str, confidence: Confidence, *descriptions: str | None) -> None:
    _text(source, "parameter_source")
    if type(confidence) is not str or confidence not in _CONFIDENCES:
        raise ValueError("confidence is unsupported")
    for value in descriptions:
        if value is not None:
            _text(value, "provenance description")


@dataclass(frozen=True)
class PvsystCellThermalAuthority:
    u_c_w_per_m2k: float
    u_v_w_per_m2k_per_ms: float
    module_efficiency: float
    alpha_absorption: float
    parameter_source: str
    confidence: Confidence
    method_reference: str
    wind_speed_basis_description: str

    def __post_init__(self) -> None:
        for name in (
            "u_c_w_per_m2k",
            "u_v_w_per_m2k_per_ms",
            "module_efficiency",
            "alpha_absorption",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        if self.u_c_w_per_m2k <= 0 or self.u_v_w_per_m2k_per_ms < 0:
            raise ValueError("PVsyst requires u_c > 0 and u_v >= 0")
        if not 0 <= self.module_efficiency < 1 or not 0 < self.alpha_absorption <= 1:
            raise ValueError("PVsyst requires 0 <= efficiency < 1 and 0 < absorption <= 1")
        _provenance(self.parameter_source, self.confidence)
        _text(self.method_reference, "method_reference")
        _text(self.wind_speed_basis_description, "wind_speed_basis_description")


@dataclass(frozen=True)
class FaimanThermalAuthority:
    u0_w_per_m2k: float
    u1_w_per_m2k_per_ms: float
    output_temperature_quantity: TemperatureQuantity
    parameter_source: str
    confidence: Confidence
    method_reference: str
    wind_speed_basis_description: str

    def __post_init__(self) -> None:
        for name in ("u0_w_per_m2k", "u1_w_per_m2k_per_ms"):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        if self.u0_w_per_m2k <= 0 or self.u1_w_per_m2k_per_ms < 0:
            raise ValueError("Faiman requires u0 > 0 and u1 >= 0")
        if (
            type(self.output_temperature_quantity) is not str
            or self.output_temperature_quantity not in _QUANTITIES
        ):
            raise ValueError("output_temperature_quantity is unsupported")
        _provenance(self.parameter_source, self.confidence)
        _text(self.method_reference, "method_reference")
        _text(self.wind_speed_basis_description, "wind_speed_basis_description")


@dataclass(frozen=True)
class ModuleBackSurfaceToCellTemperatureAuthority:
    delta_t_c_at_reference_irradiance: float
    reference_irradiance_wm2: float
    parameter_source: str
    confidence: Confidence
    method_reference: str | None = None

    def __post_init__(self) -> None:
        for name in ("delta_t_c_at_reference_irradiance", "reference_irradiance_wm2"):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        if self.delta_t_c_at_reference_irradiance < 0 or self.reference_irradiance_wm2 <= 0:
            raise ValueError("conversion requires delta_t >= 0 and reference irradiance > 0")
        _provenance(self.parameter_source, self.confidence, self.method_reference)


@dataclass(frozen=True)
class ModuleTemperatureEvidence:
    """A temperature channel; membership in an exact timestamp map supplies time."""

    temperature_c: float
    temperature_quantity: TemperatureQuantity
    evidence_kind: EvidenceKind
    parameter_source: str
    confidence: Confidence
    method_reference: str | None = None
    measurement_location_description: str | None = None
    aggregation_description: str | None = None

    def __post_init__(self) -> None:
        temperature = _number(self.temperature_c, "temperature_c")
        if temperature <= -273.15:
            raise ValueError("temperature_c must be above absolute zero")
        object.__setattr__(self, "temperature_c", temperature)
        if (
            type(self.temperature_quantity) is not str
            or self.temperature_quantity not in _QUANTITIES
        ):
            raise ValueError("temperature_quantity is unsupported")
        if type(self.evidence_kind) is not str or self.evidence_kind not in _KINDS:
            raise ValueError("evidence_kind is unsupported")
        _provenance(
            self.parameter_source,
            self.confidence,
            self.method_reference,
            self.measurement_location_description,
            self.aggregation_description,
        )


@dataclass(frozen=True)
class ModuleThermalMeasurementState:
    cell_temperature: ModuleTemperatureEvidence | None = None
    module_back_surface_temperature: ModuleTemperatureEvidence | None = None

    def __post_init__(self) -> None:
        if self.cell_temperature is None and self.module_back_surface_temperature is None:
            raise ValueError("at least one temperature evidence channel is required")
        for name in ("cell_temperature", "module_back_surface_temperature"):
            evidence = getattr(self, name)
            if evidence is not None:
                if type(evidence) is not ModuleTemperatureEvidence:
                    raise TypeError("temperature evidence must be exact ModuleTemperatureEvidence")
                evidence.__post_init__()
                if evidence.temperature_quantity != name:
                    raise ValueError(f"{name} evidence quantity does not match its channel")


ThermalModelAuthority = PvsystCellThermalAuthority | FaimanThermalAuthority
_Authority = TypeVar(
    "_Authority",
    bound=PvsystCellThermalAuthority
    | FaimanThermalAuthority
    | ModuleBackSurfaceToCellTemperatureAuthority
    | ModuleTemperatureEvidence,
)


def _revalidate(value: _Authority) -> _Authority:
    """Reconstruct frozen native evidence, including objects altered outside normal APIs."""
    return type(value)(**{field.name: getattr(value, field.name) for field in fields(value)})
