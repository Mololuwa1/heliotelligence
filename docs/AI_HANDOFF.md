# Heliotelligence AI / Developer Handoff

This is the current recovery and architectural checkpoint for Heliotelligence, an enterprise-grade, physics-first solar digital twin and benchmarking platform.

It does not replace live source, tests, Git history, CI evidence, or direct inspection of current code.

## Current status

Heliotelligence is a physics-first PV digital twin and meter-benchmarking platform.

```text
Current checkpoint:
PR #127 merge 1e5317b2a7305be54529ba8d1388b27492b8ae52
Validated generic electrical chain:
S8 → S9 → S10 → S11 → S12 → S13 → S14
Upstream readiness:
weather/irradiance/module-thermal production integration still has open gates
Production:
legacy expected-energy path remains active
Uncertainty:
measurement and pointwise model bounds complete; discrete S14B model-interval propagation complete;
combined interval magnitudes complete; eligible deterministic envelope interpretation generic, dormant
Next:
P0 complete; module thermal, weather/irradiance and bounded population residual generic, dormant
Next: platform authorization and site/P1-P2 evidence; no shadow activation
```

Current canonical code checkpoint: `1e5317b2a7305be54529ba8d1388b27492b8ae52` (PR #127 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

“Implemented generically” means the reusable physics contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

Never infer missing string/MPPT/inverter mappings, conductor paths, capability, controller requests, side temperatures, transformer loss evidence, operating voltages or meter bindings. Equipment counts, CEC fields, weather, measured output and site export caps are not substitutes. Bracon Ash still lacks the authority described in the [site record](sites/bracon-ash.md).

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`. Run optical/rear regressions when shared dependencies warrant them.

Local development uses focused changed-feature tests and the immediate affected regression slice. PR CI conservatively selects changed/transitively affected unit tests; ambiguous backend impact falls back to the full unit suite. Docs/frontend-only PRs retain a successful backend check without installing backend dependencies or running unit tests. Superseded runs for the same PR are cancelled when a newer commit is pushed; different PRs and main validation do not cancel one another. Every push to `main` must run the full `python -m pytest tests/unit/ -q --no-header --no-cov` command. **Targeted PR CI is not a complete backend pass; main remains the authoritative full-backend validation.** Check the exact commit and live CI before review/release decisions.

The [PR selector](../scripts/ci/select_pr_unit_tests.py) reads the base/head git diff and parses the checked-out source/test import graph without importing application code. It follows test helpers, relative imports, package initializers, implicit conftest fixtures/plugins and literal dynamic imports; adds mirrored tests and conservative computed-import consumers; and uses full mode for unresolved import/parse analysis, broad configuration/dependency/data changes, deleted modules or source changes with no identifiable tests. Selection is sorted/deduplicated and printed before execution. Workflow/CI-tooling changes include the selector tests.

Read the canonical [production-integration roadmap](development/production-integration-roadmap.md) before activation work. P0 source isolation is complete at PR #118 merge `04f0cf338ab86980c040e5b6fbda6942a3c28681`. Model-sensitive operations select one exact source, defaulting to legacy `physics_sdm`; legacy waterfall/report bundles reject unsupported sources. Telemetry-only health guards check existence without selecting or combining model values. Physical shadow execution remains planned, not active.

### Known pre-shadow blockers

Do not describe the full weather-to-meter chain as production-validated yet.

- **Weather time semantics:** Solcast `period_end` is stored directly and SCADA period-start timestamps are normalised to period-end, while the legacy POA runtime evaluates solar position at the stored timestamp. Generic explicit weather-time authority and observation-keyed SPA alignment now exist; source-specific binding and production integration remain absent.
- **IAM integration defect:** legacy `calculate_poa()` computes IAM-corrected beam irradiance but assembles `poa_total` from uncorrected `poa_front`.
- **Measured-front bifacial gap:** the measured-POA shortcut explicitly sets rear irradiance to zero.
- **Module thermal integration remains dormant:** the generic canonical authority/state contract now exists, but `physics/thermal.py` remains the active legacy runtime. Its measured-module cell offset currently yields 0.03 °C at 1000 W/m² despite the code comment describing about 3 °C, and configured `u_c/u_v` values are passed directly into a Faiman `u0/u1` interface.
- **Population-residual site admission remains open:** S8-1 remains homogeneous series scaling and shared-MPPT mismatch remains physical S8 ownership. A separate generic bounded intra-string residual authority now exists, with explicit negligible or post-MPPT equivalent-current-derate modes. It is lower fidelity, not member-resolved I-V physics. Missing authority leaves active population-complete output unresolved; resolved-zero upstream states remain exact zero without authority; legacy aggregate mismatch cannot be retired without allocation evidence.
- **S14B site support-policy admission remains open:** generic v2 eligibility now requires explicit per-meter maximum-gap authority after finite reconstruction. No default gap/cadence or Bracon threshold is inferred. Synthetic daylight-edge tests justify the distinction, not a universal policy value.
- **Measurement uncertainty is quantitative generically:** a separate dormant authority annotates canonical S13D with explicit complete-chain numerical bounds. Categorical confidence is provenance only. Combined interval magnitudes now exist separately; deterministic S14B envelope interpretation is now implemented generically.
- **Platform access control is not shadow-ready:** the frontend sends `VITE_ADMIN_KEY`, which is browser-bundled, and ordinary site-scoped protected routes reviewed so far authenticate users but do not enforce `user_site_access` membership.
- **S9-4A fixed-Q sign semantics are not locally declared:** downstream convention is positive Q injection / negative Q absorption; source evidence using another convention must be transformed before S9-4A construction.

P0 is complete. Generic module thermal plus weather-time/irradiance-boundary implementation does not close site admission, calibrated thermal-POA selection or production integration. P3 shadow execution and P4 accuracy claims must not pass the remaining gates by implication.

## Module-population residual recovery notes

`apply_module_population_mismatch(topology, mppt_mismatch, authority_by_mppt=...)` composes the exact `TopologyMPPTMismatchResult` with explicit physical MPPT-key authority. It replays baseline V/I/P and shared mismatch; authority never fans out implicitly. Extra/empty-MPPT keys are rejected. Both authority modes are bounded lower fidelity: `explicit_negligible_by_evidence` requires f=0; `equivalent_post_mppt_current_derate` requires 0<f<1. The exact mechanism excludes shared-MPPT mismatch, optical/thermal losses, wiring, soiling, LID and conversion.

For resolved active authority rows, V_after=V_common, I_after=I_common(1−f), P_after=V_after I_after. Population loss is P_common−P_after; total mismatch closes both as shared+population and P_independent−P_after. Missing population evidence retains valid S8 values but active adjusted V/I/P stay NaN. Unresolved upstream cannot be repaired. Resolved-zero upstream stays exactly zero with or without authority, without fabricating a fraction; its selected path is not lower fidelity. Independent validation reconstructs equations, provenance, states and diagnostics without production builders. Upstream admission verifies the published aggregated S8 contract and internal consistency, including exact cause vocabulary/order and topology-ordered unresolved IDs; it does not reconstruct unavailable member-to-cause assignments.

No SiteConfig or legacy mismatch percentage is consumed. Bracon's 1.15% is not authority and remains on the legacy series only. Nameplate tolerance alone does not define member current/voltage distribution. Future member-resolved physics must compose series voltages at common current with explicit reverse/bypass authority where needed. DC collection is not integrated with this new boundary here; P1/P2/P3 remain unimplemented.

## S14B support-policy recovery notes

`revenue_meter_interval_support_policy.py` defines frozen `RevenueMeterIntervalSupportPolicyAuthority`, supplied to S14B via `revenue_meter_interval_support_policy_by_meter_id`. Omission means an empty mapping. Partial meter coverage is allowed; unknown/non-string keys, malformed mappings and tampered frozen authorities are rejected. No global/site-config policy or automatic fan-out exists.

S14B v2 preserves exact boundaries, exact selected S13C support, piecewise-linear reconstruction and trapezoidal integration. It publishes reconstruction resolved separately from support eligibility. Missing policy gives `unresolved_missing_expected_interval_support_policy`; actual max gap greater than the admitted seconds gives `unresolved_expected_interval_support_gap_exceeds_policy`. Equality passes. Finite reconstructed energy/averages and gap diagnostics remain visible in both failure cases; all eight benchmark residual fields remain NaN. Gap/interval fraction is diagnostic, never an implicit threshold.

Policy presence/provenance is visible on supplied rows even when an earlier failure prevents assessment. Diagnostics count missing/present policy only after finite reconstruction; pass/fail partition the reconstructed rows with policy. Instantaneous and upstream-failed rows are not missing-policy gaps. The independent validator rebuilds support, integration, policy admission, fields and diagnostics without production builders or the policy-resolution helper. S14C consumes S14B eligibility and exact support timestamps; its accounting contract/numerics are unchanged.

The generic support-policy gate is complete (PR #122); site policy evidence, platform authorization and P1/P2 remain open. No production/shadow switch is activated. Bracon has no admitted support threshold. Synthetic quadratic-edge errors describe only the checked-in proxy.

## Revenue-meter numerical measurement bounds

`physics/revenue_meter_measurement_uncertainty.py` is a dormant cross-cutting annotation of canonical S13A/S13D, not another stage. Admit frozen complete-chain authorities explicitly by meter ID. Revalidate supplied authorities and replay canonical parents before evaluating independent P/Q bounds. Missing authority, invalid temporal applicability and unavailable channels stay unresolved; explicit zero bounds are valid evidence.

Only numerical coefficients affect `abs(measured) × relative + absolute` using supplied terms. Authority must explicitly attest `relative_error_reference_basis = absolute_same_channel_measured_power_in_primary_engineering_units`: the fraction is of the magnitude of that measured P/Q channel, not true value, full scale/rating, plant capacity or instrument current. Other bases need an explicit compatible conversion with provenance before admission; none is inferred. Zero and fractions greater than one remain valid. No accuracy-class inference, confidence-to-number conversion, RSS or probability model exists. The bound is already complete-chain after meter/instrument transformers/scaling/calibration; the module does not recombine component specifications. S13D values, source/confidence and boundary semantics remain unchanged.

Validity is inclusive: snapshot timestamp, or complete interval coverage for interval averages. A supplied lower limit compares against an exactly representable `end - duration`; unsafe arithmetic leaves temporal applicability unresolved. A missing lower limit does not require inventing one. Aware zones compare physical instants without rewriting evidence; naive/aware mismatch stays unresolved.

Measurement bounds are generic capability, not Bracon admission or total benchmark uncertainty. Pointwise expected-model bounds now exist separately; discrete expected-model interval propagation now exists separately; combined interval magnitudes now exist separately; deterministic S14B envelope interpretation is now implemented generically. Do not change S14 residuals, infer significance, calculate revenue or activate a shadow source from measurement bounds alone.

## Pointwise expected-model uncertainty

`physics/revenue_meter_expected_model_uncertainty.py` independently replays canonical S13A and S13C, then preserves the entire expected-meter frame while annotating pointwise P/Q bounds. It does not import measurement uncertainty or S14. The frozen per-meter authority supplies an already-combined complete-model bound; categorical confidence and external model/version/study references remain provenance only.

Required relative basis is `absolute_same_channel_expected_power_in_primary_engineering_units`; no rating, capacity, current, irradiance, other channel/plane or unknown-true-value specification is directly admissible. External conversion must produce a compatible complete-chain envelope with provenance; the engine infers nothing. Explicit zero and fractions above one remain valid. Snapshot validity is inclusive, preserving timezone provenance; incompatible naive/aware limits do not resolve.

Missing uncertainty evidence preserves valid S13C baseline power. Upstream-unresolved rows are not missing-authority diagnostic gaps. Missing or altered supplied parent rows fail exact replay; this annotation does not fabricate timestamps. Its independent validator reconstructs admission, bounds, schema and nested diagnostics without production helpers. The pointwise module publishes no interval-energy uncertainty itself. A separate layer now propagates over the exact S14B support set; measurement/model interval combination and eligible deterministic envelope interpretation are implemented separately. Bracon remains unadmitted; production is unchanged.

## Expected-model discrete interval propagation

The dormant interval module consumes two independently validated public parents: canonical S14B and the pointwise expected-model annotation, reconstructed from original inputs plus the original per-meter support-policy and pointwise-authority mappings. It defines no new numerical authority and never recalculates relative/absolute point bounds.

Only `expected_interval_reconstruction_resolved` gates propagation. Every exact S14B support point must have a resolved, finite nonnegative published magnitude for that channel. Missing policy or excessive support gap does not prevent this mathematical operation; inherited S14B eligibility/residuals remain unchanged. P/Q completeness, unresolved timestamp tuples and arithmetic states remain separate. Earlier reconstruction failure is not a pointwise coverage gap.

`B_E = fsum((b_i/2 + b_next/2) × exact_elapsed_seconds/3600)` is the tight deterministic worst-case bound for the discrete trapezoidal functional. It assumes no probability, independence or covariance and adds no support-density/continuous-trajectory error term. `B_avg = B_E / admitted_interval_hours`; lower/upper ranges use the signed canonical S14B central values without clipping. Exact pointwise support states retain all parent provenance. The independent validator does not use production composition/support/propagation/frame/diagnostic helpers.

Measurement uncertainty is not consumed by the propagation layer. Combined interval magnitudes and eligible deterministic envelope relations now exist separately. Neither statistical significance nor causal/commercial conclusions, Bracon admission or production/shadow activation are claimed.

## Canonical module thermal authority/state

`module_thermal_authority.py` separates explicit native PVsyst cell parameters (`u_c_w_per_m2k`, `u_v_w_per_m2k_per_ms`, efficiency, absorption), native Faiman parameters (`u0_w_per_m2k`, `u1_w_per_m2k_per_ms`, declared cell/module-back output quantity), module-back conversion authority and exact temperature evidence. No site configuration is promoted to authority.

`resolve_module_thermal_state` requires a named thermal zone and exactly aligned timezone-aware environmental Series. Per timestamp it selects direct cell evidence, then measured module-back conversion, then an explicit native model. Both evidence channels retain provenance. An unusable module measurement followed by a model is explicitly labelled; no whole-series switching, interpolation, extrapolation or persistence occurs. Missing wind is irrelevant only when the admitted wind coefficient is exactly zero; the missing observation remains missing.

The conversion is `T_cell = T_module_back + (E/E_ref) × deltaT`, with explicit parameter provenance. It produces 52.1°C for 50°C, 700 W/m², E_ref=1000 W/m² and deltaT=3°C. The separate legacy path still produces 50.021°C. Native model families are never silently converted. The independent validator reconstructs equations and diagnostics without production builders or pvlib calls.

Thermal POA means supplied incident broadband POA, not automatically IAM/spectral electrical-effective irradiance. The thermal contract itself does not establish weather semantics; the new separate weather-time authority must be admitted explicitly. Thermal-zone mapping, calibrated POA selection and Bracon Ash sensor placement/calibration remain external. See the [architecture](architecture/physics-architecture.md#canonical-module-thermal-authority-and-state) and [site evidence gaps](sites/bracon-ash.md#module-thermal-evidence-onboarding).

Completed generically: P0 source isolation, module thermal (PR #119), weather-time authority and date-consistent canonical irradiance boundary (PR #120), and bounded population-residual authority (PR #121). Generic S14B support eligibility was completed in PR #122; complete-chain measurement bounds were completed in PR #124; pointwise complete-model bounds were completed in PR #125; discrete expected-model interval propagation is complete generically (PR #126); combined interval magnitudes are complete generically (PR #127). Remaining sequence: platform authorization → site evidence (including population residual and support policy) / P1-P2 finalisation → P3. P1 and shadow activation are not implemented here.

## Weather-time and irradiance handoff recovery notes

Generic `weather_time_authority.py`, `solar_geometry_time_alignment.py` and `irradiance_boundary_state.py` contracts are now implemented but dormant. An explicit weather authority distinguishes instantaneous snapshots from interval averages and declares start/midpoint/end labels and duration. Interval geometry uses an explicit midpoint approximation, not interval integration. NREL-SPA runs at the evaluation instant while public optical rows keep the original observation timestamp and receiver ID.

The boundary replays existing canonical optical results: incident broadband front/rear, front optical-effective, bifacial electrical-equivalent and final spectral electrical-equivalent irradiance remain separate planes. IAM and shading are owned once by the upstream front-effective chain; bifacial and spectral response remain upstream-owned. The module-electrical handoff copies the resolved spectral result, including explicit disabled admission; unknown unresolved spectral evidence never silently becomes factor one.

Measured front incident POA is evidence alongside modelled front, not a replacement for it or a front+rear total. It never erases rear irradiance. Incident front+rear is a diagnostic only; actual module-thermal POA selection remains unresolved until a calibration-basis authority is admitted. No canonical primitive, legacy runtime, collector, timestamp storage, thermal schema or expected-energy source is changed or activated.

Exact weather observations remain the row identity. An end-labelled 11:00 one-hour average evaluates geometry at 10:30, with approximation=True; an instantaneous 10:00 observation evaluates at 10:00 with approximation=False. DST arithmetic uses elapsed duration and retains the public timezone/order. Never bind semantics merely from a source name or a measured POA field name. See the [architecture](architecture/physics-architecture.md#weather-time-and-canonical-irradiance-boundary) for canonical IDs and the [site record](sites/bracon-ash.md#weather-and-front-poa-evidence-onboarding) for missing evidence.

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

## Validated electrical chain and upstream boundary

The reusable S8–S14 electrical contracts are validated generically. The upstream weather/irradiance/module-thermal production path is **not** yet a single canonical end-to-end chain; see the pre-shadow blockers above.

```text
ADMITTED MODULE ELECTRICAL STATE
↓
S8 STRING / MPPT / PHYSICAL DC MISMATCH / DIRECT DC BRANCH
↓
S9 INVERTER CONVERSION + AC CAPABILITY + THERMAL CAPABILITY
↓
S10 EXPLICIT REQUEST / FEASIBILITY / SELECTED AC P-Q-S
↓
S11 LV AC COLLECTION
↓
S12 TRANSFORMER
↓
S13 MV/HV COLLECTION + GRID/REVENUE-METER BOUNDARY
↓
S14 METER BENCHMARK + DELIVERY-LOSS ATTRIBUTION
```

The S8–S14 chain is dormant from the default production expected-energy runtime. Upstream weather/optics/thermal integration must satisfy the production-readiness gates before the shadow model can be called end to end. Detailed S12–S14 responsibilities and exact source-copied contracts are in the [architecture](architecture/physics-architecture.md).

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

Keep these reference planes distinct:

1. module terminals;
2. physical string terminals and direct branch output;
3. parallel junction/shared feeder output where explicitly modelled;
4. inverter MPPT input;
5. inverter AC output (`inverter_ac_output`), including the S10C selected target;
6. LV collection internal nodes;
7. LV collection exit (`lv_ac_collection_exit`);
8. transformer collection terminal;
9. transformer network terminal;
10. MV/HV network nodes;
11. grid boundary;
12. revenue-meter boundary.

Equipment authority and measurement/reference-plane authority are separate. Nominal voltage or `Smax` does not establish timestamped voltage or measurement location. Grid and revenue-meter boundaries are distinct objects, co-located only by explicit binding. An LV exit is a transformer terminal only through explicit topology. Sandia pre-Paco potential is a model counterfactual, not a terminal measurement.

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
- S9-4A fixed-Q evidence uses the project convention `Q > 0` = injection into the AC network and `Q < 0` = absorption; evidence expressed under another convention must be transformed before authority construction;
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

The validated S8–S14 chain is not automatically equivalent to the production runtime path.

The legacy `calculate_dc_power()` compatibility path still retains aggregate percentage effects including soiling, LID, static mismatch, and DC wiring. Legacy `wiring_loss_ac_pct` / grid-cap behavior remains separate from dormant S11. Physical S11C loss is instantaneous `3R|I|²` on explicit segments, not an energy quantity or percentage.

Do not silently apply validated physical losses and legacy percentages together. Production integration must be a separately reviewed migration with no double counting.

## Optical / surface status

The canonical fixed-table optical chain substantially covers solar geometry and irradiance decomposition, direct-geometry shading authority, diffuse visibility, IAM / optical response, fixed-row rear irradiance / rear optical response, bifacial electrical-equivalent irradiance, and spectral response.

Current limitations remain explicit:

- rear optics are validated for supported regular fixed-row / infinite-sheds coverage, not arbitrary 3D rear obstruction;
- dynamic physical soiling is not yet canonical;
- snow is not yet implemented as a physical state model;
- bypass-diode / substring electrical behaviour and multiple local maxima remain future electrical work.

## Completed S12–S14 and next workstream

S12A–M provide transformer authority, baseline/advanced load and core loss, explicit scalar/winding-resolved thermal evidence and coupled terminals. S13A–D provide MV/HV authority, boundary voltage, network solution and meter measurement authority. S14A–C provide exact instantaneous/interval benchmarks and delivery-loss accounting.

S12K effective aggregate factors preserve side I²R/eddy sums without S12M reconstructing winding physics. OSL stays aggregate. S12M keeps harmonic loss separate from voltage-drop resistance and does not claim thermal iteration. Valid S12G-load-loss fallback stays resolved through S13C and S14A/B/C when downstream evidence closes. Fidelity and fallback flags remain visible; unresolved electrical boundaries remain unresolved.

The next major phase is production integration + site evidence onboarding. Follow P0–P6 in the [canonical activation roadmap](development/production-integration-roadmap.md); do not create another S-stage for migration.

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

Generic S8–S14 capability does not make Bracon Ash ready for the full chain. Transformer factory/construction/thermal/harmonic evidence, MV/HV parameters, grid voltage and explicit revenue-meter measurement bindings must be onboarded; no such authority is established by current site YAML. See the site record for the evidence boundary. Generic S11A/B/C therefore does not make Bracon Ash an authoritative high-fidelity LV model. Its legacy `wiring_loss_ac_pct` is not segment R/X authority. Do not infer any missing evidence from group IDs, counts, positions, capacities, geometry, `Paco`, CEC `Vac`, nominal voltage, transformer ratings, measured inverter output, or labels. See `docs/sites/bracon-ash.md`.

## Dependency lock

The validated physics environment is pinned to:

`pvlib==0.15.2`

Do not upgrade pvlib as part of an unrelated physics increment. The pin exists because version changes have already altered exact optical expectations.

## Validation expectation for future PRs

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`. Run optical/rear regressions when shared dependencies warrant them.

Local development uses focused changed-feature tests and the immediate affected regression slice. PR CI conservatively selects changed/transitively affected unit tests; ambiguous backend impact falls back to the full unit suite. Docs/frontend-only PRs retain a successful backend check without installing backend dependencies or running unit tests. Superseded runs for the same PR are cancelled when a newer commit is pushed; different PRs and main validation do not cancel one another. Every push to `main` must run the full `python -m pytest tests/unit/ -q --no-header --no-cov` command. **Targeted PR CI is not a complete backend pass; main remains the authoritative full-backend validation.** Check the exact commit and live CI before review/release decisions.

Preserve independent validator and canonical replay/tamper tests. Never merge solely because a local implementation report says tests passed.

## Operational note

Production `cloudbuild.yaml` currently deploys Cloud Run with `--min-instances=0` and `--max-instances=10`.

`RUN_SCHEDULER` controls in-process APScheduler startup. Staging has been validated with `RUN_SCHEDULER=false`, but the long-term dedicated scheduler / worker architecture remains separate operational work.

Do not mix scheduler migration with the physics roadmap unless there is a clear runtime dependency.

Never put secrets, credentials, or secret values in repository documentation.

## Combined revenue-meter interval uncertainty

`physics/revenue_meter_combined_interval_uncertainty.py` is a dormant annotation of independently validated measurement uncertainty and expected-model interval uncertainty. It introduces no numerical authority. Both parents are canonically reconstructed from original inputs/mappings and exact-replayed. The interval parent defines the ordered timestamp/meter universe; shared interval, reference-plane, sign and power-basis semantics must agree. Its complete frame is preserved, with an exact measurement-uncertainty snapshot.

For each P/Q channel and each published interval-average power/energy quantity, `B_combined = math.fsum((B_measurement, B_expected_model))`. This is the deterministic tight triangle-inequality bound for `δ_measurement - δ_model`, with no probability, independence, covariance or RSS assumption. The layer consumes published magnitudes; it does not recalculate either parent or repeat trapezoidal propagation. Missing channels and nonfinite arithmetic stay unresolved independently.

Combined resolution does not imply benchmark eligibility. Missing/exceeded S14B support policy remains unchanged; withheld residuals remain NaN. No residual, residual envelope, significance flag or commercial result is reconstructed. The bound still excludes numerical support-density/continuous-path error.

Engineering sequence: measurement uncertainty complete; pointwise expected-model uncertainty complete; expected-model interval propagation complete (PR #126); combined interval magnitudes complete (PR #127); eligible deterministic S14B envelope interpretation implemented by this increment; platform authorization next, followed by site evidence / P1-P2 finalisation. P3 shadow execution is not activated. Bracon has no invented numerical admission. S14B/S14C numerics, source isolation, `physics_sdm` and production/shadow behaviour remain unchanged.

## Deterministic interval envelope interpretation

`resolve_revenue_meter_interval_uncertainty_interpretation` reconstructs the public combined parent from original inputs and all three authority/policy mappings, then exact-replays the entire supplied result. The output preserves its full state frame and appends only envelope relations, zero-centred endpoints, nonnegative excess magnitudes and interpretation states. No additional provenance snapshot or numerical authority is introduced.

Gate order: S14B `benchmark_eligible` first; P/Q combined availability second; finite canonical residual and finite nonnegative bound third. Ineligible rows publish no relation or envelope endpoints and are not uncertainty-coverage gaps. Each channel needs both independently interpreted power and energy quantities. Exact equality means on-boundary; no tolerance or `isclose`. Missing authority and nonfinite arithmetic remain distinguishable through parent/channel states.

Measurement, pointwise-model, interval-propagation and combined bounds are complete generically. Eligible deterministic S14B envelope interpretation is implemented by this increment. Platform authorization is next, site evidence / P1-P2 finalisation later, and P3 remains inactive. Inside does not prove correctness; outside is neither a physical loss nor a fault/causal/commercial finding. No probability or statistical significance is claimed. Bracon numerical admission, source selection, production and shadow behavior are unchanged.
