# Heliotelligence AI / Developer Handoff

This is the current recovery and architectural checkpoint for Heliotelligence, an enterprise-grade, physics-first solar digital twin and benchmarking platform.

It does not replace live source, tests, Git history, CI evidence, or direct inspection of current code.

## Current status

Heliotelligence is a physics-first PV digital twin and meter-benchmarking platform.

```text
Current checkpoint:
PR #138 merge 076c310ce6087048e266bc42cc3bff95b76084d3
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
P1: immutable output contract COMPLETE; no writer or physical source selected
P2A: evidence manifest / Bracon baseline COMPLETE; P2 admission IN PROGRESS
P2B: physical-site identity admitted
P2C: configured module model/raw basis admitted only at lower fidelity
P2D: configured uniform series-count basis admitted only at lower fidelity; all paths retain blockers
P2E: consolidated upstream package implemented; remaining inputs unresolved
P2F: consolidated DC/inverter/control package implemented; labels only newly admitted
P2G: downstream evidence review complete; zero admissions; all S11/S12/S13 evidence blocked
Next: P2H benchmark/uncertainty/P2 closure; no shadow activation
```

Current canonical code checkpoint: `076c310ce6087048e266bc42cc3bff95b76084d3` (PR #138 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

“Implemented generically” means the reusable physics contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

Never infer missing string/MPPT/inverter mappings, conductor paths, capability, controller requests, side temperatures, transformer loss evidence, operating voltages or meter bindings. Equipment counts, CEC fields, weather, measured output and site export caps are not substitutes. Bracon Ash still lacks the authority described in the [site record](sites/bracon-ash.md).

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`. Run optical/rear regressions when shared dependencies warrant them.

Local development uses focused changed-feature tests and the immediate affected regression slice. PR and main-push CI both use the conservative exact-diff backend selector: `skip`, `targeted` or `full`. PR boundaries are the event's base/head SHAs; main-push boundaries are `github.event.before` and `github.sha`, with full history available. Unknown/unusable history, analysis failure, broad config/dependencies/migrations, deleted/untraceable Python or unsafe impact selects full. Docs/frontend-only changes keep a successful backend check without dependency setup/tests. Superseded same-PR runs are cancelled; different PRs, main pushes and full regressions do not cancel one another. Report the exact SHA and actual mode: a targeted post-merge pass is valid change-scoped validation, not a complete backend sweep.

The [Full Backend Regression workflow](../.github/workflows/full-backend-regression.yml) runs the complete `python -m pytest tests/unit/ -q --no-header --no-cov` suite nightly at **03:17 UTC** and on manual dispatch. It is the authoritative complete regression sweep. Before P3 activation, P5 cutover, release-candidate validation or major dependency, migration or shared-infrastructure release decisions, require a successful manually dispatched full regression on the intended `main` revision and verify the run's exact head SHA. An older nightly does not validate later commits. No CI result alone authorizes activation.

The [backend impact selector](../scripts/ci/select_pr_unit_tests.py) reads the base/head git diff and parses the checked-out source/test import graph without importing application code. It follows test helpers, relative imports, package initializers, implicit conftest fixtures/plugins and literal dynamic imports; adds mirrored tests and conservative computed-import consumers; and uses full mode for unresolved import/parse analysis, broad configuration/dependency/data changes, deleted modules or source changes with no identifiable tests. Selection is sorted/deduplicated and printed before execution. Workflow/CI-tooling changes include the selector tests.

The only data ownership exception is the reviewed Bracon P2 family: `evidence/sites/bracon-ash.yaml` and `evidence/authorities/bracon-ash/**`. These include the manifest test plus every existing `tests/unit/test_engine/test_site_*authority.py`, unioned with changed tests, transitive Python consumers and conservative opaque consumers. Missing/unavailable owner tests or evidence selects full. New/unregistered evidence paths remain full; `config/sites.yaml`, backend config/data/models/DB, dependencies and migrations stay broad. File references are not reclassified as documentation merely to reduce CI time.

Read the canonical [production-integration roadmap](development/production-integration-roadmap.md) before activation work. P0 source isolation is complete at PR #118 merge `04f0cf338ab86980c040e5b6fbda6942a3c28681`. Model-sensitive operations select one exact source, defaulting to legacy `physics_sdm`; legacy waterfall/report bundles reject unsupported sources. Telemetry-only health guards check existence without selecting or combining model values. Physical shadow execution remains planned, not active.

### P1 physical shadow-output boundary

The dormant [P1 contract](architecture/physical-shadow-output-contract.md) is implemented in `engine/physical_shadow_output_contract.py`, outside physics. It separates model source/version from explicit reference plane/boundary, uses exact run/site UUIDs and aware nanosecond snapshot identity, preserves independent P/Q resolution and carries fidelity/fallback/reason/provenance tuples. Overall state and apparent power are derived. Pure JSON-safe persistence round-trips are validated independently; no database I/O, execution, writer or hard-coded physical source is introduced.

P1 is complete at the contract level. P2 evidence admission remains in progress and P3 remains inactive. Later `expected_energy` projection requires a resolved production channel at the explicitly intended reference plane; upstream resolution cannot masquerade as meter power and unresolved output cannot become zero. Legacy `physics_sdm`, authorization and Bracon admission are unchanged.

### P2A site evidence recovery

The [site evidence contract](architecture/site-evidence-manifest.md) and `engine/site_evidence_manifest.py` define the reviewed 66-requirement catalogue, immutable inventory, strict pure YAML loader, serialization and independent coverage validation. `evidence/sites/bracon-ash.yaml` is the canonical baseline; the [Bracon matrix](sites/bracon-ash.md#p2a-controlled-evidence-baseline) is generated and drift-tested from it. No runtime reads it automatically.

The original P2A baseline had zero admitted requirements: 17 present/not admitted, 48 missing/blocked and one conflicting/blocked. Module counts 49,824 / 47,448 / 50,736 stay unresolved; capacity and geometry do not select one. At that baseline all nine path sections were blocked. Configuration is not authority; geometry is not electrical topology; telemetry labels are not measurement semantics; generic capability is not site admission. Missing means no sufficient supplied package evidence, not proof of external nonexistence. Unknown temporal validity stays unknown unless separately reviewed evidence declares its applicability.

P1 is complete. P2A inventory/baseline is complete; full P2 admission stays in progress. P3 is inactive. Create no P1 record/run/source, authority, writer or public evidence endpoint here. The eventual Digital Twin derives its definition from admitted evidence/topology, then combines timestamped physical states; the 3D layer is only spatial evidence.

### P2B reviewed site identity

`engine/site_physical_identity_authority.py` loads the separately reviewed [Bracon identity file](../evidence/authorities/bracon-ash/site-identity.yaml), not an auto-generated SiteConfig authority. See the [identity contract](architecture/site-physical-identity-authority.md). The frozen declaration covers only site ID/UUID/name, configured latitude/longitude and exact timezone; no capacity, population, inventory, geometry completeness or electrical topology belongs to it. Source is `config/sites.yaml`, confidence `unknown`. An independent validator and pure exact manifest/authority/SiteConfig binding check guard admission; no runtime consumes it automatically.

At P2B, manifest `bracon-ash-site-identity-admitted-v2` admitted only `site.identity.physical`. Evidence remains 17/48/1/0; admission is 1/16/49/0 and active fidelity 1/0/65/0. All nine baseline/full-fidelity labels become partially admitted solely through identity, with required blockers retained and no fully admitted section. The other 65 items are unchanged; all three population representations stay conflicting and `electrical_topology` is still `None`. P2 remains in progress and P3 inactive. Neither implementation-delta Priority A nor B is advanced by identity evidence.

### P2C configured lower-fidelity module basis

The [module electrical authority](architecture/site-module-electrical-authority.md)
and `engine/site_module_electrical_authority.py` bind the reviewed declaration at
`evidence/authorities/bracon-ash/module-electrical-basis.yaml` to explicit config,
manifest and supplied local-library evidence. It admits only `site.module.model_label`
and `module.electrical_parameters`, at lower fidelity: configured JKM570N-72HL4-BDV,
mono_si, datasheet_fit/low, expected Tier 3/local_library. Real runtime lookup is
regression-checked without forcing the tier. Raw STC authority is separate from
runtime-owned fit_desoto_batzelis → calcparams_desoto → singlediode.

At P2C, manifest `bracon-ash-module-electrical-lower-fidelity-admitted-v3` had
17/48/1/0 evidence, 3/14/49/0 admission and 1/2/63/0 support. Module-electrical
baseline blockers reduce 10 → 9; full blockers stay 10. All nine sections retain
blockers; other section coverage and the other 63 unadmitted items are unchanged.
The library's i_sc correction note is repository evidence, not independent
manufacturer certification. No as-built population, serial/flash inventory,
thermal/optical or topology authority is admitted. Installed temporal applicability
remains unknown, population counts remain conflicting and electrical_topology None.
P2 remains in progress; P3 inactive. Priority A/B remain pending. No runtime or
production source change is made.

### P2D — configured uniform lower-fidelity series-count basis

The [series-count authority](architecture/site-string-series-count-authority.md) admits only
`s8.string_module_count`, using the configured exact integer **24 modules/string**.
This is a configured uniform lower-fidelity series-count basis, not a physical
string inventory or topology authority. The separately reviewed declaration uses
only `config/sites.yaml`; temporal applicability and confidence remain unknown.
The configured string count of **2076 remains unadmitted**, retained only as a manifest
source fact. No IDs, members or MPPT/inverter mappings are created.

At P2D, manifest: `bracon-ash-string-series-count-lower-fidelity-admitted-v4`.
Evidence remains 17/48/1/0; admission is 4/13/49/0; support is 1/3/62/0.
S8 baseline blockers reduce 8 → 7; full-fidelity blockers remain 9.
All other coverage and all 65 other manifest items remain unchanged from P2C.
All nine sections retain blockers. Population 49,824 / 47,448 / 50,736 remains
conflicting; electrical_topology remains None. Canonical S8 still needs explicit
per-string counts in independently admitted topology. P2D creates none; later
consumption requires a reviewed binding that permits the uniform assumption.
No physics, runtime, configuration or production source changes. P2 continues;
P3 remains inactive.

### P2E — consolidated upstream physical-input admission package

The [P2E boundary](architecture/site-upstream-physical-input-admission.md) owns all remaining upstream weather/time,
irradiance/optics, spectral/thermal model and sensor/zone/environment admission.
Only `irradiance.bifacial_applicability` is newly admitted, as configured lower-fidelity
model-class applicability for JKM570N-72HL4-BDV / mono_si / bifacial true. This is
not receiver coverage or canonical electrical response: the generic 0.80 factor
remains an unadmitted fact, not phi_Isc. No rear model, shading topology, weather
time semantics, irradiance plane, spectral or thermal authority is invented.

At P2E, manifest: `bracon-ash-upstream-physical-input-admission-v5`.
Evidence remains 17/48/1/0; admission is 5/12/49/0; support is 1/4/61/0.
Only upstream-environment baseline blockers reduce 7 → 6; full blockers stay 8.
Every other section and all 65 other items remain unchanged. All paths retain
blockers. The 608 geometry points are not a 50,736-module inventory. Population
49,824 / 47,448 / 50,736 remains unresolved; electrical_topology remains None.

P2E is implemented as the current reviewed admission/evidence-request package,
not upstream readiness for P3. Future upstream evidence updates P2E in place;
do not create a new P2 letter per field. P2F is reserved for the consolidated DC
plant + inverter/control boundary. Full P2 remains in progress and P3 inactive.

The engine authority is `site_bifacial_applicability_authority.py`; the reviewed
file is `evidence/authorities/bracon-ash/bifacial-applicability.yaml`. It has an
independent validator and exact supplied-path config/library binding. It consumes
only identity/model/technology/bifacial boolean, never factor, geometry, population
or thermal data. P2G remains AC network/meter and P2H benchmark/uncertainty/closure.
Read the four consolidated evidence bundles before any further upstream work.

### P2F — consolidated DC plant + inverter/control admission package

The [P2F boundary](architecture/site-dc-inverter-control-admission.md) owns population/DC topology, inverter
equipment/capability and controller requests/allocation as one onboarding package.
Only `s8.inverter_inventory_binding` is newly admitted: 66 configured inverter
labels and layout-group memberships, at explicit lower fidelity. The ordered
MQA11/MQA21/MQA22/MQA23 groups contain 16/16/17/17 labels. Confidence and installed
temporal applicability remain unknown; no as-built equipment verification is claimed.

Current manifest: `bracon-ash-dc-inverter-control-admission-v6`.
Evidence remains 17/48/1/0; admission is 6/11/49/0; support is 1/5/60/0.
Only S8 baseline blockers reduce 7 → 6; full blockers stay 9. All other coverage
and all 65 other items remain unchanged. All sections still retain blockers.
Configured labels do not create electrical topology. Model names are not exact
CEC/SAM references; PVWatts/eta are not canonical S9 conversion authority; active
nameplate is not Smax; the aggregate grid cap is not controller dispatch.

Population 49,824 / 47,448 / 50,736 stays conflicting; 2076 strings remains
unadmitted and electrical_topology remains None. No IDs/mappings, resistance,
population residual, equipment capability or controller authority are inferred.
P2F is implemented as the current reviewed package, not physical readiness for P3.
Further DC/inverter/controller evidence updates P2F in place; P2E still owns upstream
evidence. P2 remains in progress; P3 inactive. P2G is next and remains reserved for
AC network + transformer + revenue-meter authority.

The engine module is `site_inverter_inventory_authority.py`; the reviewed file is
`evidence/authorities/bracon-ash/inverter-inventory.yaml`. Nested frozen groups and
independent validators enforce identity, count closure, unique labels and exact
provenance. Guarded binding reads only site identity, inverter.num_units and group
IDs/counts/labels. Model, capability, coordinates, module/topology and control
fields are excluded. No ElectricalTopologyConfig is constructed.

### P2G — downstream AC network / transformer / meter evidence review

The [P2G review](architecture/site-ac-network-meter-admission.md) is a **zero-admission** package spanning
S11 LV collection, S12 transformer and S13 MV/HV/grid/revenue-meter boundaries.
P2G is complete as the current evidence-review package; it is not physically
admitted. All 22 S11/S12/S13 items remain missing/blocked. No manifest, evidence
scope, authority YAML or engine authority implementation changes are made.

Manifest remains `bracon-ash-dc-inverter-control-admission-v6`: evidence 17/48/1/0,
admission 6/11/49/0 and support 1/5/60/0. All six P2F admissions are preserved.
S11 baseline/full blockers stay 5/5; S12 stays 5/7; S13 stays 9/9. Harmonic evidence
remains optional, not a baseline transformer blocker. The complete serialized
manifest and all 66 items are fingerprint-tested against PR #138 merge
`076c310ce6087048e266bc42cc3bff95b76084d3`.

The migration CSV is reviewed only for header/site-UUID association. It remains
non-authoritative migration data, not meter identity, location, CT/PT scaling,
signs, interval/timestamp semantics, calibration or accuracy. It is not added to
S13 source references and changes no missing evidence to present. Site UUID is
not meter identity. Legacy 1.70% AC loss is not physical impedance or an allocated
LV/transformer/MV-HV loss budget; future activation needs a no-double-counting
ownership decision. P2G changes no runtime and retires no percentage.

Four practical evidence bundles cover LV collection, transformers, MV/HV/grid
and revenue meter. Future downstream evidence updates P2G in place; upstream/DC
items stay owned by P2E/P2F. electrical_topology remains None and population
49,824 / 47,448 / 50,736 remains unresolved. P2 remains in progress; P3 inactive.
P2H is next and remains the final consolidated benchmark/uncertainty/P2 closure
increment. Completion of a review package does not authorize physical execution.

### Physics implementation-delta recovery

The canonical [implementation-delta ledger](architecture/physics-implementation-delta.md) reconciles supplied original Stage 1–6 design intent with current software ownership. The original seven DOCX titles are external engineering references, not repository paths; they remain valuable and are not edited or replaced here. Reconcile original engineering document detail with mechanism ownership before implementation: identify the canonical owner, evidence, reference plane, fidelity and interaction/non-overlap rule first.

Every ledger decision uses exactly one of `KEEP_CANONICAL`, `DOCUMENTATION_ALIGNMENT`, `ADVANCED_FIDELITY_PENDING` or `SITE_EVIDENCE_PENDING`. Priority A is the future advanced S8 member/sub-string/bypass route; Priority B is future cable/conductor parameter derivation feeding existing S8/S11/S13 solvers. Preserve the homogeneous string baseline, existing MPPT/branch/network solvers and S12 transformer ownership. Do not add a second gamma, spectral factor or loss subtraction to match an older stage equation. P2 evidence determines defensible site fidelity; these advanced items are not automatic blockers for every valid lower-fidelity P3 path.

Status is contingent on successful post-merge main CI #335 on the exact PR #131 merge: P0, platform authorization, P1 and P2A complete; P2 site authority admission in progress; P3 inactive. The ledger is not Twin evidence and closes no Bracon admission gap.

### Known pre-shadow blockers

Do not describe the full weather-to-meter chain as production-validated yet.

- **Weather time semantics:** Solcast `period_end` is stored directly and SCADA period-start timestamps are normalised to period-end, while the legacy POA runtime evaluates solar position at the stored timestamp. Generic explicit weather-time authority and observation-keyed SPA alignment now exist; source-specific binding and production integration remain absent.
- **IAM integration defect:** legacy `calculate_poa()` computes IAM-corrected beam irradiance but assembles `poa_total` from uncorrected `poa_front`.
- **Measured-front bifacial gap:** the measured-POA shortcut explicitly sets rear irradiance to zero.
- **Module thermal integration remains dormant:** the generic canonical authority/state contract now exists, but `physics/thermal.py` remains the active legacy runtime. Its measured-module cell offset currently yields 0.03 °C at 1000 W/m² despite the code comment describing about 3 °C, and configured `u_c/u_v` values are passed directly into a Faiman `u0/u1` interface.
- **Population-residual site admission remains open:** S8-1 remains homogeneous series scaling and shared-MPPT mismatch remains physical S8 ownership. A separate generic bounded intra-string residual authority now exists, with explicit negligible or post-MPPT equivalent-current-derate modes. It is lower fidelity, not member-resolved I-V physics. Missing authority leaves active population-complete output unresolved; resolved-zero upstream states remain exact zero without authority; legacy aggregate mismatch cannot be retired without allocation evidence.
- **S14B site support-policy admission remains open:** generic v2 eligibility now requires explicit per-meter maximum-gap authority after finite reconstruction. No default gap/cadence or Bracon threshold is inferred. Synthetic daylight-edge tests justify the distinction, not a universal policy value.
- **Measurement uncertainty is quantitative generically:** a separate dormant authority annotates canonical S13D with explicit complete-chain numerical bounds. Categorical confidence is provenance only. Combined interval magnitudes now exist separately; deterministic S14B envelope interpretation is now implemented generically.
- **Platform authorization implementation is complete:** Firebase verification supplies an exact `platform_admin` claim for global operations; exact `user_site_access` viewer/admin roles protect site resources. Browser administrator secrets are retired. Trusted claim bootstrap and deployment verification remain operational steps; no shadow output is activated.
- **S9-4A fixed-Q sign semantics are not locally declared:** downstream convention is positive Q injection / negative Q absorption; source evidence using another convention must be transformed before S9-4A construction.

P0 is complete. Generic module thermal plus weather-time/irradiance-boundary implementation does not close site admission, calibrated thermal-POA selection or production integration. P3 shadow execution and P4 accuracy claims must not pass the remaining gates by implication.

## Module-population residual recovery notes

`apply_module_population_mismatch(topology, mppt_mismatch, authority_by_mppt=...)` composes the exact `TopologyMPPTMismatchResult` with explicit physical MPPT-key authority. It replays baseline V/I/P and shared mismatch; authority never fans out implicitly. Extra/empty-MPPT keys are rejected. Both authority modes are bounded lower fidelity: `explicit_negligible_by_evidence` requires f=0; `equivalent_post_mppt_current_derate` requires 0<f<1. The exact mechanism excludes shared-MPPT mismatch, optical/thermal losses, wiring, soiling, LID and conversion.

For resolved active authority rows, V_after=V_common, I_after=I_common(1−f), P_after=V_after I_after. Population loss is P_common−P_after; total mismatch closes both as shared+population and P_independent−P_after. Missing population evidence retains valid S8 values but active adjusted V/I/P stay NaN. Unresolved upstream cannot be repaired. Resolved-zero upstream stays exactly zero with or without authority, without fabricating a fraction; its selected path is not lower fidelity. Independent validation reconstructs equations, provenance, states and diagnostics without production builders. Upstream admission verifies the published aggregated S8 contract and internal consistency, including exact cause vocabulary/order and topology-ordered unresolved IDs; it does not reconstruct unavailable member-to-cause assignments.

No SiteConfig or legacy mismatch percentage is consumed. Bracon's 1.15% is not authority and remains on the legacy series only. Nameplate tolerance alone does not define member current/voltage distribution. Future member-resolved physics must compose series voltages at common current with explicit reverse/bypass authority where needed. DC collection is not integrated with this new boundary here; P1 output contract is now implemented separately; P2 admission remains in progress and P3 inactive.

## S14B support-policy recovery notes

`revenue_meter_interval_support_policy.py` defines frozen `RevenueMeterIntervalSupportPolicyAuthority`, supplied to S14B via `revenue_meter_interval_support_policy_by_meter_id`. Omission means an empty mapping. Partial meter coverage is allowed; unknown/non-string keys, malformed mappings and tampered frozen authorities are rejected. No global/site-config policy or automatic fan-out exists.

S14B v2 preserves exact boundaries, exact selected S13C support, piecewise-linear reconstruction and trapezoidal integration. It publishes reconstruction resolved separately from support eligibility. Missing policy gives `unresolved_missing_expected_interval_support_policy`; actual max gap greater than the admitted seconds gives `unresolved_expected_interval_support_gap_exceeds_policy`. Equality passes. Finite reconstructed energy/averages and gap diagnostics remain visible in both failure cases; all eight benchmark residual fields remain NaN. Gap/interval fraction is diagnostic, never an implicit threshold.

Policy presence/provenance is visible on supplied rows even when an earlier failure prevents assessment. Diagnostics count missing/present policy only after finite reconstruction; pass/fail partition the reconstructed rows with policy. Instantaneous and upstream-failed rows are not missing-policy gaps. The independent validator rebuilds support, integration, policy admission, fields and diagnostics without production builders or the policy-resolution helper. S14C consumes S14B eligibility and exact support timestamps; its accounting contract/numerics are unchanged.

The generic support-policy gate is complete (PR #122); site policy evidence and P2 remain open; authorization implementation is complete. No production/shadow switch is activated. Bracon has no admitted support threshold. Synthetic quadratic-edge errors describe only the checked-in proxy.

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

Completed generically: P0 source isolation, module thermal (PR #119), weather-time authority and date-consistent canonical irradiance boundary (PR #120), and bounded population-residual authority (PR #121). Generic S14B support eligibility was completed in PR #122; complete-chain measurement bounds were completed in PR #124; pointwise complete-model bounds were completed in PR #125; discrete expected-model interval propagation is complete generically (PR #126); combined interval magnitudes are complete generically (PR #127). Remaining sequence: P1 output contract complete → P2 site evidence (including population residual and support policy) → P3. Shadow activation is not implemented.

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
4. Read `docs/development/physics-roadmap.md` and `docs/architecture/physics-implementation-delta.md` before translating an original design equation into code.
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

Local development uses focused changed-feature tests and the immediate affected regression slice. PR and main-push CI both use the conservative exact-diff backend selector: `skip`, `targeted` or `full`. PR boundaries are the event's base/head SHAs; main-push boundaries are `github.event.before` and `github.sha`, with full history available. Unknown/unusable history, analysis failure, broad config/dependencies/migrations, deleted/untraceable Python or unsafe impact selects full. Docs/frontend-only changes keep a successful backend check without dependency setup/tests. Superseded same-PR runs are cancelled; different PRs, main pushes and full regressions do not cancel one another. Report the exact SHA and actual mode: a targeted post-merge pass is valid change-scoped validation, not a complete backend sweep.

The [Full Backend Regression workflow](../.github/workflows/full-backend-regression.yml) runs the complete `python -m pytest tests/unit/ -q --no-header --no-cov` suite nightly at **03:17 UTC** and on manual dispatch. It is the authoritative complete regression sweep. Before P3 activation, P5 cutover, release-candidate validation or major dependency, migration or shared-infrastructure release decisions, require a successful manually dispatched full regression on the intended `main` revision and verify the run's exact head SHA. An older nightly does not validate later commits. No CI result alone authorizes activation.

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

Engineering sequence: measurement uncertainty complete; pointwise expected-model uncertainty complete; expected-model interval propagation complete (PR #126); combined interval magnitudes complete (PR #127); eligible deterministic S14B envelope interpretation complete (PR #128); platform authorization implemented and tested; P2 site evidence finalisation next. P3 shadow execution is not activated. Bracon has no invented numerical admission. S14B/S14C numerics, source isolation, `physics_sdm` and production/shadow behaviour remain unchanged.

## Deterministic interval envelope interpretation

`resolve_revenue_meter_interval_uncertainty_interpretation` reconstructs the public combined parent from original inputs and all three authority/policy mappings, then exact-replays the entire supplied result. The output preserves its full state frame and appends only envelope relations, zero-centred endpoints, nonnegative excess magnitudes and interpretation states. No additional provenance snapshot or numerical authority is introduced.

Gate order: S14B `benchmark_eligible` first; P/Q combined availability second; finite canonical residual and finite nonnegative bound third. Ineligible rows publish no relation or envelope endpoints and are not uncertainty-coverage gaps. Each channel needs both independently interpreted power and energy quantities. Exact equality means on-boundary; no tolerance or `isclose`. Missing authority and nonfinite arithmetic remain distinguishable through parent/channel states.

Measurement, pointwise-model, interval-propagation and combined bounds are complete generically. Eligible deterministic S14B envelope interpretation is complete generically (PR #128). Platform authorization is implemented and tested; P2 site evidence finalisation is next, and P3 remains inactive. Inside does not prove correctness; outside is neither a physical loss nor a fault/causal/commercial finding. No probability or statistical significance is claimed. Bracon numerical admission, source selection, production and shadow behavior are unchanged.

## Server-side authorization readiness

Firebase authentication now exposes only uid, email and the exact boolean `platform_admin` custom claim. Global operations require that claim; site reads require exact viewer/admin membership and site mutations require admin membership. Verified platform administrators explicitly bypass membership. Missing or invalid membership fails closed; viewers cannot mutate and site admins are not platform admins. No email/domain, browser-secret, environment or Bracon inference exists.

The [platform authorization policy](architecture/platform-authorization.md) documents every current route, canonical alert ownership before acknowledgement, validated access grants, secret retirement and out-of-band Firebase claim bootstrap/token refresh. The focused tests enforce all 19 application route policies and cross-site denials. Health remains public and `/api/v1/admin/me` remains authenticated identity introspection. Frontend navigation is not authorization.

The generic revenue-meter uncertainty stack is complete at PR #128. Authorization implementation is now complete and tested; P2 site evidence finalisation is next. Physics, S14, uncertainty, `physics_sdm`, source selection and Bracon physical admission remain unchanged. P1 output contract is complete generically; P2 admission remains in progress and no P3 shadow execution or deployment occurs.
