# Physics development roadmap

Current canonical code checkpoint: `d8f8d7eb44e2e611be03c09ca0f3cfda7846b42a` (PR #115 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

Source-of-truth order: live source, tests, exact git history/merged PRs and current main, then documentation. CI must be checked on the exact reviewed commit.

## Completed generic physical chain

```text
WEATHER / QC
↓
SOLAR GEOMETRY / IRRADIANCE
↓
FRONT + REAR OPTICS / SHADING / IAM / SPECTRAL
↓
CANONICAL ELECTRICAL IRRADIANCE
↓
THERMAL
↓
MODULE ELECTRICAL
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

S8 physical strings/common-voltage MPPT/direct DC branches, S9 conversion/capability/thermal capability, S10 request/feasibility/selection, S11 LV collection, S12A–M transformer, S13A–D MV/HV/meter authority and S14A–C benchmarks/accounting are implemented and validated generically. See the [architecture](../architecture/physics-architecture.md) for stage responsibilities and exact contract names.

S10 selects only an exact fully feasible request. It does not infer export allocation or controller policy for infeasible requests. S11–S13 solve modelled balanced electrical states, not measured output. S14 accounting is not proof of causality.

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

## Next major phase — production integration

Production integration + site evidence onboarding is the immediate workstream. The legacy expected-energy runtime remains active; S8–S14 capability is not automatically production-active. The canonical [production-integration roadmap](production-integration-roadmap.md) owns migration decisions, phases P0–P6 and the loss-ownership ledger. P0 expected-energy source isolation is next planned work; shadow execution has not been activated.

Production integration does not add S12N, S13E, S14D or S15. The S-stage sequence remains the physical modelling architecture.

“Implemented generically” means the reusable physics contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

## Bounded future physics

Genuine future physics extensions include arbitrary/shared DC collection beyond direct-branch coverage, substring/bypass-diode partial shading and multiple local maxima, dynamic physical/measured soiling, snow, arbitrary 3D/tracker/rear-obstruction coverage, justified unbalanced/sequence network extensions, and transformer ageing/dynamic thermal models when evidence and use cases support them. These are separate extensions, not unfinished current S12–S14 contracts.

Direct-branch resistance does not cover shared post-parallel DC conductors. A shared feeder acts on total current and must not be duplicated across branches. Resolve as-built topology before claiming that coverage. Do not replace partial-shading or dynamic soiling mechanisms with renamed percentages.

## Validation cadence

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`. Run optical/rear regressions when shared dependencies warrant them.

GitHub CI is the authoritative full-backend validation. Do not repeatedly run the full local backend after hardening changes. A full local suite may be run deliberately when justified, but is not the default. Documentation-only changes require Markdown/link/whitespace checks rather than backend tests. Check the exact base/head and live CI for review or release decisions.

## Site evidence

Bracon Ash remains a reference site, not a topology template. Review its [evidence gaps and capacity discrepancy](../sites/bracon-ash.md) before attempting a resolved end-to-end timestamp. Do not infer mappings, dispatch, thermal state, network voltage or meter identity from configuration labels or aggregate capacities.
