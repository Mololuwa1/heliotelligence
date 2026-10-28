# Physics development roadmap

Current canonical code checkpoint: `580327062d0f984c82888c5d394d60e380afaa86` (PR #119 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

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

Production integration + site evidence onboarding is the immediate workstream. The legacy expected-energy runtime remains active; S8–S14 capability is not automatically production-active. The canonical [production-integration roadmap](production-integration-roadmap.md) owns migration decisions, phases P0–P6, the loss-ownership ledger and the pre-shadow readiness gates. P0 expected-energy source isolation is complete at PR #118; module thermal is complete generically at PR #119 and weather-time/irradiance boundary is implemented in this increment; both remain dormant; shadow execution has not been activated and must not bypass the upstream readiness gates.

Production integration does not add S12N, S13E, S14D or S15. The S-stage sequence remains the physical modelling architecture.

“Implemented generically” means the reusable physics contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

## Required pre-shadow upstream hardening

These items are not additional S12/S13/S14 stages. They are prerequisites for calling a physical shadow run end-to-end:

- generic explicit weather-time authority and observation-keyed NREL-SPA alignment are now implemented; bind source-specific semantics and duration evidence before integration;
- the new canonical boundary replays upstream IAM/shading exactly once; legacy IAM defects remain in the unmodified production path until controlled migration;
- the new canonical boundary preserves measured front and modelled rear independently, without selecting a calibration/thermal basis; site evidence binding remains required;
- generic canonical module thermal authority/state is now implemented; onboard explicit site evidence and thermal POA/time authority before using it in a physical run;
- retain the legacy cell/module delta and PVsyst/Faiman mismatch in compatibility runtime until controlled migration; the new native-authority contract avoids both defects;
- decide how module-to-module tolerance/series variability is represented before retiring the entire legacy mismatch percentage;
- establish S14B support-density/max-gap eligibility with sunrise/sunset regressions;
- add quantitative uncertainty evidence, including meter accuracy/calibration evidence where available;
- close browser-admin-secret and per-site authorization gaps before shadow data is exposed outside the trusted development team;
- explicitly declare S9-4A fixed-Q sign semantics at the authority boundary.

Completed: P0, generic module thermal (PR #119), generic weather-time/irradiance boundary (this increment), all dormant from physical shadow activation. Next: site weather/optics/thermal evidence binding plus mismatch completeness → S14B density → quantitative uncertainty → platform authorization → P1/P2 finalisation → P3. P3/P4 must not treat site admission or remaining gates as implicitly solved.

## Bounded future physics

Genuine future physics extensions include arbitrary/shared DC collection beyond direct-branch coverage, substring/bypass-diode partial shading and multiple local maxima, dynamic physical/measured soiling, snow, arbitrary 3D/tracker/rear-obstruction coverage, explicit module-population variability where required, justified unbalanced/sequence network extensions, and transformer ageing/dynamic thermal models when evidence and use cases support them. These are separate extensions, not unfinished current S12–S14 contracts.

Direct-branch resistance does not cover shared post-parallel DC conductors. A shared feeder acts on total current and must not be duplicated across branches. Resolve as-built topology before claiming that coverage. Do not replace partial-shading or dynamic soiling mechanisms with renamed percentages.

## Validation cadence

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`. Run optical/rear regressions when shared dependencies warrant them.

GitHub CI is the authoritative full-backend validation. Do not repeatedly run the full local backend after hardening changes. A full local suite may be run deliberately when justified, but is not the default. Documentation-only changes require Markdown/link/whitespace checks rather than backend tests. Check the exact base/head and live CI for review or release decisions.

## Site evidence

Bracon Ash remains a reference site, not a topology template. Review its [evidence gaps and capacity discrepancy](../sites/bracon-ash.md) before attempting a resolved end-to-end timestamp. Do not infer mappings, dispatch, thermal state, network voltage or meter identity from configuration labels or aggregate capacities.
