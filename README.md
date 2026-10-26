# Heliotelligence

Enterprise-grade solar digital twin and performance benchmarking platform for utility-scale PV assets.

Heliotelligence is being built as a **physics-first, component-resolved, provenance-aware, measurement-boundary-aware** system. The goal is not simply to reproduce a site-level power number, but to preserve enough physical state to explain where energy was converted, limited, transported, curtailed, or lost.





## Current checkpoint

As of 2026-10-10, the canonical merged backend checkpoint is:

`359ac6695a19fc9781ca26b96529ed4af0566b87`

This is the merge commit of PR #91, **S12D baseline transformer operating-loss evaluation**, and marks completion of the baseline transformer-loss milestone through S12D.

Transformer milestone merges:

- S12A PR #88: `7d25a186cc071a524bcbdbeba17f28d9e750fd58`;
- S12B PR #89: `db78ef563a1c3e68dcacdb13b331a8d06395bbb0`;
- S12C PR #90: `fc9a22f4145d52acfe092fc8b8d1f11b9e14adfa`;
- S12D PR #91: `359ac6695a19fc9781ca26b96529ed4af0566b87`.

Final reviewed S12D head was `eb8008cd68fe9715eaba056d67992048d31dc934`. CI #228 (run ID `38002846864`) validated synthetic merge `eaa78fdf9bd6bf2c8701d80d8760209ccb3c1b9a`:

- backend: **3360 passed in 388.38s**;
- Python: **3.13.16**;
- `pvlib==0.15.2`;
- frontend: success.

S12A–D remain dormant from production. Transformer electrical/network terminal propagation is still deferred and is the next transformer problem to design.

## Engineering philosophy

- Use physical mechanisms rather than permanent loss percentages where the required inputs exist.
- Never invent missing electrical topology or equipment capability.
- Preserve explicit physical reference planes.
- Keep missing authority distinct from explicit zero.
- Introduce new physics through narrow, independently validated contracts.
- Keep validated capability dormant from production until integration proves no double counting and safe fallbacks.
- Preserve provenance, confidence, unresolved reasons, and not-applicable states through downstream state.





## Validated physics chain

The validated high-fidelity electrical/control chain now reaches the transformer reference-condition active-loss baseline:

```text
module electrical state
    ↓
S8 physical string / mismatch / direct DC branch physics
    ↓
S9 inverter authority / conversion / accounting / capability / thermal
    ↓
S10 request / feasibility / selected inverter P/Q/S
    ↓
S11A static radial LV topology + direct per-phase R+jX authority
    ↓
S11B timestamped collection-exit V_LL,RMS authority
    ↓
S11C balanced radial constant-PQ LV operating solution
    ↓
S12A explicit transformer static equipment + S11 boundary authority
    ├───────────────┐
    ↓               ↓
S12B             S12C
factory P_NL /   timestamped transformer
P_LL authority   energisation authority
    \               /
     \             /
      └──────┬────┘
             ↓
S12D factory-reference-condition transformer active-loss baseline
```

S12B and S12C are independent children of S12A. S12D combines canonical S11C, S12A, S12B and S12C. S12D uses delivered collection-exit P/Q and voltage after S11 series losses; it does not use selected inverter power as transformer loading and does not yet solve the transformer network-side terminal state.

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
11. transformer collection-side terminal, only where explicit S12A authority binds it directly to an S11 collection exit;
12. transformer network-side terminal, statically identified by S12A but not yet solved as an operating electrical state;
13. future MV/HV network nodes;
14. revenue-meter boundary.

S12D active loss is an internal model quantity between transformer terminals, not another conductor/reference plane. Transformer terminals are called **collection side** and **network side**; the model does not silently assume LV/HV ordering.

Static equipment authority such as inverter `Smax` or transformer rated apparent power is not a physical conductor plane. Sandia pre-Paco potential is a model counterfactual, not a terminal measurement.

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





## Completed S11, S12 baseline loss, and what is next

S11 v1 remains complete through S11C. The transformer baseline-loss milestone is now complete through S12D:

- **S12A:** explicit balanced-three-phase, two-winding transformer identity, rated apparent power, rated collection/network line-to-line RMS voltage bases, transformer terminal identities, and direct S11 collection-exit binding. It does not establish impedance, vector group, tap state, losses, energisation, or network-side operating voltage.
- **S12B:** explicit transformer-specific factory-test loss authority. `P_NL` is admitted no-load/open-circuit active loss; `P_LL` is admitted total rated load loss including winding and stray effects represented by the factory test. Missing authority is not zero and no default frequency, temperature, winding material, or test side is inferred.
- **S12C:** explicit timestamped energised/de-energised authority. `True`, `False`, and missing remain distinct; explicit `False` is resolved evidence and there is no temporal persistence or inference from power, voltage, daylight, dispatch, or schedule.
- **S12D:** instantaneous factory-reference-condition active-loss baseline. It derives current loading from delivered S11C P/Q and collection-exit voltage:
  `I_oper = |S_exit| / (sqrt(3) V_exit)`,
  `I_rated = S_rated / (sqrt(3) V_rated,collection)`,
  `beta_I = I_oper / I_rated`,
  then evaluates `P_load = P_LL beta_I²` and, where energised and authoritative, `P_total = P_NL + P_load`.

S12D does not clamp `beta_I`; Q and operating voltage therefore affect load current. Clean explicit de-energisation gives definitive zero internal loss, while de-energised nonzero collection transfer and energised zero collection voltage are unresolved contradictions.

S12D does **not** perform winding-temperature, harmonic, frequency, or voltage-dependent no-load corrections. It does not allocate loss to a terminal and must not be interpreted as `P_network = P_collection - P_loss`.

The next transformer increment is the deferred **transformer electrical/network boundary** needed to establish a defensible network-side operating state before S13 MV/HV collection. Equivalent-circuit details such as series impedance, phase displacement, or other network authority must be designed explicitly rather than inferred or assumed.

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
- authoritative S12A transformer identity/rating/boundary evidence;
- transformer factory P_NL/P_LL test evidence and reference conditions;
- timestamped transformer energisation evidence;
- transformer electrical/network parameters and network-side operating state;
- MV/HV collection topology.

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
| Testing | pytest; final reviewed PR #91 synthetic-merge CI passed 3360 backend tests |

## Running tests

Full backend unit suite:

```bash
python -m pytest tests/unit/ -q --no-header --no-cov
```

Physics PRs should additionally run focused stage tests, adjacent electrical regressions, optical/rear regressions where relevant, Ruff, strict mypy on changed files, syntax compilation, and `git diff --check`.

A green implementation report is not merge authority by itself. Review the live code, exact commit ancestry, and fresh CI.

## Production compatibility

The existing aggregate production path still contains legacy percentage effects for mechanisms that are being physically replaced. Physical mismatch, direct DC branch resistance, Sandia accounting, AC capability authority, LV collection physics, and S12A–D transformer baseline-loss physics are validated contracts but are not automatically production-active.

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
