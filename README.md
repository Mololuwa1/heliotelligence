# Heliotelligence

Enterprise-grade solar digital twin and performance benchmarking platform for
utility-scale PV assets.

Heliotelligence is being built as a **physics-first, component-resolved,
measurement-boundary-aware** system. The goal is not simply to reproduce a
site-level power number, but to preserve enough physical state to explain where
energy was converted, limited, transported, curtailed, or lost.

## Current checkpoint

As of 2026-09-28, the canonical merged backend checkpoint is:

`ad0828f42d5a5b733d79e70850df800dbc1aa5a2`

This is the merge of PR #68, **S9-3B Sandia inverter power accounting**.

Exact-main CI run #179 (`36489087563`) passed:

- backend: **2565 tests**;
- Python: **3.13.15**;
- `pvlib==0.15.2`;
- frontend production build: **success**.

These values are a historical checkpoint. Always verify live `main` and current
CI before relying on them.

## Engineering philosophy

- Use physical mechanisms rather than permanent loss percentages where the
  required inputs exist.
- Never invent missing electrical topology or equipment capability.
- Preserve explicit physical reference planes.
- Keep missing authority distinct from explicit zero.
- Introduce new physics through narrow, independently validated contracts.
- Keep validated capability dormant from production until integration proves no
  double counting and safe fallbacks.
- Preserve provenance, confidence, and unresolved reasons through downstream
  state.

## Validated physics chain

The currently validated component chain reaches inverter AC power accounting:

```text
weather / QC
    ↓
solar geometry / irradiance decomposition
    ↓
front / rear optical state
├ horizon + near shading
├ diffuse visibility
├ IAM
├ bifacial rear response
└ spectral response
    ↓
canonical electrical irradiance
    ↓
thermal + module electrical physics
    ↓
S8-1 physical string I-V
    ↓
S8-2 common-voltage MPPT / physical mismatch
    ↓
S8-3A direct branch resistance authority
    ↓
S8-3B resistive branch I-V transform
    ↓
S8-3C MPPT-input common-voltage operating point
    ↓
S9-0 inverter CEC/SAM authority
    ↓
S9-1 inverter DC envelope classification
    ↓
S9-2 Sandia single/multi-MPPT inverter conversion
    ↓
S9-3A Sandia pre-Paco AC potential
    ↓
S9-3B conversion / clipping / tare power accounting
```

The high-fidelity chain is not automatically the production runtime path. The
legacy compatibility path still contains aggregate percentage behaviour for
some mechanisms and must not be combined with physical replacements without an
explicit migration.

## Electrical reference planes

The architecture distinguishes:

1. module terminals;
2. physical string source terminals;
3. branch/string cable output;
4. parallel collection junction;
5. shared homerun / feeder output;
6. inverter MPPT input terminals;
7. inverter AC conversion boundary;
8. future controller-dispatched AC boundary;
9. LV / transformer / MV / HV network nodes;
10. revenue-meter boundary.

This prevents losses from being calculated at the wrong current/voltage state or
applied twice.

## Current electrical coverage

### Strings and MPPTs

Heliotelligence now models voltage-dependent physical string I-V state and
common-voltage MPPT aggregation. Physical mismatch is derived from the difference
between independent-string maxima and the connected common-voltage optimum.

### DC branch collection

The validated S8-3 path supports explicit **direct per-string branch series-loop
resistance**. It does not yet claim arbitrary shared combiner/homerun network
coverage.

Shared post-parallel conductors require a future node/edge DC collection solve
because shared resistance acts on total combined current.

### Inverter

The current Sandia inverter chain provides:

- exact inverter CEC/SAM authority;
- DC voltage/current envelope classification;
- single- and multi-MPPT Sandia conversion without averaging MPPT voltages;
- model-native pre-Paco AC potential;
- explicit conversion, empirical model gain, clipping, and below-startup tare
  accounting.

For applicable rows the accounting closes as:

```text
Pdc + conversion_gain - conversion_loss - clipping_loss = Pac
```

There is intentionally no generic `total_inverter_loss_w` because clipping,
conversion behaviour, empirical fit artefacts, and below-startup tare are not the
same physical category.

## What is next

The immediate next build is:

### S9-4A — explicit inverter AC capability authority

The next authority layer should establish, where real equipment data exists:

- nominal AC line voltage;
- phase configuration;
- rated apparent power `Smax`;
- reactive-power limits / capability curve;
- supported power-factor range;
- parameter source and confidence.

Do not infer `Smax = Paco` or infer Q capability from active-power rating alone.

Planned follow-ons:

- **S9-4B:** inverter P/Q/S capability envelope;
- **S9-4C:** thermal derating only with explicit manufacturer/thermal authority;
- **S10:** plant controller / dispatch boundary;
- **S11:** physical LV AC collection;
- **S12:** transformer model;
- **S13:** MV/HV collection and revenue-meter boundary;
- **S14:** production-grade benchmarking and causal loss attribution.

AC cable physics intentionally follows P/Q/S capability because AC current
cannot be calculated honestly without voltage, phase, P, and Q state.

## Optical / irradiance status

The repository contains component-resolved geometry/optical capability including
front irradiance, direct-beam shading authority, diffuse visibility, IAM,
fixed-row bifacial rear response, and spectral response.

Important remaining extensions include:

- dynamic physical/measured soiling;
- snow state modelling;
- arbitrary 3D rear obstruction / terrain / tracker coverage;
- substring / bypass-diode partial-shading electrical behaviour;
- multiple-local-maximum / MPPT tracking behaviour.

## Reference site discipline

Bracon Ash is a reference/onboarded site, **not** a topology template.

Known unresolved site facts include:

- physical MPPT-to-string mapping;
- string-to-inverter assignment from as-built evidence;
- physical DC cable / shared collection topology;
- transformer and MV/HV collection topology.

Do not infer these relationships from inverter groups, counts, positions,
capacities, or labels. See `docs/sites/bracon-ash.md`.

## Tech stack

| Component | Technology |
|---|---|
| Backend API | FastAPI + Uvicorn |
| Physics | pvlib **0.15.2** + Heliotelligence-owned contracts |
| Geometry / ray backend | Trimesh + embreex where applicable |
| Time-series DB | PostgreSQL / TimescaleDB |
| ORM | SQLAlchemy async + asyncpg |
| Configuration | Pydantic v2 + YAML / explicit topology contracts |
| Scheduler | APScheduler compatibility path; external worker architecture remains future work |
| Frontend | Vite-based frontend with CI production build |
| Testing | pytest; exact-main checkpoint above passed 2565 backend tests |

## Running the backend locally

### Prerequisites

- Python 3.13
- PostgreSQL / TimescaleDB as required by the local environment

Install the project and development dependencies using the repository's current
package configuration. The physics dependency is intentionally pinned to
`pvlib==0.15.2`.

Copy environment configuration:

```bash
cp .env.example .env
```

Never commit credentials or secret values.

Start the API using the normal project environment, for example:

```bash
uvicorn heliotelligence.api.app:app --reload
```

The scheduler can be controlled with `RUN_SCHEDULER`. Staging has been validated
with in-process scheduling disabled; see `docs/deployment-environments.md`.

## Running tests

Full backend unit suite:

```bash
python -m pytest tests/unit/ -q --no-header --no-cov
```

Physics PRs should additionally run focused stage tests, adjacent electrical
regressions, optical/rear regressions where relevant, Ruff, strict mypy on
changed files, syntax compilation, and `git diff --check`.

A green implementation report is not merge authority by itself. Review the live
code, exact commit ancestry, and fresh CI.

## Site configuration

Site configuration should provide explicit equipment and topology authority.
Adding a site must not require hardcoding site-specific assumptions into reusable
physics code.

Where high-fidelity topology is unavailable, keep a safe compatibility path or
explicit unresolved state rather than manufacturing connectivity.

Module parameter resolution retains traceable tiers such as CEC/SAM authority,
local/datasheet evidence, and lower-fidelity fallback where appropriate.

## Production compatibility

The existing aggregate production path still contains legacy percentage effects
for mechanisms that are being physically replaced. In particular, physical
mismatch and direct DC branch resistance now exist as validated contracts but
must not be blindly stacked with legacy mismatch/wiring percentages.

Production integration is a separate architecture step and must prove:

- no double counting;
- reference-plane alignment;
- deterministic fallback behaviour;
- explicit provenance;
- correct unresolved handling;
- regression safety at site and meter boundaries.

## Documentation

Start here for current architecture/development context:

- `docs/AI_HANDOFF.md` — recovery checkpoint and non-negotiable rules;
- `docs/architecture/physics-architecture.md` — target/current physical chain;
- `docs/development/physics-roadmap.md` — build order and next stages;
- `docs/decisions/ADR-001-physics-first-electrical-migration.md` — migration decision;
- `docs/validation/physics-validation-strategy.md` — validation hierarchy;
- `docs/sites/bracon-ash.md` — reference-site facts and unresolved authority;
- `docs/deployment-environments.md` — development/staging/production boundaries.

## Current development direction

Heliotelligence is no longer at an MVP-style "single aggregate physics
calculation" stage. Development is focused on completing an enterprise-grade
component chain from environmental inputs to the revenue-meter boundary, then
activating those layers in production without hiding uncertainty or double
counting physical losses.
