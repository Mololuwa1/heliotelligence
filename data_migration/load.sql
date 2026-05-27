-- Staging load script — all tables in one session so temp tables persist
-- Run with: psql "..." -f load.sql

-- Clear rows inserted by sync_sites so we load authoritative Timescale UUIDs
TRUNCATE TABLE sites;

-- ========== SITES (17 CSV cols → 10 Cloud SQL cols) ==========
CREATE TEMP TABLE _sites_stg (
  site_id uuid, site_name text, site_code text, latitude float8, longitude float8,
  timezone text, capacity_kwp float8, capacity_kw_ac float8, num_inverters int,
  strings_per_inv int, commissioning_date date, country text, subsidy_type text,
  notes text, created_at timestamptz, updated_at timestamptz, config_json jsonb
);
\copy _sites_stg FROM '/Users/mololuwaobafemimoses/heliotelligence/data_migration/ts_sites.csv' CSV HEADER
INSERT INTO sites (site_id, site_name, site_code, latitude, longitude, timezone, capacity_kwp, strings_per_inv, subsidy_type, config_json)
SELECT site_id, site_name, site_code, latitude, longitude, timezone, capacity_kwp, strings_per_inv, subsidy_type, config_json
FROM _sites_stg
ON CONFLICT (site_id) DO UPDATE SET
  site_name    = EXCLUDED.site_name,
  latitude     = EXCLUDED.latitude,
  longitude    = EXCLUDED.longitude,
  capacity_kwp = EXCLUDED.capacity_kwp;
SELECT 'sites loaded: ' || COUNT(*)::text FROM sites;

-- ========== USER_SITE_ACCESS (skip — only row has site_id='admin', not a UUID) ==========
SELECT 'user_site_access: skipped (non-UUID site_id in source data)' AS status;

-- ========== INVERTERS (28 CSV cols → map to Cloud SQL cols) ==========
CREATE TEMP TABLE _inv_stg (
  inverter_pk uuid, site_id uuid, inverter_id text, manufacturer text, model text,
  serial_number text, pdc0_kw float8, pac0_kw float8, dc_voltage_max_v float8,
  dc_voltage_mppt_min_v float8, dc_voltage_mppt_max_v float8, eta_nom float8,
  num_mppt int, num_strings int, strings_per_mppt int, modules_per_string int,
  inverter_type text, comms_protocol text, comms_address text, poll_interval_s int,
  commissioned_date date, decommissioned_date date, is_active boolean,
  pvlib_model_type text, pvlib_model_name text, notes text,
  created_at timestamptz, updated_at timestamptz
);
\copy _inv_stg FROM '/Users/mololuwaobafemimoses/heliotelligence/data_migration/ts_inverters.csv' CSV HEADER
INSERT INTO inverters (inverter_pk, site_id, inverter_id, manufacturer, model, serial_number, num_strings, inverter_type, pvlib_model_type, comms_protocol, notes, created_at, updated_at)
SELECT inverter_pk, site_id, inverter_id, manufacturer, model, serial_number, num_strings, inverter_type, pvlib_model_type, comms_protocol, notes, created_at, updated_at
FROM _inv_stg
ON CONFLICT (inverter_pk) DO NOTHING;
SELECT 'inverters loaded: ' || COUNT(*)::text FROM inverters;

-- ========== SITE_INSTRUMENTS (29 CSV cols → map to Cloud SQL cols) ==========
CREATE TEMP TABLE _si_stg (
  instrument_pk uuid, site_id uuid, instrument_id text, instrument_type text,
  manufacturer text, model text, serial_number text, calibration_date date,
  calibration_due date, iso_class text, measurement_plane text, num_channels int,
  location_desc text, latitude float8, longitude float8, height_m float8,
  column_mapping jsonb, aggregation_rule text, aggregation_target text,
  channel_columns jsonb, range_min float8, range_max float8, comms_fail_value text,
  commissioned_date date, decommissioned_date date, is_active boolean,
  notes text, created_at timestamptz, updated_at timestamptz
);
\copy _si_stg FROM '/Users/mololuwaobafemimoses/heliotelligence/data_migration/ts_site_instruments.csv' CSV HEADER
INSERT INTO site_instruments (instrument_pk, site_id, instrument_id, instrument_type, manufacturer, model, serial_number, calibration_date, iso_class, measurement_plane, num_channels, column_mapping, aggregation_rule, channel_columns, notes, active, created_at, updated_at)
SELECT instrument_pk, site_id, instrument_id, instrument_type, manufacturer, model, serial_number, calibration_date, iso_class, measurement_plane, num_channels, column_mapping, aggregation_rule, channel_columns, notes, is_active, created_at, updated_at
FROM _si_stg
ON CONFLICT (instrument_pk) DO NOTHING;
SELECT 'site_instruments loaded: ' || COUNT(*)::text FROM site_instruments;

-- ========== WEATHER_READINGS (32 CSV cols, time→ts, quality→quality_flag) ==========
CREATE TEMP TABLE _wr_stg (
  "time" timestamptz, site_id text, ghi_wm2 float8, ghi_b_wm2 float8,
  poa_wm2 float8, poa2_wm2 float8, ref_cell1_wm2 float8, ref_cell2_wm2 float8,
  temp_amb_c float8, temp_amb1_c float8, temp_amb2_c float8, temp_mod_avg_c float8,
  temp_mod1_c float8, temp_mod2_c float8, temp_mod3_c float8, temp_mod4_c float8,
  temp_mod5_c float8, temp_mod6_c float8, ref_cell1_temp_c float8, ref_cell2_temp_c float8,
  wind_speed_ms float8, wind_speed_max_ms float8, wind_dir_deg float8, precip_mm float8,
  precip_dif_mm float8, ws_com_status text, ws_com_quality text, ws_num_fails float8,
  source text, quality int, dhi_wm2 float8, dni_wm2 float8
);
\copy _wr_stg FROM '/Users/mololuwaobafemimoses/heliotelligence/data_migration/ts_weather_readings.csv' CSV HEADER
INSERT INTO weather_readings (site_id, ts, ghi_wm2, poa_wm2, poa2_wm2, ghi_b_wm2, ref_cell1_wm2, temp_amb_c, temp_mod_avg_c, wind_speed_ms, wind_dir_deg, precip_mm, ws_com_status, quality_flag)
SELECT site_id, "time", ghi_wm2, poa_wm2, poa2_wm2, ghi_b_wm2, ref_cell1_wm2, temp_amb_c, temp_mod_avg_c, wind_speed_ms, wind_dir_deg, precip_mm, ws_com_status, quality
FROM _wr_stg
ON CONFLICT (site_id, ts) DO NOTHING;
SELECT 'weather_readings loaded: ' || COUNT(*)::text FROM weather_readings;

-- ========== METER_READINGS (29 CSV cols, time→ts, quality→quality_flag) ==========
CREATE TEMP TABLE _mr_stg (
  "time" timestamptz, site_id text, p_ac_kw float8, p_ac_ph1_kw float8,
  p_ac_ph2_kw float8, p_ac_ph3_kw float8, e_exported_kwh float8, e_imported_kwh float8,
  e_net_kwh float8, v_ph1_n_v float8, v_ph2_n_v float8, v_ph3_n_v float8,
  v_ph1_ph2_v float8, v_ph2_ph3_v float8, v_ph3_ph1_v float8, i_ph1_a float8,
  i_ph2_a float8, i_ph3_a float8, freq_hz float8, power_factor float8,
  power_factor_ph1 float8, power_factor_ph2 float8, power_factor_ph3 float8,
  q_kvar float8, q_ph1_kvar float8, q_ph2_kvar float8, q_ph3_kvar float8,
  q_total_kvarh float8, quality int
);
\copy _mr_stg FROM '/Users/mololuwaobafemimoses/heliotelligence/data_migration/ts_meter_readings.csv' CSV HEADER
INSERT INTO meter_readings (site_id, ts, p_ac_kw, e_exported_kwh, e_net_kwh, freq_hz, power_factor, q_kvar, quality_flag)
SELECT site_id, "time", p_ac_kw, e_exported_kwh, e_net_kwh, freq_hz, power_factor, q_kvar, quality
FROM _mr_stg
ON CONFLICT (site_id, ts) DO NOTHING;
SELECT 'meter_readings loaded: ' || COUNT(*)::text FROM meter_readings;

-- ========== INVERTER_READINGS (15 CSV cols, time→ts, quality→quality_flag) ==========
CREATE TEMP TABLE _ir_stg (
  "time" timestamptz, site_id text, inverter_id text, inv_p_ac_kw float8,
  inv_e_kwh float8, inv_q_kvar float8, inv_pf float8, inv_avail_pct float8,
  inv_avail_exc_pct float8, inv_str_avail_pct float8, inv_str_avail_exc_pct float8,
  inv_coms_status text, plant_irr_wm2 float8, plant_insol_kwh float8, quality int
);
\copy _ir_stg FROM '/Users/mololuwaobafemimoses/heliotelligence/data_migration/ts_inverter_readings.csv' CSV HEADER
INSERT INTO inverter_readings (site_id, inverter_id, ts, inv_p_ac_kw, inv_e_kwh, inv_avail_pct, inv_avail_exc_pct, inv_str_avail_pct, plant_irr_wm2, inv_coms_status, quality_flag)
SELECT site_id, inverter_id, "time", inv_p_ac_kw, inv_e_kwh, inv_avail_pct, inv_avail_exc_pct, inv_str_avail_pct, plant_irr_wm2, inv_coms_status, quality
FROM _ir_stg
ON CONFLICT (site_id, inverter_id, ts) DO NOTHING;
SELECT 'inverter_readings loaded: ' || COUNT(*)::text FROM inverter_readings;

-- ========== STRING_READINGS (10 CSV cols, time→ts, quality→quality_flag) ==========
CREATE TEMP TABLE _sr_stg (
  "time" timestamptz, site_id text, inverter_id text, string_id text,
  str_current_a float8, str_power_kw float8, str_energy_kwh float8,
  str_avail_pct float8, str_avail_exc_pct float8, quality int
);
\copy _sr_stg FROM '/Users/mololuwaobafemimoses/heliotelligence/data_migration/ts_string_readings.csv' CSV HEADER
INSERT INTO string_readings (site_id, inverter_id, string_id, ts, str_current_a, str_energy_kwh, str_power_kw, str_avail_pct, str_avail_exc_pct, quality_flag)
SELECT site_id, inverter_id, string_id, "time", str_current_a, str_energy_kwh, str_power_kw, str_avail_pct, str_avail_exc_pct, quality
FROM _sr_stg
ON CONFLICT (site_id, inverter_id, string_id, ts) DO NOTHING;
SELECT 'string_readings loaded: ' || COUNT(*)::text FROM string_readings;

-- ========== EXPECTED_ENERGY (11 CSV cols, reorder + tier_used TEXT) ==========
CREATE TEMP TABLE _ee_stg (
  "time" timestamptz, site_id uuid, p_ac_kw float8, p_dc_kw float8,
  p_dc_stc_kw float8, poa_total_wm2 float8, t_cell_c float8,
  tier_used text, fit_quality text, source text, quality int
);
\copy _ee_stg FROM '/Users/mololuwaobafemimoses/heliotelligence/data_migration/ts_expected_energy.csv' CSV HEADER
INSERT INTO expected_energy (time, site_id, source, p_ac_kw, p_dc_kw, p_dc_stc_kw, poa_total_wm2, t_cell_c, tier_used, fit_quality, quality)
SELECT "time", site_id, source, p_ac_kw, p_dc_kw, p_dc_stc_kw, poa_total_wm2, t_cell_c, tier_used, fit_quality, quality
FROM _ee_stg
ON CONFLICT (time, site_id, source) DO NOTHING;
SELECT 'expected_energy loaded: ' || COUNT(*)::text FROM expected_energy;

-- ========== FINAL ROW COUNTS ==========
SELECT 'sites'             AS tbl, COUNT(*) FROM sites              UNION ALL
SELECT 'inverters',                COUNT(*) FROM inverters          UNION ALL
SELECT 'site_instruments',         COUNT(*) FROM site_instruments   UNION ALL
SELECT 'weather_readings',         COUNT(*) FROM weather_readings   UNION ALL
SELECT 'meter_readings',           COUNT(*) FROM meter_readings     UNION ALL
SELECT 'inverter_readings',        COUNT(*) FROM inverter_readings  UNION ALL
SELECT 'string_readings',          COUNT(*) FROM string_readings    UNION ALL
SELECT 'expected_energy',          COUNT(*) FROM expected_energy
ORDER BY tbl;
