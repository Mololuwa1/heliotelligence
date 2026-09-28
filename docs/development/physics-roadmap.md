# Physics Development Roadmap

This roadmap describes dependency order, not a fixed pull-request numbering
scheme. Stage and PR numbers may change as evidence, data authority, and review
boundaries evolve.

Source-of-truth order for implementation status is:

1. live source code;
2. automated tests;
3. Git history and exact commit ancestry;
4. exact GitHub Actions CI;
5. architecture documentation;
6. implementation reports and conversation notes.

The project is beyond MVP. New physics should remain narrow, provenance-aware,
explicit about unresolved state, and dormant from production until independently
validated.

## Current canonical checkpoint

As of 2026-09-28, live `main` is:

`ad0828f42d5a5b733d79e70850df800dbc1aa5a2`

This is the merge commit of PR #68, S9-3B inverter power accounting.

Exact-main CI:

- run #179;
- run ID `36489087563`;
- Python 3.13.15;
- `pvlib==0.15.2`;
- backend `2565 passed in 130.39s`;
- frontend success.

Always re-check live GitHub before treating this SHA as current.

## Current validated electrical chain

```text
module electrical state
    ↓
S8-1 physical string I-V
    ↓
S8-2 source-plane common-voltage MPPT / physical mismatch
    ↓
S8-3A explicit direct-branch resistance authority
    ↓
S8-3B resistive branch I-V transform
    ↓
S8-3C MPPT-input common-voltage operating point
    ↓
S9-0 explicit inverter CEC/SAM authority
    ↓
S9-1 inverter DC operating-envelope classification
    ↓
S9-2 one-physical-inverter Sandia AC conversion
    ↓
S9-3A Sandia pre-Paco AC potential
    ↓
S9-3B conversion / clipping / tare power accounting
```

Status by stage:

- **S8-1 — merged:** homogeneous physical string I-V scaling.
- **S8-2 — merged:** source-plane common-voltage MPPT and IV-consistent mismatch.
- **S8-3A — merged:** explicit direct string-branch resistance authority.
- **S8-3B — merged:** string-terminal to MPPT-input resistive I-V transform.
- **S8-3C — merged:** MPPT-input common-voltage operating point.
- **S9-0 — merged:** exact inverter ID → CEC/SAM Sandia authority.
- **S9-1 — merged:** DC voltage/current envelope classification with explicit
  tracker-current authority where required.
- **S9-2 — merged:** single- or multi-MPPT Sandia conversion for one physical
  inverter, without voltage averaging or duplicated inverter limits.
- **S9-3A — merged:** model-native Sandia pre-Paco AC potential.
- **S9-3B — merged:** explicit conversion / empirical gain / Paco clipping /
  below-startup tare power accounting with exact closure.

## Immediate next build

The next priority is **S9-4A — explicit inverter AC capability authority**.

Do not jump directly to AC cabling. Physical AC collection loss depends on
current, and AC current depends on voltage, phase configuration, active power,
reactive power, and apparent power. Building LV cable physics first would force
hidden assumptions or another percentage-loss layer.

### S9-4A — explicit inverter AC capability authority

Introduce a narrow static equipment-authority layer for AC-side inverter
capability.

Preferred explicit fields, where supported by manufacturer or equipment data:

- nominal AC line voltage;
- phase configuration;
- rated apparent power `Smax`;
- reactive-power limits or capability curve;
- supported power-factor range;
- parameter source and confidence.

Rules:

- do not infer `Smax = Paco` unless authoritative equipment evidence establishes
  that equivalence;
- do not infer Q capability from active-power rating alone;
- missing capability authority remains unresolved, not guessed;
- this stage classifies authority only and must not dispatch or curtail;
- S9-3B active-power accounting remains immutable input state.

### S9-4B — inverter P/Q/S capability envelope

Consume admitted active-power state and explicit S9-4A authority to expose:

- `P` available at the inverter AC boundary;
- requested / commanded `Q` only where explicitly supplied;
- `S = sqrt(P^2 + Q^2)`;
- power factor where defined;
- apparent-power headroom;
- Q/PF capability flags;
- explicit unresolved state when command or equipment authority is unavailable.

This stage evaluates capability only. It should not silently reduce active power
to satisfy a reactive-power request. Constrained dispatch belongs in a later
controller stage.

### S9-4C — inverter thermal derating, only with explicit authority

Add thermal derating only where defensible manufacturer curves or validated
operating-temperature authority exist.

Potential inputs include:

- ambient or inverter temperature;
- manufacturer derating curve / breakpoint table;
- temperature-dependent active/apparent capability;
- parameter source and confidence.

Do not invent derating curves from nameplate power or ambient temperature.
Absent authority must remain not-applicable / unresolved without corrupting the
validated static Sandia path.

## Next system stages after inverter capability

### S10 — plant-controller / dispatch boundary

Separate **available AC** from **dispatched AC**.

This layer should own:

- active-power curtailment;
- export setpoints;
- reactive-power / PF commands;
- grid-controller limits;
- command provenance;
- controller-induced loss / curtailment accounting.

Do not fold controller effects into Sandia conversion loss.

### S11 — physical LV AC collection

Build topology-aware three-phase LV collection only after AC voltage and P/Q/S
state are explicit.

Target physics:

- segment graph / from-node / to-node connectivity;
- conductor resistance using authoritative length / conductor data;
- current derived from admitted AC electrical state;
- `I²R` loss;
- voltage drop;
- downstream P/Q state;
- explicit unresolved handling when topology or conductor authority is missing.

Do not retain a static AC wiring percentage where physical network inputs are
available.

### S12 — transformer model

Preferred first transformer increment:

- explicit transformer equipment authority;
- no-load / core loss;
- load loss from factory-test or manufacturer data;
- loading based on admitted P/Q/S;
- independent energised / de-energised state;
- exact input/output power accounting.

Later refinements can add temperature and harmonic effects without changing the
basic transformer boundary.

### S13 — MV/HV collection and revenue-meter boundary

Extend the same network-element pattern through:

- MV feeders;
- collection transformers where applicable;
- main transformer;
- HV/export assets;
- explicit revenue-meter boundary.

Expected and actual values must refer to the same meter boundary before
benchmarking residuals are computed.

### S14 — benchmarking and causal loss attribution

Once the end-to-end expected physical chain reaches the meter boundary, build
the production-grade benchmarking layer around validated intermediate states.

Target outputs include:

- expected vs actual at aligned boundaries;
- telescoping loss waterfall;
- conversion, clipping, curtailment, cable, transformer, and network buckets;
- availability / underperformance residuals;
- model confidence and provenance;
- anomaly diagnostics without double counting physical losses.

## Deferred shared DC collection extension

The current S8-3 path supports explicit **direct per-string branch resistance**
to the parent MPPT input. It does **not** claim arbitrary DC collection-network
coverage.

Shared post-parallel conductors remain a separate required extension.

```text
String A -- Ra --\
                  +-- collection node -- Rh -- MPPT
String B -- Rb --/
```

A shared resistance `Rh` acts on total junction current and must not be copied
into each branch.

Return to generalized DC collection:

1. before claiming arbitrary DC network support; or
2. before benchmarking / activating a site whose as-built topology includes
   material shared post-parallel conductors.

Preferred future decomposition:

- explicit DC collection graph / network authority;
- parallel-junction equivalent I-V state;
- shared-edge voltage-drop transform;
- recursive / final MPPT-input solve.

## Optical and surface work still required

The canonical irradiance/optical chain is substantially implemented for the
currently validated fixed-table coverage, but enterprise completeness still
requires targeted extensions.

### Dynamic soiling

The production compatibility path still contains aggregate soiling percentage
behaviour. A canonical physical soiling layer should eventually provide
stateful accumulation / wash-off or measured soiling state with provenance.

### Snow

No canonical snow state model currently exists. Any future snow layer should be
explicitly stateful and independently validated rather than represented as an
arbitrary aggregate loss.

### Rear / bifacial coverage

Current rear modelling is validated for supported regular fixed-row /
infinite-sheds coverage. Future work may be needed for:

- arbitrary 3D rear obstruction;
- terrain and structures;
- row ends / irregular layouts;
- tracker geometries;
- module-scale rear non-uniformity.

### Bypass / partial-shading electrical physics

Still required for a complete partial-shading chain:

`module irradiance distribution → substring/bypass behaviour → module I-V → string I-V → multiple local maxima → MPPT tracking behaviour`

Do not substitute scalar mismatch or shading percentages for this mechanism.

## Production integration remains separate

The physical S8/S9 chain is validated but must not be silently mixed into the
legacy production calculation.

The compatibility path still includes aggregate effects such as:

- soiling;
- LID;
- static mismatch;
- DC wiring;
- legacy AC wiring / grid-cap behaviour.

Physical replacements should enter production only through a separately
reviewed migration proving:

- reference-plane alignment;
- no double counting;
- safe unresolved behaviour;
- equivalence where mechanisms overlap;
- clear fallback semantics for sites without required authority.

## Validation milestones

Every physical increment should include, as applicable:

- exact upstream replay / tamper resistance;
- focused unit physics tests;
- limiting-case tests;
- conservation and accounting closure;
- comparison with pvlib or another reference calculation;
- synthetic topology tests;
- provenance and deterministic ordering tests;
- full backend and frontend CI;
- only later, site SCADA / revenue-meter / PVsyst validation.

A site-data fit must not hide incorrect physics. When a reference and the model
disagree, first isolate whether the cause is inputs, topology, model assumptions,
implementation, or measurement quality.

## Multi-site and portfolio layer

Multi-site onboarding and portfolio management sit above independently validated
site-level physics. They must not be mixed into component-physics development.

Future capabilities may include:

- multiple independently configured sites;
- portfolio membership;
- expected-energy aggregation;
- actual-versus-expected performance;
- cross-site comparison;
- portfolio loss attribution;
- portfolio availability;
- fleet-wide anomaly detection;
- financial / revenue aggregation where appropriate.

Portfolio aggregation must never be used to conceal weak or unresolved
site-level physics.
