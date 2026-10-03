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
```

The current merged checkpoint is:

`4a6b318946a5a2bb688bfa29f7318403362f99de`

Final reviewed pre-merge CI for PR #79 ran `2767` backend unit tests successfully on Python 3.13.15 with `pvlib==0.15.2`; the frontend build also passed. The exact synthetic merge was `a878511281445b17b5fc070d28dd043e79f35197`.

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

S10A is now validated.

Required invariants include:

- exact replay/admission of canonical S9-4D;
- canonical `(timestamp, inverter_id)` output universe and ordering;
- exact request dataclass admission;
- finite non-negative active-power setpoints;
- positive P = inverter export/injection;
- explicit zero distinct from missing request;
- exact `inverter_ac_output` reference plane;
- exact `absolute_active_power_setpoint` semantics;
- optional controller mode preserved without interpretation;
- source/confidence preserved exactly;
- no request persistence, interpolation or resampling;
- arbitrarily large finite request admitted for later feasibility evaluation;
- no inference from available power, nameplate, `grid_limit_kwac`, actual output or plant-level export limits;
- no duplicate reactive-power authority;
- immutable independently owned mapping;
- stable empty/populated dtypes, diagnostics and exact result closure;
- no feasibility calculation, dispatch selection, P/Q/S modification, curtailment accounting or AC-network physics.

## Next validation target: S10B requested dispatch feasibility

S10B should be validated as an evaluation-only stage.

Minimum targets should include:

- exact strong replay/admission of canonical S9-4D and S10A;
- requested P taken only from S10A;
- canonical Q taken from S9-4B/S9-4D without a second Q authority;
- `S_requested = hypot(P_request, Q_request)`;
- explicit zero P handled as a real request;
- missing P request unresolved;
- static and thermal capability authority remain separately attributable;
- known static/thermal/requested-point violation remains definitive;
- passing partial authority remains partial/unknown;
- exact inclusive P/S/Q boundaries under narrow tolerance;
- no P/Q clipping, no substitution with available P, no dispatch selection;
- no site-export allocation, AC current, curtailment-loss accounting or network physics;
- exact provenance, dtypes, diagnostics, ordering and full-result closure.

S10C should remain the first stage that establishes selected/dispatched inverter AC P/Q/S.

## Future validation targets

### LV AC collection

- current must be derived from explicit voltage / phase / P/Q/S state;
- `I²R` and voltage-drop identities must close;
- segment topology and conductor authority must be explicit;
- no hidden unity-PF or nominal-voltage assumption.

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

Run, as applicable:

- focused new-stage tests;
- immediately upstream-stage tests;
- complete recent S8/S9 inverter/electrical regressions;
- optical / rear regressions when shared dependencies may interact;
- full backend unit suite;
- frontend build;
- Ruff on changed files;
- strict mypy on primary new/changed files;
- syntax compilation;
- `git diff --check`;
- fresh CI on the exact synthetic merge or merged `main`.

Record exact base SHA, head SHA, synthetic merge SHA, Python version, dependency version, and pass counts.

## Site and portfolio validation

Validation should progress through:

`component → site → portfolio`

Portfolio validation is a future layer above site validation. A good aggregate portfolio result must not be used as evidence that individual site models are correct. Each site's inputs, intermediate states, constraints, confidence, and losses must remain independently testable and explainable.
