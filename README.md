# Heliotelligence

Enterprise-grade solar digital twin and performance benchmarking platform for utility-scale PV assets.

Heliotelligence is being built as a **physics-first, component-resolved, provenance-aware, measurement-boundary-aware** system. The goal is not simply to reproduce a site-level power number, but to preserve enough physical state to explain where energy was converted, limited, transported, curtailed, or lost.





## Current checkpoint

As of 2026-10-06, the canonical merged backend checkpoint is:

`6f6dbb34027f9e648fe8623aab37b14341f193c7`

This is the merge commit of PR #86, **S11C balanced radial LV AC collection solve**, and marks the completed S11 v1 milestone.

Controller milestone merges:

- S10A PR #79: `4a6b318946a5a2bb688bfa29f7318403362f99de`;
- S10B PR #81: `2f4a4050c48203018fbf914c3853675f996bda97`;
- S10C PR #82: `a8e883b4ba04dfcab4a2736d15ceaf9eed06496e`.

LV collection milestone merges:

- S11A PR #84: `caabb06ff31d5b5cf48139fada6aeb265ae9771a`;
- S11B PR #85: `3fb4c3181c283ecf62622865b88622ac7b24ae22`;
- S11C PR #86: `6f6dbb34027f9e648fe8623aab37b14341f193c7`.

Final reviewed S11C head was `73dafc1f79c09ccd9fb61dd9ee7610cc2e62233c`. CI #217 (run ID `37544412809`) validated synthetic merge `a8ea3ec4965e75f2ae67dae835a74dc619bf4d2e`:

- backend: **3040 passed in 527.89s**;
- Python: **3.13.15**;
- `pvlib==0.15.2`;
- frontend: success.

## Engineering philosophy

- Use physical mechanisms rather than permanent loss percentages where the required inputs exist.
- Never invent missing electrical topology or equipment capability.
- Preserve explicit physical reference planes.
- Keep missing authority distinct from explicit zero.
- Introduce new physics through narrow, independently validated contracts.
- Keep validated capability dormant from production until integration proves no double counting and safe fallbacks.
- Preserve provenance, confidence, unresolved reasons, and not-applicable states through downstream state.





## Validated physics chain

The validated high-fidelity electrical/control chain now reaches the modeled LV collection-exit boundary:

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
    ↓
S11A static radial LV topology + direct per-phase R+jX authority
    ↓
S11B timestamped collection-exit V_LL,RMS authority
    ↓
S11C balanced radial constant-PQ operating solve
    ↓
modeled collection-exit P/Q after physical LV series losses
```

S10 preserves strict separation between request, feasibility and selection. S10C selects only an exact request that S10B has fully proved feasible. It never clamps P, clips Q, projects onto the apparent-power circle, substitutes available power, or fabricates a selected point under partial or unresolved authority.

S10C remains a selected controller/model target at `inverter_ac_output`, not measured inverter output. S11C computes a modeled electrical operating state from that target plus explicit S11A topology/impedance and S11B boundary-voltage authority. Neither state is automatically telemetry.

## Electrical reference planes

The architecture distinguishes:

1. module terminals;
2. physical string source terminals;
3. branch/string cable output;
4. parallel collection junction;
5. shared homerun / feeder output;
6. inverter MPPT input terminals;
7. inverter AC output / conversion boundary;
8. S10C selected target / S11A inverter-terminal binding at `inverter_ac_output`;
9. S11C-solved internal LV nodes;
10. `lv_ac_collection_exit`, the end of S11;
11. future transformer / MV / HV nodes;
12. revenue-meter boundary.

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





## Completed S11 and what is next

S11 v1 is complete through three dormant contracts:

- **S11A:** explicit balanced-three-phase radial topology, inverter-terminal bindings, collection exits, and direct per-phase `R+jX`; missing authority remains unresolved and explicit zero impedance remains valid;
- **S11B:** exact timestamped `line_to_line_rms` voltage magnitude at `lv_ac_collection_exit`; zero volts is explicit evidence, while missing evidence is not zero and is never filled or interpolated;
- **S11C:** deterministic balanced radial constant-PQ backward/forward sweep with segment current, voltage, instantaneous `3R|I|²` active loss, `3X|I|²` reactive consumption, and whole-tree P/Q conservation.

S11 supports shared segments once, multiple independent trees, and unresolved numerical/nonconvergence states without fabricated physical output. It does not model imbalance, neutral conductors, shunts, loads, transformer physics, voltage compliance, controller feedback, energy integration, or measured actual state.

The next physics milestone is **S12 — transformer**, beginning authority-first with explicit equipment/topology and reference-plane evidence. `lv_ac_collection_exit` must not be silently equated with a transformer winding.

The intended downstream sequence is:

```text
S10C selected inverter AC P/Q/S
    ↓
S11A topology/R+jX → S11B exit voltage → S11C LV operating solve
    ↓
S12 transformer authority first [next]
    ↓
S13 MV/HV collection + explicit revenue-meter boundary
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
- physical LV terminal/junction/exit topology, direct per-phase segment R/X, and exact collection-exit voltage authority;
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
