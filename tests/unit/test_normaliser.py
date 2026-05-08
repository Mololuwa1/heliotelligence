"""Unit tests for ingest.normaliser.normalise_column."""

from __future__ import annotations

import pytest

from heliotelligence.ingest.normaliser import NormalisedColumn, normalise_column, _strip_unit


# ---------------------------------------------------------------------------
# _strip_unit helper
# ---------------------------------------------------------------------------

def test_strip_unit_with_unit():
    assert _strip_unit("SMP10-GHI-F (W/m²)") == ("SMP10-GHI-F", "W/m²")


def test_strip_unit_without_unit():
    assert _strip_unit("COM STATUS") == ("COM STATUS", "")


def test_strip_unit_whitespace_trimmed():
    meas, unit = _strip_unit("  ACTIVE POWER  (kW)  ")
    assert meas == "ACTIVE POWER"
    assert unit == "kW"


# ---------------------------------------------------------------------------
# Timestamp column
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("header", ["Timestamp", "timestamp", "Date/Time", "datetime", "time"])
def test_timestamp_column_skipped(header: str):
    col = normalise_column(header)
    assert col.skip is True
    assert col.equipment_type == "__timestamp__"


# ---------------------------------------------------------------------------
# Weather Station
# ---------------------------------------------------------------------------

def test_weather_ghi_f():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - SMP10-GHI-F (W/m²)")
    assert col.equipment_type == "weather"
    assert col.db_column == "ghi_wm2"
    assert col.skip is False


def test_weather_poa():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - SMP10-POA-1 (W/m²)")
    assert col.db_column == "poa_wm2"


def test_weather_rpoa2():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - SMP10-RPOA-2 (W/m²)")
    assert col.db_column == "poa2_wm2"


def test_weather_ghi_b():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - SMP10-GHI-B (W/m²)")
    assert col.db_column == "ghi_b_wm2"


def test_weather_wind_speed():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - WS_AVG (m/s)")
    assert col.db_column == "wind_speed_ms"


def test_weather_wind_dir():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - WD_AVG (°)")
    assert col.db_column == "wind_dir_deg"


def test_weather_precipitation():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - ABS_PRECIPITATION (mm)")
    assert col.db_column == "precip_mm"


def test_weather_ref_cell():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - REF.CELL-1_IRRADIANCE (W/m²)")
    assert col.db_column == "ref_cell1_wm2"


def test_weather_com_status():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - COM STATUS (text)")
    assert col.db_column == "ws_com_status"
    assert col.skip is False


def test_weather_module_temp_avg_group():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - PT1000-MODULE-1 (°C)")
    assert col.db_column == "temp_mod_avg_c"
    assert col.is_avg_group is True
    assert col.skip is False


def test_weather_module_temp_avg_group_second_sensor():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - PT1000-MODULE-2 (°C)")
    assert col.db_column == "temp_mod_avg_c"
    assert col.is_avg_group is True


def test_weather_ambient_temp_avg_group():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - TEMP-1 (°C)")
    assert col.db_column == "temp_amb_c"
    assert col.is_avg_group is True


def test_weather_unknown_measurement_skipped():
    col = normalise_column("Bracon Ash - WEATHER STATION CT01 - UNKNOWN_SENSOR (V)")
    assert col.skip is True
    assert col.equipment_type == "weather"


# ---------------------------------------------------------------------------
# Meter
# ---------------------------------------------------------------------------

def test_meter_active_power():
    col = normalise_column("Bracon Ash - CFD METER - ACTIVE POWER (kW)")
    assert col.equipment_type == "meter"
    assert col.db_column == "p_ac_kw"
    assert col.skip is False


def test_meter_exported_energy():
    col = normalise_column("Bracon Ash - CFD METER - EXPORTED ACTIVE ENERGY (kWh)")
    assert col.db_column == "e_exported_kwh"


def test_meter_net_energy():
    col = normalise_column("Bracon Ash - CFD METER - TOTAL NET ACTIVE ENERGY DEL-REC (kWh)")
    assert col.db_column == "e_net_kwh"


def test_meter_frequency():
    col = normalise_column("Bracon Ash - CFD METER - FREQUENCY (Hz)")
    assert col.db_column == "freq_hz"


def test_meter_power_factor():
    col = normalise_column("Bracon Ash - CFD METER - POWER FACTOR (-)")
    assert col.db_column == "power_factor"


def test_meter_reactive_power():
    col = normalise_column("Bracon Ash - CFD METER - REACTIVE POWER (kVAr)")
    assert col.db_column == "q_kvar"


def test_meter_unknown_measurement_skipped():
    col = normalise_column("Bracon Ash - CFD METER - VOLTAGE (V)")
    assert col.skip is True
    assert col.equipment_type == "meter"


# ---------------------------------------------------------------------------
# Inverter
# ---------------------------------------------------------------------------

def test_inverter_total_active_power():
    col = normalise_column("Bracon Ash - MQA11-TB101 - TOTAL ACTIVE POWER (kW)")
    assert col.equipment_type == "inverter"
    assert col.db_column == "inv_p_ac_kw"
    assert col.equipment_id == "MQA11-TB101"
    assert col.skip is False


def test_inverter_total_yields():
    col = normalise_column("Bracon Ash - MQA11-TB101 - TOTAL POWER YIELDS (kWh)")
    assert col.db_column == "inv_e_kwh"
    assert col.equipment_id == "MQA11-TB101"


def test_inverter_availability():
    col = normalise_column("Bracon Ash - MQA11-TB101 - AVAILABILITY (%)")
    assert col.db_column == "inv_avail_pct"


def test_inverter_availability_exceptions():
    col = normalise_column("Bracon Ash - MQA11-TB101 - AVAILABILITY WITH EXCEPTIONS (%)")
    assert col.db_column == "inv_avail_exc_pct"


def test_inverter_availability_strings():
    col = normalise_column("Bracon Ash - MQA11-TB101 - AVAILABILITY STRINGS (%)")
    assert col.db_column == "inv_str_avail_pct"


def test_inverter_coms_status():
    col = normalise_column("Bracon Ash - MQA11-TB101 - COMS STATUS (text)")
    assert col.db_column == "inv_coms_status"
    assert col.equipment_id == "MQA11-TB101"


def test_inverter_plant_irradiance():
    col = normalise_column("Bracon Ash - MQA11-TB101 - PLANT IRRADIANCE (W/m²)")
    assert col.db_column == "plant_irr_wm2"


def test_inverter_equipment_id_uppercased():
    col = normalise_column("Bracon Ash - mqa11-tb101 - TOTAL ACTIVE POWER (kW)")
    assert col.equipment_id == "MQA11-TB101"


def test_inverter_second_unit():
    col = normalise_column("Bracon Ash - MQA11-TB102 - TOTAL ACTIVE POWER (kW)")
    assert col.equipment_id == "MQA11-TB102"


# ---------------------------------------------------------------------------
# String
# ---------------------------------------------------------------------------

def test_string_current():
    col = normalise_column("Bracon Ash - MQA11-TB101-STR01 - STRING CURRENT (A)")
    assert col.equipment_type == "string"
    assert col.db_column == "str_current_a"
    assert col.equipment_id == "MQA11-TB101"
    assert col.string_id == "STR01"
    assert col.skip is False


def test_string_energy():
    col = normalise_column("Bracon Ash - MQA11-TB101-STR01 - ENERGY (kWh)")
    assert col.db_column == "str_energy_kwh"
    assert col.string_id == "STR01"


def test_string_power():
    col = normalise_column("Bracon Ash - MQA11-TB101-STR01 - POWER (kW)")
    assert col.db_column == "str_power_kw"


def test_string_availability():
    col = normalise_column("Bracon Ash - MQA11-TB101-STR01 - AVAILABILITY (%)")
    assert col.db_column == "str_avail_pct"


def test_string_availability_exceptions():
    col = normalise_column("Bracon Ash - MQA11-TB101-STR01 - AVAILABILITY WITH EXCEPTIONS (%)")
    assert col.db_column == "str_avail_exc_pct"


def test_string_ids_parsed_correctly():
    col = normalise_column("Bracon Ash - MQA11-TB102-STR02 - STRING CURRENT (A)")
    assert col.equipment_id == "MQA11-TB102"
    assert col.string_id == "STR02"


def test_string_ids_uppercased():
    col = normalise_column("Bracon Ash - mqa11-tb101-str01 - STRING CURRENT (A)")
    assert col.equipment_id == "MQA11-TB101"
    assert col.string_id == "STR01"


# ---------------------------------------------------------------------------
# Skip rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("measurement", [
    "PR", "PERFORMANCE RATIO", "YIELD", "SPECIFIC YIELD",
    "SPECIFIC POWER", "TOTAL YIELD", "ANNUAL YIELD",
])
def test_skip_calculated_summary_fields(measurement: str):
    col = normalise_column(f"Bracon Ash - WEATHER STATION CT01 - {measurement} (-)")
    assert col.skip is True


def test_skip_rapitlog_equipment():
    col = normalise_column("Bracon Ash - RAPITLOG - SOME FIELD (V)")
    assert col.skip is True
    assert col.equipment_type == "rapitlog"


def test_skip_rapilog_typo_variant():
    col = normalise_column("Bracon Ash - RAPILOG - SOME FIELD (V)")
    assert col.skip is True


def test_skip_malformed_no_separator():
    # No " - " after site prefix
    col = normalise_column("Bracon Ash - WEATHERSTATION_NOSEP")
    assert col.skip is True


def test_skip_unknown_equipment():
    col = normalise_column("Bracon Ash - UNKNOWN_DEVICE_XYZ - VOLTAGE (V)")
    assert col.skip is True
    assert col.equipment_type == "unknown"


# ---------------------------------------------------------------------------
# Site name
# ---------------------------------------------------------------------------

def test_site_prefix_stripped_correctly():
    # Custom site name
    col = normalise_column("Test Site - WEATHER STATION CT01 - SMP10-GHI-F (W/m²)", site_name="Test Site")
    assert col.db_column == "ghi_wm2"


def test_no_site_prefix_still_parsed():
    # Header without site prefix — remainder parsed directly
    col = normalise_column("WEATHER STATION CT01 - SMP10-GHI-F (W/m²)")
    assert col.db_column == "ghi_wm2"
