# Production-integration roadmap

## Purpose and checkpoint

This is the canonical roadmap for production activation, distinct from the [physics roadmap](physics-roadmap.md). Current canonical code checkpoint: `d8f8d7eb44e2e611be03c09ca0f3cfda7846b42a`, PR #115 merge on `main`. Live GitHub CI must be rechecked for release/merge decisions.

Heliotelligence has a validated generic component-resolved electrical chain from module/string physics through inverter/control, LV collection, transformer, MV/HV network, revenue-meter benchmarking and delivery-loss attribution: S8 → S9 → S10 → S11 → S12 → S13 → S14.

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

`physics/electrical.py::calculate_dc_power` scales representative module output to the aggregate array, then applies sequential soiling, LID, mismatch and DC wiring percentages. Its legacy module wrapper has an optional spectral helper; the current pipeline supplies solar zenith but not the precipitable-water argument required to activate that helper.

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

### P3 — shadow execution

Run legacy and physical models side by side as separate expected-energy sources, first in staging. Preserve default production behaviour. Observe execution cost, failures, timestamp coverage and provenance without replacing the legacy model.

Exit decision: source-isolated, reproducible shadow runs are operationally safe. Shadow execution is planned, not currently activated.

### P4 — validation and reconciliation

Compare timestamp coverage, reference planes, expected meter output, loss decomposition, unresolved/fallback rates, measured residuals and performance across representative operating regimes. Keep unexplained residuals explicit rather than tuning correction factors to erase them. Check that physical ownership covers exactly the paths formerly represented by compatibility losses.

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
| Spectral treatment | Optional legacy spectral helper; pipeline omits required precipitable water | Canonical component spectral/electrical irradiance handoff | Spectral evidence and exactly one irradiance correction owner | Generic handoff exists; integration pending |
| Mismatch | Static DC mismatch percentage | S8 common-voltage MPPT physical mismatch | Authoritative string/MPPT mapping and IV coverage | Dormant |
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
