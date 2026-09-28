# Heliotelligence AI / Developer Handoff

This is the current recovery and architectural checkpoint for Heliotelligence,
an enterprise-grade, physics-first solar digital twin and benchmarking platform.
It does not replace live source, tests, Git history, CI evidence, or direct
inspection of current code.

## Recovery rule

When beginning from a new conversation or development session:

1. Query GitHub for the current `main` and fetch it.
2. Read this file.
3. Read `docs/architecture/physics-architecture.md`.
4. Read `docs/development/physics-roadmap.md`.
5. Read `docs/decisions/ADR-001-physics-first-electrical-migration.md`.
6. Read `docs/validation/physics-validation-strategy.md`.
7. Inspect open pull requests and recent merge commits.
8. Read the relevant implementation and tests.
9. Verify exact GitHub Actions CI for any PR being considered for merge.

Do not trust a SHA written in documentation as forever-current `HEAD`. Always
verify live GitHub state first.

## Source-of-truth order

When information disagrees, use this authority order:

1. current live source code;
2. current automated tests;
3. exact Git history / commit ancestry;
4. exact GitHub Actions CI;
5. repository architecture documentation;
6. implementation reports;
7. conversation summaries.

Never authorize a merge from an implementation report alone.

## Current canonical repository checkpoint

As of 2026-09-28, live `main` is:

`ad0828f42d5a5b733d79e70850df800dbc1aa5a2`

This is the merge commit of PR #68:

`S9-3B: add Sandia inverter power accounting`

Merge facts:

- reviewed head: `32d6637e5a98819a338cf988b3433f53d13ef812`;
- previous base: `def9d41024b79eb58e6d3c3252588e8ac9e37229`;
- merge commit: `ad0828f42d5a5b733d79e70850df800dbc1aa5a2`;
- merged at: `2026-09-28T21:53:53Z`.

Exact-main CI after merge:

- workflow: CI;
- run number: 179;
- run ID: `36489087563`;
- event: push;
- exact SHA: `ad0828f42d5a5b733d79e70850df800dbc1aa5a2`;
- Python: 3.13.15;
- `pvlib==0.15.2`;
- backend: `2565 passed in 130.39s`;
- frontend: success.

Before relying on this checkpoint in a later session, verify that `main` has not
advanced.

## Product / engineering position

Heliotelligence is beyond MVP. The target is an:

- enterprise-grade;
- physics-first;
- component-resolved;
- provenance-aware;
- defensively validated;
- measurement-boundary-aware

solar digital twin and benchmarking platform.

Do not replace physical mechanisms with arbitrary percentages when sufficient
physical inputs exist. Do not invent unavailable topology or equipment data.
Prefer explicit `unresolved`, `unknown`, or `not_applicable` states over guessed
values.

New physical capability should normally be introduced as narrow,
independently validated contracts and remain dormant from production until its
lower-level physics and handoff invariants are proven.

## Current validated physics chain

The validated backend now reaches the inverter AC power-accounting boundary:

```text
weather / QC
    ↓
solar geometry / irradiance decomposition
    ↓
front POA irradiance
    ↓
far-horizon + near-shading authority
    ↓
selected direct geometry + diffuse visibility
    ↓
IAM / front optical response
    ↓
rear irradiance / rear optical response
    ↓
bifacial electrical-equivalent irradiance
    ↓
spectral response
    ↓
canonical module electrical irradiance
    ↓
module electrical physics
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

## S8 electrical contracts

### S8-1 — physical string I-V

Validated homogeneous physical-string scaling from module I-V.

- source/reference plane: physical `string_terminal`;
- voltage and power scale with module count;
- current does not scale in series;
- unresolved upstream state is preserved;
- explicit zero-string state is distinct from missing authority.

### S8-2 — common-voltage MPPT and physical mismatch

Strings connected to the same MPPT are solved at a common voltage over their
shared valid voltage domain.

```text
I_MPPT(V) = Σ I_string(V)
P_MPPT(V) = V × I_MPPT(V)
P_common = max_V P_MPPT(V)
```

Physical mismatch is the difference between the independent-string maximum
counterfactual and the common-voltage result.

Mixed active / zero strings remain unresolved without an explicit blocking /
dark-string model.

### S8-3A — direct branch resistance authority

Explicit per-string direct branch series-loop resistance authority.

Rules:

- explicit zero resistance is a valid ideal path;
- absent resistance authority is unresolved;
- configured resistance is already total loop resistance and must not be
  automatically doubled;
- do not infer resistance from geometry, cable-plan labels, string IDs, zone
  IDs, aggregate loss percentages, or unrelated fields.

### S8-3B — resistive branch I-V transform

```text
V_mppt_input(I) = V_string_terminal(I) - I × R_branch
```

Current is unchanged. Negative-voltage curve portions are not silently clamped;
the validated non-negative voltage domain is preserved.

### S8-3C — MPPT-input common-voltage operating point

Runs common-voltage MPPT aggregation on already transformed MPPT-input string
curves. This establishes the defensible inverter DC input state for the
currently supported direct-branch topology.

## Electrical reference planes

Keep these physical planes distinct:

1. module terminals;
2. physical string source terminals;
3. branch/string cable output;
4. parallel collection junction;
5. shared homerun / feeder output;
6. inverter MPPT input terminals;
7. inverter conversion boundary / AC output.

Do not collapse them into a generic site DC value when intermediate state is
available.

## Deferred shared DC collection

The current S8-3 path supports explicit **direct per-string branch resistance**
to the parent MPPT input. It does **not** claim arbitrary DC collection-network
coverage.

For a shared post-parallel conductor, current is the sum of parallel branch
currents and the loss is based on that shared current. A shared resistance must
not be duplicated into every branch.

Future generalized DC collection should model explicit nodes and edges, for
example:

```text
String A -- Ra --\
                  +-- collection node -- Rh -- MPPT
String B -- Rb --/
```

Return to this extension:

1. before claiming arbitrary DC-network support; or
2. before benchmarking / activating a real site whose as-built topology has
   shared post-parallel conductors that materially affect inverter-terminal
   state.

## S9 inverter contracts

### S9-0 — inverter authority

Resolves explicit `inverter_id → CEC/SAM model` authority.

- exact model names only;
- missing authority remains unresolved;
- no inference from geometry, capacity, labels, or site heuristics;
- no conversion physics in this layer.

### S9-1 — DC operating envelope

Evaluates admitted MPPT-input DC state against explicit inverter voltage/current
limits.

- MPPT voltages remain independent;
- inverter-level `Idcmax` is not copied to every tracker;
- explicit tracker-current authority wins;
- a single populated MPPT may use inverter-level CEC `Idcmax`;
- multi-MPPT current capability remains unresolved without tracker-specific
  authority;
- this stage classifies; it does not clamp or re-solve the operating point.

### S9-2 — Sandia inverter conversion

Produces one physical inverter AC-available state.

- single populated MPPT uses the validated scalar Sandia primitive;
- multi-MPPT conversion retains independent tracker voltages and aggregates
  power only;
- tracker voltages are never averaged;
- tracker currents are never summed into a synthetic inverter input;
- `Paco` limiting and `Pnt` night tare are applied once per physical inverter.

### S9-3A — pre-Paco Sandia AC potential

Calculates the published Sandia pre-limit AC potential without applying a second
`Paco`, `Pnt`, or startup rule.

For multi-MPPT operation it retains each independent MPPT voltage and follows
the pinned pvlib multi-input weighting semantics.

Production code does not depend on pvlib private Sandia helpers. Private
`_sandia_eff` is used only as a pinned-version test oracle.

Below startup (`Pdc < Pso`), pre-limit conversion potential is resolved as
not-applicable rather than fabricated.

### S9-3B — conversion / clipping / tare power accounting

S9-3B performs accounting algebra only. It does not modify the physical
operating point or rerun Sandia.

For applicable rows:

```text
conversion_delta = Pdc - Praw
conversion_loss = max(conversion_delta, 0)
conversion_gain = max(-conversion_delta, 0)
clipping_loss = Praw - Pac
net_delta = Pdc - Pac
```

Central closure:

```text
Pdc + conversion_gain - conversion_loss - clipping_loss = Pac
```

Important semantics:

- `Praw > Paco` means clipping is active;
- `Praw == Paco` is the nameplate boundary with zero clipping loss;
- empirical `Praw > Pdc` is preserved as an explicit model gain term and is not
  claimed to represent physical energy creation;
- negative `Praw` above startup remains conversion accounting, not night tare;
- below startup, tare is accounted separately as `Pnt`;
- there is intentionally no generic `total_inverter_loss_w` field.

## Legacy production compatibility path

The validated S8/S9 chain is not automatically equivalent to the production
runtime path.

The legacy `calculate_dc_power()` compatibility path still retains aggregate
percentage effects including:

- soiling;
- LID;
- static mismatch;
- DC wiring.

Legacy AC wiring / grid-cap behaviour also remains separate from the dormant
component-resolved migration until explicitly replaced.

Do not silently apply validated physical losses and legacy percentages together.
Production integration must be a separately reviewed migration with no double
counting.

## Optical / surface status

The canonical fixed-table optical chain substantially covers:

- solar geometry and irradiance decomposition;
- direct-geometry shading authority;
- diffuse visibility;
- IAM / optical response;
- fixed-row rear irradiance / rear optical response;
- bifacial electrical-equivalent irradiance;
- spectral response.

Current limitations remain explicit:

- rear optics are validated for supported regular fixed-row / infinite-sheds
  coverage, not arbitrary 3D rear obstruction;
- dynamic physical soiling is not yet canonical;
- snow is not yet implemented as a physical state model;
- bypass-diode / substring electrical behaviour and multiple local maxima remain
  future electrical work.

## Next build

The next electrical increment is:

### S9-4A — explicit inverter AC capability authority

This should establish static AC-side equipment authority before any AC-network
physics is built.

Preferred explicit equipment fields, where authoritative data exists:

- nominal AC line voltage;
- phase configuration;
- rated apparent power `Smax`;
- reactive-power limits or capability curve;
- supported power-factor range;
- parameter source;
- confidence.

Rules:

- do not assume `Smax == Paco` unless authoritative equipment data establishes
  that equivalence;
- do not infer Q capability from active-power rating alone;
- missing authority remains unresolved;
- S9-4A classifies equipment capability only; it does not dispatch, curtail, or
  alter S9-3B power.

Planned follow-ons:

- **S9-4B:** inverter `P/Q/S` capability envelope;
- **S9-4C:** thermal derating only where explicit manufacturer curves / thermal
  authority exist;
- **S10:** plant-controller / dispatch boundary;
- **S11:** physical LV AC collection;
- **S12:** transformer model;
- **S13:** MV/HV collection and revenue-meter boundary;
- **S14:** production-grade benchmarking and causal loss attribution.

AC cabling should not be built before AC voltage, phase configuration, and
`P/Q/S` state exist because current depends on those quantities.

## Non-negotiable project rules

- Use physics-first modelling where a mechanism can reasonably be calculated.
- Preserve physical reference planes.
- Do not replace one arbitrary percentage with another disguised approximation.
- Preserve legacy behaviour until its replacement is independently validated.
- Prefer focused PRs with exact admission, limiting-case, closure, provenance,
  and equivalence tests.
- Do not invent unavailable physical topology or equipment authority.
- Missing authority and explicit zero are different states.
- Do not average independent MPPT voltages.
- Do not duplicate inverter limits per tracker.
- Do not apply shared feeder resistance as if it were independent branch
  resistance.
- Do not integrate new physical layers into production before validating their
  contracts and double-counting boundaries.

## Reference site: Bracon Ash

Bracon Ash is a reference/onboarded site, not a template for other sites.

Critical unresolved facts remain:

- no physical MPPT-to-string map is currently known;
- no string-to-inverter assignment should be inferred from aggregate counts;
- no physical cable layout is established by current configuration;
- no transformer or MV/HV collection topology is established by current
  configuration.

Do not infer any of these from group IDs, counts, positions, capacities, or
labels. See `docs/sites/bracon-ash.md`.

## Dependency lock

The validated physics environment is pinned to:

`pvlib==0.15.2`

Do not upgrade pvlib as part of an unrelated physics increment. The pin exists
because version changes have already altered exact optical expectations.

## Validation expectation for future PRs

At minimum, independently verify:

- exact base and head SHAs;
- changed-file scope;
- exact replay / tamper resistance where upstream result objects are admitted;
- focused new-stage tests;
- adjacent S8/S9 regressions;
- broader electrical regressions;
- optical/rear regressions when dependencies may interact;
- full backend unit suite;
- frontend build;
- dependency version;
- Ruff / strict mypy on changed files where applicable;
- syntax compilation and `git diff --check`;
- fresh CI on the exact synthetic merge or exact merged `main`.

Never merge solely because a local implementation report says tests passed.

## Operational scheduler note

`RUN_SCHEDULER` controls in-process APScheduler startup. Staging has been
validated with `RUN_SCHEDULER=false`, but the long-term dedicated scheduler /
worker architecture remains separate operational work.

Do not mix scheduler migration with the physics roadmap unless there is a clear
runtime dependency.

Never put secrets, credentials, or secret values in repository documentation.
