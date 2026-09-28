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

## Current validated electrical chain

As of 2026-09-28, live `main` is:

`def9d41024b79eb58e6d3c3252588e8ac9e37229`

The canonical validated chain is now:

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
- **S9-3B — validated / ready to merge:** PR #68, head
  `32d6637e5a98819a338cf988b3433f53d13ef812`. It separates conversion
  loss, empirical conversion gain, Paco clipping, and below-startup tare while
  preserving exact accounting closure. It is not yet on `main` at the time of
  this roadmap update.

## Immediate next build after PR #68 merges

The next priority should be **AC-side inverter capability authority and P/Q/S
state**, not AC cabling yet.

Physical AC collection loss depends on current, and AC current depends on
voltage, phase configuration, active power, and reactive/apparent power. Building
LV cable physics before that state exists would either force hidden assumptions
or recreate another percentage-loss layer.

### S9-4A — explicit inverter AC capability authority

Introduce a narrow static authority layer for AC-side inverter capability.

Preferred explicit fields, where available from manufacturer / equipment data:

- nominal AC line voltage;
- phase configuration;
- rated apparent power `Smax`;
- reactive-power limits or capability curve;
- supported power-factor range;
- parameter source and confidence.

Rules:

- do not infer `Smax = Paco` unless an authoritative equipment source explicitly
  establishes that equivalence;
- do not infer Q capability from active-power rating alone;
- missing capability authority must remain unresolved, not guessed;
- this stage should classify authority only and must not dispatch or curtail.

### S9-4B — inverter P/Q/S capability envelope

Consume the admitted active-power state and explicit S9-4A authority to expose:

- `P` available at the inverter AC boundary;
- requested / commanded `Q` where explicitly supplied;
- `S = sqrt(P^2 + Q^2)`;
- power factor where defined;
- apparent-power headroom;
- Q/PF capability flags;
- explicit unresolved state when command or equipment authority is unavailable.

This stage should evaluate capability only. It should **not** apply plant-control
curtailment or silently reduce active power to satisfy a reactive-power request.
Any constrained dispatch / control solve belongs in a later controller stage.

### S9-4C — inverter thermal derating, only with explicit authority

Add thermal derating only where defensible manufacturer curves or validated
operating-temperature authority exist.

Potential inputs include:

- ambient or inverter temperature;
- manufacturer derating curve / breakpoint table;
- temperature-dependent active/apparent capability;
- parameter source and confidence.

Do not invent derating curves from nameplate power or ambient temperature.
If the required authority does not exist for a site, this layer remains
not-applicable / unresolved and must not block the validated static Sandia path.

## Next system stages after inverter capability

### S10 — plant-controller / dispatch boundary

Separate **available AC** from **dispatched AC**.

This layer should own:

- active-power curtailment;
- export setpoints;
- reactive-power / PF commands;
- grid-controller limits;
- explicit command provenance;
- controller-induced loss / curtailment accounting.

Do not fold these controls into Sandia conversion loss.

### S11 — physical LV AC collection

Build topology-aware three-phase LV collection only after AC voltage and P/Q/S
state are explicit.

Target physics:

- segment graph / from-node / to-node connectivity;
- conductor resistance with authoritative length / conductor data;
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
the production-grade benchmarking layer around the validated intermediate
states.

Target outputs include:

- expected vs actual at aligned boundaries;
- telescoping loss waterfall;
- conversion, clipping, curtailment, cable, transformer, and network buckets;
- availability / underperformance residuals;
- model confidence and provenance;
- anomaly diagnostics without double counting physical losses.

## Deferred DC collection extension

The current S8-3 path supports explicit **direct per-string branch resistance**
to the parent MPPT input. It does **not** claim arbitrary DC collection-network
coverage.

Shared post-parallel conductors remain a separate required extension.

Example physical topology:

```text
String A -- Ra --\
                  +-- collection node -- Rh -- MPPT
String B -- Rb --/
```

The shared feeder loss depends on total junction current and must not be copied
into each string branch.

Return to the shared-collection build when either condition becomes true:

1. before Heliotelligence claims arbitrary DC collection-network support; or
2. before benchmarking / activating a real site whose as-built topology has
   shared post-parallel conductors that materially affect inverter-terminal
   state.

Preferred future structure:

- explicit DC collection graph authority;
- parallel-junction equivalent I-V;
- shared-edge resistive transform;
- recursive / final MPPT-input solve;
- exact power and reference-plane closure.

This deferred extension does not block the current inverter and AC-side
capability sequence for supported direct-branch topology.

## Optical / environmental work still outstanding

The canonical irradiance/optical chain is substantially ahead of the original
roadmap, but several enterprise-grade extensions remain:

- time-varying physical or measured soiling;
- arbitrary 3D near-object shading;
- terrain / row-end / irregular-row rear shading;
- tracker-specific rear and shading behaviour;
- module/submodule nonuniform irradiance where bypass-diode modelling requires
  it;
- evidence-driven spectral refinement where site data justifies it.

Soiling remains a legacy aggregate approximation and must not be presented as a
canonical physical surface-state model yet.

## Electrical enhancements still outstanding

After the current inverter/AC path is established, continue with:

- bypass-diode modelling;
- partial-shading electrical behaviour;
- multiple local maxima;
- explicit MPPT tracking dynamics where required;
- shared DC collection topology;
- inverter thermal derating where explicit authority exists;
- P/Q/S capability and controller dispatch;
- physical LV/MV/HV collection;
- transformer losses;
- revenue-meter boundary;
- production benchmarking and causal loss attribution.

## Validation milestones

Every physical increment should include, as applicable:

- focused unit physics tests;
- limiting-case and exact-boundary tests;
- conservation / power-balance closure;
- equivalence against an authoritative reference where one exists;
- strong replay admission from the immediately upstream canonical state;
- synthetic topology tests;
- immutable inputs and independently owned outputs;
- exact model / scope / coverage / parameter-source provenance;
- full adjacent regression suites;
- full backend CI on the exact synthetic merge;
- only later, comparison with site SCADA, manufacturer data, and PVsyst.

A site-data fit must not be used to hide incorrect physics. When a reference and
the model disagree, first isolate whether the cause is inputs, topology, model
assumptions, implementation, or measurement quality.

## Multi-site and portfolio layer

Multi-site onboarding and portfolio management remain platform layers above
independently validated site-level physics. They must not be mixed into the
component-level electrical migration.

Future capabilities may include:

- multiple independently configured sites;
- portfolio membership;
- portfolio expected-energy aggregation;
- portfolio actual-versus-expected performance;
- cross-site comparison;
- portfolio loss attribution;
- portfolio availability;
- fleet-wide anomaly detection; and
- portfolio financial or revenue aggregation where appropriate.

The repository already models physics in a site-scoped form, but it does not
currently establish a `PortfolioConfig`, organisation hierarchy, portfolio
dashboard, or portfolio aggregation implementation.
