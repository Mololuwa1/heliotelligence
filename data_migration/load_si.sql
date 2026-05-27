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
