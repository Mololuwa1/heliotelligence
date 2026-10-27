# Heliotelligence

Heliotelligence is a physics-first solar digital twin and performance benchmarking platform for utility-scale PV assets. It preserves component state, provenance and measurement boundaries so energy conversion, limits, transport and losses can be explained.

## Architectural principles

Use explicit equipment, topology, operating and measurement evidence. Preserve missing authority separately from zero, modelled state separately from telemetry, and each mechanism's single owner. Never infer topology, capability, dispatch or reference planes from counts, labels or aggregate ratings.

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

## Current validated scope

Current canonical code checkpoint: `faf51065d3d49ed0f223be244b27752713f111d0` (PR #116 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

The **generic electrical chain from S8 through S14 is implemented and validated**:

```text
MODULE ELECTRICAL STATE
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

S12 includes winding-resolved load-loss correction and coupled terminal solving. S13/S14 retain valid transformer fallback fidelity through network solving, meter benchmarking and delivery-loss accounting. Accounting attribution does not establish causality.

Do **not** read this as proof that the full weather-to-meter production chain is validated. Upstream production weather/irradiance/thermal integration still has unresolved migration work:

- weather rows can represent interval-labelled data, but the production POA runtime evaluates solar position at the stored timestamp without a canonical interval-time authority;
- legacy `calculate_poa()` computes beam IAM but does not apply it to `poa_total`;
- the legacy measured-front-POA shortcut sets rear contribution to zero, so bifacial rear energy is lost on that path;
- the current module/cell-temperature runtime is legacy, not a canonical admitted thermal stage;
- its measured-module-temperature cell offset is coded as `0.03 / 1000 °C/(W/m²)`, which gives 0.03 °C at 1000 W/m² despite the code comment describing about 3 °C;
- configured `u_c/u_v` values are currently passed directly to pvlib's Faiman `u0/u1` interface, so PVsyst/Faiman coefficient semantics must be resolved before shadow activation.

## Current production path

```text
fetch_weather → calculate_poa → calculate_cell_temp
→ calculate_dc_power → calculate_ac_power → expected_energy
```

The legacy compatibility path remains active: aggregate irradiance/thermal handling, DC soiling/LID/mismatch/wiring percentages, constant `eta_nom`, aggregate inverter clipping, `grid_limit_kwac` cap and AC wiring percentage. This path is not the canonical component-resolved S8–S14 runtime.

The database identifies expected energy by `(time, site_id, source)` with current source `physics_sdm`; catch-up and several readers are not yet fully source-isolated.

## Generic capability and site readiness

“Implemented generically” means a reusable contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

Bracon Ash's configured equipment counts and groups do not provide complete electrical authority. Its topology, capability, operating-state and meter evidence gaps remain explicit in the [site record](docs/sites/bracon-ash.md).

## Pre-shadow readiness gates

P0 expected-energy source isolation remains the next production-integration implementation step, but **P3 shadow execution must not begin merely because P0 is complete**. Before physical shadow results are treated as an end-to-end site model, the project must close or explicitly bound:

1. weather interval/timestamp semantics;
2. transposition/optics ownership, including IAM and bifacial rear treatment;
3. a canonical module thermal state/authority and correction of the legacy thermal defects;
4. the coverage gap between homogeneous S8 string scaling and real module-to-module tolerance/series mismatch;
5. an S14B expected-sample density / maximum-gap eligibility policy, backed by deterministic sunrise/sunset regressions;
6. quantitative uncertainty evidence, including revenue-meter accuracy/calibration evidence where available;
7. platform authorization hardening before shadow data is exposed outside the trusted development team;
8. local declaration of the S9-4A fixed-Q sign convention so `Qmin/Qmax` evidence cannot be interpreted ambiguously.

## Next major phase — production integration

Controlled production integration and site-evidence onboarding begin with **P0 expected-energy source isolation**, followed by a shadow-output contract, evidence onboarding, pre-shadow readiness gates, separate shadow execution, uncertainty-aware reconciliation, site-specific cutover and mechanism-specific legacy retirement.

The [production-integration roadmap](docs/development/production-integration-roadmap.md) is canonical for activation work. No additional S-stage is required for production integration.

## Future physics extensions

Genuine future physics extensions include arbitrary/shared DC collection beyond direct-branch coverage, substring/bypass-diode partial shading and multiple local maxima, dynamic physical/measured soiling, snow, arbitrary 3D/tracker/rear-obstruction coverage, justified unbalanced/sequence network extensions, transformer ageing/dynamic thermal models, and explicit module-population variability where required. These are separate extensions from the completed S12–S14 contracts.

## Development and testing

Backend: FastAPI, pvlib and Heliotelligence-owned contracts; storage: PostgreSQL/TimescaleDB; frontend: Vite/React. The validated physics dependency remains `pvlib==0.15.2`; do not upgrade it incidentally.

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`.

GitHub CI is the authoritative full-backend validation. Do not repeatedly run the full local backend after hardening changes. A full local suite may be run deliberately when justified, but is not the default. Documentation-only changes require Markdown/link/whitespace checks rather than backend tests. Check the exact base/head and live CI for review or release decisions.

## Documentation map

- [AI handoff](docs/AI_HANDOFF.md): recovery context, known blockers and non-negotiable rules.
- [Physics architecture](docs/architecture/physics-architecture.md): reference planes, stage responsibilities, fidelity and upstream migration boundaries.
- [Physics roadmap](docs/development/physics-roadmap.md): completed capabilities and future physics scope.
- [Production-integration roadmap](docs/development/production-integration-roadmap.md): canonical activation phases, pre-shadow gates and ownership ledger.
- [ADR-001](docs/decisions/ADR-001-physics-first-electrical-migration.md): physics-first migration decision.
- [Validation strategy](docs/validation/physics-validation-strategy.md): invariants, pre-shadow validation gates and cadence.
- [Deployment environments](docs/deployment-environments.md): staging/production and access-control boundaries.
- [Bracon Ash](docs/sites/bracon-ash.md): known facts and evidence gaps.
