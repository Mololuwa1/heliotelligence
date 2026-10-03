# Heliotelligence AI / Developer Handoff

This is the current recovery and architectural checkpoint for Heliotelligence, an enterprise-grade, physics-first solar digital twin and benchmarking platform.

It does not replace live source, tests, Git history, CI evidence, or direct inspection of current code.

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

Do not trust a SHA written in documentation as forever-current `HEAD`. Always verify live GitHub state first.

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

As of 2026-10-03, live `main` is:

`9f25c8297d569ef541aecf10c7090875912b55fa`

This is the merge commit of PR #77:

`S9-4D: add inverter temperature-dependent capability evaluation`

Merge facts:

- previous physics base: `2ab952e2109965431bda48965c2b5485f76b1060`;
- reviewed head: `ec88649846524b97b0b23bc7db9e5f19b20fc3fe`;
- merge commit: `9f25c8297d569ef541aecf10c7090875912b55fa`;
- merged at: `2026-10-03T19:45:25Z`.

Final reviewed pre-merge CI evidence for PR #77:

- workflow: CI;
- run #197;
- run ID `37148451803`;
- synthetic merge `0f973dc638b248720e57a307b826243712c62c36`;
- Python 3.13.15;
- `pvlib==0.15.2`;
- backend: `2729 passed in 274.53s`;
- frontend: success.

No separate post-merge workflow run was associated with `9f25c829...` at the time of this handoff update. Verify live `main` before relying on this checkpoint in a later session.

## Product / engineering position

Heliotelligence is beyond MVP. The target is an enterprise-grade, physics-first, component-resolved, provenance-aware, defensively validated, measurement-boundary-aware solar digital twin and benchmarking platform.

Do not replace physical mechanisms with arbitrary percentages when sufficient physical inputs exist. Do not invent unavailable topology or equipment data. Prefer explicit `unresolved`, `unknown`, or `not_applicable` states over guessed values.

New physical capability should normally be introduced as narrow, independently validated contracts and remain dormant from production until lower-level physics and handoff invariants are proven.




## Current validated physics chain

The validated backend now reaches temperature-dependent inverter capability evaluation:

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
    +
S9-4A explicit static inverter AC capability authority
    +
explicit timestamped Q request
    ↓
S9-4B P/Q/S capability-state evaluation
    +
S9-4C explicit inverter thermal-derating authority
    +
explicit timestamped inverter-temperature state
    ↓
S9-4D temperature-dependent inverter capability evaluation
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

Strings connected to the same MPPT are solved at a common voltage over their shared valid voltage domain.

```text
I_MPPT(V) = Σ I_string(V)
P_MPPT(V) = V × I_MPPT(V)
P_common = max_V P_MPPT(V)
```

Physical mismatch is the difference between the independent-string maximum counterfactual and the common-voltage result.

Mixed active / zero strings remain unresolved without an explicit blocking / dark-string model.

### S8-3A — direct branch resistance authority

Explicit per-string direct branch series-loop resistance authority.

Rules:

- explicit zero resistance is a valid ideal path;
- absent resistance authority is unresolved;
- configured resistance is already total loop resistance and must not be automatically doubled;
- do not infer resistance from geometry, cable-plan labels, string IDs, zone IDs, aggregate loss percentages, or unrelated fields.

### S8-3B — resistive branch I-V transform

```text
V_mppt_input(I) = V_string_terminal(I) - I × R_branch
```

Current is unchanged. Negative-voltage curve portions are not silently clamped; the validated non-negative voltage domain is preserved.

### S8-3C — MPPT-input common-voltage operating point

Runs common-voltage MPPT aggregation on already transformed MPPT-input string curves. This establishes the defensible inverter DC input state for the currently supported direct-branch topology.

## Electrical reference planes

Keep these physical planes distinct:

1. module terminals;
2. physical string source terminals;
3. branch/string cable output;
4. parallel collection junction;
5. shared homerun / feeder output;
6. inverter MPPT input terminals;
7. inverter AC conversion/output boundary;
8. future controller-dispatched AC output;
9. downstream LV / transformer / MV / HV nodes;
10. revenue-meter boundary.

Do not collapse them into a generic site DC/AC value when intermediate state is available.

Static equipment capability such as `Smax` is authority, not a conductor reference plane. Sandia pre-Paco potential is a model quantity, not a physical terminal measurement.

## Deferred shared DC collection

The current S8-3 path supports explicit **direct per-string branch resistance** to the parent MPPT input. It does **not** claim arbitrary DC collection-network coverage.

For a shared post-parallel conductor, current is the sum of parallel branch currents and the loss is based on that shared current. A shared resistance must not be duplicated into every branch.

Future generalized DC collection should model explicit nodes and edges, for example:

```text
String A -- Ra --\
                  +-- collection node -- Rh -- MPPT
String B -- Rb --/
```

Return to this extension:

1. before claiming arbitrary DC-network support; or
2. before benchmarking / activating a real site whose as-built topology has shared post-parallel conductors that materially affect inverter-terminal state.

## S9 inverter contracts

### S9-0 — inverter authority

Resolves explicit `inverter_id → CEC/SAM model` authority.

- exact model names only;
- missing authority remains unresolved;
- no inference from geometry, capacity, labels, or site heuristics;
- no conversion physics in this layer.

### S9-1 — DC operating envelope

Evaluates admitted MPPT-input DC state against explicit inverter voltage/current limits.

- MPPT voltages remain independent;
- inverter-level `Idcmax` is not copied to every tracker;
- explicit tracker-current authority wins;
- a single populated MPPT may use inverter-level CEC `Idcmax`;
- multi-MPPT current capability remains unresolved without tracker-specific authority;
- this stage classifies; it does not clamp or re-solve the operating point.

### S9-2 — Sandia inverter conversion

Produces one physical inverter AC-available state.

- single populated MPPT uses the validated scalar Sandia primitive;
- multi-MPPT conversion retains independent tracker voltages and aggregates power only;
- tracker voltages are never averaged;
- tracker currents are never summed into a synthetic inverter input;
- `Paco` limiting and `Pnt` night tare are applied once per physical inverter.

### S9-3A — pre-Paco Sandia AC potential

Calculates the published Sandia pre-limit AC potential without applying a second `Paco`, `Pnt`, or startup rule.

Below startup (`Pdc < Pso`), pre-limit conversion potential is resolved as not-applicable rather than fabricated.

### S9-3B — conversion / clipping / tare power accounting

S9-3B performs accounting algebra only. It does not modify the physical operating point or rerun Sandia.

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
- empirical `Praw > Pdc` is preserved as an explicit model gain term and is not claimed to represent physical energy creation;
- negative `Praw` above startup remains conversion accounting, not night tare;
- below startup, tare is accounted separately as `Pnt`;
- there is intentionally no generic `total_inverter_loss_w` field.

### S9-4A — explicit inverter AC capability authority

Contract:

- `topology_inverter_ac_capability_authority_v1`;
- model `explicit_ac_nameplate_and_fixed_q_limit_authority_v1`;
- scope `static_inverter_ac_capability_authority_before_pqs_state_evaluation`;
- coverage `explicit_per_inverter_voltage_phase_smax_with_optional_fixed_q_limits`.

S9-4A is static equipment authority only. It does not consume timestamps or operating-state power.

Each resolved inverter carries explicit:

- nominal AC voltage;
- AC voltage basis: `line_to_line`, `line_to_neutral`, or `single_phase_terminal`;
- phase configuration: `single_phase` or `three_phase`;
- rated apparent power `Smax`;
- optional fixed `Qmin/Qmax`;
- parameter source;
- confidence.

Critical rules:

- missing inverter mapping remains `unresolved_no_explicit_ac_capability_authority`;
- no authority is inferred from `Paco`, `pnom_kwac`, grid limits, CEC/SAM `Vac`, `model_ref`, inverter groups, MPPT/string counts, topology position, or legacy AC wiring loss;
- `three_phase + single_phase_terminal` is invalid;
- fixed Q limits must be supplied as a pair and each magnitude must not exceed `Smax`;
- missing Q authority is different from explicit zero Q capability (`Qmin = Qmax = 0`);
- S9-4A does not define operating P/Q/S, AC current, PF compliance, thermal derating, dispatch, cable loss, or transformer state.


### S9-4B — inverter P/Q/S capability-state evaluation

Contract:

- `admitted_inverter_ac_and_capability_to_pqs_evaluation_v1`;
- model `explicit_q_request_apparent_power_circle_and_fixed_q_limits_v1`;
- scope `inverter_ac_pqs_capability_evaluation_before_dispatch_and_ac_network`;
- coverage `active_sandia_ac_with_explicit_smax_q_request_and_optional_fixed_q_limits`.

S9-4B strongly replays S9-3B and S9-4A before evaluating a timestamped request.

Operating convention:

- `Q > 0`: injection into the AC network;
- `Q < 0`: absorption from the AC network;
- `Q = 0`: explicit zero-reactive request;
- missing request is not zero.

For an applicable row:

```text
P = admitted p_ac_available_w
Q = explicit request
S = hypot(P, Q)
```

Rules:

- evaluate `S <= Smax`;
- evaluate `Qmin <= Q <= Qmax` only where fixed-Q authority exists;
- a passing S-circle with missing fixed-Q authority remains partial / overall satisfaction unknown;
- any known S-circle or fixed-Q violation is definitive;
- `|P| > Smax` remains a known violation when Q is missing;
- full static capability authority is inherited from S9-4A and does not depend on request presence;
- night-tare / non-producing rows are resolved not-applicable;
- unresolved S9-3B state propagates without fabricating P/Q/S;
- no P reduction, Q clipping, dispatch, AC current, PF compliance, thermal derating, cable, transformer, or production integration occurs here.


### S9-4C — explicit inverter thermal-derating authority

Contract:

- `topology_inverter_thermal_derating_authority_v1`;
- model `explicit_temperature_domain_piecewise_capability_derating_authority_v1`;
- scope `static_inverter_thermal_derating_authority_before_temperature_state_evaluation`;
- coverage `explicit_per_inverter_temperature_domain_with_no_derating_or_piecewise_limits`.

S9-4C records static per-inverter manufacturer authority only.

It distinguishes:

- missing authority from explicit no-derating authority;
- active-power, apparent-power, and reactive-power thermal channels;
- the physical `temperature_quantity` and supported temperature domain;
- explicit no-derating mode from aligned piecewise-linear limit curves.

Reactive-power convention is fixed:

- positive Q = injection into the AC network;
- negative Q = absorption from the AC network.

Source data using another sign convention must be transformed before authority construction; S9-4C never infers or reverses signs.

S9-4C records `linear` as the downstream interpolation model for piecewise curves and `unresolved` outside-domain policy, but performs no interpolation or timestamped operating evaluation.

It does not use module/cell temperature, S9-4A, or S9-4B as inputs and does not modify power.


### S9-4D — temperature-dependent inverter capability evaluation

Contract:

- `admitted_inverter_pqs_and_thermal_authority_to_temperature_capability_evaluation_v1`;
- model `explicit_inverter_temperature_piecewise_thermal_capability_evaluation_v1`;
- scope `inverter_ac_temperature_dependent_capability_evaluation_before_dispatch_and_ac_network`;
- coverage `active_inverter_pqs_with_explicit_thermal_authority_and_matching_temperature_state`.

S9-4D strongly replays canonical S9-4B and S9-4C, then admits an exact timestamped `InverterTemperatureState` keyed by `(timestamp, inverter_id)`.

Its key semantics are:

- exact case-sensitive temperature-quantity match to S9-4C authority;
- inclusive authority-domain boundaries;
- no clamping or extrapolation;
- exact manufacturer value at authority breakpoints;
- explicit piecewise-linear interpolation only between points;
- explicit-no-derating authority distinct from missing authority;
- P, S and Q thermal channels evaluated independently only when explicitly authoritative;
- known violations remain definitive even under partial authority;
- passing partial authority remains unknown rather than becoming true;
- static S9-4A/S9-4B capability remains distinct from thermal authority;
- no dispatch, P/Q/S modification, thermal-loss accounting, AC current or network physics.

The final validator deterministically reconstructs the complete expected result from canonical parents, immutable thermal authority and admitted temperature state, with exact dtypes, provenance and diagnostics closure.

## Legacy production compatibility path

The validated S8/S9 chain is not automatically equivalent to the production runtime path.

The legacy `calculate_dc_power()` compatibility path still retains aggregate percentage effects including soiling, LID, static mismatch, and DC wiring. Legacy AC wiring / grid-cap behaviour also remains separate from the dormant component-resolved migration until explicitly replaced.

Do not silently apply validated physical losses and legacy percentages together. Production integration must be a separately reviewed migration with no double counting.

## Optical / surface status

The canonical fixed-table optical chain substantially covers solar geometry and irradiance decomposition, direct-geometry shading authority, diffuse visibility, IAM / optical response, fixed-row rear irradiance / rear optical response, bifacial electrical-equivalent irradiance, and spectral response.

Current limitations remain explicit:

- rear optics are validated for supported regular fixed-row / infinite-sheds coverage, not arbitrary 3D rear obstruction;
- dynamic physical soiling is not yet canonical;
- snow is not yet implemented as a physical state model;
- bypass-diode / substring electrical behaviour and multiple local maxima remain future electrical work.




## Next build

The next control increment is:

### S10A — explicit plant-controller / dispatch-request authority

S10A should introduce a narrow authority/request contract for explicit plant-controller commands without changing the S9-4D available state.

The next-stage design should preserve:

- explicit timestamped active-power request / setpoint where known;
- explicit timestamped reactive-power request / setpoint where known;
- controller operating mode where authoritative;
- explicit plant/export constraint where authoritative;
- controller or command source;
- provenance and confidence;
- exact missing-vs-zero semantics.

Do not infer dispatch from measured output, nominal power, S9-4D capability, grid-limit configuration, historical clipping, power factor, or arbitrary defaults.

Recommended downstream sequence:

```text
S9-4D available temperature-dependent capability
    ↓
S10A explicit controller / dispatch-request authority
    ↓
S10B dispatch-feasibility evaluation
    ↓
S10C selected/dispatched inverter AC P/Q/S
    ↓
S11 LV AC collection
    ↓
S12 transformer
    ↓
S13 MV/HV + revenue-meter boundary
    ↓
S14 benchmarking / causal loss attribution
```

Keep capability, requested dispatch, selected dispatch and downstream physical network losses as separately attributable states.

## Non-negotiable project rules

- Use physics-first modelling where a mechanism can reasonably be calculated.
- Preserve physical reference planes.
- Do not replace one arbitrary percentage with another disguised approximation.
- Preserve legacy behaviour until its replacement is independently validated.
- Prefer focused PRs with exact admission, limiting-case, closure, provenance, and equivalence tests.
- Do not invent unavailable physical topology or equipment authority.
- Missing authority and explicit zero are different states.
- Do not average independent MPPT voltages.
- Do not duplicate inverter limits per tracker.
- Do not apply shared feeder resistance as if it were independent branch resistance.
- Do not infer inverter apparent/reactive capability from active-power or CEC fields.
- Do not integrate new physical layers into production before validating their contracts and double-counting boundaries.

## Reference site: Bracon Ash

Bracon Ash is a reference/onboarded site, not a template for other sites.

Critical unresolved facts remain:

- no physical MPPT-to-string map is currently known;
- no string-to-inverter assignment should be inferred from aggregate counts;
- no physical cable layout is established by current configuration;
- no authoritative S9-4A AC capability authority has been established for the installed inverters, so generic S9-4B cannot resolve Bracon Ash capability without additional equipment evidence and explicit Q requests;
- no transformer or MV/HV collection topology is established by current configuration.

Do not infer any of these from group IDs, counts, positions, capacities, `Paco`, CEC `Vac`, or labels. See `docs/sites/bracon-ash.md`.

## Dependency lock

The validated physics environment is pinned to:

`pvlib==0.15.2`

Do not upgrade pvlib as part of an unrelated physics increment. The pin exists because version changes have already altered exact optical expectations.

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

## Operational note

Production `cloudbuild.yaml` currently deploys Cloud Run with `--min-instances=0` and `--max-instances=10`.

`RUN_SCHEDULER` controls in-process APScheduler startup. Staging has been validated with `RUN_SCHEDULER=false`, but the long-term dedicated scheduler / worker architecture remains separate operational work.

Do not mix scheduler migration with the physics roadmap unless there is a clear runtime dependency.

Never put secrets, credentials, or secret values in repository documentation.
