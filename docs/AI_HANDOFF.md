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

As of 2026-10-06, live `main` is:

`6f6dbb34027f9e648fe8623aab37b14341f193c7`

This is the merge commit of PR #86:

`S11C: add balanced radial LV AC collection solve`

S10 controller milestone:

- S10A PR #79 merged as `4a6b318946a5a2bb688bfa29f7318403362f99de`;
- S10B PR #81 merged as `2f4a4050c48203018fbf914c3853675f996bda97`;
- S10C PR #82 merged as `a8e883b4ba04dfcab4a2736d15ceaf9eed06496e`.

S11 milestone:

- S11A PR #84, reviewed head `07cb048dec18ca42b3b668a3b7407e9e27b784ce`, merged as `caabb06ff31d5b5cf48139fada6aeb265ae9771a`;
- S11B PR #85, reviewed head `c4e8ba2e3545bbf64037759730cdc6746bd45f79`, merged as `3fb4c3181c283ecf62622865b88622ac7b24ae22`;
- S11C PR #86, reviewed hardened head `73dafc1f79c09ccd9fb61dd9ee7610cc2e62233c`, merged as `6f6dbb34027f9e648fe8623aab37b14341f193c7`.

GitHub reports the S11C merge signature as verified. Its parents are canonical S11B main `3fb4c3181c283ecf62622865b88622ac7b24ae22` and reviewed S11C head `73dafc1f79c09ccd9fb61dd9ee7610cc2e62233c`.

Final reviewed pre-merge CI evidence:

- workflow: CI;
- run #217;
- run ID `37544412809`;
- base `3fb4c3181c283ecf62622865b88622ac7b24ae22`;
- synthetic merge `a8ea3ec4965e75f2ae67dae835a74dc619bf4d2e`;
- Python 3.13.15;
- `pvlib==0.15.2`;
- backend: `3040 passed in 527.89s`;
- frontend: success.

Reviewed S11 CI history:

| Stage | CI | Run ID | Synthetic merge | Backend | Frontend |
|---|---:|---:|---|---|---|
| S11A | #212 | `37246123578` | `b11c0ccf463eabe7a7797c4027f9f672852e2ea0` | 2939 passed in 627.40s | success |
| S11B | #214 | `37384225311` | `014ff7db4218cc4668604cbcb1e7031c25daac63` | 2989 passed in 518.15s | success |
| S11C hardened | #217 | `37544412809` | `a8ea3ec4965e75f2ae67dae835a74dc619bf4d2e` | 3040 passed in 527.89s | success |

All three used Python 3.13.15 and `pvlib==0.15.2`. Verify live `main` before relying on this checkpoint in a later session.

## Product / engineering position

Heliotelligence is beyond MVP. The target is an enterprise-grade, physics-first, component-resolved, provenance-aware, defensively validated, measurement-boundary-aware solar digital twin and benchmarking platform.

Do not replace physical mechanisms with arbitrary percentages when sufficient physical inputs exist. Do not invent unavailable topology or equipment data. Prefer explicit `unresolved`, `unknown`, or `not_applicable` states over guessed values.

New physical capability should normally be introduced as narrow, independently validated contracts and remain dormant from production until lower-level physics and handoff invariants are proven.





## Current validated physics chain

```text
S8-1  physical string I-V
S8-2  common-voltage MPPT / physical mismatch
S8-3A direct branch resistance authority
S8-3B resistive branch I-V transform
S8-3C MPPT-input operating point
S9-0  explicit CEC/SAM inverter authority
S9-1  DC envelope classification
S9-2  Sandia inverter conversion
S9-3A pre-limit Sandia AC potential
S9-3B conversion / clipping / tare accounting
S9-4A explicit static AC capability authority
S9-4B timestamped P/Q/S capability-state evaluation
S9-4C explicit inverter thermal-derating authority
S9-4D temperature-dependent inverter capability
S10A  explicit timestamped active-power dispatch request
S10B  requested P/Q/S feasibility evaluation
S10C  selected inverter AC P/Q/S state
S11A  explicit static LV topology and direct per-phase R+jX authority
S11B  timestamped collection-exit V_LL,RMS authority
S11C  balanced radial constant-PQ LV operating solution
```

The S10 chain is deliberately split:

- **request:** S10A owns explicit per-inverter active-power request; canonical Q request remains S9-4B-owned;
- **feasibility:** S10B evaluates the exact requested point against instantaneous availability, static S/Q capability and temperature-dependent capability;
- **selection:** S10C establishes a selected point only for an exact request that is fully proved feasible.

No S10 stage infers plant-level allocation, command persistence, measured output, AC current or network loss.

S11 preserves the next separation: S11A is static network authority, S11B is exact operating boundary-voltage authority, and S11C is the physical operating solve. S10C and S11C remain modeled target/state, not measured telemetry.

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


### S10A — explicit inverter active-power dispatch-request authority

Contract:

- `topology_inverter_active_power_dispatch_request_authority_v1`;
- model `explicit_absolute_inverter_ac_active_power_setpoint_authority_v1`;
- scope `timestamped_inverter_active_power_dispatch_request_authority_before_feasibility_and_selection`;
- coverage `explicit_direct_per_inverter_active_power_setpoints_at_inverter_ac_output`.

S10A admits exact timestamped per-inverter absolute active-power requests at `inverter_ac_output`. Missing request is not zero, explicit zero is resolved, no temporal persistence occurs, and `grid_limit_kwac` or a site export limit is never reinterpreted as a per-inverter command. Canonical Q request remains S9-4B-owned.

### S10B — requested inverter dispatch-feasibility evaluation

Contract:

- `admitted_inverter_capability_and_dispatch_request_to_feasibility_evaluation_v1`;
- model `explicit_requested_pq_against_available_static_and_thermal_capability_v1`;
- scope `inverter_ac_dispatch_request_feasibility_before_selection_and_ac_network`;
- coverage `per_inverter_requested_pq_against_available_ac_static_and_thermal_capability`.

S10B strongly replays S9-4D and S10A and evaluates the **requested** point:

- `P_requested` comes only from S10A;
- `Q_requested` remains the canonical S9-4B request;
- `S_requested = hypot(P_requested, Q_requested)`;
- instantaneous active-power availability, static S/Q capability and thermal P/S/Q capability remain separately attributable;
- known violations remain definitive under partial information;
- a passing partial-authority result remains partial/unknown.

S10B never clamps, selects or modifies P/Q/S.

### S10C — selected inverter AC dispatch state

Contract:

- `admitted_dispatch_feasibility_to_selected_inverter_dispatch_state_v1`;
- model `exact_fully_feasible_request_passthrough_selection_v1`;
- scope `inverter_ac_dispatch_selection_before_ac_current_and_network`;
- coverage `fully_feasible_per_inverter_requested_pq_at_inverter_ac_output`.

S10C strongly replays canonical S10B. Its v1 policy is deliberately narrow:

- fully feasible exact request → exact requested P/Q/S becomes selected;
- known infeasible request → no selected point;
- partial capability authority → no selected point;
- unresolved feasibility → no selected point;
- inactive state → resolved not applicable without fabricated P/Q/S zero.

S10C never performs `P=min(request,available)`, Q clipping, apparent-power projection, thermal clipping or fallback dispatch. Selected P/Q/S is a controller/model target, not measured telemetry.

## S11 LV AC collection contracts

### S11A — static topology and series-impedance authority

Contract `explicit_lv_ac_collection_topology_and_series_impedance_authority_v1`, model `radial_balanced_three_phase_direct_series_impedance_authority_v1`.

Scope `static_lv_ac_collection_authority_before_operating_voltage_current_and_network_solve`; coverage `explicit_inverter_terminal_junction_collection_exit_and_segment_series_impedance_authority`.

S11A admits only explicit `balanced_three_phase`, `line_to_line_rms`, `per_phase_series` basis; `inverter_terminal`, `junction`, and `collection_exit` nodes; direct per-phase R/X segments oriented toward exits; and inverter bindings at `inverter_ac_output`. It supports shared segments and multiple trees, rejects malformed radial graphs, preserves valid partial authority, and treats explicit R=X=0 as resolved evidence. It has no timestamp, voltage magnitude, P/Q/S, current, loss, or transformer solve.

### S11B — timestamped collection-exit voltage authority

Contract `admitted_lv_ac_collection_authority_to_timestamped_collection_exit_voltage_state_v1`, model `explicit_balanced_three_phase_collection_exit_line_to_line_rms_voltage_state_v1`.

Scope `timestamped_lv_ac_collection_exit_voltage_boundary_authority_before_network_solve`; coverage `explicit_collection_exit_line_to_line_rms_voltage_states_for_admitted_lv_ac_collection_topology`.

S11B strongly replays S11A and admits exact `(pd.Timestamp, collection_exit_node_id)` values at reference plane `lv_ac_collection_exit`. Voltage is finite, non-Boolean, non-negative `line_to_line_rms`; explicit 0 V is evidence and missing is not zero. Its timestamp universe comes only from supplied evidence, with timestamp × canonical-exit closure. There is no fill, interpolation, persistence, cross-exit copying, nameplate/CEC/transformer inference, S10C dependency, phase conversion, current, or network solve.

### S11C — balanced radial operating solution

Contract `admitted_selected_dispatch_lv_topology_and_exit_voltage_to_balanced_radial_operating_solution_v1`, model `balanced_three_phase_radial_constant_pq_backward_forward_sweep_v1`.

Scope `lv_ac_collection_operating_solve_from_inverter_ac_output_to_collection_exit_before_transformer`; coverage `complete_radial_lv_collection_trees_with_selected_inverter_pq_and_explicit_collection_exit_voltage`.

S11C strongly replays S10C, S11A, and S11B. S10C selected P/Q is assumed realised as balanced constant-PQ injection at `inverter_ac_output`; it remains a modeled controller target. For each fully admitted tree:

```text
V_exit,phase = V_exit,LL,RMS / sqrt(3) at mathematical angle 0
I_inverter = conj((P_selected + jQ_selected) / (3 V_terminal,phase))
V_from = V_to + (R + jX) I_segment
P_loss = 3 R |I|²
Q_series = 3 X |I|²
S_from - S_to = 3 (R + jX) |I|²
```

Backward sweep aggregates complex current once through shared segments; forward sweep reconstructs voltages. The fixed-point model uses 200 maximum iterations, `1e-7 V` absolute and `1e-10` relative voltage tolerances, and fresh-current final closure. Collection-exit angle zero is a coordinate convention, not measured phase-angle authority.

Global S11A membership must close for every canonical inverter before any tree solves. Once closed, independent trees may resolve independently. Each timestamp/tree requires selected dispatch for every member and exact S11B voltage. Missing dispatch is never zero; explicit P=Q=0 is real zero injection.

Zero exit voltage plus all-zero dispatch resolves to zero voltage/current/loss. Zero exit voltage plus any nonzero P or Q is singular: `unresolved_zero_exit_voltage_with_nonzero_selected_power`. Nonfinite and nonconvergent results remain unresolved with physical outputs NaN. Nonconvergence may preserve a finite final voltage delta and iteration count 200 as solver diagnostics.

Outputs are modeled `collection_exit_states`, `node_states`, and `segment_states`. Validation independently closes parent replay, immutable mappings, membership, diagnostics, terminal power, junction KCL, segment `V=ZI`, segment complex power/loss, exit delivery, and whole-tree P/Q conservation.

S11C has no unbalanced phases, neutral, shunt, loads, transformer, voltage compliance, inverter feedback, redispatch, energy integration, or production activation.

## Legacy production compatibility path

The validated S8/S9/S10/S11 chain is not automatically equivalent to the production runtime path.

The legacy `calculate_dc_power()` compatibility path still retains aggregate percentage effects including soiling, LID, static mismatch, and DC wiring. Legacy `wiring_loss_ac_pct` / grid-cap behavior remains separate from dormant S11. Physical S11C loss is instantaneous `3R|I|²` on explicit segments, not an energy quantity or percentage.

Do not silently apply validated physical losses and legacy percentages together. Production integration must be a separately reviewed migration with no double counting.

## Optical / surface status

The canonical fixed-table optical chain substantially covers solar geometry and irradiance decomposition, direct-geometry shading authority, diffuse visibility, IAM / optical response, fixed-row rear irradiance / rear optical response, bifacial electrical-equivalent irradiance, and spectral response.

Current limitations remain explicit:

- rear optics are validated for supported regular fixed-row / infinite-sheds coverage, not arbitrary 3D rear obstruction;
- dynamic physical soiling is not yet canonical;
- snow is not yet implemented as a physical state model;
- bypass-diode / substring electrical behaviour and multiple local maxima remain future electrical work.





## Next build

### S12 — transformer authority first

S11 v1 is complete; no S11D physics increment is currently required. Proceed from the exact `lv_ac_collection_exit` boundary to explicit transformer equipment/topology authority before any operating transformer solve.

Potential later transformer physics may require explicit terminal/reference planes, winding voltage bases, rated power, turns/voltage ratio, series impedance/copper loss, no-load/core loss, loading, and tap/control state. Do not lock these into an operating model or infer them from S11 exit voltage, CEC `Vac`, nominal site voltage, capacities, labels, geometry, or current site YAML.

`lv_ac_collection_exit` is not automatically the transformer LV winding. Measurement reconciliation, energy integration, reporting/accounting aggregation, and production activation remain separate future work.

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
- no authoritative S11A terminal/junction/exit topology, inverter bindings, or direct per-phase R/X exists;
- no exact timestamped S11B `lv_ac_collection_exit` voltage evidence exists;
- no authoritative S9-4A AC capability authority has been established for the installed inverters, so generic S9-4B cannot resolve Bracon Ash capability without additional equipment evidence and explicit Q requests;
- no transformer or MV/HV collection topology is established by current configuration.

Generic S11A/B/C therefore does not make Bracon Ash an authoritative high-fidelity LV model. Its legacy `wiring_loss_ac_pct` is not segment R/X authority. Do not infer any missing evidence from group IDs, counts, positions, capacities, geometry, `Paco`, CEC `Vac`, nominal voltage, transformer ratings, measured inverter output, or labels. See `docs/sites/bracon-ash.md`.

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
