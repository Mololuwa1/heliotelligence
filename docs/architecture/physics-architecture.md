# Physics Architecture

Heliotelligence targets a component-resolved photovoltaic digital twin. The architecture should explain energy movement and loss through explicit physical state, not merely reproduce a final site-level number.

## Architectural principles

- **Physics first:** use component behaviour where inputs support it.
- **No invented authority:** missing topology or equipment data remains explicit.
- **Measurement-boundary aware:** expected and actual quantities must refer to the same physical point before comparison.
- **State rich:** preserve V/I/P and later P/Q/S, operating state, model source, confidence, and unresolved reasons where relevant.
- **No double counting:** optical, thermal, electrical, conversion, controller, cable, transformer, and network effects must each be applied once.
- **Narrow contracts:** independently validate each physical layer before production integration.
- **Graceful degradation:** high-fidelity models may fall back only through explicit, provenance-bearing logic.

## System modelling hierarchy

The future platform hierarchy is:

`Organisation / Client → Portfolio → Site → Inverter → MPPT → String → Module`

Organisation/client and portfolio management sit above site-level physics. Reusable physics functions must consume explicit site/equipment configuration and must not encode reference-site assumptions.

## Canonical electrical chain and upstream production boundary

Current canonical code checkpoint: `580327062d0f984c82888c5d394d60e380afaa86` (PR #119 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

```text
UPSTREAM WEATHER / IRRADIANCE / MODULE THERMAL
(production integration not yet canonical end to end)
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

The generic **S8–S14 electrical chain is validated**, but the full upstream weather → irradiance/optics → module-thermal → electrical production path is not yet a single canonical end-to-end chain. The current default expected-energy runtime remains a compatibility path.

“Implemented generically” means the reusable physics contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

## Upstream production-readiness boundary

The repository contains reusable irradiance, shading, IAM, spectral and module-electrical capabilities, but current production orchestration does not execute them as one canonical admitted chain. The following are current architectural blockers for a meaningful end-to-end shadow model:

- **Weather time integration:** the generic time authority and SPA alignment now admit snapshot/interval labels explicitly, but legacy production still evaluates stored timestamps and source/site binding remains required.
- **Legacy IAM ownership:** `calculate_poa()` publishes IAM-corrected beam output but builds `poa_total` from uncorrected front POA, so IAM does not affect production electrical irradiance.
- **Measured-front bifacial ownership:** accepting measured front POA currently sets rear contribution to zero.
- **Module thermal integration:** a generic canonical module-temperature authority/result now exists but is dormant; site evidence and upstream thermal-POA/time admission remain required. The legacy measured-module path has a cell/module delta inconsistency, and configured PVsyst-style `u_c/u_v` values are fed directly to a Faiman `u0/u1` call.
- **Module population variability:** S8-1 is homogeneous string scaling. It does not represent module-to-module manufacturing/tolerance variation inside a series string.
- **Interval benchmark support density:** S14B reports sample count and maximum gap but currently has no density/gap eligibility threshold.
- **Quantitative uncertainty:** S13D provides source/confidence metadata, not meter accuracy class or numerical uncertainty propagation.

These are production-readiness gaps, not reasons to weaken the validated S8–S14 contracts. P0 source isolation is complete at the PR #118 checkpoint. P3 shadow execution and P4 accuracy claims must still address the remaining integration/evidence gates explicitly.

## Canonical module thermal authority and state

The new dormant modules `module_thermal_authority.py` and `module_thermal_state.py` provide a steady-state/measurement contract, not a new S-stage. The production pipeline still calls legacy `calculate_cell_temp`; it does not call this resolver.

Static types are `PvsystCellThermalAuthority`, `FaimanThermalAuthority` and `ModuleBackSurfaceToCellTemperatureAuthority`. Native parameters, source/confidence, method and wind calibration basis are explicit. PVsyst requires u_c>0, u_v≥0, 0≤efficiency<1 and 0<absorption≤1; Faiman requires u0>0 and u1≥0 plus an explicit output quantity. No defaults from module configuration or model-family conversion are admitted.

`ModuleTemperatureEvidence` declares cell or module-back quantity and sensor/aggregated-sensor/documented-external-estimate kind. Method, location and aggregation descriptions are preserved where supplied; an external estimate is not relabelled as a sensor reading. `ModuleThermalMeasurementState` may carry both channels at an exact timestamp. Direct cell evidence wins while the unused channel's provenance remains visible.

The resolver requires an explicit `thermal_zone_id` and exactly aligned timezone-aware, unique, NaT-free input Series; order is preserved. Present POA/wind must be finite and non-negative, ambient/evidence temperatures above absolute zero, all numeric authority non-Boolean and finite. NaN environmental inputs remain missing. Thermal POA is supplied **total incident broadband irradiance for thermal balance**, not automatically electrical-effective irradiance. This thermal contract does not itself establish weather semantics; those now belong to separately admitted weather-time authority and alignment. Zone-to-module/site mapping and upstream irradiance authority remain separate onboarding/integration responsibilities.

Timestamp precedence is direct cell evidence → measured module-back plus explicit conversion/POA → explicit native PVsyst/Faiman model → a specific unresolved reason. No whole-series completeness threshold, filling, persistence or interpolation is applied. A zero wind coefficient removes the wind term algebraically without fabricating a wind observation. Nonzero coefficients require wind evidence.

```text
T_cell = T_module_back + (E / E_reference) × deltaT
PVsyst: T_cell = T_air + E × alpha × (1 - efficiency) / (u_c + u_v × wind)
Faiman: T_declared_quantity = T_air + E / (u0 + u1 × wind)
```

Conversion deltaT≥0 and E_reference>0 are explicit authorities, with no default 3°C. With admitted deltaT=3°C and E_reference=1000 W/m², 50°C module-back becomes 53°C at 1000 W/m² or 52.1°C at 700 W/m². Faiman module-back output remains unresolved for cell temperature without conversion authority; its module output can still be visible. PVsyst parameters are never passed into Faiman.

Resolved fidelity states are `resolved_direct_cell_temperature_evidence`, `resolved_measured_module_back_to_cell_temperature`, `resolved_pvsyst_cell_temperature`, `resolved_faiman_cell_temperature` and `resolved_faiman_module_back_to_cell_temperature`. Unresolved reasons distinguish absent evidence/model, missing POA, ambient, required wind, measured-module conversion authority, model-module output without conversion, and invalid model output/inputs.

The frozen result envelope publishes typed timestamp rows, raw environmental inputs, both evidence channels, native model/conversion provenance, selected fidelity and explicit unusable-measurement/model-fallback flags. Interpolation/extrapolation flags are always false. Diagnostics distinguish evidence inventory from selected pathways; missing-input counts refer to primary unresolved reasons rather than mathematically irrelevant NaNs. No thermal inertia, lag, spatial heat transfer or production activation is claimed.

Independent validation reconstructs native equations, exact row universe, schema, provenance, states and counts without the production record/selection/frame/diagnostic helpers or pvlib. The shared admission layer only validates input evidence.

Contract IDs:

- authority: `explicit_native_module_thermal_model_and_module_back_to_cell_conversion_authority_v1`;
- authority model: `native_pvsyst_cell_faiman_declared_quantity_and_reference_irradiance_delta_t_authority_v1`;
- state: `admitted_module_temperature_evidence_and_explicit_thermal_model_authority_to_timestamped_cell_temperature_state_v1`;
- state model: `per_timestamp_direct_cell_measurement_module_back_conversion_or_explicit_pvsyst_faiman_thermal_resolution_v1`;
- scope: `module_cell_temperature_state_before_temperature_dependent_module_electrical_evaluation`;
- coverage: `explicit_thermal_zone_timestamped_measurement_or_native_model_parameter_authority`.

The generic thermal gate is implemented; Bracon Ash admission and production integration are not. The legacy offset and legacy PVsyst/Faiman mismatch remain in compatibility code until controlled migration. Current `physics_sdm` numerical behaviour is unchanged.

## Weather-time and canonical irradiance boundary

The dormant `WeatherTimeBasisAuthority` declares `instantaneous_snapshot` with label `instant`, no interval duration and `observation_timestamp` geometry, or `interval_average` with explicit positive duration, interval-start/midpoint/end label and `interval_midpoint_approximation`. Unsupported combinations, padded provenance, Boolean/nonfinite durations and invalid timezone/duplicate/NaT indexes are rejected. Durations must permit exact nanosecond boundaries and midpoint in pandas. No duration is inferred from adjacent rows or source names.

`resolve_weather_time_state` retains supplied order and timezone. For a one-hour interval, 10:00 start, 10:30 midpoint and 11:00 end labels all describe [10:00,11:00] with evaluation at 10:30. Arithmetic represents elapsed physical time across DST. Instantaneous rows have NaT interval boundaries and approximation=False; averages explicitly publish approximation=True. Midpoint transposition is not mathematically identical to integrating nonlinear geometry through an interval.

`calculate_time_aligned_solar_geometry` invokes the existing canonical `nrel_spa` model at evaluation instants and replays its output under original observation keys, retaining evaluation time and temporal provenance. It does not introduce another astronomical model. Downstream canonical optics consume those explicit geometry values; the boundary verifies their replay against alignment.

`resolve_canonical_irradiance_boundary` admits explicit receivers and canonical `OpticalStateResult`, `FrontEffectiveIrradianceResult`, `BifacialEquivalentIrradianceResult` and `SpectralResponseResult` with exact matching `(observation_timestamp, receiver_id)` row universe, timezone and order. It compares parent identity/replayed fields and checks flags, metadata and diagnostics. It does not rebuild optics, change timestamp storage, nearest-match, resample or interpolate.

The distinct published planes are:

- `modeled_front_incident_poa_wm2` / `poa_front_global_raw_wm2`: incident broadband front, before IAM/electrical response;
- `modeled_rear_incident_poa_wm2` / `poa_rear_global_raw_wm2`: canonical raw rear, before rear optical/bifacial response; NaN for missing rear or monofacial not-applicable, distinguished by state;
- `measured_front_incident_poa_wm2`: separate nonnegative/missing observations, requiring receiver-specific `FrontPoaMeasurementAuthority` for `front_surface_incident_broadband_poa`, source/confidence/method and plane description;
- `front_optical_effective_irradiance_wm2`: exact upstream front-effective replay, already owning shading and IAM;
- `bifacial_electrical_equivalent_irradiance_wm2`: upstream bifacial response, never multiplied again;
- `module_electrical_irradiance_wm2`: exact `SpectralResponseResult.spectral_electrical_equivalent_irradiance_wm2` when its resolved flag is true. Explicit spectral disabled is admitted factor-one behaviour; unknown unresolved spectral state never falls back to the pre-spectral value.

Measured front does not select a truth, calibrate the model, imply a front+rear total, erase rear or repair missing optical authority. A real canonical rear of 120 W/m² remains 120 alongside measured front 800 W/m². No 920 W/m² input is selected automatically. `total_incident_broadband_both_surfaces_wm2` sums only resolved modelled front and rear as a diagnostic when both apply.

Thermal candidates preserve front and front+rear incident broadband quantities separately from electrical-effective irradiance. `module_thermal_poa_handoff_wm2` remains NaN, resolved=False, state `unresolved_no_explicit_thermal_poa_basis_authority`. The admitted thermal model's calibration basis must justify selection later; this increment does not modify PR #119's authority schema or infer that relationship.

Ownership flags indicate that the corresponding resolved upstream contract owns the mechanism, including explicit no-op spectral admission. They do not apply another factor. Monofacial electrical output can resolve with rear not applicable; bifacial missing rear remains unresolved and NaN. Optional measured evidence and intentionally deferred thermal selection do not block an otherwise resolved canonical electrical boundary.

Independent validators reconstruct temporal boundaries/approximation, directly replay canonical SPA, and verify boundary field identity, ownership, states/schema and diagnostics without calling boundary record/frame/diagnostic builders or recomputing IAM/shading/bifacial/spectral physics.

Canonical IDs:

- weather contract: `explicit_weather_observation_interval_and_solar_geometry_evaluation_time_authority_v1`;
- weather model: `instantaneous_or_interval_average_label_to_explicit_representative_solar_geometry_time_v1`;
- alignment contract: `admitted_weather_time_authority_to_observation_keyed_nrel_spa_solar_geometry_v1`;
- alignment model: `explicit_evaluation_instants_observation_keyed_nrel_spa_replay_v1`;
- boundary contract: `admitted_time_aligned_canonical_optical_bifacial_and_spectral_results_to_module_irradiance_boundary_v1`;
- boundary model: `reference_plane_preserving_incident_optical_and_spectral_irradiance_handoff_v1`.

No site is automatically admitted, no physical shadow source is defined, and the legacy weather/POA/thermal runtime remains active and numerically unchanged.

### Date-consistent irradiance calculation times

The generic weather-time authority and date-consistent canonical irradiance boundary are implemented, dormant. `resolve_horizontal_irradiance_components`, `calculate_raw_poa_transposition` and `calculate_fixed_bifacial_rear_irradiance` accept explicit positional `solar_model_times`. Erbs decomposition and front/rear Hay-Davies extraterrestrial irradiance use the same admitted physical evaluation instant as NREL-SPA. Public rows retain observation timestamps. Explicit times must be timezone-aware, unique, NaT-free, equal in length and in the exact observation timezone; no sorting or inference occurs. Omitting the keyword preserves the existing primitive calculation-time behaviour.

The boundary requires the horizontal component frame, receiver-keyed raw front frames and applicable raw rear frame. It independently checks their decomposition/extra-radiation time provenance against weather authority, and replays their actual irradiance values into the optical parent. Complete supplied horizontal triplets do not require Erbs time; isotropic rear does not require an unused extraterrestrial term. Receiver arguments are canonicalised by sorted unique IDs, matching upstream contracts.

A one-hour interval ending at `2027-01-01 00:00 Europe/London` uses `2026-12-31 23:30` for all relevant solar/date calculations. An interval ending at `00:30` instead has midpoint `00:00`. Midpoint evaluation remains an approximation, not interval integration. Production legacy irradiance remains active; site/source temporal admission, Bracon Ash evidence and thermal POA calibration basis remain pending. This does not establish P3 readiness.


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

## Model status

| Layer | Current status | Current validated / compatibility approach | Target / next direction |
|---|---|---|---|
| Organisation/client | planned | Not a physics layer | Ownership/access boundary above portfolios |
| Portfolio | planned | Site models remain independent | Composition and analytics across sites |
| Weather / QC | ingestion plus generic temporal authority implemented, dormant | Explicit snapshot/interval authority and observation-keyed SPA; legacy storage unchanged | Bind actual source/site time evidence before integration |
| Solar geometry / decomposition | reusable capability exists; production integration needs hardening | pvlib-based geometry/component resolution | Prove time alignment and single ownership in physical shadow path |
| Front POA | reusable capability exists; legacy runtime has integration defects | Perez/modelled or measured-front compatibility path | Correct/replace legacy total-POA ownership before P3 |
| Horizon / near shading | implemented for validated generic coverage | Explicit geometry authority and visibility state | Wire canonical shading into the physical shadow path exactly once |
| IAM / optics | generic optical capability exists; legacy POA path defective | Legacy `calculate_poa` computes beam IAM but does not apply it to `poa_total` | Physical shadow must use a canonical IAM/optical-effective irradiance handoff |
| Rear / bifacial | implemented for supported generic fixed-row coverage; measured-POA shortcut incomplete | Infinite-sheds/fixed-row rear model, but measured-front shortcut forces rear to zero | Generic boundary preserves measured-front/modelled-rear planes; site binding and runtime integration pending |
| Spectral correction | generic capability exists | Component-resolved spectral response; legacy wrapper is optional and not active without required inputs | Retain one explicit spectral owner with evidence |
| Soiling | legacy approximation | Aggregate production compatibility percentage | Time-varying physical or measured state |
| Snow | not implemented | No canonical snow state | Explicit stateful snow model |
| Module thermal | **generic canonical contract implemented, dormant** | Explicit zone/evidence/native PVsyst or Faiman state, separate from legacy `physics/thermal.py` | Onboard site evidence and thermal POA/time handoff before activation; legacy numerics unchanged |
| Module parameter lookup | implemented | CEC / local / datasheet / fallback tiers | Maintain traceable parameter provenance |
| Module electrical | implemented | De Soto / single-diode + voltage-dependent state | Extend bypass/sub-string behaviour later |
| Physical string I-V | implemented | S8-1 homogeneous series scaling | Add partial-shading/bypass complexity later |
| Common-voltage MPPT | implemented | S8-2 and S8-3C | Future tracker-dynamic behaviour if justified |
| Physical mismatch | implemented | IV-consistent common-voltage difference | Bypass/multiple-local-maxima extensions later |
| Direct DC branch cable | implemented for explicit R authority | S8-3A/B series-loop resistance transform | Add richer conductor authority only when evidence exists |
| Shared DC collection | deferred | Not claimed by direct-branch S8-3 coverage | Explicit node/edge network with shared-current solve |
| Inverter authority | implemented | Exact CEC/SAM model reference | Extend resolver hierarchy later if required |
| Inverter DC constraints | implemented | S9-1 classification; no clamp/re-solve | Add only explicit constrained solve if future need demands |
| Sandia conversion | implemented | S9-2 single/multi-MPPT physical inverter conversion | ADR/PVWatts fallback hierarchy may follow separately |
| Pre-limit AC potential | implemented | S9-3A published Sandia algebra | Used for loss/accounting decomposition |
| Inverter conversion accounting | implemented | S9-3B conversion/gain/clipping/tare accounting | Preserve as immutable accounting boundary |
| Inverter AC static capability authority | implemented | S9-4A explicit voltage/basis/phase/Smax + optional fixed Q authority | Immutable equipment authority for S9-4B and later stages |
| Inverter P/Q/S capability state | implemented | S9-4B explicit timestamped Q request + Smax/fixed-Q evaluation | Preserve as evaluation-only state before thermal/controller layers |
| Inverter thermal derating authority | implemented | S9-4C explicit no-derating or piecewise P/S/Q limits over an explicit temperature domain | Immutable manufacturer authority for later temperature-dependent evaluation |
| Temperature-dependent inverter capability | implemented | S9-4D exact timestamped temperature-state admission and explicit thermal P/S/Q evaluation | Evaluates available capability without dispatch, extrapolation or power modification |
| Inverter active-power dispatch request | implemented | S10A exact timestamped per-inverter absolute P-setpoint authority at inverter_ac_output | Preserve as controller evidence before feasibility/selection |
| Inverter requested dispatch feasibility | implemented | S10B exact requested P/Q/S evaluation against availability and static/thermal capability | Preserve evaluation separately from selection |
| Inverter selected dispatch | implemented | S10C exact fully-feasible-request passthrough at `inverter_ac_output` | Remains a modeled target, not telemetry |
| LV AC static network authority | implemented, dormant | S11A balanced radial topology, explicit nodes/bindings/exits and direct per-phase R+jX | Site authority remains explicit and may be unresolved |
| LV collection-exit voltage authority | implemented, dormant | S11B exact timestamped `line_to_line_rms` magnitude at `lv_ac_collection_exit` | No persistence, interpolation or inferred nominal voltage |
| LV AC operating solution | implemented, dormant | S11C balanced radial constant-PQ backward/forward sweep with physical series losses | Production migration must prevent legacy-loss double counting |
| Legacy AC wiring loss | compatibility only | Static aggregate `wiring_loss_ac_pct` | Never combine with physical S11C loss on the same path without migration proof |
| Transformer | implemented, dormant | S12A–M authority, corrected losses and coupled terminals | Controlled evidence onboarding and activation |
| MV/HV network | implemented, dormant | S13A–C balanced radial nominal-pi network | Explicit site topology and operating boundaries |
| Revenue meter | implemented, dormant chain | S13D measurement authority and S13C expected boundary | Site binding and measurement onboarding |
| Benchmarking | implemented, dormant chain | S14A/B comparison and S14C delivery accounting | Controlled production integration; no causal claim |

## String and MPPT architecture

For strings `s` sharing an MPPT:

```text
P_independent = Σ_s P_mp,s
I_MPPT(V) = Σ_s I_s(V)
V* = argmax_V [V × I_MPPT(V)]
P_common = V* × I_MPPT(V*)
P_mismatch = P_independent - P_common
```

Individual string MPP values are not enough to determine the connected operating point. Connected strings share a voltage, so full I-V curves are required.

Mixed active and explicit-zero strings remain unresolved without a blocking / dark-string model because the electrical interaction cannot be invented.

## DC collection architecture

For a direct branch with explicit total loop resistance `R_s`:

```text
V_downstream,s(I) = V_source,s(I) - I × R_s
P_loss,s = I² × R_s
```

An explicit zero resistance is a valid ideal path. Missing resistance authority is unresolved. The configured value is already total loop resistance; do not auto-double it.

For a shared feeder after parallel combination:

```text
I_J(V_J) = Σ I_s(V_J)
V_MPPT = V_J - I_J × R_H
P_loss,H = I_J² × R_H
```

A shared `R_H` cannot be copied into each branch. The generalized shared network therefore needs an explicit node/edge model and a recursive operating-point solve.

## Inverter architecture

### DC envelope

S9-1 evaluates admitted MPPT-input state against explicit equipment limits. Independent MPPT voltages must never be averaged. Inverter-level current limits must not be duplicated to every tracker.

### Sandia conversion

S9-2 treats one physical inverter as one conversion device. Multi-MPPT voltage rails remain independent; only DC power is additive according to the validated Sandia multi-input semantics.

### Pre-Paco potential

S9-3A exposes model-native AC potential before the `Paco` ceiling. It is a model counterfactual, not a physical AC conductor measurement.

### Accounting

For applicable rows:

```text
conversion_delta = Pdc - Praw
conversion_loss = max(conversion_delta, 0)
conversion_gain = max(-conversion_delta, 0)
clipping_loss = Praw - Pac
```

with closure:

```text
Pdc + conversion_gain - conversion_loss - clipping_loss = Pac
```

`Praw == Paco` is a boundary condition with zero clipping loss. Below startup, `Pnt` tare is accounted separately. A generic total inverter-loss field is not used because it would blur different physical/accounting regimes.

### Static AC capability authority

S9-4A is independent of timestamped operating state. It accepts only explicit inverter-level equipment authority:

- nominal AC voltage;
- voltage basis;
- phase configuration;
- rated apparent power `Smax`;
- optional fixed `Qmin/Qmax`;
- source and confidence.

It rejects inference from `Paco`, `pnom_kwac`, grid limits, CEC/SAM `Vac`, `model_ref`, inverter groups, MPPT/string counts, topology position, and legacy AC wiring loss.

`three_phase + single_phase_terminal` is invalid. S9-4A fixed-Q evidence uses the project convention `Q > 0` = injection into the AC network and `Q < 0` = absorption; source evidence expressed under another convention must be transformed before authority construction. Missing fixed-Q authority remains distinct from explicit zero Q capability.

### P/Q/S capability-state evaluation

S9-4B is a merged evaluation layer, not a controller.

It combines:

- admitted S9-3B active AC power;
- canonical S9-4A static AC capability authority;
- an explicit provenance-bearing Q request at `(timestamp, inverter_id)`.

Core state:

```text
S = hypot(P, Q)
```

It evaluates the Smax circle and, where explicit fixed-Q authority exists, the Q range. Positive Q is injection, negative Q is absorption.

The layer preserves several important distinctions:

- missing Q request != explicit Q=0;
- missing fixed-Q authority != unrestricted Q;
- Smax-circle pass with unknown fixed-Q authority is partial, not full capability proof;
- known Smax-circle violations remain known even with partial Q authority;
- `|P| > Smax` is a known violation even with missing Q;
- full equipment authority is inherited from S9-4A independently of request availability;
- inactive/tare states are resolved not-applicable;
- unresolved upstream state remains unresolved.

S9-4B never dispatches, clips, curtails, calculates AC current, or applies network loss.

### Inverter thermal-derating authority

S9-4C is now merged and validated as a static authority layer.

It records:

- explicit `temperature_quantity`;
- explicit supported temperature domain;
- explicit no-derating authority or aligned piecewise P/S/Q capability-limit curves;
- downstream interpolation model `linear` for piecewise curves;
- outside-domain policy `unresolved`;
- parameter source and confidence.

It does not calculate inverter temperature or interpolate an operating limit.

Reactive thermal authority uses the project sign convention:

- positive Q = injection into the AC network;
- negative Q = absorption.

Manufacturer data using another sign convention must be transformed before authority construction.

S9-4C remains independent of S9-4A and S9-4B so static thermal evidence is not contaminated by operating state.

### Temperature-dependent inverter capability evaluation

S9-4D is now merged and validated.

It combines canonical S9-4B operating capability/request state, canonical S9-4C thermal authority and an explicit timestamped inverter-temperature state.

It requires exact temperature-quantity matching, treats S9-4C authority-domain boundaries as inclusive, performs no extrapolation, replays exact authority values at breakpoints and uses explicit piecewise-linear interpolation only between breakpoints.

S9-4D preserves partial information:

- known static or thermal violations remain definitive;
- passing partial authority remains unknown;
- explicit no-derating authority is not confused with missing authority;
- S9-4C thermal authority never repairs missing S9-4A static capability authority.

It evaluates capability only and does not alter P/Q/S, dispatch, calculate AC current, or apply cable/transformer/network losses.

### Explicit inverter active-power dispatch-request authority

S10A admits exact timestamped per-inverter absolute active-power setpoints at `inverter_ac_output`. Missing is not zero, explicit zero is resolved, no request is persisted through time, `grid_limit_kwac` is not controller evidence, and canonical Q remains S9-4B-owned.

### Requested dispatch-feasibility evaluation

S10B evaluates the exact requested P/Q/S point without modifying it. It separates instantaneous active-power availability, static S/Q authority and temperature-dependent P/S/Q authority. A known violation is definitive even when other authority is partial; a passing partial-authority result is not promoted to full feasibility.

### Selected inverter AC dispatch state

S10C establishes selected P/Q/S only when the exact request is fully proven feasible. The selected values replay requested P/Q/S exactly at `inverter_ac_output`.

Known-infeasible, partial-authority and unresolved requests do not produce a selected point. Inactive rows do not fabricate zero. S10C contains no clamping, Q clipping, S-circle projection, thermal clipping, fallback policy, curtailment accounting or measured-output inference.

## Controller and LV AC network boundary

S10 is now complete as a narrow per-inverter controller boundary:

```text
physical capability
    ↓
explicit request
    ↓
requested-point feasibility
    ↓
exact feasible-request selection
```

S10 does **not** solve plant-level export allocation or infer controller policy for infeasible requests. Those require separate explicit authority if introduced later.

S11 v1 is complete through S11C while remaining dormant from production.

### S11A — static LV collection authority

S11A admits an explicit `balanced_three_phase`, `line_to_line_rms`, `per_phase_series` network basis; `inverter_terminal`, `junction`, and `collection_exit` nodes; directed radial segments toward each exit; direct per-phase `R+jX`; and one-to-one inverter bindings at `inverter_ac_output`. It validates cycles, outgoing degree, binding uniqueness, ordered terminal-to-exit paths, shared segments, and multiple independent trees. Explicit zero R/X is valid; missing basis, binding, or path stays unresolved. It performs no operating calculation.

### S11B — collection-exit voltage authority

S11B strongly replays S11A and admits exact `(pd.Timestamp, collection_exit_node_id)` operating voltage magnitude at `lv_ac_collection_exit`. The only basis is `line_to_line_rms`; values are finite and non-negative with explicit zero distinct from missing. Its row universe is explicit timestamps × canonical exits. It never fills, interpolates, persists, copies between exits, or infers voltage from CEC/nameplate/transformer data. It does not consume S10C.

### S11C — balanced radial operating solution

S11C strongly replays S10C, S11A, and S11B. It treats selected S10C P/Q as balanced constant-PQ injection targets, converts the exact exit boundary as `V_phase = V_LL/sqrt(3)`, and uses:

```text
I_inverter = conj(S_3ph / (3 V_phase))
V_from = V_to + (R + jX) I_segment
P_loss = 3 R |I|²
Q_series = 3 X |I|²
```

A deterministic backward sweep aggregates complex current once on shared segments; a forward sweep reconstructs node voltages. The fixed-point solver uses at most 200 iterations, `1e-7 V` absolute and `1e-10` relative voltage tolerances, and a fresh-current final closure. Exit angle zero is a mathematical coordinate reference, not telemetry.

S11C outputs modeled `collection_exit_states`, `node_states`, and `segment_states` indexed respectively by `(timestamp, collection_exit_node_id)`, `(timestamp, node_id)`, and `(timestamp, segment_id)`. It validates terminal constant-PQ identity, junction KCL, segment `V=ZI`, segment complex-power/loss identity, exit delivery, and whole-tree P/Q conservation.

Every canonical inverter must first have closed S11A tree membership. Once that global membership is known, independent trees may solve independently at each timestamp. Each tree requires selected dispatch for every member and exact S11B voltage for that timestamp/exit. Missing selection is never zero. Explicit zero P/Q is a real injection state.

At zero exit voltage, all-zero dispatch resolves to zero voltage/current/loss; any nonzero P or Q is singular and becomes `unresolved_zero_exit_voltage_with_nonzero_selected_power`. Nonfinite or nonconvergent solves remain unresolved with physical outputs NaN. A genuine nonconvergence may retain its finite final delta and 200-iteration diagnostic.

The physical S11C instantaneous losses replace no production quantity automatically. Legacy `wiring_loss_ac_pct` remains compatibility logic and must not be applied to the same path as `3R|I|²` without an explicit migration proving no double counting.

S11C is balanced equivalent-phase physics only: no unbalanced phases, neutral, loads, shunts, cable charging, transformer, voltage-compliance logic, inverter voltage feedback, energy integration, or measured-output claim.

## Completed S12 — transformer

S12A–M form an authority-first chain. Live implementations are the `transformer_*.py` modules under `src/heliotelligence/physics/`.

| Stage | Implemented responsibility |
|---|---|
| S12A | Static two-winding equipment ratings and explicit S11-exit/transformer terminal topology authority. |
| S12B | Factory no-load and rated load-loss evidence with reference test conditions. |
| S12C | Exact timestamped energisation authority; no inferred persistence or state. |
| S12D | Factory-reference operating active-loss baseline; no terminal phasor solve. |
| S12E | Positive-sequence fixed voltage transfer, explicit ratio/tapping and short-circuit impedance authority, including impedance reference-side ownership. |
| S12F | Balanced three-phase factory-reference effective series `R + jX`, reproducing total rated load loss; R is not copper-only resistance. |
| S12G | Positive-sequence collection/network terminal P/Q/V/current solution and baseline transformer losses. |
| S12H | Construction and factory load-loss component authority: strict I²R/eddy/other-stray decomposition or explicitly lower-fidelity aggregate-stray evidence; winding conductor materials and I²R/eddy allocations when supplied. |
| S12I | Transformer-terminal harmonic current authority and dimensionless current/harmonic factors. |
| S12J | Timestamped thermal evidence: legacy transformer-wide average winding temperature and/or explicit collection/network average winding temperatures. |
| S12K | Temperature/harmonic corrected load loss with scalar and winding-resolved paths, effective aggregate factors, and a separately labelled S12G selected fallback where advanced evidence is insufficient. |
| S12L | Voltage/frequency core/no-load scaling from admitted authority, with valid factory/S12G baseline fallback when optional advanced scaling evidence is unavailable. Contradictory evidence remains unresolved. |
| S12M | Coupled positive-sequence terminal solution with fixed-point reconciliation of selected S12K load loss and S12L no-load loss, retaining leakage X and active/reactive conservation. |

S12H's strict component basis is:

```text
P_LL = P_I²R + P_winding_eddy + P_other_stray
```

S12I winding-eddy harmonic weighting uses h²; other stray uses h^0.8. The latter is harmonic-order weighting, not a temperature exponent. Inverter type-test spectra are not automatically transformer-terminal spectra.

S12K reads materials/allocations only from canonical S12H and temperatures only from canonical S12J. It never infers a missing side temperature, copies a transformer-wide temperature into either side, or averages side temperatures. Standard constants are copper 234.5°C and aluminium 225.0°C. For homogeneous construction an explicit matching custom constant takes precedence; a mismatched supplied authority is rejected. A transformer-level scalar custom constant cannot independently override heterogeneous side materials. At the reference temperature the side factor is exactly one without requiring a constant.

For side resistance factors k_R,c and k_R,n, eddy factors are their reciprocals. Effective aggregate factors preserve the side sums:

```text
P_I²R,ref k_R = P_I²R,c,ref k_R,c + P_I²R,n,ref k_R,n
P_EC,ref k_EC = P_EC,c,ref / k_R,c + P_EC,n,ref / k_R,n
```

Other-stray loss (OSL) remains aggregate; it is never split by winding. Zero OSL needs no aggregate thermal proxy. Homogeneous nonzero OSL may use the existing scalar temperature basis, including matching custom authority. Heterogeneous nonzero OSL requires a defensible explicit aggregate structural proxy: an aggregate temperature plus applicable `mixed_or_other_explicit` authority. It does not invent a factor from side temperatures. Without that basis, advanced correction reports `unresolved_missing_other_stray_temperature_proxy_basis` while a valid selected S12G fallback can remain resolved.

S12M consumes S12G, S12K and S12L public contracts, not direct S12H/I/J side allocations. At S12K's coefficient-construction current I₀:

```text
P_f = P_I²R,ref k_R + P_EC,ref k_EC + P_OSL,ref k_OSL
R_f = P_f / (3 I_rated²)
P_h = P_I²R,ref k_R (S₂ - 1)
    + P_EC,ref k_EC (S₂ F_EC - 1)
    + P_OSL,ref k_OSL (S₂ F_OSL - 1)
R_h = P_h / (3 I_rated²)
P_S12K,fundamental = 3 R_f I₀²
P_S12K,harmonic = 3 R_h I₀²
```

Here P_f/P_h are rated-current coefficients; timestamp losses scale with I₀²/I_rated². Coupling re-solves current, so published S12M load loss is `3(R_f + R_h) I_coupled²`, not necessarily the original S12K timestamp loss. Harmonic increment is a separate active sink, never positive-sequence voltage-drop resistance. S12L core loss is re-evaluated at coupled internal excitation voltage; selected losses replace baseline losses rather than adding to them. Both transformer series reference sides are supported without another impedance referral. No thermal iteration, harmonic voltage-drop model, excitation Q or saturation is claimed.

S12M resolved states include:

- `resolved_coupled_advanced_transformer_terminal_solution`: fidelity `coupled_advanced_load_loss`;
- `resolved_coupled_transformer_terminal_solution_with_s12g_load_loss_fallback`: fidelity `coupled_s12g_load_loss_fallback`;
- `resolved_deenergised_transformer_zero_advanced_transfer`: fidelity `deenergised_zero`.

**Resolved lower fidelity != unresolved physics.** Fallback uses valid S12G series resistance, zero harmonic accounting resistance and explicit provenance; advanced-only quantities may remain NaN. It must not leak a partial advanced result or claim advanced fidelity.

## Completed S13 — MV/HV and meter boundary

- **S13A:** explicit nodes, same-voltage radial topology, nominal-pi segment electrical parameters, transformer terminal bindings, grid boundaries and revenue-meter relationships. Equipment/topology authority does not establish operating voltage.
- **S13B:** exact timestamped grid-boundary operating-voltage authority.
- **S13C:** balanced radial nominal-pi solve, using canonical S12M terminal P/Q injection and voltage coupling; accounts for series/shunt consumption and publishes expected meter-boundary P/Q with active/reactive conservation.
- **S13D:** already-scaled signed three-phase measured P/Q at explicit revenue-meter boundaries, with declared instantaneous-snapshot or interval-average-ending-at-timestamp semantics. It neither infers CT/PT scaling nor computes expected power.

S13C admits both energised resolved S12M states above, plus the separate deenergised zero-transfer state. It copies canonical `p_network_terminal_w`, `q_network_terminal_var` and `network_terminal_voltage_line_to_line_rms_v`; it does not reconstruct transformer loss, return to S12G or recompute S12K. Loss ownership remains `transformer_losses_owned_by_s12m_not_reapplied_in_s13c`.

Both energised states undergo the same terminal-voltage magnitude consistency checks at the existing absolute/relative tolerances. A fallback terminal mismatch remains `unresolved_s12m_s13_transformer_terminal_voltage_mismatch`. Missing, nonfinite, nonconvergent or otherwise unresolved upstream states do not become ready merely because a transformer is energised.

The transformer terminal frame retains exact `s12m_operating_state`, `s12m_terminal_solution_fidelity` and `s12m_load_loss_fallback_applied`. Advanced/fallback/deenergised combinations may resolve the same network state, `resolved_balanced_radial_nominal_pi_mv_hv_operating_solution`, without making an advanced transformer-fidelity claim.

## Completed S14 — benchmark and delivery-loss attribution

- **S14A:** expected S13C versus measured S13D instantaneous P/Q at the same meter ID, physical boundary and exact timestamp. Residual is measured minus expected; no nearest-time match, hidden calibration or correction factor.
- **S14B:** exact interval boundaries and admitted S13C support timestamps, piecewise-linear expected-power reconstruction and trapezoidal energy integration against S13D interval-average measurement authority. No nearest boundary or extrapolation. Expected and measured energy retain the same meter boundary.
- **S14C:** instantaneous and interval post-inverter delivery-loss accounting:

```text
selected inverter AC source
→ LV collection loss
→ transformer loss
→ MV/HV network consumption
→ expected revenue-meter power
→ measured revenue-meter residual
```

S14C uses generic canonical S12M collection input, network output and total transformer active loss, not advanced-only loss fields. A valid fallback transformer therefore contributes resolved accounting. Transformer loss closes as collection input minus network terminal output against `p_total_transformer_active_loss_w`.

`s12m_fallback_transformer_ids` is a deterministically ordered tuple of contributing fallback transformers; `s12m_load_loss_fallback_present` reports whether it is nonempty. Interval IDs are the union across all admitted S14B support timestamps, including a transformer if fallback occurs at any such timestamp. Deenergised is not fallback.

Accounting attribution is not automatically causal attribution. The unexplained measured-minus-expected residual remains residual and is never fed back as a correction factor. Independent validators reconstruct readiness, accounting and provenance, rejecting public-field tampering without invoking production builders.

PR #115 established fidelity propagation through `S12M → S13C → S14A/B/C`. Lower transformer loss fidelity does not imply an unresolved network or unresolved meter accounting when all required downstream electrical and boundary evidence resolves. Fidelity remains visible at each layer.

## Partial shading target

The intended dependency remains:

`module-level irradiance → substring/bypass behaviour → module I-V → string I-V → possible multiple local maxima → MPPT behaviour`

A scalar shading or mismatch percentage is not the final target mechanism.

## Production integration boundary

Validated physical layers are not automatically production-active. The legacy compatibility path still contains aggregate loss behaviour. Production migration must prove no double counting and preserve explicit unresolved/fallback fidelity. The next phase is production integration and site evidence onboarding, following completed P0 source isolation and the pre-shadow readiness sequence. See the canonical [production-integration roadmap](../development/production-integration-roadmap.md).

Genuine future physics extensions include arbitrary/shared DC collection beyond direct-branch coverage, substring/bypass-diode partial shading and multiple local maxima, dynamic physical/measured soiling, snow, arbitrary 3D/tracker/rear-obstruction coverage, justified unbalanced/sequence network extensions, and transformer ageing/dynamic thermal models when evidence and use cases support them. These are separate extensions, not unfinished current S12–S14 contracts.

## Reference site discipline

Bracon Ash remains a reference site, not a reusable topology template. Its physical MPPT-to-string map, DC/LV cable networks, S9-4A AC capability authority, S11 terminal/junction/exit topology, direct R/X, collection-exit voltage, transformer network, and MV/HV connectivity must not be invented from counts, groups, labels, capacities, geometry, `Paco`, CEC `Vac`, or legacy losses.

## Dependency lock

Current validated physics is pinned to:

`pvlib==0.15.2`

Do not upgrade the dependency as part of an unrelated model increment.

## Live contract index

Exact contract IDs at the checkpoint, copied from the source constants. Existing v1 IDs remain in use.

| Stage | Source module | Contract ID |
|---|---|---|
| S12A | `transformer_authority.py` | `explicit_transformer_static_ratings_and_s11_boundary_topology_authority_v1` |
| S12B | `transformer_loss_authority.py` | `admitted_transformer_static_authority_to_explicit_factory_test_loss_authority_v1` |
| S12C | `transformer_energisation_authority.py` | `admitted_transformer_static_authority_to_timestamped_transformer_energisation_state_v1` |
| S12D | `transformer_operating_loss.py` | `admitted_lv_collection_transformer_static_factory_loss_and_energisation_to_reference_condition_active_loss_evaluation_v1` |
| S12E | `transformer_network_authority.py` | `admitted_transformer_static_authority_to_positive_sequence_transfer_and_short_circuit_impedance_authority_v1` |
| S12F | `transformer_series_equivalent.py` | `admitted_transformer_factory_load_loss_and_short_circuit_impedance_to_effective_series_equivalent_v1` |
| S12G | `transformer_operating_solution.py` | `admitted_s11_collection_transformer_energisation_network_and_series_equivalent_to_balanced_terminal_operating_solution_v1` |
| S12H | `transformer_loss_component_authority.py` | `admitted_transformer_static_and_factory_loss_authority_to_advanced_construction_and_load_loss_component_basis_v1` |
| S12I | `transformer_harmonic_current_authority.py` | `admitted_transformer_static_authority_to_terminal_integer_harmonic_current_characterisation_v1` |
| S12J | `transformer_thermal_state_authority.py` | `admitted_transformer_advanced_construction_to_timestamped_multichannel_thermal_state_authority_v1` |
| S12K | `transformer_corrected_load_loss.py` | `admitted_transformer_operating_component_harmonic_and_thermal_authorities_to_corrected_load_loss_v1` |
| S12L | `transformer_core_no_load_loss.py` | `admitted_transformer_factory_no_load_operating_voltage_frequency_and_core_scaling_authorities_to_corrected_no_load_loss_v1` |
| S12M | `transformer_advanced_operating_solution.py` | `admitted_s12g_terminal_s12k_corrected_load_and_s12l_corrected_no_load_to_coupled_advanced_transformer_terminal_solution_v1` |
| S13A | `mv_hv_network_authority.py` | `explicit_mv_hv_network_topology_nominal_pi_and_meter_boundary_authority_v1` |
| S13B | `mv_hv_grid_boundary_voltage_authority.py` | `admitted_mv_hv_network_authority_to_timestamped_grid_boundary_voltage_state_v1` |
| S13C | `mv_hv_operating_solution.py` | `admitted_s12m_s13a_s13b_to_balanced_radial_nominal_pi_mv_hv_operating_solution_v1` |
| S13D | `revenue_meter_measurement_authority.py` | `admitted_revenue_meter_boundary_to_timestamped_measured_power_state_v1` |
| S14A | `revenue_meter_power_benchmark.py` | `admitted_s13a_s13c_s13d_to_exact_timestamp_instantaneous_revenue_meter_power_benchmark_v1` |
| S14B | `revenue_meter_interval_benchmark.py` | `admitted_s13a_s13c_s13d_to_exact_interval_average_revenue_meter_energy_benchmark_v1` |
| S14C | `revenue_meter_loss_attribution.py` | `admitted_s11c_s12a_s12m_s13a_s13c_s14a_s14b_to_revenue_meter_delivery_loss_attribution_v1` |
