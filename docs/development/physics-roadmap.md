# Physics development roadmap

Current canonical code checkpoint: `df54d99267f451718a125a1cebcc090726514241` (PR #141 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

Source-of-truth order: live source, tests, exact git history/merged PRs and current main, then documentation. CI must be checked on the exact reviewed commit.

## Completed generic electrical chain

```text
UPSTREAM WEATHER / IRRADIANCE / MODULE THERMAL
(production-readiness hardening still required)
↓
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

S8 physical strings/common-voltage MPPT/direct DC branches, S9 conversion/capability/thermal capability, S10 request/feasibility/selection, S11 LV collection, S12A–M transformer, S13A–D MV/HV/meter authority and S14A–C benchmarks/accounting are implemented and validated generically **from admitted module electrical state onward**. See the [architecture](../architecture/physics-architecture.md) for stage responsibilities and exact contract names.

S10 selects only an exact fully feasible request. It does not infer export allocation or controller policy for infeasible requests. S11–S13 solve modelled balanced electrical states, not measured output. S14 accounting is not proof of causality.

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

## Next major phase — production integration

Production integration + site evidence onboarding is the immediate workstream. The legacy expected-energy runtime remains active; S8–S14 capability is not automatically production-active. The canonical [production-integration roadmap](production-integration-roadmap.md) owns migration decisions, phases P0–P6, the loss-ownership ledger and the pre-shadow readiness gates. P0 expected-energy source isolation is complete at PR #118; module thermal is complete generically at PR #119 and weather-time/irradiance boundary was implemented in PR #120; both remain dormant; shadow execution has not been activated and must not bypass the upstream readiness gates.

Production integration does not add S12N, S13E, S14D or S15. The S-stage sequence remains the physical modelling architecture.

“Implemented generically” means the reusable physics contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

## Required pre-shadow upstream hardening

These items are not additional S12/S13/S14 stages. They are prerequisites for calling a physical shadow run end-to-end:

- generic explicit weather-time authority and observation-keyed NREL-SPA alignment are now implemented; bind source-specific semantics and duration evidence before integration;
- the new canonical boundary replays upstream IAM/shading exactly once; legacy IAM defects remain in the unmodified production path until controlled migration;
- the new canonical boundary preserves measured front and modelled rear independently, without selecting a calibration/thermal basis; site evidence binding remains required;
- generic canonical module thermal authority/state is now implemented; onboard explicit site evidence and thermal POA/time authority before using it in a physical run;
- retain the legacy cell/module delta and PVsyst/Faiman mismatch in compatibility runtime until controlled migration; the new native-authority contract avoids both defects;
- the generic bounded intra-string population-residual authority now complements physical shared-MPPT mismatch; admit site evidence and legacy allocation before retirement; member-resolved manufacturing/reverse/bypass physics remains future work;
- generic S14B v2 maximum-gap eligibility authority and synthetic daylight-edge regressions are now implemented; admit an evidence-backed per-meter site policy without inferring a universal threshold;
- admit site evidence for the generic measurement and pointwise expected-model bounds; retain separate discrete interval propagation and generic eligible deterministic envelope interpretation; retain authorization enforcement and continue P2 site authority admission after completed P1/P2A;
- preserve the completed platform-authorization boundary (PR #129); no browser-admin-secret fallback or site-membership bypass for ordinary users;
- explicitly declare S9-4A fixed-Q sign semantics at the authority boundary.

Completed: P0, generic module thermal (PR #119), generic weather-time/irradiance boundary (PR #120), bounded population residual (PR #121), all dormant from physical shadow activation. S14B explicit support eligibility is complete generically (PR #122), as are measurement bounds (PR #124). Pointwise complete-model bounds are complete generically (PR #125). Discrete S14B expected-model interval propagation is complete generically (PR #126); combined interval magnitudes are complete generically (PR #127). P1 and P2A–P2H review are complete; outstanding evidence updates P2E–P2H in place. Bracon physical admission remains incomplete; P3 is BLOCKED and INACTIVE. Site weather/optics/thermal, population residual and support-policy admission remain explicit. P3/P4 must not treat site admission or remaining gates as implicitly solved.

## Bounded population mismatch capability

Generic mismatch coverage now supports physical shared-MPPT mismatch, an explicit lower-fidelity intra-string population residual, and explicit unresolved active population output when evidence is absent. Resolved-zero upstream remains exact zero without population authority because the mechanism is inactive. The two residual modes are negligible-by-evidence and equivalent post-MPPT current derate. Neither changes homogeneous string scaling. Valid S8 baseline survives missing residual authority; no legacy percentage is read. Bracon is not admitted and its aggregate 1.15% is not retired. Site applicability/MPPT coverage and non-overlap evidence remain required. P1 and P2A are complete; P2 review is complete, Bracon physical admission incomplete and P3 blocked/inactive.

## Bounded future physics

The canonical [implementation-delta ledger](../architecture/physics-implementation-delta.md) reconciles the original external Stage 1–6 design intent with current owners. It identifies two principal advanced-fidelity workstreams, with topology and isolated section reverse-I-V slices implemented:

1. **Priority A — advanced S8 member/sub-string and bypass-diode path:** Stage4a-1 topology authority is complete and dormant; Stage4a-2 explicit reverse-breakdown authority and isolated Bishop section I-V are complete by this PR; [bounded sequence and evidence rules](../architecture/advanced-string-bypass-architecture.md). Geometry/shading binding, diode authority/clamp and composition remain pending. No module parameters are split into sections. Remaining work: shaded cell/sub-string state, explicit diode clamp behavior, current-consistent series composition and reviewed multi-peak/all-candidate/global selection/diagnostics. Preserve homogeneous string I-V as a valid baseline and the existing string-terminal → direct branch → shared MPPT → S9 boundaries. Existing sampled-candidate selection must not be relabelled as a bypass-resolved global tracking model.
2. **Priority B — cable/conductor parameter authority:** derive electrical parameters from explicit construction, installation and temperature evidence, including additional AC effects only where admitted. Feed existing S8 direct branch, S11 series R/X and S13 nominal-pi owners; extend those contracts where needed rather than subtracting cable power in a parallel engine. Keep S12 transformer losses separate.

Neither is a universal prerequisite for P3. P2 determines the site's evidence, intended fidelity and material benefit; a valid lower-fidelity path still needs explicit admission and all remaining activation gates. Engerer2, thermal calibration/dynamics, flash-data variability and arbitrary shared DC collection remain lower-priority refinements where evidence/use case requires them. Shared-feeder sites cannot pretend direct independent branches cover their shared conductors.

Genuine future physics extensions include arbitrary/shared DC collection beyond direct-branch coverage, substring/bypass-diode partial shading and multiple local maxima, dynamic physical/measured soiling, snow, arbitrary 3D/tracker/rear-obstruction coverage, member-resolved module-population variability where required, justified unbalanced/sequence network extensions, and transformer ageing/dynamic thermal models when evidence and use cases support them. These are separate extensions, not unfinished current S12–S14 contracts.

Direct-branch resistance does not cover shared post-parallel DC conductors. A shared feeder acts on total current and must not be duplicated across branches. Resolve as-built topology before claiming that coverage. Do not replace partial-shading or dynamic soiling mechanisms with renamed percentages.

## Validation cadence

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`. Run optical/rear regressions when shared dependencies warrant them.

PR/main CI uses conservative exact-diff skip/targeted/full selection; nightly/manual CI supplies the complete backend regression. Do not repeatedly run the full local backend after hardening changes. A full local suite may be run deliberately when justified, but is not the default. Documentation-only changes require Markdown/link/whitespace checks rather than backend tests. Check the exact base/head and live CI for review or release decisions.

## Site evidence

Bracon Ash remains a reference site, not a topology template. Review its [evidence gaps and capacity discrepancy](../sites/bracon-ash.md) before attempting a resolved end-to-end timestamp. Do not infer mappings, dispatch, thermal state, network voltage or meter identity from configuration labels or aggregate capacities.

## Combined revenue-meter interval uncertainty

`physics/revenue_meter_combined_interval_uncertainty.py` is a dormant annotation of independently validated measurement uncertainty and expected-model interval uncertainty. It introduces no numerical authority. Both parents are canonically reconstructed from original inputs/mappings and exact-replayed. The interval parent defines the ordered timestamp/meter universe; shared interval, reference-plane, sign and power-basis semantics must agree. Its complete frame is preserved, with an exact measurement-uncertainty snapshot.

For each P/Q channel and each published interval-average power/energy quantity, `B_combined = math.fsum((B_measurement, B_expected_model))`. This is the deterministic tight triangle-inequality bound for `δ_measurement - δ_model`, with no probability, independence, covariance or RSS assumption. The layer consumes published magnitudes; it does not recalculate either parent or repeat trapezoidal propagation. Missing channels and nonfinite arithmetic stay unresolved independently.

Combined resolution does not imply benchmark eligibility. Missing/exceeded S14B support policy remains unchanged; withheld residuals remain NaN. No residual, residual envelope, significance flag or commercial result is reconstructed. The bound still excludes numerical support-density/continuous-path error.

Engineering sequence: measurement uncertainty complete; pointwise expected-model uncertainty complete; expected-model interval propagation complete (PR #126); combined interval magnitudes complete (PR #127); eligible deterministic S14B envelope interpretation complete (PR #128); platform authorization implemented and tested; P2 site authority admission next. P3 shadow execution is not activated. Bracon has no invented numerical admission. S14B/S14C numerics, source isolation, `physics_sdm` and production/shadow behaviour remain unchanged.

## Deterministic envelope interpretation readiness

Eligible S14B residual-envelope interpretation is now implemented generically and dormant, following the completed measurement, pointwise-model, interval-propagation and combined-bound layers. It classifies the exact canonical residual against the deterministic zero-centred envelope only after S14B eligibility; inside is not model correctness and outside is not physical loss, fault, causality or statistical significance.

Platform authorization is implemented and tested; P2 site authority admission is next. S14C remains unchanged, Bracon has no invented numerical admission, and P3/production/shadow execution is not activated.

## Server-side authorization readiness

Firebase authentication now exposes only uid, email and the exact boolean `platform_admin` custom claim. Global operations require that claim; site reads require exact viewer/admin membership and site mutations require admin membership. Verified platform administrators explicitly bypass membership. Missing or invalid membership fails closed; viewers cannot mutate and site admins are not platform admins. No email/domain, browser-secret, environment or Bracon inference exists.

The [platform authorization policy](../architecture/platform-authorization.md) documents every current route, canonical alert ownership before acknowledgement, validated access grants, secret retirement and out-of-band Firebase claim bootstrap/token refresh. The focused tests enforce all 19 application route policies and cross-site denials. Health remains public and `/api/v1/admin/me` remains authenticated identity introspection. Frontend navigation is not authorization.

The generic revenue-meter uncertainty stack is complete at PR #128. Authorization implementation is now complete and tested; P2 site authority admission is next. Physics, S14, uncertainty, `physics_sdm`, source selection and Bracon physical admission remain unchanged. P1 and P2A are complete; P2 review is complete, Bracon physical admission incomplete and P3 blocked/inactive.

## Integration checkpoint and evidence gate

Status is contingent on successful main CI #335 on `879bb186b459b7be344b3ad01337863213b0a086`: P0 source isolation, platform authorization, P1 output contract and P2A evidence manifest/baseline are complete; full P2 site authority admission is in progress; P3 shadow execution is inactive. Generic capability, evidence, admission, timestamp resolution, output and activation remain distinct. The implementation-delta ledger adds governance only and does not close Bracon's population, topology, equipment, meter or uncertainty gaps.
