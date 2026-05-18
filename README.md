# Heliotelligence

Solar farm digital twin and performance benchmarking platform. Physics-based expected energy modelling, multi-site SCADA ingestion, and loss attribution for utility-scale PV assets.

---

## Overview

Heliotelligence computes what a solar farm *should* produce under prevailing conditions, then compares it against what it *actually* produced. The gap between the two — broken down by loss category — is the performance ratio waterfall. This gives asset managers, O&M engineers, and investors a causal, auditable explanation of every percentage point of underperformance.

The platform is built around the single-diode model (SDM) as implemented in pvlib, the NREL/Sandia open-source PV simulation library. The SDM is the industry standard for physics-based PV simulation and the foundation of IEC 61853 and NREL's System Advisor Model (SAM).

---

## Architecture — 7 layers

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 7 — Platform outputs                          [ planned ]│
│  React dashboard · alerting engine · PDF reports · forecast API │
├─────────────────────────────────────────────────────────────────┤
│  Layer 6 — Analysis modules                          [ planned ]│
│  Degradation tracker · anomaly detection · day-ahead forecast   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 5 — Benchmarking core                         [ planned ]│
│  PR = E_act / E_exp · losses waterfall · yield · availability   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4 — Expected energy engine                    [ planned ]│
│  Orchestrates physics pipeline · writes to expected_energy table│
├─────────────────────────────────────────────────────────────────┤
│  Layer 3 — Physics model stack                       [  BUILT  ]│
│  Irradiance · thermal · single-diode · inverter · module lookup │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2 — Time-series storage and quality           [  BUILT  ]│
│  TimescaleDB · gap-fill · outlier detection · unit validation   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1 — Data ingestion                            [  BUILT  ]│
│  SCADA CSV · Solcast · met station · site config DB             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech stack

| Component | Technology |
|---|---|
| Backend API | FastAPI + uvicorn |
| Physics engine | pvlib 0.15.1 |
| Time-series DB | TimescaleDB (Tiger Data / Timescale Cloud) |
| ORM | SQLAlchemy async + asyncpg |
| Scheduler | APScheduler |
| Config | Pydantic v2 + YAML |
| Frontend (planned) | React + Recharts |
| Weather data | Solcast API |
| Testing | pytest (179 tests) |

---

## Layer 3 — Physics model stack

### Overview

The physics stack converts raw weather measurements into expected DC and AC power for any solar farm. It is entirely driven by `SiteConfig` — no site-specific values are hardcoded anywhere in the physics package. Adding a new site means adding a YAML entry, not touching physics code.

The stack chains four models in sequence:

```
weather_readings (DB)
        │
        ▼
┌───────────────────┐
│  Irradiance model │  GHI → POA (Perez) · bifacial rear gain · IAM
└────────┬──────────┘
         │  poa_total W/m²
         ▼
┌───────────────────┐
│  Thermal model    │  Faiman (Uc/Uv) · NOCT fallback · measured override
└────────┬──────────┘
         │  t_cell °C
         ▼
┌───────────────────┐
│  Electrical model │  Single-diode (SDM) · five-tier module lookup
│  (single-diode)   │  spectral correction · loss cascade
└────────┬──────────┘
         │  p_dc_kw
         ▼
┌───────────────────┐
│  Inverter model   │  PVWatts · clipping detection · grid limit
└────────┬──────────┘
         │  p_ac_kw
         ▼
  expected_energy (DB)
```

---

### Irradiance model (`physics/irradiance.py`)

**Function:** `calculate_poa(site, weather_df, solar_position=None) -> pd.DataFrame`

**What it does:**

1. Builds a `pvlib.location.Location` from site latitude, longitude, altitude, and timezone.
2. Calculates solar position for every timestamp using `pvlib.solarposition.get_solarposition()`.
3. **Measured POA path** — if `weather_df` contains a `poa_wm2` column with fewer than 20% NaN values, uses measured plane-of-array irradiance directly. This is the most accurate path and is used for Bracon Ash which has an on-site POA pyranometer.
4. **Modelled POA path** — if measured POA is unavailable, transposes GHI to POA using the Perez model via `pvlib.irradiance.get_total_irradiance(model='perez')`. Uses `site.pvlib_azimuth` (which converts PVsyst convention 0=South to pvlib convention 180=South) and `site.tilt_deg`.
5. **Bifacial rear irradiance** — if `site.module.bifacial=True`, calculates rear irradiance using `pvlib.bifacial.infinite_sheds.get_irradiance()` with `site.gcr` and `site.height_m`. Scales by `site.module.bifaciality_factor`. Bracon Ash: bifaciality factor 0.80.
6. Applies IAM (incidence angle modifier) correction using `pvlib.iam.physical()`.

**Outputs:** DataFrame with `poa_total`, `poa_direct`, `poa_diffuse`, `poa_rear`, `aoi`, `solar_zenith`, `solar_azimuth`.

**Azimuth convention note:** PVsyst uses 0=South, negative=West. pvlib uses 180=South. The `pvlib_azimuth` property on `SiteConfig` handles this conversion automatically: `pvlib_azimuth = azimuth_deg + 180`.

---

### Thermal model (`physics/thermal.py`)

**Function:** `calculate_cell_temp(site, poa_total, temp_amb, wind_speed, temp_module_measured=None) -> pd.Series`

**What it does:**

1. **Measured module temperature path** — if `temp_module_measured` is provided with fewer than 10% NaN values, derives cell temperature from measured module temperature with a small irradiance-dependent correction: `t_cell = t_module + poa_total × 0.03 / 1000`. This is the most accurate path and is used for Bracon Ash which has module temperature sensors.
2. **Faiman model (primary)** — uses `pvlib.temperature.faiman(poa_total, temp_amb, wind_speed, u_c, u_v)` where `u_c` and `u_v` come from `site.module.u_c` and `site.module.u_v`. The Faiman model is what PVsyst uses. Bracon Ash: Uc=29.0 W/m²K, Uv=0.0 (no wind correction).
3. **NOCT fallback** — if Faiman parameters are unavailable, uses `pvlib.temperature.noct_sam()` with `site.module.noct_c` (default 45°C).

**Output:** Series `t_cell_c`.

---

### Single-diode electrical model (`physics/electrical.py`)

**Function:** `calculate_dc_power(site, poa_total, t_cell, aoi) -> pd.DataFrame`

This is the core physics engine. It implements the five-parameter single-diode equivalent circuit model of a PV module.

**The governing equation:**

```
I = I_ph − I_0 · [exp((V + I·Rs) / (n·Vt)) − 1] − (V + I·Rs) / Rsh
```

where Vt = nkT/q is the thermal voltage. pvlib solves this iteratively via Newton-Raphson.

**What it does:**

1. **Module parameter resolution** — calls `resolve_module_params()` (see five-tier lookup below).
2. **Spectral correction** — applies `pvlib.spectrum.spectral_factor_firstsolar()` as a mandatory step before the electrical calculation. Corrects for real spectral variation from the AM1.5 reference spectrum. Skipped with a WARNING if precipitable water or air mass inputs are unavailable.
3. **Routes by tier:**
   - Tiers 1–2 (CEC): `pvlib.pvsystem.calcparams_desoto()` + `pvlib.pvsystem.singlediode()`
   - Tiers 3–4 (local library / datasheet): `pvlib.pvsystem.calcparams_pvsyst()` + `pvlib.pvsystem.singlediode()`
   - Tier 5 (PVWatts): `pvlib.pvsystem.pvwatts_dc()`
4. **Technology warning** — logs WARNING for non-crystalline-silicon modules (`cdte`, `cigs`, `hjt`) since the SDM was derived for c-Si and may have 2–5% error for other technologies.
5. **Scales to array:** single-module output × `num_strings` × `modules_per_string`.
6. **Loss cascade** (applied in order):
   - Soiling: `site.module.soiling_loss_pct` (default 1.0%)
   - LID (light-induced degradation): `site.module.lid_loss_pct` (default 0.60%)
   - Mismatch: `site.module.mismatch_loss_pct` (default 1.15%)
   - DC wiring: `site.module.wiring_loss_dc_pct` (default 0.48%)

**Outputs:** DataFrame with `p_dc_kw`, `p_dc_stc_kw`, `v_mp`, `i_mp`, `tier_used`, `fit_quality`.

---

### Five-tier module parameter lookup (`physics/module_lookup.py`)

**Function:** `resolve_module_params(module_cfg) -> dict`

The lookup resolves module parameters in order of accuracy, stopping at the first tier that succeeds. The tier used is logged at INFO level on every call and returned in the output.

| Tier | Source | Accuracy | When used |
|---|---|---|---|
| 1 | CEC database (explicit) | Highest | `module.cec_name` set and found in `retrieve_sam('CECMod')` |
| 2 | CEC database (auto-search) | Highest | Fuzzy match on manufacturer + model found in CEC DB. Logs WARNING to set `cec_name` explicitly |
| 3 | Local module library | Medium | `module.local_module_name` found in `config/module_library.yaml` |
| 4 | Inline datasheet params | Low | `v_mp`, `i_mp`, `v_oc`, `i_sc` all set in `SiteConfig` |
| 5 | PVWatts fallback | Lowest | Only `pnom_wp` and `gamma_pmp` available |

**Why this hierarchy matters:** CEC coefficients are fitted to full measured I-V curves at multiple operating conditions — significantly more accurate than three-point datasheet extraction. The pipeline automatically upgrades from Tier 3 to Tier 1 the moment a module appears in the CEC database, with no config changes needed.

**Physical validity guard:** The lookup validates that `i_sc > i_mp` before accepting any parameter set. This catches a common datasheet error (rounded values can produce `i_sc < i_mp` which is physically impossible).

---

### Local module library (`config/module_library.yaml`)

A YAML file that acts as a proprietary module database sitting above the CEC database in the lookup hierarchy. Every new site onboarded potentially adds modules to this library that future sites can benefit from.

Current entries:

| Module | i_sc | i_mp | Source | Fit quality |
|---|---|---|---|---|
| JKM570N-72HL4-BDV | 14.36 A | 13.69 A | Datasheet fit | Low |
| JKM575N-72HL4-BDV | 14.45 A | 13.77 A | Datasheet fit | Low |

**Note on fit quality:** `low` means parameters were derived from three STC datasheet points (underdetermined). `high` means parameters were fitted to measured I-V curves at multiple conditions. CEC database entries are always `high`. Once Jinko submits these modules to the CEC database, the pipeline will automatically upgrade to Tier 1.

**Adding a new module:**

```yaml
modules:
  YOUR_MODULE_NAME:
    manufacturer: "Manufacturer Name"
    model: "Model Number"
    technology: "mono_si"        # mono_si | poly_si | cdte | cigs | hjt
    source: "datasheet_fit"      # datasheet_fit | iv_curve_measured
    fit_quality: "low"           # low | high
    date_added: "YYYY-MM-DD"
    notes: "Brief description of source and any corrections made."
    pnom_wp: 400.0
    v_mp: 38.5
    i_mp: 10.39
    v_oc: 46.2
    i_sc: 11.05                  # Must be > i_mp
    alpha_sc: 0.045              # %/°C
    beta_voc: -0.27              # %/°C
    gamma_pmp: -0.35             # %/°C
    cells_in_series: 120
    bifacial: false
    bifaciality_factor: 0.0
    u_c: 29.0
    u_v: 0.0
    noct_c: 45.0
```

---

## Layer 1 & 2 — Data ingestion and storage

### SCADA CSV pipeline

The platform polls a drop folder every 5 minutes for new CSV exports. Files are parsed, quality-flagged, and upserted into TimescaleDB.

**Drop folder structure:**
```
data/
  scada/
    site-001/          ← drop CSVs here
      archive/         ← processed files moved here
      failed/          ← files that errored
    site-002/
```

**Quality flag convention:** `0`=good, `1`=gap-filled, `2`=flagged, `3`=missing.

**Timestamp convention:** UTC, period-END.

### TimescaleDB schema

Four hypertables, all with `site_id UUID` and `time TIMESTAMPTZ`:

| Table | Primary key | Key columns |
|---|---|---|
| `weather_readings` | `(time, site_id, source)` | GHI, POA, module temp, wind, ambient temp |
| `meter_readings` | `(time, site_id)` | AC power, exported energy, frequency |
| `inverter_readings` | `(time, site_id, inverter_id)` | AC power, energy, availability, comms status |
| `string_readings` | `(time, site_id, inverter_id, string_id)` | String current, power, energy, availability |

Five continuous aggregates provide hourly and daily rollups. Compression after 7 days, 3-year retention.

---

## Site configuration

### Adding a new site

1. Add an entry to `config/sites.yaml`:

```yaml
sites:
  - id: "site-003"
    name: "Kent Solar Park"
    latitude: 51.28
    longitude: 0.52
    altitude_m: 35
    timezone: "Europe/London"
    capacity_kwp: 5000.0
    tilt_deg: 20.0
    azimuth_deg: 0.0            # 0 = South (PVsyst convention)
    gcr: 0.40
    height_m: 1.0
    solcast_resource_id: "your-solcast-id"
    scada_csv_dir: "data/scada/site-003/"
    module:
      cec_name: "Jinko_Solar_Co___Ltd_JKM410M_72HL"  # if in CEC DB
      technology: "mono_si"
      bifacial: false
      soiling_loss_pct: 1.5
    inverter:
      pvlib_model: "pvwatts"
      pnom_kwac: 250.0
      num_units: 20
      eta_nom: 0.975
      grid_limit_kwac: 5000.0
```

2. Restart the server — `sync_sites()` automatically upserts the new site into the database on startup.

3. Create the drop folder: `mkdir -p data/scada/site-003/`

4. Drop a CSV export into the folder — the scheduler picks it up within 5 minutes.

### Module tier selection guide

| Situation | What to set in YAML |
|---|---|
| Module is in pvlib CEC database | Set `module.cec_name` — highest accuracy, recommended |
| Module is in local library | Set `module.local_module_name` |
| Module not in either database | Provide `v_mp`, `i_mp`, `v_oc`, `i_sc`, `alpha_sc`, `beta_voc`, `gamma_pmp`, `cells_in_series` |
| Only nameplate data available | Provide `pnom_wp` and `gamma_pmp` — PVWatts fallback |

---

## Running the platform

### Prerequisites

- Python 3.13
- Tiger Data (Timescale Cloud) service
- pvlib 0.15.1 (installed in `.venv`)

### Environment setup

```bash
cp .env.example .env
# Edit .env with your Tiger Data connection string and Solcast API key
```

`.env` required variables:

```
DATABASE_URL=postgresql+asyncpg://tsdbadmin:PASSWORD@HOST:36400/tsdb?ssl=require
SOLCAST_API_KEY=your-solcast-api-key        # optional — Solcast collector skipped if not set
```

### Start the server

```bash
cd /path/to/heliotelligence
.venv/bin/uvicorn heliotelligence.api.app:app --reload
```

On startup the server:
1. Loads `config/sites.yaml`
2. Syncs all sites to the `sites` table in Tiger Data (upsert)
3. Starts APScheduler — polls each site's CSV drop folder every 5 minutes
4. Begins serving API requests

### Health check

```bash
curl http://localhost:8000/health
# {"status":"ok","db":"ok","version":"PostgreSQL 18.x | TimescaleDB 2.x"}
```

### Ingest status

```bash
curl http://localhost:8000/api/v1/ingest/status
# Shows last_run, last_success, last_error, files_processed per site
```

---

## Running the tests

```bash
.venv/bin/python -m pytest tests/unit/ -q --no-header --no-cov
```

Current test count: **179 tests, all passing.**

Test coverage:

| Module | Tests |
|---|---|
| CSV parser | 24 |
| Normaliser | 18 |
| Quality flags | 21 |
| SCADA CSV collector | 12 |
| Solcast collector | 14 |
| Site sync (DB) | 11 |
| Physics — module lookup | 6 |
| Physics — irradiance | 5 |
| Physics — thermal | 4 |
| Physics — electrical | 4 |

---

## Reference site — Bracon Ash

The reference site used to validate the physics stack. All physics model calibration targets are derived from the PVsyst simulation report (BELECTRIC GmbH, June 2023).

| Parameter | Value |
|---|---|
| Capacity (DC STC) | 28,524 kWp |
| Capacity (AC) | 21,120 kWac |
| Grid connection limit | 20,000 kWac |
| Location | 52.56°N, 1.21°E, 47m altitude |
| Tilt / Azimuth | 15° / -0.6° (near-south) |
| GCR | 65.4% |
| Modules | Jinkosolar JKM570N + JKM575N (N-type TOPCon bifacial) |
| Inverters | 66 × Sungrow SG350HX-15A (320 kWac each) |
| Thermal model | Faiman — Uc=29.0 W/m²K, Uv=0.0 |
| Bifaciality factor | 0.80 |
| PVsyst design PR | 86.56% |
| PVsyst specific yield | 993 kWh/kWp/year |

**PVsyst loss breakdown (calibration targets):**

| Loss | Value |
|---|---|
| GHI → POA transposition | +11.9% |
| Near shading (irradiance) | -3.38% |
| IAM | -2.92% |
| Soiling | -1.00% |
| Bifacial rear gain | +2.76% |
| Temperature | -0.36% |
| Mismatch | -1.15% |
| DC wiring | -0.48% |
| Inverter efficiency | -1.58% |
| AC + transformer | -1.70% |
| Grid curtailment | -1.24% |

---

## Known technical debt

| Item | Priority | Notes |
|---|---|---|
| Alembic migration defines `site_id` as VARCHAR but live DB uses UUID | Medium | Corrective migration needed before fresh environment setup |
| ETL column mapping for non-Bracon-Ash SCADA formats | High | `instrument_column_map` table designed but not populated for second sites |
| Solcast collector needs real resource IDs in `sites.yaml` | Low | Placeholder IDs in config — Solcast jobs skipped until set |
| Module library entries are `fit_quality: low` | Low | Will auto-upgrade to CEC Tier 1 when Jinko submits modules |

---

## Project structure

```
heliotelligence/
├── config/
│   ├── sites.yaml               # Site configuration (one entry per site)
│   ├── module_library.yaml      # Local module parameter database
│   └── sites.example.yaml       # Template for new sites
├── data/
│   └── scada/                   # SCADA CSV drop folders (gitignored)
├── migrations/                  # Alembic migration files
├── src/heliotelligence/
│   ├── api/
│   │   ├── app.py               # FastAPI application + lifespan
│   │   └── routers/             # health, ingest endpoints
│   ├── collectors/
│   │   ├── scada_csv.py         # CSV drop folder watcher
│   │   ├── solcast.py           # Solcast API collector
│   │   └── scheduler.py         # APScheduler wiring
│   ├── config/
│   │   ├── site.py              # SiteConfig, ModuleConfig, InverterConfig
│   │   └── settings.py          # App settings
│   ├── db/
│   │   ├── session.py           # Async SQLAlchemy engine
│   │   ├── sync.py              # Site sync on startup
│   │   └── health.py            # DB health check
│   ├── ingest/
│   │   ├── csv_parser.py        # SCADA CSV → typed rows
│   │   ├── normaliser.py        # Column routing by equipment group
│   │   └── upsert.py            # Idempotent DB upserts
│   ├── models/
│   │   ├── orm.py               # SQLAlchemy ORM models
│   │   └── schemas.py           # Pydantic input schemas
│   ├── physics/
│   │   ├── module_lookup.py     # Five-tier module parameter resolution
│   │   ├── irradiance.py        # POA irradiance (Perez + bifacial + IAM)
│   │   ├── thermal.py           # Cell temperature (Faiman / NOCT)
│   │   └── electrical.py        # Single-diode DC power + loss cascade
│   └── quality/
│       └── flags.py             # Quality flag assignment
└── tests/
    └── unit/
        ├── test_csv_parser.py
        ├── test_flags.py
        ├── test_normaliser.py
        ├── test_scada_csv_collector.py
        ├── test_solcast_collector.py
        ├── test_sync.py
        └── test_physics/
            ├── test_module_lookup.py
            ├── test_irradiance.py
            ├── test_thermal.py
            └── test_electrical.py
```

---

## Roadmap

| Layer | Status | Next milestone |
|---|---|---|
| Layer 1 — Ingestion | ✅ Built | Multi-SCADA format support (column mapping per site) |
| Layer 2 — Storage | ✅ Built | — |
| Layer 3 — Physics | ✅ Built | CEC auto-upgrade monitoring |
| Layer 4 — Expected energy engine | 🔲 Next | `expected_energy` table + pipeline orchestrator |
| Layer 5 — Benchmarking core | 🔲 Planned | PR, losses waterfall, availability |
| Layer 6 — Analysis | 🔲 Planned | Degradation tracker, anomaly detection |
| Layer 7 — UI + API | 🔲 Planned | React dashboard, PDF reports, forecast API |
