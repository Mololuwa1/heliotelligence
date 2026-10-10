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

## Canonical physical chain

```text
WEATHER / QC
↓
SOLAR GEOMETRY + IRRADIANCE DECOMPOSITION
↓
FRONT / REAR OPTICAL STATE
├ horizon / near shading
├ diffuse visibility
├ IAM
├ bifacial rear response
└ spectral response
↓
CANONICAL ELECTRICAL IRRADIANCE
↓
THERMAL
↓ Tcell
MODULE ELECTRICAL MODEL
├ parameter resolution
├ De Soto / single diode
├ operating point
└ voltage-dependent I-V
↓
STRING ELECTRICAL MODEL
↓
COMMON-VOLTAGE MPPT / PHYSICAL MISMATCH
↓
DC COLLECTION
├ direct branch resistance [validated]
├ parallel collection node [future generalized network]
└ shared feeder / homerun [future generalized network]
↓
INVERTER DC ENVELOPE
↓
INVERTER CONVERSION
├ Sandia AC available
├ pre-Paco potential
└ conversion / clipping / tare accounting
↓
INVERTER STATIC AC CAPABILITY AUTHORITY [validated]
├ nominal AC voltage
├ voltage basis
├ phase configuration
├ Smax
└ optional fixed Q limits
↓
INVERTER P/Q/S CAPABILITY-STATE EVALUATION [validated]
↓
INVERTER THERMAL-DERATING AUTHORITY [validated]
↓
TEMPERATURE-DEPENDENT INVERTER CAPABILITY EVALUATION [validated]
↓
EXPLICIT INVERTER ACTIVE-POWER DISPATCH REQUEST [validated]
↓
REQUESTED DISPATCH FEASIBILITY [validated]
↓
SELECTED INVERTER AC DISPATCH [validated]
↓
LV AC STATIC RADIAL TOPOLOGY + R+jX AUTHORITY [validated]
↓
COLLECTION-EXIT V_LL,RMS AUTHORITY [validated]
↓
BALANCED RADIAL CONSTANT-PQ LV OPERATING SOLVE [validated]
↓
TRANSFORMER [next: authority first]
↓
MV / HV NETWORK
↓
GRID / REVENUE METER
↓
BENCHMARKING / CAUSAL LOSS ATTRIBUTION
```





## Current validated electrical implementation

The validated dormant electrical/control path now extends through **S12D transformer reference-condition active-loss evaluation**.

The transformer portion is intentionally authority-first and DAG-shaped:

```text
                       S12B factory P_NL/P_LL authority
                      /
S12A static authority+
                      \
                       S12C timestamped energisation authority

S11C collection-exit operating state
              \       |       /
               \      |      /
                +---- S12D ----+
                      |
             internal active-loss baseline
```

S12A establishes transformer identity/rated terminal bases and the direct S11-exit boundary. S12B and S12C are independent evidence channels. S12D performs the first transformer operating calculation only after canonical parent replay. No transformer network-side operating voltage/current/power state is solved yet.

## Electrical reference planes

Electrical state is boundary-specific:

1. module terminals;
2. physical string source terminals;
3. branch/string cable output;
4. parallel collection junction;
5. shared homerun / feeder output;
6. inverter MPPT input;
7. inverter AC output / conversion boundary;
8. S10C selected target / S11A inverter-terminal binding at `inverter_ac_output`;
9. S11C internal LV nodes;
10. `lv_ac_collection_exit`;
11. S12A transformer collection-side terminal when explicitly bound to the S11 exit;
12. S12A transformer network-side terminal identity, without a solved operating electrical state yet;
13. future MV/HV network nodes;
14. revenue meter.

S12D active loss is an internal model quantity and does not create a new conductor plane. Transformer sides remain **collection side** and **network side** unless explicit future authority establishes a voltage-order interpretation.

## Model status

| Layer | Current status | Current validated / compatibility approach | Target / next direction |
|---|---|---|---|
| Organisation/client | planned | Not a physics layer | Ownership/access boundary above portfolios |
| Portfolio | planned | Site models remain independent | Composition and analytics across sites |
| Weather / QC | implemented | Database-backed weather with existing quality handling | Multi-source resolver refinement where needed |
| Solar geometry / decomposition | implemented | pvlib-based geometry and component resolution | Continue evidence-driven validation |
| Front POA | implemented | Component-resolved irradiance chain | Maintain boundary/provenance clarity |
| Horizon / near shading | implemented for validated coverage | Explicit geometry authority and visibility state | Extend geometry coverage only with validated contracts |
| IAM / optics | implemented | Physical IAM / optical-effective state | Retain and validate by module/site evidence |
| Rear / bifacial | implemented for supported fixed-row coverage | Infinite-sheds / fixed-row rear chain with optical response | Future arbitrary 3D/terrain/tracker extensions |
| Spectral correction | implemented | Component-resolved spectral response | Retain/refine where evidence requires |
| Soiling | legacy approximation | Aggregate production compatibility percentage | Time-varying physical or measured state |
| Snow | not implemented | No canonical snow state | Explicit stateful snow model |
| Thermal | implemented | Existing measured / Faiman / fallback hierarchy | Improve only through validated authority |
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
| Transformer static/boundary authority | implemented, dormant | S12A explicit identity, rated terminal bases and direct S11-exit binding | Preserve explicit authority; no inferred winding/network physics |
| Transformer factory-test loss authority | implemented, dormant | S12B explicit P_NL / total rated P_LL with test/reference conditions | Enhanced loss channels only when separately authoritative |
| Transformer energisation authority | implemented, dormant | S12C exact timestamped energised/de-energised evidence | No persistence or operating inference |
| Transformer baseline active loss | implemented, dormant | S12D current-based factory-reference baseline | Preserve as baseline; no terminal power allocation |
| Transformer electrical/network state | deferred | No canonical network-side operating solve yet | Design explicit authority/solve before S13 |
| MV/HV network | planned | Not canonical | Topology-aware network elements |
| Revenue meter | partial | Actual data exists for comparison | Explicit end-of-chain expected boundary |
| Benchmarking | partial / legacy | Existing reporting and residual concepts | Physics-telescoping causal attribution |

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

`three_phase + single_phase_terminal` is invalid. Missing fixed-Q authority remains distinct from explicit zero Q capability.


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

The S12 baseline-loss milestone is now implemented through S12D. S12A explicitly establishes any direct `lv_ac_collection_exit` to transformer collection-side boundary; transformer electrical/network terminal propagation remains deferred.

## Transformer architecture

### S12A — static transformer authority

S12A admits explicit two-winding balanced-three-phase identity, rated apparent power, rated collection/network line-to-line RMS voltages, transformer terminal identities/reference planes, and direct S11 collection-exit binding. It does not infer winding ratio physics, impedance, vector group, tap state, phase displacement, loss or operating state.

### S12B — factory-test loss authority

S12B separately admits transformer-specific `P_NL` and total rated `P_LL` with their test/reference conditions and independent provenance. Missing values remain missing; explicit zero is valid. Aggregate `P_LL` must not be silently decomposed into copper, eddy and stray components.

### S12C — energisation authority

S12C is exact timestamped binary evidence. `True`, `False` and missing remain distinct. It does not infer energisation from power, voltage, time, daylight, inverter state or schedules and does not persist state between timestamps.

### S12D — baseline active-loss evaluation

S12D uses delivered S11C collection-exit `P`, `Q` and `V_LL` after LV collection loss:

```text
|S_exit| = sqrt(P_exit² + Q_exit²)
I_oper = |S_exit| / (sqrt(3) V_exit)
I_rated = S_rated / (sqrt(3) V_rated,collection)
beta_I = I_oper / I_rated
P_load = P_LL beta_I²
P_total = P_NL + P_load
```

This is a factory-reference-condition baseline. `beta_I` is not clamped. Q and operating voltage therefore affect current and load loss.

Clean explicit de-energisation resolves zero internal loss; de-energised nonzero transfer is a contradiction, and energised zero collection voltage is unresolved. No temperature, harmonic, frequency or voltage-dependent no-load correction is applied.

S12D does not solve transformer terminal phasors or allocate the loss to one terminal. In particular it does not imply `P_network_side = P_collection_exit - P_loss`.

### Deferred transformer electrical/network layer

A future independent transformer electrical/network model must establish the defensible network-side operating boundary required before S13. Possible required evidence may include series impedance, magnitude transformation and phase displacement, but the exact contract remains to be designed. The superseded branch-only R/X/G/B S12B implementation is not part of the merged architecture.

## Partial shading target

The intended dependency remains:

`module-level irradiance → substring/bypass behaviour → module I-V → string I-V → possible multiple local maxima → MPPT behaviour`

A scalar shading or mismatch percentage is not the final target mechanism.

## Production integration boundary

Validated physical layers through S12D are not automatically production-active. The legacy compatibility path still contains aggregate loss behaviour. Production migration must prove no double counting and preserve safe fallback behaviour for sites without required authority.

## Reference site discipline

Bracon Ash remains a reference site, not a reusable topology template. Its physical MPPT-to-string map, DC/LV cable networks, S9-4A AC capability authority, S11 terminal/junction/exit topology, direct R/X, collection-exit voltage, S12 transformer authority/evidence, transformer network state, and MV/HV connectivity must not be invented from counts, groups, labels, capacities, geometry, `Paco`, CEC `Vac`, geography, or legacy losses.

## Dependency lock

Current validated physics is pinned to:

`pvlib==0.15.2`

Do not upgrade the dependency as part of an unrelated model increment.
