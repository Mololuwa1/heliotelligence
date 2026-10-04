# Heliotelligence

Enterprise-grade solar digital twin and performance benchmarking platform for utility-scale PV assets.

Heliotelligence is being built as a **physics-first, component-resolved, provenance-aware, measurement-boundary-aware** system. The goal is not simply to reproduce a site-level power number, but to preserve enough physical state to explain where energy was converted, limited, transported, curtailed, or lost.





## Current checkpoint

As of 2026-10-04, the canonical merged backend checkpoint is:

`a8e883b4ba04dfcab4a2736d15ceaf9eed06496e`

This is the merge commit of PR #82, **S10C selected inverter AC dispatch state**, and marks the completed S10 controller milestone.

Controller milestone merges:

- S10A PR #79: `4a6b318946a5a2bb688bfa29f7318403362f99de`;
- S10B PR #81: `2f4a4050c48203018fbf914c3853675f996bda97`;
- S10C PR #82: `a8e883b4ba04dfcab4a2736d15ceaf9eed06496e`.

S10C merge facts:

- previous canonical main: `2f4a4050c48203018fbf914c3853675f996bda97`;
- reviewed head: `90e0ba6cc219a1b288bfda0f215ad787141dd68f`;
- merge commit: `a8e883b4ba04dfcab4a2736d15ceaf9eed06496e`;
- merged at: `2026-10-04T21:47:50Z`.

Final reviewed pre-merge CI evidence for S10C was CI #207 (run ID `37236331555`) on synthetic merge `663a5a0e157296bbd74d8c3cf60c6d58a2dafdec`:

- backend: **2877 passed in 509.72s**;
- Python: **3.13.15**;
- `pvlib==0.15.2`;
- frontend: success.

No separate post-merge workflow was attached directly to the merge commit when this documentation was prepared. Verify live `main` before treating this SHA as current.

## Engineering philosophy

- Use physical mechanisms rather than permanent loss percentages where the required inputs exist.
- Never invent missing electrical topology or equipment capability.
- Preserve explicit physical reference planes.
- Keep missing authority distinct from explicit zero.
- Introduce new physics through narrow, independently validated contracts.
- Keep validated capability dormant from production until integration proves no double counting and safe fallbacks.
- Preserve provenance, confidence, unresolved reasons, and not-applicable states through downstream state.





## Validated physics chain

The validated high-fidelity electrical/control chain now reaches a selected inverter AC dispatch state:

```text
module electrical state
    ↓
S8-1 physical string I-V
    ↓
S8-2 source-plane common-voltage MPPT / mismatch
    ↓
S8-3A explicit direct branch resistance authority
    ↓
S8-3B resistive branch I-V transform
    ↓
S8-3C MPPT-input operating point
    ↓
S9-0 explicit CEC/SAM inverter authority
    ↓
S9-1 DC envelope classification
    ↓
S9-2 Sandia conversion
    ↓
S9-3A pre-limit AC potential
    ↓
S9-3B conversion / clipping / tare accounting
    ↓
S9-4A static AC capability authority
    ↓
S9-4B requested P/Q/S capability evaluation
    + S9-4C thermal authority
    + explicit inverter temperature
    ↓
S9-4D temperature-dependent capability
    ↓
S10A explicit active-power dispatch request
    ↓
S10B requested P/Q/S feasibility
    ↓
S10C selected inverter AC P/Q/S
```

S10 preserves strict separation between request, feasibility and selection. S10C selects only an exact request that S10B has fully proved feasible. It never clamps P, clips Q, projects onto the apparent-power circle, substitutes available power, or fabricates a selected point under partial or unresolved authority.

The S10C boundary is a selected controller/model target at `inverter_ac_output`; it is not measured inverter output and it does not yet include AC current or downstream network physics.

## Electrical reference planes

The architecture distinguishes:

1. module terminals;
2. physical string source terminals;
3. branch/string cable output;
4. parallel collection junction;
5. shared homerun / feeder output;
6. inverter MPPT input terminals;
7. inverter AC output / conversion boundary;
8. future controller-dispatched AC boundary;
9. LV / transformer / MV / HV network nodes;
10. revenue-meter boundary.

Static equipment authority such as `Smax` is not a physical conductor plane. Sandia pre-Paco potential is a model counterfactual, not a terminal measurement.

## Current electrical coverage

### Strings and MPPTs

Heliotelligence models voltage-dependent physical string I-V state and common-voltage MPPT aggregation. Physical mismatch is derived from the difference between independent-string maxima and the connected common-voltage optimum.

### DC branch collection

The validated S8-3 path supports explicit **direct per-string branch series-loop resistance**. It does not yet claim arbitrary shared combiner/homerun network coverage.

Shared post-parallel conductors require a future node/edge DC collection solve because shared resistance acts on total combined current.

### Inverter conversion and accounting

The Sandia inverter chain provides:

- exact inverter CEC/SAM authority;
- DC voltage/current envelope classification;
- single- and multi-MPPT Sandia conversion without averaging MPPT voltages;
- model-native pre-Paco AC potential;
- explicit conversion, empirical model gain, clipping, and below-startup tare accounting.

For applicable rows:

```text
Pdc + conversion_gain - conversion_loss - clipping_loss = Pac
```

There is intentionally no generic `total_inverter_loss_w` because clipping, conversion behaviour, empirical fit artefacts, and below-startup tare are not the same physical category.


### Inverter AC capability authority

S9-4A adds a separate static authority contract for each physical inverter:

- nominal AC voltage;
- voltage basis: `line_to_line`, `line_to_neutral`, or `single_phase_terminal`;
- phase configuration: `single_phase` or `three_phase`;
- rated apparent power `Smax`;
- optional fixed `Qmin/Qmax`;
- source and confidence.

Important rules:

- no `Smax = Paco` inference;
- no AC voltage inference from CEC/SAM `Vac`;
- no capability inference from `pnom_kwac`, grid limits, model labels, MPPT counts, string counts, topology position, or legacy wiring loss;
- `three_phase + single_phase_terminal` is rejected;
- missing Q authority and explicit `Qmin = Qmax = 0` remain distinct.

### Inverter P/Q/S capability-state evaluation

S9-4B is now merged and validated.

Contract:

- `admitted_inverter_ac_and_capability_to_pqs_evaluation_v1`;
- model `explicit_q_request_apparent_power_circle_and_fixed_q_limits_v1`;
- scope `inverter_ac_pqs_capability_evaluation_before_dispatch_and_ac_network`;
- output index `(timestamp, inverter_id)`.

For applicable active rows:

```text
P = admitted S9-3B p_ac_available_w
Q = explicit timestamped reactive-power request
S = hypot(P, Q)
```

The stage evaluates `S <= Smax` and, only where explicit fixed-Q authority exists, `Qmin <= Q <= Qmax`.

Key semantics:

- `Q > 0` means injection into the AC network;
- `Q < 0` means absorption from the AC network;
- explicit `Q = 0` is different from a missing Q request;
- missing fixed-Q authority is not synthesized as `±Smax`;
- a passing apparent-power circle with missing fixed-Q authority is a partial result, not proof of complete reactive capability;
- a known circle violation remains definitive even when fixed-Q authority is absent;
- `|P| > Smax` is a known violation even if Q is missing;
- night-tare / non-producing states are resolved but not applicable;
- static full capability authority remains independent of whether a timestamped Q request exists;
- the evaluator never clamps Q, curtails P, dispatches a replacement setpoint, calculates AC current, or applies network losses.





## What is next

The next physics milestone is **S11 — physical LV AC collection**.

S11 starts from authoritative S10C selected inverter AC P/Q/S at the exact `inverter_ac_output` reference plane. It must introduce explicit LV electrical topology and conductor/voltage authority before calculating current, voltage drop or `I²R` loss.

Key boundaries:

- do not infer AC conductor topology from inverter labels, positions, capacities or aggregate AC-wiring percentages;
- do not infer nominal voltage basis, phase arrangement or power factor when authority is missing;
- do not convert a missing S10C selected point into zero power;
- do not treat selected dispatch as measured telemetry;
- do not double count physical LV losses with legacy aggregate AC-wiring percentages;
- preserve segment-level reference planes so transformer and revenue-meter stages can follow later.

The intended downstream sequence is:

```text
S10C selected inverter AC P/Q/S
    ↓
S11 physical LV AC collection
    ↓
S12 transformer
    ↓
S13 MV/HV collection and revenue-meter boundary
    ↓
S14 benchmarking / causal attribution
```

## Optical / irradiance status

The repository contains component-resolved geometry/optical capability including front irradiance, direct-beam shading authority, diffuse visibility, IAM, fixed-row bifacial rear response, and spectral response.

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
- authoritative S9-4A AC capability authority for the installed inverters;
- transformer and MV/HV collection topology.

Do not infer these relationships from inverter groups, counts, positions, capacities, CEC fields, or labels. See `docs/sites/bracon-ash.md`.

## Tech stack

| Component | Technology |
|---|---|
| Backend API | FastAPI + Uvicorn |
| Physics | pvlib **0.15.2** + Heliotelligence-owned contracts |
| Geometry / ray backend | Trimesh + embreex where applicable |
| Time-series DB | PostgreSQL / TimescaleDB |
| ORM | SQLAlchemy async + asyncpg |
| Configuration | Pydantic v2 + YAML / explicit topology contracts |
| Frontend | Vite-based frontend with CI production build |
| Testing | pytest; final PR #79 synthetic-merge CI passed 2767 backend tests |

## Running tests

Full backend unit suite:

```bash
python -m pytest tests/unit/ -q --no-header --no-cov
```

Physics PRs should additionally run focused stage tests, adjacent electrical regressions, optical/rear regressions where relevant, Ruff, strict mypy on changed files, syntax compilation, and `git diff --check`.

A green implementation report is not merge authority by itself. Review the live code, exact commit ancestry, and fresh CI.

## Production compatibility

The existing aggregate production path still contains legacy percentage effects for mechanisms that are being physically replaced. Physical mismatch, direct DC branch resistance, Sandia accounting, and AC capability authority are validated contracts but are not automatically production-active.

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
