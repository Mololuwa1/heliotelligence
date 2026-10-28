"""Strict native module thermal evidence; no implicit site/default authority."""

from dataclasses import FrozenInstanceError, replace
from typing import Any

import numpy as np
import pytest

from heliotelligence.physics.module_thermal_authority import (
    MODULE_THERMAL_AUTHORITY_CONTRACT_ID,
    MODULE_THERMAL_AUTHORITY_MODEL_ID,
    FaimanThermalAuthority,
    ModuleBackSurfaceToCellTemperatureAuthority,
    ModuleTemperatureEvidence,
    ModuleThermalMeasurementState,
    PvsystCellThermalAuthority,
)


def pvsyst(**changes: Any) -> PvsystCellThermalAuthority:
    return PvsystCellThermalAuthority(
        **dict(
            {
                "u_c_w_per_m2k": 29.0,
                "u_v_w_per_m2k_per_ms": 1.2,
                "module_efficiency": 0.2,
                "alpha_absorption": 0.9,
                "parameter_source": "explicit thermal fit",
                "confidence": "high",
                "method_reference": "PVsyst native calibration",
                "wind_speed_basis_description": "module height",
            },
            **changes,
        )
    )


def faiman(**changes: Any) -> FaimanThermalAuthority:
    return FaimanThermalAuthority(
        **dict(
            {
                "u0_w_per_m2k": 25.0,
                "u1_w_per_m2k_per_ms": 6.84,
                "output_temperature_quantity": "cell_temperature",
                "parameter_source": "explicit Faiman fit",
                "confidence": "medium",
                "method_reference": "native calibration",
                "wind_speed_basis_description": "calibration height",
            },
            **changes,
        )
    )


def conversion(**changes: Any) -> ModuleBackSurfaceToCellTemperatureAuthority:
    return ModuleBackSurfaceToCellTemperatureAuthority(
        **dict(
            {
                "delta_t_c_at_reference_irradiance": 3.0,
                "reference_irradiance_wm2": 1000.0,
                "parameter_source": "explicit conversion evidence",
                "confidence": "high",
                "method_reference": "documented module-to-cell relation",
            },
            **changes,
        )
    )


def evidence(
    quantity: str = "cell_temperature", value: float = 50.0, **changes: Any
) -> ModuleTemperatureEvidence:
    return ModuleTemperatureEvidence(
        **dict(
            {
                "temperature_c": value,
                "temperature_quantity": quantity,
                "evidence_kind": "direct_sensor_measurement",
                "parameter_source": "sensor record",
                "confidence": "high",
                "method_reference": "measurement method",
                "measurement_location_description": "explicit location description",
            },
            **changes,
        )
    )


@pytest.mark.parametrize(
    "factory,field",
    [
        (pvsyst, "u_c_w_per_m2k"),
        (pvsyst, "u_v_w_per_m2k_per_ms"),
        (pvsyst, "module_efficiency"),
        (pvsyst, "alpha_absorption"),
        (faiman, "u0_w_per_m2k"),
        (faiman, "u1_w_per_m2k_per_ms"),
        (conversion, "delta_t_c_at_reference_irradiance"),
        (conversion, "reference_irradiance_wm2"),
        (evidence, "temperature_c"),
    ],
)
@pytest.mark.parametrize(
    "bad", [True, np.bool_(True), float("inf"), float("-inf"), float("nan"), "3", None]
)
def test_numeric_authority_requires_finite_real_nonboolean(
    factory: Any, field: str, bad: Any
) -> None:
    with pytest.raises(ValueError):
        factory(**{field: bad})


@pytest.mark.parametrize(
    "factory,field,bad",
    [
        (pvsyst, "u_c_w_per_m2k", 0),
        (pvsyst, "u_v_w_per_m2k_per_ms", -1),
        (pvsyst, "module_efficiency", -0.1),
        (pvsyst, "module_efficiency", 1),
        (pvsyst, "alpha_absorption", 0),
        (pvsyst, "alpha_absorption", 1.01),
        (faiman, "u0_w_per_m2k", 0),
        (faiman, "u1_w_per_m2k_per_ms", -1),
        (conversion, "delta_t_c_at_reference_irradiance", -1),
        (conversion, "reference_irradiance_wm2", 0),
        (evidence, "temperature_c", -273.15),
        (evidence, "temperature_c", -300),
    ],
)
def test_physical_parameter_domains(factory: Any, field: str, bad: float) -> None:
    with pytest.raises(ValueError):
        factory(**{field: bad})


@pytest.mark.parametrize("factory", [pvsyst, faiman, conversion, evidence])
@pytest.mark.parametrize(
    "field,bad",
    [
        ("parameter_source", ""),
        ("parameter_source", " source"),
        ("parameter_source", "source "),
        ("method_reference", "\t"),
        ("confidence", "HIGH"),
        ("confidence", " high"),
    ],
)
def test_strict_provenance(factory: Any, field: str, bad: str) -> None:
    with pytest.raises(ValueError):
        factory(**{field: bad})


@pytest.mark.parametrize(
    "quantity", ["ambient_temperature", "module_temperature", "cell_temperature "]
)
def test_quantity_must_be_explicit_supported_quantity(quantity: str) -> None:
    with pytest.raises(ValueError):
        faiman(output_temperature_quantity=quantity)
    with pytest.raises(ValueError):
        evidence(quantity)


def test_optional_evidence_descriptions_preserved_without_inference() -> None:
    description = "Mean of sensors A and B; documented weights 1:2"
    value = evidence(
        evidence_kind="aggregated_sensor_measurement", aggregation_description=description
    )
    assert value.aggregation_description == description
    for field in ["measurement_location_description", "aggregation_description"]:
        with pytest.raises(ValueError):
            evidence(**{field: " padded "})
    with pytest.raises(ValueError):
        evidence(evidence_kind="inferred_sensor_placement")


def test_state_requires_channels_and_exact_quantity_match() -> None:
    with pytest.raises(ValueError):
        ModuleThermalMeasurementState()
    with pytest.raises(ValueError):
        ModuleThermalMeasurementState(cell_temperature=evidence("module_back_surface_temperature"))
    with pytest.raises(TypeError):
        ModuleThermalMeasurementState(cell_temperature=50.0)  # type: ignore[arg-type]
    state = ModuleThermalMeasurementState(evidence(), evidence("module_back_surface_temperature"))
    assert state.cell_temperature and state.module_back_surface_temperature


def test_frozen_authority_and_explicit_zero_parameters() -> None:
    value = pvsyst(u_v_w_per_m2k_per_ms=0, module_efficiency=0, alpha_absorption=1)
    assert value.module_efficiency == 0
    assert conversion(delta_t_c_at_reference_irradiance=0).delta_t_c_at_reference_irradiance == 0
    with pytest.raises(FrozenInstanceError):
        value.u_c_w_per_m2k = 50  # type: ignore[misc]
    assert replace(value, u_c_w_per_m2k=30).u_c_w_per_m2k == 30


def test_no_parameter_family_leakage_or_generic_defaults() -> None:
    with pytest.raises(TypeError):
        faiman(u_c_w_per_m2k=29)
    with pytest.raises(TypeError):
        pvsyst(u0_w_per_m2k=25)
    with pytest.raises(TypeError):
        PvsystCellThermalAuthority()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        FaimanThermalAuthority(25, 6.84)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ModuleBackSurfaceToCellTemperatureAuthority()  # type: ignore[call-arg]
    assert MODULE_THERMAL_AUTHORITY_CONTRACT_ID == (
        "explicit_native_module_thermal_model_and_module_back_to_cell_conversion_authority_v1"
    )
    assert MODULE_THERMAL_AUTHORITY_MODEL_ID == (
        "native_pvsyst_cell_faiman_declared_quantity_and_reference_irradiance_delta_t_authority_v1"
    )
