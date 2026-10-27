# Heliotelligence

Heliotelligence is a physics-first solar digital twin and performance benchmarking platform for utility-scale PV assets. It preserves component state, provenance and measurement boundaries so energy conversion, limits, transport and losses can be explained.

## Architectural principles

Use explicit equipment, topology, operating and measurement evidence. Preserve missing authority separately from zero, modelled state separately from telemetry, and each mechanism's single owner. Never infer topology, capability, dispatch or reference planes from counts, labels or aggregate ratings.

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

## Current validated physical chain

Current canonical code checkpoint: `d8f8d7eb44e2e611be03c09ca0f3cfda7846b42a` (PR #115 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

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

This is a **validated component-physics chain, not yet the default production expected-energy runtime**. S12 includes winding-resolved load-loss correction and coupled terminal solving. S13/S14 retain valid transformer fallback fidelity through network solving, meter benchmarking and delivery-loss accounting. Accounting attribution does not establish causality.

## Current production path

```text
fetch_weather → calculate_poa → calculate_cell_temp
→ calculate_dc_power → calculate_ac_power → expected_energy
```

The legacy compatibility path remains active: DC soiling/LID/mismatch/wiring percentages, constant `eta_nom`, aggregate inverter clipping, `grid_limit_kwac` cap and AC wiring percentage. This path is not component-resolved. The database identifies expected energy by `(time, site_id, source)` with current source `physics_sdm`; catch-up and several readers are not yet fully source-isolated.

## Generic capability and site readiness

“Implemented generically” means the reusable physics contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

Bracon Ash's configured equipment counts and groups do not provide complete electrical authority. Its topology, capability, operating-state and meter evidence gaps remain explicit in the [site record](docs/sites/bracon-ash.md).

## Next major phase — production integration

Controlled production integration and site-evidence onboarding begin with **P0 expected-energy source isolation**, followed by an output contract, evidence onboarding, separate shadow execution, reconciliation, site-specific cutover and mechanism-specific legacy retirement. P0 and shadow execution are planned, not implemented. Alternative model series must never be averaged, mixed or treated as additive loss layers.

The [production-integration roadmap](docs/development/production-integration-roadmap.md) is canonical for activation work. No additional S-stage is required for production integration.

## Future physics extensions

Genuine future physics extensions include arbitrary/shared DC collection beyond direct-branch coverage, substring/bypass-diode partial shading and multiple local maxima, dynamic physical/measured soiling, snow, arbitrary 3D/tracker/rear-obstruction coverage, justified unbalanced/sequence network extensions, and transformer ageing/dynamic thermal models when evidence and use cases support them. These are separate extensions, not unfinished current S12–S14 contracts.

## Development and testing

Backend: FastAPI, pvlib and Heliotelligence-owned contracts; storage: PostgreSQL/TimescaleDB; frontend: Vite/React. The validated physics dependency remains `pvlib==0.15.2`; do not upgrade it incidentally.

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`. Run optical/rear regressions when shared dependencies warrant them.

GitHub CI is the authoritative full-backend validation. Do not repeatedly run the full local backend after hardening changes. A full local suite may be run deliberately when justified, but is not the default. Documentation-only changes require Markdown/link/whitespace checks rather than backend tests. Check the exact base/head and live CI for review or release decisions.

## Documentation map

- [AI handoff](docs/AI_HANDOFF.md): recovery context and non-negotiable rules.
- [Physics architecture](docs/architecture/physics-architecture.md): reference planes, stage responsibilities and fidelity.
- [Physics roadmap](docs/development/physics-roadmap.md): completed capabilities and future physics scope.
- [Production-integration roadmap](docs/development/production-integration-roadmap.md): canonical activation phases and ownership ledger.
- [ADR-001](docs/decisions/ADR-001-physics-first-electrical-migration.md): physics-first migration decision.
- [Validation strategy](docs/validation/physics-validation-strategy.md): invariants and cadence.
- [Deployment environments](docs/deployment-environments.md): staging/production boundaries.
- [Bracon Ash](docs/sites/bracon-ash.md): known facts and evidence gaps.
