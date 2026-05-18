"""Layer 4 — Expected energy engine.

Orchestrates the physics pipeline (irradiance → thermal → electrical →
inverter) over weather_readings data and writes results to the
expected_energy hypertable.

Entry point:
    from heliotelligence.engine.pipeline import run_pipeline
"""
