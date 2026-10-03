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
INVERTER THERMAL-DERATING AUTHORITY [next]
↓
TEMPERATURE-DEPENDENT INVERTER CAPABILITY EVALUATION [planned]
↓
PLANT CONTROLLER / DISPATCH
↓
LV AC COLLECTION
↓
TRANSFORMER
↓
MV / HV NETWORK
↓
GRID / REVENUE METER
↓
BENCHMARKING / CAUSAL LOSS ATTRIBUTION
```


## Current validated electrical implementation

As of the PR #73 merge checkpoint, the validated electrical chain includes:

```text
S8-1  physical string I-V
S8-2  source-plane common-voltage MPPT / physical mismatch
S8-3A direct branch resistance authority
S8-3B resistive branch I-V transform
S8-3C MPPT-input common-voltage operating point
S9-0  inverter CEC/SAM authority
S9-1  inverter DC envelope classification
S9-2  Sandia inverter conversion
S9-3A Sandia pre-Paco AC potential
S9-3B conversion / clipping / tare power accounting
S9-4A explicit static inverter AC capability authority
S9-4B timestamped inverter P/Q/S capability-state evaluation
```

The canonical merged checkpoint is:

`a39026379df00e5756ac2690977e005b169f920e`

The reviewed PR #73 synthetic merge was `88e80f751be3ffff10265fe6d8d4a7d27a5a8154`; CI #189 passed 2663 backend tests on Python 3.13.15 with `pvlib==0.15.2`, and the frontend build passed.

Always verify live `main` before relying on this SHA.

## Electrical reference planes

The architecture distinguishes these physical locations:

1. module terminals;
2. physical string source terminals;
3. branch/string cable output;
4. parallel collection junction;
5. shared homerun / feeder output;
6. inverter MPPT input terminals;
7. inverter conversion boundary / AC output;
8. future controller-dispatched inverter AC output;
9. downstream LV / transformer / MV / HV nodes;
10. revenue-meter boundary.

An accounting or counterfactual quantity such as Sandia pre-Paco potential is not automatically a physical conductor plane. Static equipment authority such as `Smax`, phase or nominal voltage is also not a physical operating-state plane.

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
| Inverter thermal derating | next | No canonical inverter thermal authority yet | S9-4C authority-first; operating derating only after explicit manufacturer/temperature authority |
| Plant controller | planned | Legacy grid-cap behaviour exists outside new chain | Explicit available → dispatched AC layer |
| LV AC cables | legacy approximation | Static compatibility AC wiring percentage | Physical segment network after P/Q/S state exists |
| Transformer | planned | Not separately canonical | Core + load loss model from equipment authority |
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

### Next: inverter thermal-derating authority

No canonical inverter thermal-derating authority exists yet.

S9-4C should first define explicit manufacturer-backed authority for the relevant inverter temperature quantity, valid temperature range / breakpoints or curves, affected active/apparent/reactive capability, interpolation/boundary rules, source and confidence.

Do not use module-cell temperature, ambient temperature alone, nameplate power, `Paco`, `Smax`, or a generic percentage as a substitute.

Temperature-dependent operating capability should be evaluated only after this authority exists, preferably as a separate narrow increment if combining authority and evaluation would widen the contract.

## Plant controller and AC network boundary

Available AC and dispatched AC are different states. Plant-control curtailment, Q/PF commands, and export setpoints belong in a controller layer after inverter capability evaluation.

Only after voltage, phase configuration, P, Q, and S are explicit should LV AC cable current and `I²R` loss be calculated. This prevents AC network physics from embedding hidden unity-PF or nominal-voltage assumptions.

## Partial shading target

The intended dependency remains:

`module-level irradiance → substring/bypass behaviour → module I-V → string I-V → possible multiple local maxima → MPPT behaviour`

A scalar shading or mismatch percentage is not the final target mechanism.

## Production integration boundary

Validated physical layers are not automatically production-active. The legacy compatibility path still contains aggregate loss behaviour. Production migration must prove no double counting and preserve safe fallback behaviour for sites without required authority.

## Reference site discipline

Bracon Ash remains a reference site, not a reusable topology template. Its physical MPPT-to-string map, cable network, S9-4A AC capability authority, transformer network, and MV/HV connectivity must not be invented from counts, groups, labels, capacities, `Paco`, or CEC `Vac`.

## Dependency lock

Current validated physics is pinned to:

`pvlib==0.15.2`

Do not upgrade the dependency as part of an unrelated model increment.
