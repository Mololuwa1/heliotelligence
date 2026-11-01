# Heliotelligence

Heliotelligence is a physics-first solar digital twin and performance benchmarking platform for utility-scale PV assets. It preserves component state, provenance and measurement boundaries so energy conversion, limits, transport and losses can be explained.

## Architectural principles

Use explicit equipment, topology, operating and measurement evidence. Preserve missing authority separately from zero, modelled state separately from telemetry, and each mechanism's single owner. Never infer topology, capability, dispatch or reference planes from counts, labels or aggregate ratings.

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

## Current validated scope

Current canonical code checkpoint: `f7fbfd177e234becff78b7748576d583bc494e9d` (PR #129 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

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

- weather rows can represent interval-labelled data; explicit generic weather-time authority and observation-keyed SPA alignment now exist, but production still evaluates the stored timestamp without that admission;
- legacy `calculate_poa()` computes beam IAM but does not apply it to `poa_total`;
- the legacy measured-front-POA shortcut sets rear contribution to zero, so bifacial rear energy is lost on that path;
- the production module/cell-temperature runtime remains legacy; a separate canonical module thermal authority/state contract is now implemented generically but is dormant;
- its measured-module-temperature cell offset is coded as `0.03 / 1000 °C/(W/m²)`, which gives 0.03 °C at 1000 W/m² despite the code comment describing about 3 °C;
- configured `u_c/u_v` values are currently passed directly to pvlib's Faiman `u0/u1` interface, so PVsyst/Faiman coefficient semantics must be resolved before shadow activation.

## Current production path

```text
fetch_weather → calculate_poa → calculate_cell_temp
→ calculate_dc_power → calculate_ac_power → expected_energy
```

The legacy compatibility path remains active: aggregate irradiance/thermal handling, DC soiling/LID/mismatch/wiring percentages, constant `eta_nom`, aggregate inverter clipping, `grid_limit_kwac` cap and AC wiring percentage. This path is not the canonical component-resolved S8–S14 runtime.

**P0 source isolation is complete** at PR #118 merge `04f0cf338ab86980c040e5b6fbda6942a3c28681`. Expected-energy identity is `(time, site_id, source)`; model-sensitive reads, writes, aggregates and catch-up select one source, defaulting to legacy `physics_sdm`. Alternative series are never additive. Bundled legacy loss-waterfall/report endpoints explicitly reject unsupported source semantics; telemetry-only health existence guards remain source-independent.

## Generic capability and site readiness

“Implemented generically” means a reusable contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

Bracon Ash's configured equipment counts and groups do not provide complete electrical authority. Its topology, capability, operating-state and meter evidence gaps remain explicit in the [site record](docs/sites/bracon-ash.md).

## Pre-shadow readiness gates

P0 expected-energy source isolation is complete. The generic canonical module thermal gate was completed in PR #119, but **P3 shadow execution must not begin merely because those reusable contracts exist**. Before physical shadow results are treated as an end-to-end site model, the project must close or explicitly bound:

1. site weather-source temporal evidence binding to the new explicit authority;
2. site optics/measurement coverage and integration of the new canonical boundary, whose optical ownership is already explicit;
3. site thermal evidence admission and later integration of the new canonical contract; legacy thermal defects remain isolated in production compatibility code;
4. site admission of the generic bounded population-residual authority; homogeneous S8 string scaling remains unchanged and member-resolved variability remains future work;
5. site-specific admission of the generic S14B maximum-support-gap eligibility policy; no universal cadence threshold is chosen;
6. quantitative uncertainty evidence, including revenue-meter accuracy/calibration evidence where available;
7. retain the implemented server-side authorization boundary and verify deployment membership/claim provisioning before exposing shadow data;
8. local declaration of the S9-4A fixed-Q sign convention so `Qmin/Qmax` evidence cannot be interpreted ambiguously.

## Module-population mismatch coverage

Generic mismatch coverage now distinguishes physical S8 shared-MPPT/common-voltage mismatch from an explicit lower-fidelity intra-string population residual. `module_population_mismatch.py` admits evidence per `(inverter_id, mppt_id)`: either explicitly negligible residual, or an equivalent post-MPPT current derate. Missing authority preserves valid S8 baseline values while active population-complete output remains unresolved. Resolved-zero upstream states remain exact zero without authority because the residual mechanism is inactive. It does not change homogeneous series scaling or the existing MPPT mismatch calculation.

Nameplate power tolerance alone is neither mismatch loss nor a member current/voltage distribution. No synthetic populations or member-resolved reverse/bypass physics are implemented. The legacy mismatch percentage is not consumed or retired. Bracon Ash's 1.15% remains unallocated legacy compatibility data, and Bracon is not admitted to this dormant authority. This population capability activates no production or expected-energy source; P2 remains pending and P3 inactive.

## Interval benchmark support eligibility

Generic dormant S14B v2 now requires explicit per-meter maximum-gap policy for a finite reconstructed interval to become benchmark eligible. Exact boundaries, selected support timestamps, piecewise-linear reconstruction and trapezoidal integration are unchanged. Reconstruction resolved ≠ benchmark eligible: missing policy or excess gap retains reconstructed averages/energy and support diagnostics, but all benchmark residuals remain NaN. S14C consumes that eligibility gate without reinterpreting support density.

There is no project-wide or Bracon threshold. Test-only analytic sunrise/sunset proxies demonstrate support sensitivity; they are not real-site accuracy claims. Bracon policy admission and P2 finalisation remain open; authorization implementation is complete; no production or shadow activation occurs.

## Revenue-meter measurement uncertainty

A dormant generic contract now evaluates explicit complete-measurement-chain symmetric maximum error bounds for P and Q independently. It uses only supplied numerical relative/absolute terms; categorical confidence and meter/CT/PT accuracy descriptions do not imply numerical bounds. Relative terms require explicit attestation to the magnitude of the same measured P/Q in primary units; other reference bases need an evidence-backed conversion before admission. Declared validity covers complete intervals for interval-average measurements, with exact boundary arithmetic, or the observation timestamp for snapshots. It performs no internal component recombination or accuracy-class lookup.

This is measurement uncertainty only, separate from S14B support-density eligibility. Combined interval magnitudes are now implemented separately; deterministic S14B envelope interpretation is now implemented generically. Bracon Ash has no admitted numerical measurement uncertainty. Production and shadow execution remain unchanged.

## Pointwise expected-model uncertainty

A separate dormant contract now annotates canonical S13C revenue-meter P/Q with explicit already-combined complete-model symmetric maximum bounds. P and Q resolve independently using only admitted `abs(expected channel power) × relative fraction + absolute bound`. The relative term must attest to that same expected channel magnitude in primary engineering units; categorical confidence, component ratings and legacy percentages do not define a numerical bound. Inclusive validity is pointwise at the exact S13C timestamp.

Measurement bounds remain independently owned. A separate dormant module now propagates the published pointwise envelopes through S14B's exact discrete trapezoidal functional; it does not multiply one point bound by an invented duration or quantify support-density/continuous-path error. Combined interval magnitudes are implemented separately; deterministic S14B envelope interpretation is now implemented generically. No Bracon bound, production or shadow activation is admitted.

## Discrete expected-model interval uncertainty

`revenue_meter_expected_model_interval_uncertainty.py` replays canonical S14B and pointwise expected-model uncertainty, then propagates only the published bound magnitudes over S14B's exact support timestamps. For each channel, `B_E = sum((b_i/2 + b_next/2) × elapsed_hours)` and `B_avg = B_E / interval_hours`. All S14B values, policies, eligibility flags and residuals remain unchanged; an exact pointwise support/provenance snapshot is retained.

Resolved interval model uncertainty **does not imply benchmark eligibility**. Missing or exceeded support policy can coexist with mathematically resolved propagation. This bound covers the discrete reconstructed functional, not sparse-support error or continuous physical truth. Measurement uncertainty remains separate; combined interval uncertainty magnitudes now exist separately and deterministic S14B envelope interpretation is now implemented generically. Bracon has no admitted model bound, and production/shadow execution remains dormant.

## Next major phase — production integration

Weather-time authority and canonical irradiance boundary are complete generically and dormant. The remaining readiness sequence addresses site weather/optical/thermal evidence binding, population-residual and S14B policy site evidence, the implemented authorization boundary before P2 finalisation and P3 shadow execution. No shadow source is activated. See the canonical roadmap for ordering and site admission gates.

The [production-integration roadmap](docs/development/production-integration-roadmap.md) is canonical for activation work. No additional S-stage is required for production integration.

## Canonical module thermal capability

The dormant `module_thermal_authority.py` / `module_thermal_state.py` contract resolves an explicit thermal zone per timestamp: direct cell evidence, measured module-back temperature with explicit conversion, or a native PVsyst/Faiman model. PVsyst `u_c/u_v` are never passed to Faiman `u0/u1`. With supplied deltaT=3°C at E_ref=1000 W/m², module-back 50°C gives cell 53°C at 1000 W/m² and 52.1°C at 700 W/m². Those parameters are evidence, not site defaults.

Thermal POA is admitted total incident broadband irradiance, not automatically electrical-effective irradiance. The new weather-time contract supplies explicit temporal semantics only when admitted by a caller; source evidence and zone-to-module binding remain external. Bracon Ash is not automatically thermally admitted. The active `physics/thermal.py` path and `physics_sdm` numerics are unchanged, including its legacy 50.021°C result for the separate 700 W/m² example.

## Weather-time and canonical irradiance boundary

Generic `weather_time_authority.py`, `solar_geometry_time_alignment.py` and `irradiance_boundary_state.py` contracts are now implemented but dormant. An explicit weather authority distinguishes instantaneous snapshots from interval averages and declares start/midpoint/end labels and duration. Interval geometry uses an explicit midpoint approximation, not interval integration. NREL-SPA runs at the evaluation instant while public optical rows keep the original observation timestamp and receiver ID.

The boundary replays existing canonical optical results: incident broadband front/rear, front optical-effective, bifacial electrical-equivalent and final spectral electrical-equivalent irradiance remain separate planes. IAM and shading are owned once by the upstream front-effective chain; bifacial and spectral response remain upstream-owned. The module-electrical handoff copies the resolved spectral result, including explicit disabled admission; unknown unresolved spectral evidence never silently becomes factor one.

Measured front incident POA is evidence alongside modelled front, not a replacement for it or a front+rear total. It never erases rear irradiance. Incident front+rear is a diagnostic only; actual module-thermal POA selection remains unresolved until a calibration-basis authority is admitted. No canonical primitive, legacy runtime, collector, timestamp storage, thermal schema or expected-energy source is changed or activated.

## Future physics extensions

Genuine future physics extensions include arbitrary/shared DC collection beyond direct-branch coverage, substring/bypass-diode partial shading and multiple local maxima, dynamic physical/measured soiling, snow, arbitrary 3D/tracker/rear-obstruction coverage, justified unbalanced/sequence network extensions, transformer ageing/dynamic thermal models, and member-resolved module-population variability where required. These are separate extensions from the completed S12–S14 contracts.

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

## Combined revenue-meter interval uncertainty

`physics/revenue_meter_combined_interval_uncertainty.py` is a dormant annotation of independently validated measurement uncertainty and expected-model interval uncertainty. It introduces no numerical authority. Both parents are canonically reconstructed from original inputs/mappings and exact-replayed. The interval parent defines the ordered timestamp/meter universe; shared interval, reference-plane, sign and power-basis semantics must agree. Its complete frame is preserved, with an exact measurement-uncertainty snapshot.

For each P/Q channel and each published interval-average power/energy quantity, `B_combined = math.fsum((B_measurement, B_expected_model))`. This is the deterministic tight triangle-inequality bound for `δ_measurement - δ_model`, with no probability, independence, covariance or RSS assumption. The layer consumes published magnitudes; it does not recalculate either parent or repeat trapezoidal propagation. Missing channels and nonfinite arithmetic stay unresolved independently.

Combined resolution does not imply benchmark eligibility. Missing/exceeded S14B support policy remains unchanged; withheld residuals remain NaN. No residual, residual envelope, significance flag or commercial result is reconstructed. The bound still excludes numerical support-density/continuous-path error.

Engineering sequence: measurement uncertainty complete; pointwise expected-model uncertainty complete; expected-model interval propagation complete (PR #126); combined interval magnitudes complete (PR #127); eligible deterministic S14B envelope interpretation complete (PR #128); platform authorization implemented and tested; P2 site evidence finalisation next. P3 shadow execution is not activated. Bracon has no invented numerical admission. S14B/S14C numerics, source isolation, `physics_sdm` and production/shadow behaviour remain unchanged.

## Eligible interval uncertainty-envelope interpretation

The dormant `revenue_meter_interval_uncertainty_interpretation.py` exact-replays the combined parent and interprets only already-published, benchmark-eligible S14B residuals. Each P/Q power and energy residual is compared independently to `[-B, +B]`: strictly within, exactly on either boundary, outside positive or outside negative. There is no epsilon or statistical interpretation. Zero bound with zero residual is on the boundary.

The excess `max(abs(canonical residual) - B, 0)` is a mathematical distance only. Inside does not establish model correctness; outside does not establish physical loss, fault, causality or commercial impact. Missing/exceeded support policy blocks interpretation even when combined uncertainty resolves. No residual is regenerated. Platform authorization is implemented and tested; P2 site evidence finalisation is next, and P3 is not activated.

## Server-side authorization readiness

Firebase authentication now exposes only uid, email and the exact boolean `platform_admin` custom claim. Global operations require that claim; site reads require exact viewer/admin membership and site mutations require admin membership. Verified platform administrators explicitly bypass membership. Missing or invalid membership fails closed; viewers cannot mutate and site admins are not platform admins. No email/domain, browser-secret, environment or Bracon inference exists.

The [platform authorization policy](docs/architecture/platform-authorization.md) documents every current route, canonical alert ownership before acknowledgement, validated access grants, secret retirement and out-of-band Firebase claim bootstrap/token refresh. The focused tests enforce all 19 application route policies and cross-site denials. Health remains public and `/api/v1/admin/me` remains authenticated identity introspection. Frontend navigation is not authorization.

The generic revenue-meter uncertainty stack is complete at PR #128. Authorization implementation is now complete and tested; P2 site evidence finalisation is next. Physics, S14, uncertainty, `physics_sdm`, source selection and Bracon physical admission remain unchanged. P1 output contract is complete generically; P2 remains pending and no P3 shadow execution or deployment occurs.

## P1 physical shadow-output boundary

The immutable [P1 output contract](docs/architecture/physical-shadow-output-contract.md) now separates run/model identity, physical boundary, independent P/Q resolution and declared fidelity. Pure persistence round-trips retain exact snapshot timestamps and provenance; unresolved channels remain absent with reason codes. A future expected-energy projection requires resolved power at its explicitly intended reference plane. No physical source is named, writer or execution activated, or Bracon evidence admitted. P2 remains pending and P3 remains inactive.
