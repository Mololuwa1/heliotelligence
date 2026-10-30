# Reference Site: Bracon Ash

Bracon Ash is one current reference/onboarded site used during Heliotelligence development. Its values do not define the architecture and must not be copied to another site unless that site's evidence and configuration establish them.

## Known configuration

- Capacity: 28,524 kWp
- Module: JKM570N-72HL4-BDV, nominally 570 W
- Modules per string: 24
- Strings: 2,076
- Inverter: Sungrow SG350HX-15A
- Inverter nominal power: 320 kWac
- Inverter units: 66
- Nominal efficiency: 0.9842
- Grid export limit: 20 MW
- Inverter groups: MQA11 (16), MQA21 (16), MQA22 (17), MQA23 (17)

Current legacy loss assumptions:

- Soiling: 1.0%
- LID: 0.60%
- Mismatch: 1.15%
- DC wiring: 0.48%
- AC wiring: 1.70%

## Known data gaps

- No physical MPPT-to-string map is currently known.
- No string-to-inverter assignment should be inferred from aggregate counts.
- No physical cable layout is established by the current site configuration.
- No physical LV inverter-terminal, junction, collection-exit, or directed segment topology is established.
- No direct per-phase LV segment R/X or collection-exit operating-voltage authority is established.
- No transformer or MV/HV collection topology is established by the current site configuration.
- No authoritative shared post-parallel DC collection network is established.
- No explicit S9-4A per-inverter AC capability authority has yet been established for Bracon Ash.

The current repository values `320 kWac`, grid export limit, inverter model name, CEC/SAM fields, and legacy AC wiring percentage do **not** by themselves establish:

- rated apparent power `Smax`;
- AC voltage basis;
- phase configuration;
- fixed reactive-power capability;
- manufacturer P-Q/PF capability.

Do not invent these relationships or use group membership, equipment count, capacity, labels, positions, `Paco`, CEC/SAM `Vac`, or cable-plan assumptions as substitutes for electrical/equipment authority.

## Applicability of the validated S8–S14 chain

Heliotelligence now contains independently validated generic contracts through S14 meter benchmarking and delivery-loss attribution. Generic S12–S14 implementation does **not** make Bracon Ash S12–S14 ready.

“Implemented generically” means the reusable physics contract exists and is tested. It does not mean every configured site has enough evidence to resolve that stage. **Code capability ≠ site evidence ≠ resolved timestamp ≠ production activation.**

The current generic chain includes:

```text
physical string I-V
→ common-voltage MPPT / physical mismatch
→ explicit direct branch resistance transform
→ MPPT-input operating point
→ inverter CEC/SAM authority
→ inverter DC envelope
→ Sandia conversion
→ pre-Paco potential
→ conversion / clipping / tare accounting
→ static P/Q/S capability
→ temperature-dependent capability
→ explicit active-power dispatch request
→ requested P/Q/S feasibility
→ exact feasible-request selected P/Q/S
→ explicit static radial LV topology + direct per-phase R+jX
→ explicit timestamped collection-exit V_LL,RMS
→ modeled balanced radial LV operating solution
→ S12 transformer authority/loss correction/coupled terminals
→ S13 MV/HV network and expected/measured meter boundaries
→ S14 instantaneous/interval benchmarks and delivery-loss accounting
```

For Bracon Ash specifically, topology-dependent stages must remain unresolved where required MPPT/string/cable authority is absent. S9-4A requires explicit per-inverter AC capability evidence; S9-4B additionally requires explicit timestamped Q requests; S9-4C requires authoritative inverter thermal-derating evidence; S9-4D additionally requires explicit matching inverter-temperature state; S10A requires explicit timestamped per-inverter active-power request; S10B requires the preceding capability/request evidence; and S10C can establish a selected point only where S10B fully proves the exact request feasible.

Do not back-fill missing authority from total string count, inverter groups, inverter count, 320 kWac nominal power, grid export limit, CEC `Vac`, active-power nameplate, geometry or measured output.

The validated direct-branch resistance model also does not establish Bracon Ash's real shared combiner/homerun network. That still requires as-built electrical evidence before generalized DC collection can be activated.

## S9-4B applicability

S9-4B is implemented generically and evaluates admitted S9-3B active power plus S9-4A static capability authority and an explicit timestamped Q request.

Its existence does **not** make Bracon Ash S9-4B-ready.

For Bracon Ash, S9-4B requires:

- authoritative per-inverter S9-4A voltage/basis/phase/`Smax` authority;
- fixed Q limits where available, with missing limits preserved as partial authority;
- an explicit requested/commanded Q at the evaluated timestamp;
- the project Q sign convention: positive injection, negative absorption.

Do not infer these inputs from 320 kWac nominal power, grid export limit, `Paco`, CEC `Vac`, inverter groups, model labels, MPPT/string counts, or legacy AC wiring percentages.

If fixed-Q capability evidence is unavailable, an Smax-circle pass remains only a partial capability result. If `|P| > Smax`, that known violation can still be preserved. No S9-4B result should be interpreted as dispatch, thermal derating, AC-current state, or site-network validation.

## S9-4C applicability

S9-4C is implemented generically as independent static thermal-derating authority, but no Bracon Ash inverter thermal authority should be invented from site weather, PV module temperature, nominal inverter power, CEC/SAM records, or generic inverter assumptions.

Bracon Ash S9-4C requires authoritative per-inverter evidence for:

- the relevant inverter `temperature_quantity`;
- the supported temperature domain;
- explicit no-derating authority or aligned P/S/Q thermal capability curves;
- provenance and confidence.

Reactive thermal limits use the project convention: positive Q is injection and negative Q is absorption. Manufacturer evidence using another convention must be transformed before authority construction.

Until such evidence is supplied, Bracon Ash thermal authority remains unresolved. S9-4D must not substitute module/cell temperature or ambient temperature unless that exact quantity is the admitted S9-4C authority basis.

## S9-4D applicability

S9-4D is implemented generically, but its existence does **not** make Bracon Ash thermally resolved.

For Bracon Ash, S9-4D requires all upstream S9-4B authority plus:

- resolved S9-4C thermal authority for the physical inverter;
- an explicit timestamped `InverterTemperatureState`;
- exact physical temperature-quantity match to S9-4C;
- a temperature inside the declared inclusive authority domain.

Do not substitute module/cell temperature for inverter temperature. Do not infer heatsink/internal temperature from ambient air unless the admitted manufacturer authority itself uses that exact ambient quantity.

Outside the authority domain S9-4D remains unresolved; it does not clamp or extrapolate. Missing thermal channels remain partial authority. A known upstream or thermal violation remains definitive, but a passing partial result does not become a fully satisfied capability state.

No S9-4D result should be interpreted as controller dispatch, actual inverter output, AC-current state, or site-network validation.

## S10A applicability

S10A is implemented generically, but no Bracon Ash controller request should be inferred from existing configuration.

`grid_limit_kwac` is **not** a timestamped per-inverter dispatch setpoint. A site export limit is also not equivalent to an individual inverter request because allocation across physical inverters requires separate controller authority.

Bracon Ash S10A resolution therefore requires direct explicit evidence such as a PPC/SCADA/OEM per-inverter active-power command at the relevant timestamp and at the `inverter_ac_output` reference plane.

Missing command remains unresolved. Explicit zero is a valid resolved command. S10A does not persist a previous request forward in time. Canonical Q request remains S9-4B-owned.

## S10B applicability

S10B evaluates the exact Bracon Ash requested P/Q/S point only when the upstream evidence exists.

It must not substitute `p_ac_available_w` for a missing P request, synthesize Q=0, allocate the site export limit across inverters, or use measured output as a request. Static and thermal capability evidence remain separately attributable.

A known explicit violation can be definitive under partial information, but a passing partial-authority state must remain partial rather than being promoted to full feasibility.

## S10C applicability

S10C can establish a Bracon Ash selected inverter target only when canonical S10B fully proves the exact requested point feasible.

It must not infer saturation behaviour for an infeasible request. In particular, it must not set `P_selected=min(P_requested,P_available)`, clip Q, project onto an S limit or thermal limit, or infer zero for inactive/missing state.

The S10C selected state is a controller/model target, not proof of actual inverter output. Bracon Ash telemetry reconciliation remains a separate future boundary.

## S11 applicability

S11A, S11B, and S11C are implemented generically, but Bracon Ash is not S11-ready from current configuration.

Bracon Ash S11A requires explicit evidence, as applicable, for:

- physical `inverter_terminal`, `junction`, and `collection_exit` nodes;
- exact inverter-to-terminal bindings at `inverter_ac_output`;
- directed radial connectivity toward each collection exit;
- direct segment resistance and reactance per phase;
- balanced-three-phase, line-to-line RMS, and per-phase series-impedance bases.

Bracon Ash S11B additionally requires exact timestamped `V_LL,RMS` evidence at each physical `lv_ac_collection_exit`. Do not infer it from inverter CEC `Vac`, nameplate or nominal voltage, transformer ratings, site labels, capacity, geometry, or measured inverter output. A voltage at some other physical plane is not collection-exit authority.

S11C can solve a tree only where canonical S10C selected P/Q exists for every member inverter, global S11A inverter membership is closed, and the exact timestamp/exit S11B boundary is resolved. Missing selected dispatch is not zero; explicit selected P=Q=0 is zero injection. The resulting voltage, current, delivered P/Q, and loss quantities are modeled states, not measurements.

The legacy `wiring_loss_ac_pct` does not establish nodes, connectivity, R/X, or voltage and is not consumed by S11. Physical `3R|I|²` loss and legacy aggregate AC wiring loss must not both be applied to the same path without an explicit production migration.

Missing Bracon Ash S11 authority remains unresolved. Existing MPPT/string mapping, S9 AC capability/controller evidence, and transformer/MV/HV topology gaps also remain unresolved; no site values are populated by the generic implementation.

## S12–S14 evidence onboarding

Repository site configuration (`config/sites.yaml`) supplies aggregate equipment/layout and loss settings, not a complete authority package. Generic test fixtures demonstrate contracts and are not Bracon Ash as-built evidence. Existing SCADA/meter ingestion does not itself establish an S13D physical meter binding, scaling or temporal semantics.

In addition to the MPPT/string/DC, S9/S10 and S11 gaps above, current site configuration does not establish:

- transformer equipment, terminal bindings, ratio/tapping and impedance reference-side authority;
- factory no-load/load-loss test evidence, construction/component allocations, thermal channels or transformer-terminal harmonic authority;
- transformer-to-MV/HV connectivity, complete MV/HV topology and nominal-pi electrical parameters;
- exact timestamped grid-boundary voltage authority;
- explicit revenue-meter physical binding and admitted signed/scaled snapshot or interval measurement authority.

Timestamped controller P/Q requests and inverter thermal authority/state also require explicit evidence; weather, module temperature and the site grid cap cannot supply them. The existence of documents or external site records must be checked during onboarding; absence from this configured authority package is not a claim that evidence cannot exist externally.

S12M can select valid lower-fidelity transformer physics where evidence supports the S12G baseline. Such fallback may pass through S13C and S14A/B/C only when their own boundary/electrical evidence resolves. It cannot repair missing topology or voltage evidence. Fallback provenance remains visible, including S14C fallback IDs/presence across interval support.

The next workstream is controlled [production integration and site evidence onboarding](../development/production-integration-roadmap.md), following completed P0 source isolation at PR #118. No site activation is performed by the generic module thermal increment.

## Weather and front-POA evidence onboarding

Repository behaviour is explicit: Solcast stores `period_end`; SCADA CSV parsing documents source period-start labels and converts them to stored UTC period-end. The new generic authority can represent these labels, but **Bracon Ash is not automatically admitted** from storage conventions or field names. No collector/parser changes or automatic site bindings are made.

Required source/site evidence includes whether values are snapshots or interval averages, actual averaging duration/coverage and timestamp-label semantics, and explicit admission of the midpoint approximation where used. The new time contract never infers duration from neighbouring rows. Source documentation must justify a binding rather than assuming all instruments share one temporal meaning.

For front POA, establish sensor calibration, exact front measurement plane/quantity, method, applicability and receiver/zone coverage. A `poa_wm2` field alone is not `front_surface_incident_broadband_poa` authority. Modelled rear coverage/evidence, bifacial response and spectral enabled/disabled/unknown admission also remain explicit requirements. Measured front is not front+rear total and never implies rear=0 or replaces the canonical electrical chain.

Generic weather-time and canonical irradiance boundary capability is implemented and dormant. Raw front/rear and their diagnostic sum are available independently of optical/spectral electrical irradiance. Actual module-thermal POA handoff remains unresolved until calibration-basis evidence justifies front-only or both-surfaces selection. Existing module-thermal sensor/model/zone admission gaps below remain open; no full upstream production or P3 readiness claim follows.

## Module thermal evidence onboarding

The repository normaliser maps `PT1000-MODULE-*` channels into an averaging group for `temp_mod_avg_c`; the ORM documents the average of MODULE-1..6. That establishes ingestion/aggregation behaviour only. It does not establish a canonical cell or module-back physical measurement quantity for Bracon Ash.

The generic `module_thermal_authority.py` / `module_thermal_state.py` contract is implemented but dormant. **Bracon Ash cannot yet be admitted to it from current repository evidence.** Required evidence includes:

- exact sensor physical location, attachment/backsheet mounting method, calibration/verification and temporal applicability;
- whether the channel measures cell temperature or module-back-surface temperature;
- explicit thermal-zone identity, zone-to-module coverage, sensor membership/weights and aggregation suitability;
- for module-back conversion, explicit deltaT and reference irradiance with source/confidence/method evidence;
- for a model path, native PVsyst u_c/u_v plus module efficiency/absorption, or native Faiman u0/u1 plus declared output quantity, method and wind calibration-height basis;
- admitted total incident broadband thermal POA and aligned ambient/wind evidence where that selected model requires them, with source/site weather-time authority admitted explicitly through the separate generic temporal contract.

No deltaT=3°C, mounting/construction, sensor placement or calibration is inferred from channel labels, module name, geometry or `temp_mod_avg_c`. Existing `ModuleConfig.u_c/u_v/noct_c` values are legacy compatibility fields, not canonical authority. Thermal POA is not automatically electrical-effective irradiance. Generic implementation ≠ Bracon thermal admission.

Production still uses `physics/thermal.py`: its measured-module offset and PVsyst/Faiman semantic mismatch remain unchanged until controlled migration. The new explicit-authority conversion and the legacy compatibility API must not be presented as numerically equivalent. Weather/optical site evidence and runtime integration, population-residual and S14B support-policy site admission, uncertainty and authorization gates remain open; generic temporal/irradiance-boundary implementation alone does not close them.

## Module-population mismatch evidence onboarding

Bracon Ash remains **module-population mismatch authority not admitted**. Repository evidence establishes only the legacy aggregate `mismatch_loss_pct = 1.15%`; it does not allocate that percentage among manufacturing variability, operating-condition differences, shared-MPPT interaction or other assumptions. The new generic authority does not consume 1.15%, and this percentage is not retired.

Admission requires a factory flash population study, commissioning/string-I-V study, validated engineering mismatch study or other independently justified population evidence. Supply the quantified fraction (or explicit negligible conclusion), source, confidence, method, physical applicability period, and exact MPPT/string coverage. The study must explicitly isolate the intra-string population residual and exclude shared-MPPT common-voltage mismatch, wiring, shading, spectral/thermal effects, soiling, LID and conversion. Existing missing string/MPPT mappings are not inferred.

Nameplate power tolerance alone is neither mismatch loss nor a current/voltage distribution. The generic fallback is an honestly labelled lower-fidelity post-MPPT current derate, not member-resolved reverse/bypass physics. Legacy aggregate mismatch cannot coexist with this replacement in one expected series without an evidence-backed non-overlap allocation; none is established for Bracon. Legacy production stays unchanged and no P1/P2/P3 activation follows.

## Interval support-policy evidence onboarding

No Bracon Ash support-gap threshold is inferred, and **Bracon support policy is not admitted**. Generic S14B v2 now requires explicit per-meter maximum-gap eligibility authority for a finite reconstructed interval to become benchmark eligible. Mathematical reconstruction alone does not admit benchmark evidence. Missing/excess-gap policy keeps reconstructed energy visible but residuals unpublished; S14C does not bypass eligibility.

Required evidence includes intended physical-shadow model cadence, actual timestamp completeness, measurement interval duration, daylight-edge/fast-ramp and representative operating-regime sensitivity, benchmark accuracy objective, and temporal applicability. Supply the study/method, source, confidence and explicit meter coverage. Nominal source cadence, hourly duration or SCADA label format alone does not establish an acceptable gap. Synthetic quadratic regressions and their test policies are not site evidence or threshold recommendations. No production or shadow activation occurs.

## Legacy compatibility note

The site's current aggregate soiling, LID, mismatch, DC wiring, AC wiring and grid-limit configuration belong to the legacy compatibility path. The generic S8–S14 component chain remains dormant from the default production path; S11 does not consume `wiring_loss_ac_pct`. Legacy and physical replacements must not be combined without an explicit production migration demonstrating no double counting.

## Capacity arithmetic discrepancy

The configured component counts imply:

`24 modules/string × 2,076 strings × 570 W/module = 28,399.68 kWp`

The documented/configured site capacity is `28,524 kWp`, a difference of `124.32 kWp` (approximately `0.436%`). Both values are recorded in current repository configuration or module data, but the repository does not establish the reason for the difference.

Do not invent an explanation. Resolve the discrepancy only from authoritative as-built, module, or commissioning records, then update configuration and documentation through a separately reviewed change.

## Revenue-meter quantitative uncertainty evidence

Generic complete-chain measurement bounds are implemented but **Bracon numerical measurement uncertainty remains unadmitted**. No percentage is inferred from equipment names, legacy configuration, categorical confidence or an accuracy-class string. Required evidence includes:

- Meter make/model and explicit numerical accuracy specification.
- CT ratio/class and applicable numerical accuracy evidence.
- PT/VT ratio/class and applicable numerical accuracy evidence.
- Scaling configuration and calibration certificate/results.
- Calibration validity/applicability period covering the complete represented measurement interval for interval averages (or the observation timestamp for snapshots), inclusive of the declared boundaries.
- Whether a quoted bound is component-only or an admitted complete-chain bound after instrument transformers, scaling and calibration.
- P/Q applicability, snapshot versus interval-average applicability, and source/provenance.
- Relative-bound reference basis: magnitude of the same measured P/Q in primary engineering units. Other specifications (true value, full scale/rating, capacity or instrument current) require an explicit compatible bound conversion and its provenance before admission.

Site admission must supply the already-combined complete-chain numerical bound; the generic module does not add or RSS component specifications. Measurement-only bounds do not establish expected/model uncertainty or S14/P4 significance. Combined interpretation and production/shadow activation remain pending.

## Expected-model uncertainty evidence

Pointwise complete-model uncertainty is implemented generically but **Bracon numerical expected/model uncertainty remains unadmitted**. Admission needs an explicit validated complete-chain bound or engineering uncertainty budget at the canonical S13C revenue-meter P/Q boundary, with model/version/study provenance, applicable operating domain and dates, P/Q channel coverage and exact meter mapping. Relative terms must reference the magnitude of the same expected P/Q in primary engineering units; other references require an externally documented compatible conversion.

No nameplate/site capacity, component specification, legacy loss percentage, categorical confidence or S14 residual is numerical model-bound authority. Measurement uncertainty is separate. Expected interval propagation, combined envelopes, uncertainty-aware interpretation and production/shadow activation remain pending; no Bracon percentage or interval rule is inferred.
