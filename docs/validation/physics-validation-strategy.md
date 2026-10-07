# Physics Validation Strategy

Physics validation progresses from exact local identities to site evidence. Higher levels do not replace lower-level tests.

## Validation philosophy

Every new physical layer should answer four questions independently:

1. Is the local equation / algorithm correct?
2. Is the input authority valid and tamper resistant?
3. Does the handoff to the next reference plane close exactly?
4. Is the model supported by the site's available topology/equipment data?

A model that matches site output but violates one of these rules is not accepted.

## Level 1 — algebra / identities

Examples:

- series voltage scaling;
- current conservation;
- `P = V × I` where that identity is the represented state;
- resistive drop `ΔV = I × R`;
- resistive loss `P_loss = I²R`;
- conversion / clipping accounting closure;
- `S² = P² + Q²` once S9-4B exists.

## Level 2 — limiting and boundary cases

Examples:

- identical strings sharing an MPPT produce approximately zero physical mismatch when their I-V curves are identical;
- explicit zero resistance produces an identity branch transform;
- zero irradiance yields the appropriate inactive / zero electrical state;
- exact MPPT/inverter voltage and current limits follow documented inclusivity;
- `Praw == Paco` is at the AC nameplate boundary but has zero clipping loss;
- `Pdc == Pso` follows normal Sandia conversion, while `Pdc < Pso` follows the below-startup tare regime;
- missing authority remains unresolved instead of becoming zero;
- missing fixed-Q authority is distinct from explicit `Qmin = Qmax = 0`;
- contradictory `three_phase + single_phase_terminal` capability authority is rejected.

## Level 3 — reference-model comparison

Compare suitable layers against public pvlib calculations, pinned-version private helpers only as test oracles where no public pre-limit reference exists, datasheet/manufacturer operating points, known analytical cases, and independent engineering calculations.

Production code must not depend on a private reference helper merely because it is useful as a test oracle.

## Level 4 — exact admission and handoff closure

When a stage consumes a structured result from an upstream stage, prefer exact canonical replay when practical.

Validation should cover:

- exact result type;
- exact diagnostics type;
- exact DataFrame / index / ordering;
- stable dtypes, including empty-result schemas;
- state vocabulary;
- provenance and model IDs;
- reference-plane labels;
- diagnostics closure against independent source authority;
- rejection of coherent downstream tampering.

The S8/S9 chain deliberately uses this pattern so a caller cannot alter a seemingly plausible upstream result and still obtain an authoritative downstream state.

## Level 5 — system equivalence and migration safety

Before replacing a legacy layer in production, demonstrate expected equivalence under conditions where legacy and physical models should agree. Differences outside those conditions must be explainable from physical assumptions.

Production migration must explicitly prove:

- no physical loss is applied twice;
- legacy aggregate percentages are removed or bypassed at the correct boundary;
- unresolved physical authority falls back safely and transparently;
- reference planes are aligned;
- production outputs remain deterministic.

A validated dormant physics module is not automatically approved for production activation.

## Level 6 — site validation

Compare against, where authoritative and aligned:

- SCADA;
- inverter telemetry;
- weather / irradiance sensors;
- the revenue meter;
- commissioning / factory test data;
- PVsyst or another engineering model where appropriate.

Do not tune away structural physics errors with unexplained empirical correction factors. Site-data fit is evidence, not permission to conceal an incorrect mechanism.





## Current validated trace

The independently validated electrical/control trace now includes:

```text
module electrical state
string-terminal I-V
source-plane common-voltage MPPT
physical mismatch
branch-resistance authority
branch-transformed I-V
MPPT-input common-voltage DC state
inverter equipment authority
inverter DC envelope state
Sandia AC available power
Sandia pre-Paco AC potential
conversion / clipping / tare accounting
static inverter AC capability authority
timestamped inverter P/Q/S capability-state evaluation
static inverter thermal-derating authority
temperature-dependent inverter capability evaluation
explicit inverter active-power dispatch-request authority
requested inverter P/Q/S feasibility evaluation
selected inverter AC P/Q/S state
static LV collection topology and direct per-phase R+jX authority
timestamped collection-exit line-to-line RMS voltage authority
balanced radial constant-PQ LV operating solution
```

Current merged checkpoint:

`6f6dbb34027f9e648fe8623aab37b14341f193c7`

Final reviewed CI for PR #86 ran `3040` backend unit tests successfully in `527.89s` on Python 3.13.15 with `pvlib==0.15.2`; the frontend build also passed. Run #217 / ID `37544412809` validated exact synthetic merge `a8ea3ec4965e75f2ae67dae835a74dc619bf4d2e` from reviewed head `73dafc1f79c09ccd9fb61dd9ee7610cc2e62233c`.

Always verify the live repository before treating those numbers as current.

## Required invariants for S8/S9

### String / MPPT

- series voltage scales with module count;
- series current does not scale with module count;
- common-voltage aggregation never sums independent MPP powers as the actual connected operating point;
- mixed active / zero strings remain unresolved where blocking behaviour is unknown.

### Direct DC branch

- explicit zero resistance is a resolved ideal path;
- missing resistance authority is unresolved;
- total loop resistance is not auto-doubled;
- no geometry / ID / aggregate-loss inference is accepted;
- transformed curve follows `V' = V - I R`.

### Shared DC network

Current direct-branch support must not be misrepresented as shared feeder support. A future shared edge must operate on total junction current and be validated separately.

### Inverter envelope

- independent MPPT voltages are never averaged;
- inverter-level current limits are not copied to every tracker;
- unresolved current authority remains visible;
- classification does not silently clamp / re-solve the DC state.

### Sandia conversion

- one physical inverter is converted once;
- multi-MPPT voltage rails remain independent;
- power aggregation follows pinned Sandia semantics;
- `Paco` and night tare are applied once per inverter.

### Pre-limit potential and accounting

For applicable rows:

```text
conversion_delta = Pdc - Praw
conversion_loss - conversion_gain = conversion_delta
clipping_loss = Praw - Pac
net_delta = Pdc - Pac
Pdc + gain - loss - clipping = Pac
```

Additional guards:

- `Praw > Paco` ↔ clipping active;
- `Praw == Paco` → zero clipping loss;
- `Praw > Pdc` is preserved as empirical conversion gain;
- negative `Praw` above startup is not reclassified as tare;
- tare-only rows keep conversion/clipping quantities not-applicable.

### S9-4A static AC capability authority

The authority layer must remain independent of timestamped operating state.

Required invariants:

- every resolved row exactly replays the supplied authority object;
- missing mapping entries remain unresolved with NaN numerics and explicit unresolved state;
- stable empty/populated DataFrame dtypes;
- exact contract/model/scope/coverage provenance on every row;
- diagnostics close independently against topology and explicit authority mapping;
- no inference from `Paco`, CEC/SAM `Vac`, `pnom_kwac`, grid limits, `model_ref`, groups, MPPT/string counts, topology position or legacy AC wiring loss;
- `three_phase + single_phase_terminal` is invalid;
- fixed Q limits must be both present or both absent;
- each fixed-Q magnitude must not exceed `Smax`;
- missing fixed-Q authority is different from explicit zero Q capability;
- no P/Q/S operating state, AC current, PF compliance, thermal derating, controller, cable or transformer physics appears in S9-4A.


### S9-4B P/Q/S capability-state evaluation

S9-4B is now validated.

Required invariants include:

- exact replay/admission of canonical S9-3B and S9-4A inputs;
- request keys are `(timestamp, inverter_id)`;
- explicit request source/confidence and Q sign convention are preserved;
- missing request is distinct from explicit Q=0;
- `S = hypot(P,Q)`;
- exact inclusive Smax and fixed-Q boundary semantics under the declared tolerance;
- partial authority remains unknown rather than a false pass when fixed-Q authority is absent;
- known circle/fixed-Q violations remain definitive;
- `|P| > Smax` remains a known violation even when Q is missing;
- inactive Sandia states are resolved not-applicable;
- unresolved S9-3B state propagates, including NaN active power;
- static full-capability authority is inherited from S9-4A independently of request presence;
- mapping insertion order cannot change canonical output order;
- P and Q are never changed to force feasibility;
- no AC-current, thermal, controller, cable or transformer physics appears in S9-4B.


### S9-4C thermal-derating authority

S9-4C is now validated.

Required invariants include:

- exact topology-order replay of explicit per-inverter authority;
- missing authority distinct from explicit no-derating authority;
- explicit non-empty temperature quantity;
- finite strictly increasing temperature domain;
- immutable aligned P/S/Q curve tuples;
- exact partial-channel authority without fabrication;
- per-point P<=S and |Q|<=S where those channels coexist;
- Qmin<=Qmax with asymmetric capability allowed;
- positive Q = injection and negative Q = absorption;
- no automatic sign reversal;
- linear interpolation recorded only as downstream metadata;
- outside-domain policy recorded as unresolved;
- no interpolation or timestamped operating evaluation;
- no module/cell-temperature reuse;
- no S9-4A/S9-4B coupling;
- exact provenance, diagnostics, dtypes, ordering and ownership;
- no dispatch, AC current, network or production integration.


### S9-4D temperature-dependent inverter capability

S9-4D is now validated.

Required invariants include:

- exact replay/admission of canonical S9-4B and S9-4C;
- exact timestamped `InverterTemperatureState` keyed by `(timestamp, inverter_id)`;
- explicit temperature quantity, source and confidence;
- exact case-sensitive basis match to S9-4C;
- inclusive temperature-domain boundaries;
- unresolved state outside the authority domain;
- no clamping or extrapolation;
- exact authority-value replay at breakpoints;
- piecewise-linear interpolation only between explicit points;
- explicit no-derating authority distinct from missing authority;
- only explicitly supplied P/S/Q thermal channels evaluated;
- absent thermal channels preserved as partial authority;
- known upstream or thermal violations remain definitive;
- static S9-4A/S9-4B capability and S9-4C thermal authority remain separately attributable;
- no controller dispatch, P/Q/S modification, AC current, thermal-loss accounting, cables or transformers;
- exact dtypes, provenance, state semantics, diagnostics and deterministic full-result closure.


### S10A explicit inverter active-power dispatch-request authority

Required invariants include:

- exact replay/admission of canonical S9-4D;
- canonical `(timestamp, inverter_id)` universe/order;
- finite non-negative P setpoints;
- explicit zero distinct from missing request;
- exact `inverter_ac_output` reference plane;
- no temporal persistence or resampling;
- no inference from available power, nameplate, `grid_limit_kwac`, measured output or plant export limit;
- no duplicate reactive-power authority.

### S10B requested dispatch feasibility

Required invariants include:

- strong exact replay of S9-4D and S10A;
- requested P only from S10A;
- requested Q only from canonical S9-4B request;
- `S_requested = hypot(P_requested,Q_requested)`;
- independent checks for instantaneous P availability, static S/Q limits and thermal P/S/Q limits;
- known violations remain definitive under partial information;
- passing partial authority remains partial/unknown;
- no P/Q clipping, substitution, selection or plant-level allocation.

### S10C selected inverter AC dispatch state

Required invariants include:

- strong exact replay of canonical S10B;
- selection only for `resolved_requested_dispatch_feasible_full_capability` with resolved/applicable/no-violation/satisfied closure;
- exact selected P/Q/S passthrough from the request;
- finite selected values with P >= 0 and S >= 0;
- exact Q injection/absorption/zero semantics;
- no selected point for known infeasible, partial-authority or unresolved feasibility;
- inactive state resolved/not-applicable without fabricated zero;
- no P clamp, Q clip, S-circle projection, thermal clip or fallback policy;
- selected-count and Q-direction diagnostic partitions close exactly;
- selected target is not measured output;
- no AC current/network physics or curtailment accounting.

## Validated S11 progression

S11 followed the authority-first sequence and is complete through S11C.

### S11A static LV collection authority

Validation covers exact balanced-three-phase/line-to-line/per-phase-series basis, node and segment identity, direct non-negative R/X including explicit zero, inverter-terminal binding, acyclic radial/outdegree rules, ordered terminal-to-exit paths, shared segments, multiple trees, malformed-versus-partial authority, immutable ownership, and independent path/diagnostic closure. No topology or impedance is inferred.

### S11B collection-exit voltage authority

Validation covers strong S11A replay, exact `(pd.Timestamp, collection_exit_node_id)` keys, collection-exit-only reference plane, finite non-negative line-to-line RMS voltage, explicit zero versus missing, explicit-timestamp × canonical-exit closure, no temporal/cross-exit inference, immutable ownership, provenance, and independent diagnostics.

### S11C balanced radial operating solve

Validation covers:

- strong S10C, S11A, and S11B replay, including rejection of mutable-but-equal S11A/S11B result mappings;
- pure numerical-kernel tests separated from expensive parent admission;
- analytical single-resistive-feeder current/voltage regression;
- positive Q and reactive absorption;
- shared-feeder complex-current aggregation and shared `3R|I|²` loss exactly once;
- multilevel and independent trees;
- exact zero dispatch and zero-exit-voltage cases;
- missing authority/dispatch/boundary handling;
- deterministic nonconvergence and nonfinite handling with unresolved physical values;
- independent validator tree-membership and diagnostics reconstruction;
- output tamper rejection;
- terminal constant-PQ, junction KCL, segment `V=ZI`, segment complex-power/loss, exit delivery, and whole-tree P/Q conservation closure.

S11C solved state remains modeled, not measured, and does not validate voltage compliance, transformer behavior, controller feedback, or energy integration.

## Next validation target: S12 transformer authority

Validate explicit transformer equipment/topology and reference planes before operating transformer physics. Do not infer winding identity, voltage bases, rating, ratio, impedance, losses, loading, or tap state from S11 exit voltage, names, capacity, CEC fields, geometry, or site configuration.

## Future validation targets

### Transformer

- no-load loss appears when energised even at low load;
- load loss follows authoritative loading dependence;
- input/output accounting closes;
- P/Q/S loading semantics remain explicit.

### Benchmarking

- expected and actual are aligned to the same boundary;
- loss waterfalls telescope exactly;
- residual is defined rather than used as a hidden correction factor;
- confidence / unresolved state propagates into diagnostics.

## Regression matrix for each new physics PR

Use a non-redundant cadence, as applicable:

- focused new-stage tests;
- immediately upstream-stage tests;
- Ruff, strict mypy, syntax compilation, and `git diff --check`;
- one full backend unit suite before PR review;
- frontend build;
- one fresh CI on the exact synthetic merge.

Run additional historical subsets or optical/rear regressions only when shared dependencies changed or when diagnosing a failure; do not repeat nested suites already subsumed by the full backend.

Record exact base SHA, head SHA, synthetic merge SHA, Python version, dependency version, and pass counts.

## Site and portfolio validation

Validation should progress through:

`component → site → portfolio`

Portfolio validation is a future layer above site validation. A good aggregate portfolio result must not be used as evidence that individual site models are correct. Each site's inputs, intermediate states, constraints, confidence, and losses must remain independently testable and explainable.
