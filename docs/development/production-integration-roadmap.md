# Production-integration roadmap

## Purpose and checkpoint

This is the canonical roadmap for production activation, distinct from the [physics roadmap](physics-roadmap.md). Current canonical code checkpoint: `faf51065d3d49ed0f223be244b27752713f111d0`, PR #116 merge on `main`. Live GitHub CI must be rechecked for release/merge decisions.

Heliotelligence has a validated generic **electrical** chain from admitted module/string electrical state through inverter/control, LV collection, transformer, MV/HV network, revenue-meter benchmarking and delivery-loss attribution: S8 → S9 → S10 → S11 → S12 → S13 → S14. This does not establish that the upstream production weather → irradiance/optics → module-thermal path is canonical or ready for end-to-end shadow activation.

Four distinct decisions govern activation:

1. **Validated physical capability:** reusable contracts and tests exist.
2. **Site authority/evidence:** actual topology, equipment and timestamped boundaries support those contracts.
3. **Shadow production execution:** a separate model series runs without replacing legacy expected energy.
4. **Production cutover:** explicit per-site promotion after reconciliation.

Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation. Production integration uses P phases, not new S-stage numbering.

## Current production path

The active runtime in `src/heliotelligence/engine/pipeline.py` is:

```text
fetch_weather
→ calculate_poa
→ calculate_cell_temp
→ calculate_dc_power
→ calculate_ac_power
→ expected_energy
```

`physics/irradiance.py::calculate_poa` and `physics/thermal.py::calculate_cell_temp` are also part of the current compatibility runtime. They must not be treated as canonical production authorities merely because reusable optical/thermal-related components exist elsewhere in the repository.

Known production-path gaps that must be tracked explicitly are:

- Solcast stores `period_end` directly and SCADA period-start data is normalised to period-end, while `calculate_poa()` evaluates solar position at the stored timestamp. There is no canonical authority declaring whether interval irradiance should be evaluated at start, midpoint, end, or another representative instant.
- `calculate_poa()` computes `poa_direct_iam` and publishes it as `poa_direct`, but `poa_total` is assembled from the earlier uncorrected `poa_front`; IAM therefore does not reduce the irradiance sent to thermal/DC power.
- When measured front `poa_wm2` is accepted, the legacy shortcut sets `poa_rear = 0`, so a bifacial site's rear contribution is omitted on that path.
- `physics/thermal.py` is a legacy cell-temperature runtime, not a canonical admitted module-thermal stage. Its measured-module path uses `_DELTA_T_COEFF = 0.03 / 1000`, yielding 0.03 °C at 1000 W/m² despite the code comment describing about 3 °C.
- Site/module `u_c/u_v` values are passed directly to pvlib Faiman `u0/u1`; PVsyst and Faiman coefficient semantics must be reconciled rather than assumed interchangeable.

`physics/electrical.py::calculate_dc_power` then scales representative module output to the aggregate array and applies sequential soiling, LID, mismatch and DC wiring percentages. Its legacy module wrapper has an optional spectral helper; the current pipeline supplies solar zenith but not the precipitable-water argument required to activate that helper.

`engine/inverter.py::calculate_ac_power` applies constant `eta_nom`, aggregate inverter nameplate clipping, optional `grid_limit_kwac` cap, then AC wiring percentage. This is a legacy compatibility path, not component-resolved inverter/controller/network physics. It does not automatically execute the validated S8–S14 chain.

## Expected-energy source architecture

The database identity is `(time, site_id, source)` (`models/expected_energy.py`). The current writer in `engine/upsert.py` selects `physics_sdm`; that remains the default legacy source.

**Application source isolation is not complete.** `engine/weather_query.py::get_latest_expected_energy_time` queries latest time by site without source. Several expected-energy readers also omit source selection; bucketed API reads aggregate by time with `AVG` and `MIN(source)`, rather than isolating model series. Analysis/benchmarking readers need the same audit. The schema's source column alone does not make shadow activation safe.

No physical shadow source should be activated until P0 is complete. A source represents an alternative model series, not an additive layer. Different sources must never be averaged or silently mixed.

## Bounded migration phases

### P0 — expected-energy source isolation — next planned work

Make reads, writes, catch-up, aggregation and downstream reports explicitly model-source aware. Preserve `physics_sdm` as the default legacy source. Inventory all expected-energy consumers and define consistent default/source-selection behaviour, including empty-source coverage. Demonstrate that one model's latest timestamp cannot suppress another's catch-up, and that alternative sources cannot overwrite, combine or average each other's values.

Exit decision: source-isolation regressions and reader/writer inventory prove separate model identities end to end. P0 is not completed by this documentation change.

### P1 — physical shadow-output contract

Define a physical run's output before activating a writer: exact timestamp identity, site/model source, meter or other explicit reference plane, units/signs, resolved/unresolved state, physical fidelity, provenance and reason codes. Decide how intermediate states and unresolved rows are retained without fabricating power.

No hidden fallback to legacy percentages is allowed inside a physical source. An explicit physically valid lower-fidelity contract may be selected with visible provenance; unsupported evidence remains unresolved. A source label must not imply meter-plane output when the run only resolves an upstream plane.

Exit decision: reviewed contract and persistence/reader semantics agree on boundary and missing-state behaviour. No physical source name is prescribed here before that decision.

### P2 — site evidence onboarding

Bind authoritative receiver/string mapping, MPPT/string/inverter topology, DC cable coverage, inverter conversion/capability, controller P/Q requests and thermal evidence, LV topology/R/X and exit voltage, transformer equipment/factory/construction/harmonic/thermal evidence, MV/HV connectivity/parameters, grid/meter boundaries and meter measurements.

Track each evidence item’s source, physical plane, temporal applicability and supported fidelity. Missing advanced evidence may allow explicit lower fidelity only where an independently valid baseline exists. Do not infer evidence from labels, capacities, geometry, weather, measured output or aggregate limits.

Exit decision: a per-site coverage matrix proves which timestamps and paths can resolve; document remaining gaps. Generic implementation alone is not admission.

### Pre-shadow readiness gates

P0, P1 and P2 are necessary but not sufficient for P3. Before a physical source is treated as an end-to-end site shadow, all of the following must be implemented or explicitly bounded by an approved lower-fidelity contract:

1. **Weather temporal semantics:** define the meaning of interval-labelled weather timestamps and the solar-position instant used by transposition/optics.
2. **Irradiance/optics ownership:** prove transposition, shading, IAM, spectral and front/rear contributions are each applied exactly once. The current legacy IAM and measured-front bifacial behaviours above are not acceptable physical-shadow semantics.
3. **Canonical module thermal state:** establish an admitted module/cell thermal contract with explicit quantity, source/provenance, model family/parameters and measured-temperature basis. Correct or bypass the legacy cell-to-module offset and PVsyst/Faiman coefficient mismatch.
4. **Mismatch coverage:** distinguish S8 common-voltage string/MPPT mismatch from module-to-module manufacturing/tolerance variation inside a series string. Do not retire the full legacy mismatch percentage until ownership of all material mechanisms is established.
5. **S14B support density:** add an explicit expected-sample density / maximum-gap eligibility policy. The existing `maximum_expected_sample_gap_seconds` diagnostic is not currently a gate. Quantify sunrise/sunset sensitivity with deterministic regressions before adopting numerical thresholds.
6. **Uncertainty evidence:** define numerical measurement/model uncertainty inputs and reporting. Revenue-meter evidence should support accuracy/calibration information where available; categorical confidence alone is not an uncertainty model.
7. **Platform access control:** remove browser-bundled admin secrets as an authorization boundary and enforce server-side site authorization for site-scoped routes before shadow data is exposed beyond the trusted development team.
8. **S9-4A Q semantics:** explicitly declare the fixed-Q sign convention for `reactive_power_min_var/reactive_power_max_var` and require source evidence using another convention to be transformed before authority construction.

These gates do not imply that P0 source isolation should wait. They block promotion into meaningful P3/P4 site validation, not the preparatory isolation work itself.

### P3 — shadow execution

Run legacy and physical models side by side as separate expected-energy sources, first in staging. Preserve default production behaviour. Observe execution cost, failures, timestamp coverage, uncertainty metadata and provenance without replacing the legacy model.

Exit decision: source-isolated, reproducible shadow runs are operationally safe **and all pre-shadow readiness gates above are closed or explicitly bounded by reviewed lower-fidelity contracts**. Shadow execution is planned, not currently activated.

### P4 — validation and reconciliation

Compare timestamp coverage, reference planes, expected meter output, loss decomposition, unresolved/fallback rates, measured residuals, uncertainty envelopes and performance across representative operating regimes. Keep unexplained residuals explicit rather than tuning correction factors to erase them. Check that physical ownership covers exactly the paths formerly represented by compatibility losses.

Exit decision: reviewers accept site-specific accuracy/coverage and operational evidence; unresolved mechanisms and ownership decisions are documented.

### P5 — controlled cutover

Promote a physical source only after shadow validation, explicitly per site. Define selection, monitoring and rollback to the separately preserved legacy series. Changing the default source must never silently combine histories or relabel fidelity.

Exit decision: authorised site-specific cutover with reproducible comparison and rollback evidence.

### P6 — legacy retirement

Retire each percentage only after its physical replacement owns the same mechanism/reference path. Do not remove all legacy losses globally in one action. Preserve legacy series needed for comparison and historical interpretation.

Exit decision: mechanism-specific ownership and retirement evidence, with uncovered mechanisms retained explicitly.

## Migration ledger

All candidate replacements below are validated generic capabilities unless stated otherwise; none is automatically active in the default expected-energy runtime.

| Legacy mechanism | Current compatibility implementation | Candidate physical replacement | Activation prerequisite | Current status |
|---|---|---|---|---|
| Weather time semantics | Solcast/SCADA stored at period-end; solar position evaluated at stored timestamp | Explicit interval-labelled weather time authority and representative-instant policy | Source interval semantics, cadence and deterministic time alignment | Missing canonical authority |
| Front transposition / POA | Legacy Perez or measured-front shortcut | Canonical front irradiance/transposition state | Exact source/boundary semantics and single transposition owner | Integration hardening required |
| Shading authority | Legacy runtime does not execute the canonical shading chain end to end | Canonical horizon/near-shading authority and optical state | Geometry/evidence coverage and exactly one shading owner | Generic capability exists; runtime integration pending |
| IAM | Beam IAM computed in legacy `calculate_poa` but not applied to `poa_total` | Canonical IAM/optical-effective irradiance | Correct total-irradiance ownership and regression proving beam IAM affects electrical input exactly once | Confirmed legacy integration defect |
| Bifacial rear | Legacy infinite-sheds path when modelled; measured-front shortcut forces rear to zero | Canonical front/rear optical combination | Explicit measured-front versus rear-model boundary and rear evidence | Confirmed measured-POA compatibility gap |
| Module thermal | Legacy measured/Faiman/NOCT cell-temperature runtime | Canonical admitted module/cell thermal state | Quantity/model/parameter provenance; correct cell-module relation; PVsyst/Faiman semantic alignment | Canonical stage pending |
| Module tolerance / series variation | Collapsed into aggregate legacy mismatch percentage | Explicit module-population/series variability where required, combined with S8 network mismatch without double counting | Datasheet/manufacturing tolerance authority or measured module population model | Not covered by homogeneous S8-1 |
| Spectral treatment | Optional legacy spectral helper; pipeline omits required precipitable water | Canonical component spectral/electrical irradiance handoff | Spectral evidence and exactly one irradiance correction owner | Generic handoff exists; integration pending |
| Mismatch | Static DC mismatch percentage | S8 common-voltage MPPT physical mismatch for admitted string I-V curves | Authoritative string/MPPT mapping and IV coverage **plus an explicit decision for module-tolerance/series variability not represented by homogeneous S8-1** | Partial physical ownership; do not retire full legacy percentage yet |
| DC wiring | DC wiring percentage | S8 direct-branch series-loop resistance | Explicit resistance and same covered conductor path; arbitrary shared collection needs separate physics | Dormant for direct branches |
| Inverter efficiency | Constant `eta_nom` | S9 physical inverter authority, Sandia conversion/accounting | Exact equipment/model mapping and DC input authority | Dormant |
| Inverter clipping | Aggregate nameplate cap | S9 per-physical-inverter conversion/clipping accounting | Correct inverter/MPPT aggregation and model authority | Dormant |
| Grid/export cap | Static `grid_limit_kwac` cap | S10 explicit request/feasibility/selection, only with external controller evidence | Timestamped per-inverter P/Q commands and allocation authority; static cap is not dispatch | No automatic replacement |
| AC wiring | Aggregate AC wiring percentage | S11 LV conductors and possibly downstream network assets | Determine what the percentage represented; map covered paths to explicit topology/R/X/voltage | Requires evidence / allocation decision |
| Transformer loss | No separately resolved runtime transformer component; may be embedded in aggregate assumptions | S12 selected-fidelity transformer model | Factory/equipment/operating evidence and explicit migration ownership | Generic model exists; legacy allocation requires evidence |
| MV/HV network loss | No separately resolved runtime MV/HV component; may be embedded in aggregate assumptions | S13 nominal-pi network consumption | Topology/parameters/grid voltage and explicit migration ownership | Generic model exists; legacy allocation requires evidence |
| Meter boundary | Aggregate runtime AC output is not proof of an authoritative meter plane | S13 expected/measurement boundaries plus S14 comparison/accounting | Physical meter binding, scaling/sign/time semantics and resolved upstream boundary | Generic contracts exist; site admission pending |
| Soiling | Static soiling percentage | Future dynamic physical/measured soiling state | Authoritative dynamic evidence and validated replacement contract | Legacy retained |
| LID | Static LID percentage | No established replacement claimed | Evidence-backed mechanism and ownership decision | Legacy retained |

## No-double-counting ledger

For each mechanism/reference path transitioning from legacy to physical, **one and only one owner may be active in one model path**. Separate alternative model series can coexist for comparison; overlapping owners in the same series cannot.

| Mechanism | Legacy owner | Physical owner | May coexist in same expected series? |
|---|---|---|---|
| MPPT mismatch | Mismatch percentage | S8 | No |
| Direct DC cable loss | DC wiring percentage | S8 | No for the same covered conductor path |
| Inverter conversion | `eta_nom` | S9 | No |
| Inverter clipping | Aggregate inverter cap | S9 | No for the same inverter limit |
| LV AC conductor loss | AC wiring percentage | S11 | No for the same covered path |
| Transformer loss | Legacy aggregate if embedded; requires evidence / allocation decision | S12 | No |
| MV/HV network loss | Legacy aggregate if embedded; requires evidence / allocation decision | S13 | No |

Do not guess how aggregate percentages divide among LV, transformer and MV/HV assets. Partial path coverage requires an explicit allocation decision before activation. A physical model must not quietly retain a percentage for a mechanism it already owns.

## Fidelity and accounting gates

Evidence determines fidelity. Valid S12G-load-loss fallback can pass through S12M → S13C → S14A/B/C with explicit fallback provenance, provided downstream electrical and meter evidence closes. It must never be relabelled advanced. Missing topology, nonfinite/nonconvergent solutions or terminal-voltage mismatch remain unresolved.

S14 delivery attribution is accounting, not automatic causal attribution. Measured-minus-expected residual remains unexplained residual rather than a model correction. Shadow comparisons must retain this distinction.

## Validation and operations

Use focused changed-feature tests and parent/downstream regression slices, Ruff, formatting, strict mypy where relevant, compilation and `git diff --check`. GitHub CI provides authoritative full-backend validation; repeated full local suites are not the default. Documentation-only work needs Markdown/link/whitespace checks.

Staging is the first environment for future source-separated shadow execution. Production cutover requires a separate explicit decision. Scheduler/worker migration remains separate operational work unless a demonstrated runtime dependency requires coordination.


## Uncertainty and validation evidence

P4 must not treat a raw measured-minus-expected residual as self-interpreting accuracy evidence. At minimum the validation contract should be able to retain:

- revenue-meter accuracy class or equivalent numerical accuracy specification where available;
- CT/PT or scaling-chain accuracy where relevant to the admitted measurement;
- calibration/verification source and applicability period;
- model/input uncertainty or bounded sensitivity for material upstream quantities;
- the distinction between numerical uncertainty and categorical provenance/confidence.

A complete probabilistic uncertainty engine is not required before P0, but P4 acceptance criteria must not claim sub-percent model accuracy when the admitted measurement/evidence uncertainty is of comparable magnitude.

## Platform security gate

Authentication and site authorization are separate concerns. The API currently applies Firebase authentication to normal protected routers, but the repository's `get_user_sites()` / `user_site_access` mechanism is not currently enforced by the ordinary site-scoped routes reviewed for expected energy, benchmarking and reports.

The frontend also sends `VITE_ADMIN_KEY` as `X-Admin-Key` for admin calls. `VITE_*` values are embedded in browser JavaScript, so this key must not remain an admin authorization boundary.

Before staging shadow data is exposed outside the trusted development team:

- admin authorization must be server-side and user/role based rather than dependent on a browser-bundled shared secret;
- every site-scoped protected route must enforce server-side site membership/role checks;
- negative cross-site authorization tests must exist;
- staging and production authorization policy must be documented and independently testable.
