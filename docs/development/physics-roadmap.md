# Physics Development Roadmap

This roadmap describes dependency order, not a fixed pull-request numbering scheme. Stage and PR numbers may change as evidence, data authority, and review boundaries evolve.

Source-of-truth order for implementation status is:

1. live source code;
2. automated tests;
3. Git history and exact commit ancestry;
4. exact GitHub Actions CI;
5. architecture documentation;
6. implementation reports and conversation notes.

The project is beyond MVP. New physics should remain narrow, provenance-aware, explicit about unresolved state, and dormant from production until independently validated.


## Current canonical checkpoint

As of 2026-10-03, live `main` is:

`a39026379df00e5756ac2690977e005b169f920e`

This is the merge commit of PR #73, S9-4B inverter P/Q/S capability-state evaluation.

Final reviewed pre-merge CI for PR #73:

- run #189;
- run ID `37118718668`;
- synthetic merge `88e80f751be3ffff10265fe6d8d4a7d27a5a8154`;
- Python 3.13.15;
- `pvlib==0.15.2`;
- backend `2663 passed in 122.38s`;
- frontend success.

No separate post-merge workflow run was associated with the merge commit when this roadmap was updated.

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

parallel static branch:
S9-4A explicit inverter AC capability authority
```

Status by stage:

- **S8-1 — merged:** homogeneous physical string I-V scaling.
- **S8-2 — merged:** source-plane common-voltage MPPT and IV-consistent mismatch.
- **S8-3A — merged:** explicit direct string-branch resistance authority.
- **S8-3B — merged:** string-terminal to MPPT-input resistive I-V transform.
- **S8-3C — merged:** MPPT-input common-voltage operating point.
- **S9-0 — merged:** exact inverter ID → CEC/SAM Sandia authority.
- **S9-1 — merged:** DC voltage/current envelope classification with explicit tracker-current authority where required.
- **S9-2 — merged:** single- or multi-MPPT Sandia conversion for one physical inverter, without voltage averaging or duplicated inverter limits.
- **S9-3A — merged:** model-native Sandia pre-Paco AC potential.
- **S9-3B — merged:** conversion / empirical gain / Paco clipping / below-startup tare accounting with exact closure.
- **S9-4A — merged:** static explicit inverter AC capability authority for voltage, voltage basis, phase, `Smax`, optional fixed Q limits, provenance and confidence.
- **S9-4B — merged:** timestamped explicit-Q P/Q/S capability-state evaluation with exact S9-3B/S9-4A replay, partial-authority semantics, known-violation preservation, and no control action.


## Immediate next build

The next priority is **S9-4C — explicit inverter thermal-derating authority**.

Do not jump directly to thermal power modification or AC cabling.

### S9-4C — inverter thermal-derating authority

This increment should establish static / manufacturer-backed authority only.

Candidate fields should be determined from authoritative manufacturer data and may include:

- temperature quantity / reference used by the derating specification;
- valid temperature domain;
- ordered breakpoints or curve representation;
- active-power limit versus temperature;
- apparent-power limit versus temperature;
- reactive capability versus temperature only where explicitly documented;
- interpolation and boundary semantics;
- source and confidence.

Non-negotiable rules:

- no derating curve inferred from module-cell temperature;
- no generic ambient-temperature coefficient invented for the inverter;
- no `Paco` or `Smax` scaling used as a substitute for manufacturer thermal data;
- absent authority remains unresolved;
- explicit zero/no-derating authority must remain distinct from missing authority;
- the authority layer must not alter S9-4B P/Q/S state.

### Planned S9-4D — temperature-dependent capability evaluation

After S9-4C authority exists, a separate narrow evaluator should combine:

```text
S9-4B admitted capability/request state
+
explicit inverter temperature state
+
S9-4C thermal-derating authority
```

and calculate the temperature-dependent available capability without dispatching the inverter.

Keep thermal capability evaluation separate from plant-controller curtailment. If evidence shows S9-4C can safely include evaluation without widening the contract, re-review that decision before implementation rather than silently combining the layers.

## Next system stages after inverter capability

### S10 — plant-controller / dispatch boundary

Separate **available AC** from **dispatched AC**.

This layer should own:

- active-power curtailment;
- export setpoints;
- reactive-power / PF commands;
- grid-controller limits;
- command provenance;
- controller-induced curtailment accounting.

Do not fold controller effects into Sandia conversion loss.

### S11 — physical LV AC collection

Build topology-aware LV collection only after AC voltage and P/Q/S state are explicit.

Target physics:

- segment graph / from-node / to-node connectivity;
- conductor resistance using authoritative length / conductor data;
- current derived from admitted AC electrical state;
- `I²R` loss;
- voltage drop;
- downstream P/Q state;
- explicit unresolved handling when topology or conductor authority is missing.

Do not retain a static AC wiring percentage where physical network inputs are available.

### S12 — transformer model

Preferred first transformer increment:

- explicit transformer equipment authority;
- no-load / core loss;
- load loss from factory-test or manufacturer data;
- loading based on admitted P/Q/S;
- independent energised / de-energised state;
- exact input/output power accounting.

### S13 — MV/HV collection and revenue-meter boundary

Extend the same network-element pattern through MV feeders, collection transformers where applicable, main transformer, HV/export assets, and the explicit revenue-meter boundary.

Expected and actual values must refer to the same meter boundary before benchmarking residuals are computed.

### S14 — benchmarking and causal loss attribution

Once the end-to-end expected physical chain reaches the meter boundary, build production-grade benchmarking around validated intermediate states.

Target outputs include expected vs actual at aligned boundaries, telescoping loss waterfalls, conversion/clipping/curtailment/cable/transformer/network buckets, availability/underperformance residuals, model confidence, provenance, and anomaly diagnostics without double counting.


## S9-4A / S9-4B merged capability semantics

S9-4A establishes static inverter-level equipment facts only.

Resolved S9-4A fields include:

- nominal AC voltage;
- voltage basis: `line_to_line`, `line_to_neutral`, or `single_phase_terminal`;
- phase configuration: `single_phase` or `three_phase`;
- rated apparent power `Smax`;
- optional fixed `Qmin/Qmax` pair;
- parameter source and confidence.

S9-4B then evaluates timestamped operating requests without control action:

```text
P = admitted S9-3B p_ac_available_w
Q = explicit timestamped request
S = hypot(P, Q)
```

S9-4B semantics:

- positive Q = injection; negative Q = absorption;
- missing Q != explicit Q=0;
- `S <= Smax` is always evaluated where P/Q are admitted;
- fixed Q limits are evaluated only when S9-4A supplies them;
- missing fixed-Q authority yields partial capability rather than a false pass;
- `|P| > Smax` is a definitive violation even with missing Q;
- full static capability authority is inherited from S9-4A independently of request availability;
- night-tare/non-producing rows are resolved not-applicable;
- no dispatch, P curtailment, Q clamping, AC current, thermal derating, wiring or transformer modelling occurs.

Safety rules across both stages:

- no `Smax = Paco` inference;
- no AC voltage inference from CEC/SAM `Vac`;
- no inference from `pnom_kwac`, grid/export limits, topology labels, model refs, groups, MPPT/string counts, or legacy AC wiring loss;
- `three_phase + single_phase_terminal` is invalid;
- missing fixed-Q authority and explicit zero fixed-Q capability remain distinct.

## Deferred shared DC collection extension

The current S8-3 path supports explicit **direct per-string branch resistance** to the parent MPPT input. It does **not** claim arbitrary DC collection-network coverage.

Shared post-parallel conductors remain a separate required extension.

```text
String A -- Ra --\
                  +-- collection node -- Rh -- MPPT
String B -- Rb --/
```

A shared resistance `Rh` acts on total junction current and must not be copied into each branch.

Return to generalized DC collection:

1. before claiming arbitrary DC network support; or
2. before benchmarking / activating a site whose as-built topology includes material shared post-parallel conductors.

## Optical and surface work still required

Enterprise completeness still requires targeted extensions including dynamic physical/measured soiling, snow, arbitrary 3D rear obstruction/terrain/tracker coverage, and substring/bypass-diode partial-shading electrical behaviour.

The intended partial-shading chain remains:

`module irradiance distribution → substring/bypass behaviour → module I-V → string I-V → multiple local maxima → MPPT tracking behaviour`

Do not substitute scalar mismatch or shading percentages for this mechanism.

## Production integration remains separate

The physical S8/S9 chain is validated but must not be silently mixed into the legacy production calculation.

The compatibility path still includes aggregate effects such as soiling, LID, static mismatch, DC wiring, and legacy AC wiring / grid-cap behaviour.

Physical replacements should enter production only through a separately reviewed migration proving reference-plane alignment, no double counting, safe unresolved behaviour, equivalence where mechanisms overlap, and clear fallback semantics for sites without required authority.

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
