# Heliotelligence AI / Developer Handoff

This is a recovery and architectural checkpoint document for Heliotelligence,
an enterprise-grade, physics-first solar digital twin and benchmarking platform.
It does not replace the repository, automated tests, Git history, CI evidence,
or direct inspection of current code.

## Recovery rule

When beginning from a new conversation or development session:

1. Query Git for the current `main`, then fetch it.
2. Read this file.
3. Read `docs/architecture/physics-architecture.md`.
4. Read `docs/development/physics-roadmap.md`.
5. Inspect open pull requests and recent merge commits.
6. Read the relevant implementation and tests.
7. Verify exact GitHub Actions CI for any PR being considered for merge.
8. Treat current source, tests, Git history, and exact CI as authoritative when
   documentation, implementation reports, or remembered conversation context
   disagrees.

Do not trust a SHA written in documentation as forever-current `HEAD`. Always
query Git first.

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

## Current validated repository checkpoint

As of 2026-09-28, live `main` is:

`def9d41024b79eb58e6d3c3252588e8ac9e37229`

This is the merge commit of PR #67:

`S9-3A: add Sandia pre-limit AC potential`

Current open physics PR:

- PR #68 — `S9-3B: add Sandia inverter power accounting`
- Branch: `feature/inverter-power-accounting`
- Base: `def9d41024b79eb58e6d3c3252588e8ac9e37229`
- Reviewed head: `32d6637e5a98819a338cf988b3433f53d13ef812`
- Status: independently validated / ready to merge / still unmerged at the
  time of this documentation update.
- Fresh CI: run #178, synthetic merge
  `cde5f9436374fe33f4c656b1620df65a66050c00`, frontend success, backend
  `2565 passed`, Python 3.13.15, `pvlib==0.15.2`.

Before using any of these values, verify that live GitHub state has not moved.

## Product / engineering position

Heliotelligence is beyond MVP.

The target is an:

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

New physical capability should normally be introduced as narrow, independently
validated contracts and remain dormant from production until its lower-level
physics and handoff invariants are proven.

## Current validated physics chain

The canonical backend physics chain now reaches the inverter AC accounting
boundary.

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
S8-3B branch resistance I-V transform
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
        (validated PR #68; not yet on main at this checkpoint)
```

## S8 electrical state

### S8-1 — physical string I-V

Validated homogeneous physical-string scaling from module I-V.

Key properties:

- source/reference plane: physical `string_terminal`;
- voltage and power scale with module count;
- current does not scale in series;
- unresolved upstream state is preserved;
- explicit zero-string state is distinct from missing authority.

### S8-2 — common-voltage MPPT and physical mismatch

Strings connected to the same MPPT are solved at a common voltage over their
shared valid voltage domain.

Conceptually:

`I_MPPT(V) = Σ I_string(V)`

`P_MPPT(V) = V × I_MPPT(V)`

`P_common = max_V P_MPPT(V)`

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
- no inference from geometry, cable-plan labels, string IDs, zone IDs, aggregate
  loss percentages, or unrelated fields.

### S8-3B — resistive branch I-V transform

Transforms each physical string source curve to the parent MPPT-input plane:

`V_mppt_input(I) = V_string_terminal(I) - I × R_branch`

Current is unchanged.

Negative-voltage curve portions are not silently clamped; the non-negative
valid domain is preserved according to the validated transform contract.

### S8-3C — MPPT-input common-voltage operating point

Runs common-voltage MPPT aggregation on the already transformed MPPT-input
string curves.

This establishes the physically defensible inverter DC input state for the
currently supported direct-branch topology.

## Electrical reference planes

Keep these physical reference planes distinct:

1. module terminals;
2. physical string source terminals;
3. branch/string cable output;
4. parallel collection junction;
5. shared homerun / feeder output;
6. inverter MPPT input terminals;
7. inverter conversion boundary / AC output.

Do not collapse these boundaries into a generic site DC power value when the
intermediate state is available.

## Deferred shared DC collection

The current S8-3 path supports explicit **direct per-string branch resistance**
to the parent MPPT input.

It does **not** yet claim arbitrary DC collection-network coverage.

A shared post-parallel conductor must be treated as a separate network element.
For example:

```text
String A -- Ra --\
                  +-- collection node -- Rh -- MPPT
String B -- Rb --/
```

The shared resistance `Rh` carries aggregate current and therefore cannot be
copied into each branch.

Required future extension should use an explicit collection-node / edge graph
or equivalent authority, then solve branch junction state and shared feeder
voltage drop recursively.

Return to this work:

1. before claiming arbitrary DC collection-network support; or
2. before benchmarking / activating a real site whose as-built topology
   contains material shared post-parallel conductors.

Do not invent shared topology from site geometry or naming conventions.

## S9 inverter state

### S9-0 — inverter equipment authority

Resolves explicit inverter ID to exact CEC/SAM equipment authority.

Rules:

- exact model references only;
- missing reference remains unresolved;
- unknown model reference raises;
- no equipment inference from site labels or aggregate ratings.

### S9-1 — DC operating-envelope classification

Classifies the admitted MPPT-input DC state against authoritative inverter
voltage/current limits.

Important rule:

- CEC `Idcmax` is inverter-row level authority, not automatically a per-MPPT
  current limit;
- for multi-MPPT operation, explicit tracker current-limit authority is
  required unless a single populated MPPT makes inverter-level `Idcmax`
  unambiguous;
- do not divide or duplicate inverter-level current authority across trackers;
- this stage classifies only and does not clamp or re-solve the operating point.

### S9-2 — Sandia inverter conversion

Converts admitted DC state into one physical inverter AC available state.

For multi-MPPT inverters:

- each independent MPPT voltage is preserved;
- DC power is additive;
- voltage is never averaged;
- tracker currents are not summed into a synthetic inverter input;
- the inverter is not duplicated once per tracker;
- Sandia limits are applied once per physical inverter.

Below startup, one inverter night-tare result is used rather than attempting a
multi-input divide-by-zero path.

### S9-3A — Sandia pre-Paco AC potential

Provides the model-native pre-limit Sandia AC potential so conversion behaviour
can be separated from Paco clipping.

Production code implements the published Sandia polynomial directly and does
not depend on pvlib private helper names. Pinned private `_sandia_eff` is only a
test oracle.

At / above startup:

`Pac_available = min(Paco, Pac_pre_limit)`

Below startup:

`Pac_available = -Pnt`

A finite negative pre-limit AC result above startup is preserved exactly; it is
not clamped to `-Pnt`.

### S9-3B — inverter power accounting

PR #68 is independently validated and ready to merge but remains outside
`main` at this checkpoint.

For applicable conversion rows:

`conversion_delta = Pdc - Praw`

`conversion_loss = max(conversion_delta, 0)`

`conversion_gain = max(-conversion_delta, 0)`

`clipping_loss = Praw - Pac`

`net_dc_to_available_ac_delta = Pdc - Pac`

Central closure:

`Pdc + conversion_gain - conversion_loss - clipping_loss = Pac`

Important semantics:

- `Praw > Paco` means clipping is active;
- `Praw == Paco` is the exact AC nameplate boundary with zero clipping loss;
- `Praw > Pdc` is preserved as an empirical Sandia-model conversion-gain term,
  not silently clamped;
- a negative `Praw` above startup is conversion accounting, not night tare;
- below startup only Sandia tare consumption is accounted; conversion/clipping
  components are not applicable;
- no generic `total_inverter_loss_w` is introduced because the signed boundary
  delta has different physical meaning across these regimes.

S9-3B is accounting only. It does not alter any physical DC or AC operating
point.

## Dependency lock

The project currently pins:

`pvlib==0.15.2`

Do not upgrade it casually. The pin protects validated exact behaviour,
including dependency-sensitive optical and inverter tests.

## Current temporary / compatibility behaviour

The legacy aggregate `calculate_dc_power()` path still retains compatibility
loss percentages including:

`soiling → LID → static mismatch → DC wiring`

This compatibility path is not the canonical physical S8/S9 chain.

Do not delete legacy percentages merely because a new physical primitive exists.
Production integration must happen only when the replacement contract, data
authority, reference plane, and regression behaviour are explicitly validated.

Soiling is still legacy aggregate rather than a canonical time-varying physical
surface model.

## Rear / optical scope

The rear optical chain is validated for supported regular fixed-row,
infinite-sheds-style coverage.

Do not describe it as a generic enterprise rear-shading engine.

Still outside current validated coverage:

- arbitrary 3D rear obstruction;
- terrain / structures;
- tracker geometry;
- row ends / irregular layouts / sloped structures;
- module-scale rear nonuniformity.

## Next physics build after PR #68

After PR #68 is merged and its merge SHA is independently verified, the next
recommended increment is:

### S9-4A — explicit inverter AC capability authority

Build a narrow static authority layer for AC-side inverter capability.

Preferred explicit equipment fields, when authoritative data exists:

- nominal AC line voltage;
- phase configuration;
- rated apparent power `Smax`;
- reactive-power limit / capability curve;
- supported power-factor range;
- parameter source;
- confidence.

Rules:

- do not infer `Smax = Paco` unless equipment authority explicitly establishes
  that equivalence;
- do not infer Q capability from active-power rating alone;
- missing capability authority remains unresolved;
- S9-4A classifies authority only and does not dispatch or curtail.

### S9-4B — inverter P/Q/S capability envelope

Consume admitted active-power state plus S9-4A authority and expose, where
supported:

- active power `P` at the inverter AC boundary;
- explicit reactive-power request / command `Q`;
- apparent power `S = sqrt(P² + Q²)`;
- power factor where defined;
- apparent-power headroom;
- Q / PF capability flags;
- explicit unresolved state when required command or equipment authority is
  absent.

This stage evaluates capability only. It must not silently reduce active power
to satisfy a Q request and must not implement plant-controller dispatch.

### S9-4C — inverter thermal derating

Add only when manufacturer derating curves or equivalent explicit authority
exist.

Do not invent temperature derating from nameplate values or ambient temperature.
Sites without such authority should remain not-applicable / unresolved without
blocking the validated static Sandia path.

## Subsequent target stages

After inverter AC capability:

### S10 — plant-controller / dispatch boundary

Separate `available AC` from `dispatched AC`.

Own:

- active-power curtailment;
- export setpoints;
- reactive-power / PF commands;
- controller limits;
- command provenance;
- controller-induced curtailment accounting.

Do not mix controller actions into inverter conversion loss.

### S11 — physical LV AC collection

Only build AC cable physics after AC voltage, phase, and P/Q/S state are
explicit.

Target:

- explicit AC segment topology;
- authoritative conductor length / resistance data;
- current derived from admitted AC state;
- three-phase `I²R` loss;
- voltage drop;
- downstream P/Q state;
- unresolved state when required network authority is absent.

### S12 — transformer model

Preferred first increment:

- explicit transformer authority;
- no-load / core loss;
- load loss from factory-test / manufacturer data;
- loading based on admitted P/Q/S;
- energised / de-energised state;
- exact input/output accounting.

### S13 — MV/HV collection and meter boundary

Extend the same explicit network-element pattern through MV feeders,
transformers, export assets, and the revenue-meter boundary.

Expected and actual values must be aligned to the same measurement boundary
before benchmarking residuals are calculated.

### S14 — benchmarking and causal loss attribution

Once the expected physical chain reaches the meter boundary, build the
production-grade benchmarking layer around the validated intermediate states.

Target outputs:

- expected vs actual at aligned boundaries;
- telescoping loss waterfall;
- conversion, clipping, curtailment, cable, transformer, and network buckets;
- availability / underperformance residuals;
- confidence and provenance;
- anomaly diagnostics without double counting.

## Non-negotiable project rules

- Use physics-first modelling where a mechanism can reasonably be calculated.
- Do not replace one arbitrary loss percentage with another disguised
  approximation.
- Preserve exact electrical reference planes.
- Once resistance participates in the voltage-dependent DC network, solve it in
  the operating-point physics; do not append an independent percentage loss.
- Preserve legacy behaviour until its physical replacement is independently
  validated and deliberately integrated.
- Prefer focused PRs with equivalence, closure, and physics-invariant tests.
- Do not invent unavailable physical topology or equipment authority.
- Missing authority and explicit zero are different states.
- Bracon Ash MPPT/string mapping is unknown and must not be invented.
- Never generalize Bracon Ash-specific values to another site unless that
  site's configuration establishes them.
- Do not infer electrical topology from geometry, IDs, labels, cable-plan
  names, capacities, arbitrary defaults, or aggregate loss percentages.
- Do not integrate new physical layers into production before validating their
  lower-level contracts.
- Do not average independent MPPT voltages.
- Do not duplicate a physical inverter once per MPPT.
- Do not duplicate shared post-parallel conductor resistance into branch paths.
- Do not label empirical model accounting terms as measured heat or physical
  energy dissipation without evidence.

## Reference site: Bracon Ash

Bracon Ash is a development reference site, not a template whose equipment,
topology, grid, or loss values should be assumed for future sites.

See [`docs/sites/bracon-ash.md`](sites/bracon-ash.md) for established site facts
and known data gaps.

In particular:

- no authoritative physical MPPT-to-string mapping is currently known;
- that mapping must not be inferred from string IDs, inverter labels, physical
  position, module count, or aggregate capacity arithmetic.

Any physics stage requiring unavailable Bracon Ash authority must remain
unresolved or use a clearly separate compatibility path.

## Validation discipline

For each new physical increment, run as applicable:

- focused new-stage tests;
- immediately upstream-stage regression;
- inverter / electrical regression when near inverter boundaries;
- complete S8 regression;
- broader electrical / recent-stage regression;
- optical / rear regression to prove no upstream perturbation;
- dependency-sensitive optical tests;
- full backend unit suite;
- changed-file Ruff;
- strict mypy on the new production / test files where practical;
- syntax compilation;
- `git diff --check`.

For PR review, independently verify:

- exact base and head SHAs;
- branch staleness / ancestry;
- exact changed files;
- scope;
- contract / model / coverage identifiers;
- state semantics;
- reference planes;
- tamper resistance;
- CI synthetic merge SHA;
- Python and pinned dependency versions;
- exact backend result.

Do not merge unless explicitly authorized.

## Known operational issue: in-process scheduler

`RUN_SCHEDULER` explicitly controls whether a FastAPI process configures and
starts APScheduler. Its default remains `true` for backward compatibility.
The request-serving staging API was validated with in-process scheduling
disabled through `RUN_SCHEDULER=false`.

Production and other runtimes that do not explicitly set the gate retain the
previous in-process scheduler behaviour. Docker can run multiple Uvicorn
workers and Cloud Run can run multiple service instances, so duplicate
scheduled-job execution remains a risk wherever the gate is enabled.

The long-term scheduler architecture is still separate from the physics roadmap
and has not been fully solved.

## Application logging checkpoint

Application-specific logging for the `heliotelligence` namespace is active.
`settings.log_level` is consumed, application INFO lifecycle records are
observable, and Uvicorn/root logging is not globally replaced.

## Historical staging checkpoint

The following values are historical operational evidence, not current physics
`main`:

- Project: `heliotelligence-staging`.
- Validated Git SHA: `e3186f288fb8a0da723809648c306e2527acb926`.
- Validated Cloud Build: `c5a8788c-62cb-499c-b2e5-7902ee4fe0d6`.
- Validated image: `api:e3186f2` at digest
  `sha256:1c101683cc35310a89b60e2d521ea138fc00fc62e2216625f9931dea5dc42a2d`.
- Validated Cloud Run revision: `heliotelligence-api-staging-00004-4bn`.
- Runtime configuration: `RUN_SCHEDULER=false`, `APP_ENV=staging`.

Always target staging explicitly for staging commands. Do not rely on local CLI
defaults.

Never put secrets, credentials, or secret values in repository documentation.
