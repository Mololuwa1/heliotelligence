# Heliotelligence AI / Developer Handoff

This is the durable recovery and architectural checkpoint for Heliotelligence.
It does **not** replace the repository, automated tests, Git history, or direct
inspection of current code.

Heliotelligence is now being developed as an **enterprise-grade solar digital
twin / physics benchmarking platform**, not an MVP. The current implementation
strategy is physics-first, component-resolved, provenance-aware, and defensive
at every authority boundary.

## Recovery rule

When beginning from a new conversation or development session:

1. Query Git for the current `main`, then fetch it.
2. Read this file.
3. Read `docs/architecture/physics-architecture.md`.
4. Read `docs/development/physics-roadmap.md`.
5. Inspect open pull requests.
6. Read the relevant implementation and tests.
7. Treat current source, tests, CI, and Git history as authoritative when
   documentation or remembered conversation context disagrees.

Do not trust a SHA written in documentation as "current main" indefinitely.
Always query Git first.

## Status language

Use these terms consistently throughout this document:

- **VALIDATED / MERGED / CLOSED** — independently reviewed, merged to `main`,
  exact merge ancestry checked, and exact-main push CI verified.
- **OPEN / IN REVIEW** — code exists only on a branch or pull request and must
  not be described as a current `main` capability.
- **PLANNED / PROPOSED** — architecture or implementation direction only; no
  production capability should be inferred.
- **PARKED** — deliberately deferred until a later product or physics phase.
- **BLOCKED** — implementation depends on unavailable evidence, topology, data,
  or another prerequisite.

Future stage numbers after the current open work are **provisional** until an
architecture review locks each contract. Do not treat a proposed stage number
as an implementation commitment.

## Current validated baseline

As of the latest validated merge in this handoff:

- live validated `main`:
  `11ef177b609a284ff48830a035d56d62933d2b7a`
- merge: PR #57 — S8-1 state-aware physical string I-V scaling
- exact-main CI: run #149
- backend exact-main result: **2366 passed**
- frontend build: passed as a passive compatibility check

This SHA is a checkpoint, not a permanent source of truth. Always query Git.

## Current implementation status

### Completed / validated physics chain

The validated backend now reaches:

```text
Weather / QC
  ↓
Solar position / decomposition
  ↓
Front POA irradiance
  ↓
Far-horizon authority
  ↓
Near-shading authority
  ↓
Selected direct-geometry authority
  ↓
Diffuse visibility
  ↓
IAM
  ↓
Front optical-effective irradiance
  ↓
Rear irradiance / rear optical chain
  ↓
Bifacial electrical response
  ↓
Component-resolved spectral response
  ↓
Receiver-resolved module electrical state
  ↓
Explicit receiver → physical string module-I-V routing
  ↓
Physical homogeneous string I-V scaling
  ↓
S8-2 common-voltage MPPT + physical mismatch  ← currently in PR #58
  ↓
Future architecture review before cable / inverter / system integration
```

Thermal remains a separate physical authority and must not consume
bifacial/spectral electrical-equivalent irradiance as a thermal irradiance
surrogate.

## Stage tracker

- S1 / S2 / S3 / S4A — completed
- S4B — blocked by private PVcase `.pvc2` evidence
- S5A ray backend — completed
- S5B mesh adapter — completed
- S5C near-object beam — completed
- S6A terrain horizon — completed
- S6B fixed inter-row — completed
- S6C tracker — parked
- S6D diffuse — completed
- S6E fixed rear raw — completed
- S6F-0 — completed
- S6F-1 — completed
- S6F-2 — completed
- S6F-3 — completed
- S6F-4 — completed / merged
- S7A — completed, v2 authority active
- S7B-1 / S7B-2 — completed
- S7C — completed
- S7D-0 / S7D-1 — completed
- S7E-0 — VALIDATED / MERGED / CLOSED
- S7E-1 — VALIDATED / MERGED / CLOSED
- S8-0 — VALIDATED / MERGED / CLOSED
- S8-1 — VALIDATED / MERGED / CLOSED
- S8-2 — OPEN / IN REVIEW in PR #58; merge currently withheld pending one
  narrow active-string replay correction
- S8-3 and later — PROPOSED only; architecture must be reviewed before stage
  numbering and boundaries are locked

## Recent validated merge history

### S6F-4 — selected shading authority

PR #53 completed the selected direct-geometry authority used by downstream
optical physics.

Key contract:

```text
final front direct geometry
  = selected horizon authority
  × selected near-shading authority
```

Raw terrain, fixed-row, and near-shading channels are retained as evidence and
provenance, but are not independently re-applied downstream.

The design prevents direct-shading double counting and keeps diffuse visibility
separate.

### S7E-0 — component-resolved spectral response

PR #54 merged component-resolved spectral response.

Reviewed head:

`06e5ff6fcbcf2ed2b8e9f14701d3ab6ee2d52db9`

Merge / validated main at that checkpoint:

`719875aba6d61b652f39c6a2da1080ff1a3be1bd`

Exact-main backend result at that checkpoint:

**2276 passed**

Production:

`src/heliotelligence/physics/spectral_response.py`

Canonical electrical-equivalent spectral irradiance:

```text
G_spectral,electrical,eq
  = M_f × G_front,eff
  + φ_Isc × M_r × G_rear,eff
```

Important ordering:

```text
front spectral response
rear spectral response
rear φ_Isc equivalence
sum into final spectral electrical-equivalent irradiance
```

Do **not** replace this with one scalar multiplication over a previously
combined bifacial irradiance unless a future contract explicitly proves the
front and rear spectral authorities are identical.

Front spectral authority:

- `enabled`
- `disabled`
- `unknown`

Rear spectral authority:

- `disabled`
- `explicit_factor`
- `unknown`

There is no HJT → mono-Si spectral inference in the canonical path.

There is no rear spectral inference from broadband albedo.

Atmospheric inputs are explicit. The spectral layer does not fabricate
precipitable water, pressure, altitude-derived pressure, or weather.

S7E-0 also retains a compatibility lock with `pvlib>=0.11.0`: Heliotelligence
performs explicit absolute-airmass clamping before calling the First Solar
spectral factor rather than relying on newer pvlib-only keyword arguments.

### S7E-1 — spectral electrical handoff to module solver

PR #55 merged the canonical spectral-electrical → module operating-point
boundary.

Reviewed head:

`c659fe07ffb28cc33ab117dbed19a96142f4cbc0`

Merge commit:

`f9ba1b59ce74e4c60aed8304538cf5127b5ff00e`

Public API:

`calculate_receiver_module_operating_points_from_spectral_response(...)`

Contract:

`receiver-resolved module electrical before topology`

The sole canonical electrical irradiance entering the module solver is:

`spectral_electrical_equivalent_irradiance_wm2`

The canonical path does **not** call the legacy spectral correction helper and
never applies First Solar twice.

Critical authority regression:

```text
front effective = 800 W/m²
front spectral factor = 0.95
rear effective = 200 W/m²
rear spectral factor = 1.05
φ_Isc = 0.80

front spectral = 760
rear spectral = 210
rear electrical-equivalent = 168
final spectral electrical-equivalent = 928 W/m²

pre-spectral S7D equivalent = 960 W/m²
```

The canonical module solver must consume **928 W/m²**, never 960 W/m².

Zero spectral electrical irradiance is a resolved exact-zero electrical state
and dominates missing cell temperature. Positive irradiance with missing cell
temperature remains unresolved.

Tier-5 remains PVWatts power-only for positive rows; voltage/current remain
unavailable there by design.

### S8-0 — explicit receiver → string module-I-V routing

PR #56 merged receiver-resolved electrical state into explicit physical string
routing.

Reviewed head:

`2adc2cb87191014423af4ff53b7e4a58809ec273`

Merge commit:

`63a5242e84c08b1ac8dbb71eab33caf44ace39cc`

Exact-main backend result:

**2331 passed**

Public API:

`calculate_topology_module_iv_curves_from_receiver_electrical(...)`

Canonical assignment authority is explicit runtime mapping from physical string
ID to receiver ID.

Do **not** infer receiver/string assignment from:

- `zone_id`;
- geometry;
- table proximity;
- receiver order;
- semantic names.

Multiple strings may legitimately share one receiver.

S8-0 creates representative-module voltage-dependent I-V curves for the
assigned receiver state, but does **not** yet scale them by
`modules_per_string`.

S8-0 defensively replays S7E-1 authority and rejects stale module physics.
The current module configuration is resolved once per call and is used for both
upstream operating-point replay and I-V generation.

Tier 3/4 datasheet reference fitting is performed at most once per call; the
same precomputed result, including authoritative `None`, is reused for both
operating-point replay and I-V generation.

S8-0 does not perform:

- string scaling;
- MPPT;
- mismatch;
- cable loss;
- inverter conversion;
- thermal calculation;
- legacy DC loss percentages.

### S8-1 — physical homogeneous string I-V scaling

PR #57 merged state-aware physical series-string scaling.

Reviewed head:

`34a1e5ac329e28a0708aa5403ecd4514f70bdb05`

Merge commit / current validated main:

`11ef177b609a284ff48830a035d56d62933d2b7a`

Exact-main backend result:

**2366 passed**

Public API:

`calculate_topology_string_iv_curves_from_receiver_module_iv(...)`

Series-length authority is exclusively:

`StringConfig.modules_per_string`

For a homogeneous physical series string:

```text
V_string = N_s × V_module
I_string = I_module
P_string = N_s × P_module
```

and pointwise:

```text
P_string = V_string × I_string
```

S8-1 requires exact `TopologyStringIVResult`-style authority replay from S8-0,
including:

- complete timestamp/string grid;
- explicit inverter/MPPT routing identity;
- canonical S8-0 provenance;
- tier / fit-quality domain closure;
- retained S7E-1 root-cause conditions;
- curve schema / point-grid closure;
- `P = V × I` closure;
- irradiance closure;
- shared-receiver normalized equivalence.

Strings sharing one receiver may have different physical string voltage and
power only because they can have different `modules_per_string`; their
representative-module basis remains identical.

S8-1 still does **not** perform parallel MPPT aggregation, mismatch, cable loss,
or inverter conversion.

## Current open work — S8-2

PR #58:

`feature/state-aware-mppt-mismatch`

Exact base:

`11ef177b609a284ff48830a035d56d62933d2b7a`

Current reviewed head before correction:

`449f33c2784dc9b0f6765036bbfc1bca5cc90f9b`

PR CI #150:

- event: `pull_request`
- frontend: success
- backend: success
- backend result: **2390 passed in 63.81s**

The implementation is **not yet merge-authorized**.

### S8-2 intended contract

Public API:

`calculate_topology_mppt_mismatch_from_string_iv(...)`

Per populated MPPT and timestamp, every member string is classified as:

- active;
- exact zero;
- unresolved.

Rules:

1. Any unresolved member makes the whole MPPT unresolved.
2. Active + zero is explicitly unresolved because Heliotelligence does not yet
   model dark-string reverse current or blocking-device behaviour.
3. All-zero MPPTs resolve exactly to zero without invoking MPPT physics.
4. All-active MPPTs use the existing IV-consistent common-voltage physical
   mismatch primitive.
5. No string may be silently dropped.
6. Distinct MPPTs remain independent; voltages are never averaged across MPPTs.

For active strings sharing one MPPT:

```text
I_MPPT(V) = Σ I_string(V)

V* = argmax_V [V × I_MPPT(V)]

P_common = V* × I_MPPT(V*)

P_independent = Σ Pmp,string

P_mismatch = P_independent - P_common
```

Active timestamps are batched so physical mismatch is called once per eligible
MPPT, not once per timestamp.

### Current S8-2 merge blocker

The S8-2 defensive admission layer must additionally prove that every row
labelled:

`resolved_string_iv`

contains a genuinely active physical string curve.

In addition to the existing voltage-grid and algebra checks, it must require:

```text
max(current_a) > 0
max(power_w) > 0
```

This prevents a forged "active" curve with positive voltage samples but zero
usable current/power from reaching common-voltage MPPT physics.

Until that correction is committed, reviewed, and exact-head CI is green, PR
#58 must remain unmerged.

## Common-voltage MPPT and mismatch authority

The project must distinguish two different quantities:

```text
P_independent = Σ Pmp,string
```

This is a counterfactual: each string operating independently at its own MPP.

Actual parallel strings connected to one MPPT share one operating voltage:

```text
I_MPPT(V) = Σ I_string(V)
P_actual = max_V [V × I_MPPT(V)]
P_mismatch = P_independent - P_actual
```

Never use independent-string MPP summation as actual common-MPPT power.

Never average the voltages of distinct MPPTs on one inverter.

## Current modelling boundary for zero / dark strings

The current exact-zero I-V representation is:

```text
V = 0
I = 0
P = 0
```

This is sufficient for an all-zero MPPT.

It is **not** enough to determine a zero/night string's behaviour when another
parallel string imposes positive voltage on the shared MPPT bus.

Therefore active + zero remains explicitly unresolved until a future stage
introduces justified physics for one or more of:

- dark-string reverse current;
- blocking diodes;
- isolation / switching behaviour.

Do not silently treat zero strings as disconnected.

## Current temporary / legacy compatibility behaviour

Legacy aggregate APIs remain available for compatibility.

`calculate_dc_power()` still retains the historical aggregate loss cascade:

`soiling → LID → static mismatch → DC wiring`

- `mismatch_loss_pct` remains active in the legacy path.
- `wiring_loss_dc_pct` remains active in the legacy path.
- `soiling_loss_pct` and `lid_loss_pct` remain active in the legacy path.

The new canonical S7/S8 chain must **not** reuse those percentages at the
component-resolved authority boundaries.

In particular:

- do not apply `mismatch_loss_pct` after S8-2 physical mismatch;
- do not apply `wiring_loss_dc_pct` before a physical cable model exists;
- do not apply a second spectral correction;
- do not use the electrical-equivalent irradiance as thermal irradiance.

## Geometry and topology locks

Canonical geometry uses ENU:

- X east
- Y north
- Z up
- metres

`PVReceiver.normal_enu` is the physical front normal. Rear is the opposite
normal. Do not mutate the receiver normal to represent the rear.

Electrical topology is explicit:

`Site → Inverter → MPPT → String`

Never infer electrical connectivity from geometry or proximity.

`zone_id` is descriptive metadata, not a canonical receiver/string assignment
authority.

## Fixed-table product scope

Heliotelligence v1 currently supports **fixed-tilt / fixed-table PV systems**.

Tracker modelling remains parked as S6C and must not be inferred from the fixed
receiver pipeline.

Product statement:

> Heliotelligence v1 supports fixed-tilt PV systems. Tracker modelling is
> deferred to a future capability.

## Thermal authority

Thermal remains a separate stage using physically appropriate thermal
irradiance and thermal inputs.

Do not feed either of these electrical constructs directly into thermal:

- `bifacial_electrical_equivalent_irradiance_wm2`
- `spectral_electrical_equivalent_irradiance_wm2`

unless a future thermal architecture explicitly establishes and validates such
a relationship.

The existing `_DELTA_T_COEFF = 0.03/1000.0` comment/code discrepancy is locked
by current tests and should be addressed separately rather than casually
changed during S8 work.

## Frontend boundary

The recent S7E / S8 work is **backend physics only**.

Frontend source is frozen during these stages.

The frontend CI job may run as a passive compatibility build, but S7E/S8 PRs
must not change frontend components, routes, styles, or UI logic unless a
separate frontend task is explicitly approved.

## Future implementation roadmap — NOT YET IMPLEMENTED

Everything in this section is **future architecture direction**, not a claim
about current `main` capability.

The only current coding work beyond validated `main` is S8-2 in PR #58.
All stages after S8-2 remain proposed until their own architecture contract is
reviewed and locked.

### Gate 0 — close and validate S8-2

Before starting any later electrical stage:

1. add the genuine-positive active-string checks:
   `max(current_a) > 0` and `max(power_w) > 0`;
2. independently review the correction delta;
3. verify new exact-head pull-request CI;
4. merge only the reviewed exact head;
5. verify merge ancestry;
6. verify exact-main push CI on the merge SHA;
7. mark S8-2 VALIDATED / MERGED / CLOSED.

No later stage should be built on an unvalidated S8-2 branch state.

### Proposed S8-3 — electrical reference-plane and DC collection architecture

**Status: PROPOSED — architecture review required before implementation.**

The next step must first define the electrical reference planes in the DC
network. At minimum distinguish:

```text
module terminals
  ↓
physical string terminals
  ↓
string / branch cable
  ↓
combiner or parallel junction, if present
  ↓
DC homerun / feeder, if present
  ↓
inverter MPPT input terminals
  ↓
inverter conversion stage
```

The architecture must establish exactly where each voltage/current/power value
is measured and which component owns each loss.

This review is necessary because cable resistance is not merely an aggregate
post-processing percentage. A branch resistance can change the voltage-current
relationship presented to the MPPT:

```text
V_terminal = V_source - I × R
P_loss = I²R
```

Therefore a string/branch cable model may need to transform each string I-V
curve **before** common-voltage MPPT optimization. Do not simply append all
cable loss after S8-2 because that can preserve the wrong MPPT operating point.

The S8-3 architecture review must decide, based on actual topology, which
resistive elements belong:

- on each string branch before parallel aggregation;
- after a combiner / parallel node;
- on a shared homerun;
- directly at inverter input terminals.

No implementation should start until those reference planes are explicit.

### Proposed physical DC collection model

**Status: PLANNED — exact stage number depends on S8-3 architecture.**

Required physical basis:

```text
R = ρ × L / A
P_loss = I²R
ΔV = I × R
```

Potentially model:

- positive and negative conductor path lengths;
- conductor material / resistivity;
- conductor cross-sectional area;
- conductor temperature or an explicitly documented resistance basis;
- string cable;
- branch cable;
- combiner connectivity;
- shared DC homerun / feeder;
- parallel branch current distribution.

Do not implement physical cable loss from a static percentage alone.

Minimum evidence required before physical cable implementation:

- actual cable topology;
- one-way or loop length definition;
- conductor material;
- cross-section or authoritative resistance-per-length;
- location of combiners / junctions;
- mapping from strings to those DC paths.

If these are unavailable, retain an explicit unresolved or compatibility state;
do not invent cable lengths or conductor sizes.

### Proposed inverter input capability model

**Status: PLANNED — not yet implemented in the canonical S8 chain.**

Future inverter integration must preserve **independent MPPT inputs**.

For each `(inverter_id, mppt_id)` retain its own:

- DC voltage;
- DC current;
- DC power;
- resolved / unresolved state;
- physical mismatch provenance;
- upstream cable / collection provenance when implemented.

Do **not** average MPPT voltages into one inverter voltage.

Future inverter capability evidence may include:

- MPPT operating-voltage window;
- absolute maximum DC voltage;
- MPPT input current limit;
- short-circuit current limit where relevant;
- number of MPPT trackers;
- string inputs per tracker;
- nominal / maximum DC power;
- manufacturer-specific clipping or derating rules.

These limits must come from authoritative inverter configuration or equipment
data, not from generic defaults guessed from inverter size.

### Proposed inverter conversion and clipping

**Status: PLANNED.**

After the DC reference plane and input-limit architecture are validated, add
per-inverter conversion using an appropriate validated model.

Potential capabilities:

- per-unit DC → AC conversion;
- model-specific efficiency curve;
- DC input clipping;
- AC nameplate clipping;
- voltage-dependent inverter behavior where supported;
- thermal / power derating only when authoritative inputs exist;
- explicit unresolved state when required manufacturer data is absent.

Do not collapse multiple independently controlled MPPT voltages into one
synthetic voltage merely to satisfy an aggregate inverter API.

If an existing lower-level inverter primitive cannot represent multiple MPPT
inputs faithfully, build an explicit adapter/contract or improve the inverter
model rather than fabricating one voltage.

### Proposed site-level DC / AC aggregation

**Status: PLANNED.**

Only after per-inverter electrical states are validated should the canonical
pipeline aggregate to site level.

Future site-level outputs should preserve enough provenance to answer:

- which inverter / MPPT caused a loss;
- which strings were unresolved;
- how much physical mismatch occurred;
- how much cable loss occurred;
- how much inverter conversion / clipping occurred;
- whether a grid/export constraint was active.

A site total must be a composition of component-resolved states, not a shortcut
that bypasses them.

### Proposed AC collection and transformer model

**Status: PLANNED.**

Potential later layers:

```text
inverter AC terminals
  ↓
LV cable
  ↓
local transformer
  ↓
MV collection
  ↓
main transformer
  ↓
HV / export network
  ↓
revenue meter / grid boundary
```

Physical AC network modelling may require:

- phase / voltage level;
- cable length and conductor data;
- transformer ratings;
- no-load and load losses;
- impedance;
- power factor / reactive-power state;
- topology and switching state.

Do not represent a physical AC network by a new arbitrary percentage if the
required physical data becomes available.

### Future dark-string / blocking-device model

**Status: PLANNED / evidence-dependent.**

S8-2 intentionally leaves active + zero parallel strings unresolved.

A future implementation may resolve this only after choosing a physically
justified model for the site/equipment, such as:

- dark-string reverse current;
- blocking diode behavior;
- string isolation / switching;
- other equipment-specific reverse-bias protection.

Required evidence may include:

- module reverse I-V characteristics;
- blocking-diode presence and orientation;
- protection / combiner design;
- inverter reverse-current behavior.

Do not assume every plant has blocking diodes.

### Future bypass-diode and partial-shading electrical model

**Status: PLANNED.**

The target dependency is:

```text
module / substring irradiance distribution
  ↓
cell or substring electrical state
  ↓
bypass-diode conduction
  ↓
module I-V
  ↓
heterogeneous string I-V
  ↓
possible multiple local maxima
  ↓
MPPT tracking behavior
```

This is separate from the current homogeneous-string S8 contract.

Do not add a scalar "partial shading loss" to the canonical component-resolved
chain as a substitute for this physics.

### Future MPPT tracking behavior

**Status: PLANNED.**

Current common-voltage MPPT physics finds the static maximum over the supplied
I-V curves. Future higher-fidelity behavior may include:

- multiple local maxima;
- tracker search algorithm;
- scan cadence;
- local-vs-global MPP capture;
- dynamic irradiance changes;
- tracker operating limits.

Only implement this when the product requirement justifies the additional
complexity and suitable validation evidence exists.

### Tracker geometry / irradiance modelling

**Status: PARKED (S6C).**

Heliotelligence v1 remains fixed-tilt / fixed-table.

Future tracker support requires an explicit architecture for:

- tracker axis geometry;
- rotation convention;
- backtracking;
- row-to-row shading under motion;
- dynamic front/rear normals;
- rear irradiance under changing geometry;
- tracker control / stow states where relevant.

Do not route tracker sites through fixed-table assumptions.

### Future soiling, LID and degradation replacement

**Status: PLANNED / evidence-dependent.**

The legacy aggregate percentages remain compatibility assumptions.

Future replacements should use measured or physically supported state where
possible, for example:

- time-varying measured soiling ratio;
- rainfall / cleaning events when scientifically justified;
- validated LID / LeTID or degradation state;
- equipment-specific degradation models.

Never remove a legacy percentage from a production path until its replacement
has been independently validated and the migration boundary is explicit.

### Future SCADA / digital-twin validation layer

**Status: PLANNED and iterative.**

As the physical chain matures, validate at multiple reference planes rather
than only comparing final site energy.

Potential validation hierarchy:

```text
weather
irradiance
module / string DC
MPPT DC
inverter DC input
inverter AC output
transformer / feeder output
revenue meter
```

For each comparison preserve:

- timestamp alignment;
- timezone;
- sensor quality flags;
- measurement uncertainty;
- availability / curtailment state;
- data provenance.

Do not tune one physical mechanism merely to compensate for error in another
layer.

### Future multi-site / portfolio layer

**Status: PLANNED platform layer, not part of the current physics migration.**

Portfolio analytics should compose independently validated site results.

Potential future capabilities:

- organisation / client ownership;
- portfolios;
- portfolio energy aggregation;
- cross-site benchmarking;
- fleet availability;
- fleet anomaly detection;
- loss attribution across sites;
- portfolio financial / revenue analytics.

Do not treat multiple sites as one electrical plant.

### Evidence required before future mechanisms are enabled

Future implementation should prefer explicit `unknown`, `unresolved`, or
`not_applicable` states over guessed parameters.

Examples of mechanism-specific evidence:

| Mechanism | Minimum authoritative evidence before high-fidelity implementation |
|---|---|
| String / DC cable | topology, path length, conductor size or resistance, conductor material |
| Combiner / homerun | connectivity, shared path, resistance / conductor data |
| Inverter MPPT limits | exact inverter model or authoritative configured limits |
| Blocking devices | confirmed device presence, topology, electrical behavior |
| Bypass diodes | module substring / diode architecture or validated module model |
| Tracker | axis geometry, control convention, backtracking / stow behavior |
| AC cable | topology, voltage level, length, conductor / impedance data |
| Transformer | rating, loss / impedance data, topology |
| SCADA calibration | channel mapping, timestamp basis, units, quality / availability flags |

Absence of evidence is not permission to infer a convenient default.

### Definition of done for every future physical stage

A future stage is not complete merely because its implementation runs.

At minimum require:

1. **Narrow physical contract** — define exactly what mechanism is owned by the
   stage and where its electrical / optical reference plane sits.
2. **Explicit authority inputs** — identify configuration, measurements, or
   upstream result types that are allowed to drive the model.
3. **Unresolved semantics** — define behavior when required evidence is absent
   or contradictory; no silent fallback to zero/unity unless physically
   justified.
4. **Provenance** — emit contract/model/scope identifiers where appropriate.
5. **No double counting** — prove legacy or upstream mechanisms are not applied
   again after the physical replacement.
6. **Limiting cases** — test exact zero, unity/no-loss, symmetry, and other
   physically meaningful limits.
7. **Conservation / closure** — e.g. `P = V × I`, energy/loss balance, or
   mechanism-specific conservation checks.
8. **Reference parity** — compare against a trusted lower-level primitive,
   pvlib, analytical result, manufacturer curve, or another defensible
   reference where applicable.
9. **Adversarial authority tests** — forged provenance, stale topology,
   contradictory state, NaN/inf, duplicate/missing rows, and wrong parameter
   domains must fail before downstream physics.
10. **Immutability / determinism** — input reordering or deep-copy behavior must
    not silently change physical output.
11. **Focused regression suite** — existing upstream and adjacent physics must
    remain green.
12. **Full backend** — unit suite green without increasing known static-analysis
    debt.
13. **Exact-head PR CI** — verify the actual reviewed commit, not only local
    tests.
14. **Independent live-code review** — do not rely only on an implementation
    report.
15. **Exact merge ancestry** — confirm the merged head is the reviewed head.
16. **Exact-main push CI** — only then mark the stage
    VALIDATED / MERGED / CLOSED.

### Explicitly prohibited future shortcuts

Unless a future architecture explicitly proves otherwise, do **not**:

- average distinct MPPT voltages;
- use `Σ Pmp,string` as actual shared-MPPT power;
- drop unresolved or zero strings from a parallel MPPT;
- treat a zero string as disconnected;
- infer blocking diodes;
- infer string-to-MPPT mapping from geometry;
- infer cable length from receiver spacing;
- use `zone_id` as electrical authority;
- apply static mismatch after physical mismatch;
- apply static wiring loss after physical cable loss;
- reapply spectral response after S7E-0/S7E-1;
- feed electrical-equivalent irradiance into thermal without an explicit
  thermal contract;
- combine separate site electrical networks into one physics solve;
- label a proposed roadmap capability as implemented before its exact-main
  validation gate is complete.

## Non-negotiable project rules

- Use physics-first modelling where a mechanism can reasonably be calculated.
- Do not replace one arbitrary loss percentage with another disguised
  approximation.
- Preserve legacy behaviour until its replacement is independently validated.
- Prefer focused PRs with equivalence, limiting-case, provenance, and physics
  tests.
- Do not invent unavailable physical topology.
- Do not infer electrical topology from geometry.
- Do not silently replace unresolved physical states with zeros or unity.
- Do not double-count a physical mechanism after it has been calculated
  explicitly.
- Validate upstream authority before invoking downstream physics.
- Reuse validated lower-level primitives rather than creating duplicate physics
  implementations.
- Treat exact commit SHA and exact CI checkout as part of the validation gate.
- PR CI is not exact-main CI; after merge, verify the push workflow on the exact
  merge SHA.
- Do not merge a PR merely because a Codex report says tests passed; inspect the
  live repository independently.
- Do not modify the frontend during backend-only physics increments.
- Never generalize Bracon Ash-specific values to another site unless that
  site's own configuration establishes them.

## Reference site: Bracon Ash

Bracon Ash remains a development/reference site, not a reusable site template.

See [`docs/sites/bracon-ash.md`](sites/bracon-ash.md) for established site facts,
known data gaps, and site-specific configuration.

Do not generalize its:

- module count;
- modules per string;
- inverter model;
- inverter count;
- grid limit;
- legacy loss percentages;
- unresolved electrical mapping

to other sites.

## Known operational issue: in-process scheduler

`RUN_SCHEDULER` explicitly controls whether a FastAPI process configures and
starts APScheduler. Its default remains `true` for backwards compatibility.

The request-serving staging API was previously validated with in-process
scheduling disabled through:

`RUN_SCHEDULER=false`

The long-term scheduler architecture is still separate from the physics
migration and remains unresolved. Periodic workloads should ultimately move to
an execution model that guarantees one intended execution of each workload.

## Application logging checkpoint

Application-specific logging exists for the `heliotelligence` namespace.
`settings.log_level` is consumed, application INFO lifecycle records are
observable, and Uvicorn/root logging is not globally replaced.

## Historical staging checkpoint

Historical validated staging checkpoint:

- project: `heliotelligence-staging`
- Git SHA: `e3186f288fb8a0da723809648c306e2527acb926`
- Cloud Build: `c5a8788c-62cb-499c-b2e5-7902ee4fe0d6`
- image: `api:e3186f2`
- image digest:
  `sha256:1c101683cc35310a89b60e2d521ea138fc00fc62e2216625f9931dea5dc42a2d`
- Cloud Run revision: `heliotelligence-api-staging-00004-4bn`
- runtime: `RUN_SCHEDULER=false`, `APP_ENV=staging`

This is historical operational context only. Do not assume it describes the
current deployed revision without rechecking deployment state.

Staging and production are separate. Always target the intended environment
explicitly.

Never put secrets, credentials, tokens, or secret values in repository
documentation.
