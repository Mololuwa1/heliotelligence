# Physics Validation Strategy

Physics validation progresses from exact local identities to site evidence.
Higher levels do not replace lower-level tests.

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
- `S² = P² + Q²` once P/Q/S capability exists.

## Level 2 — limiting and boundary cases

Examples:

- identical strings sharing an MPPT produce approximately zero physical
  mismatch when their I-V curves are identical;
- explicit zero resistance produces an identity branch transform;
- zero irradiance yields the appropriate inactive / zero electrical state;
- exact MPPT/inverter voltage and current limits follow documented inclusivity;
- `Praw == Paco` is at the AC nameplate boundary but has zero clipping loss;
- `Pdc == Pso` follows normal Sandia conversion, while `Pdc < Pso` follows the
  below-startup tare regime;
- missing authority remains unresolved instead of becoming zero.

## Level 3 — reference-model comparison

Compare suitable layers against:

- public pvlib calculations;
- pinned-version private helpers only as test oracles where no public pre-limit
  reference exists;
- datasheet / manufacturer operating points;
- known analytical cases;
- independent engineering calculations.

Production code must not depend on a private reference helper merely because it
is useful as a test oracle.

## Level 4 — exact admission and handoff closure

When a stage consumes a structured result from an upstream stage, prefer exact
canonical replay when practical.

Validation should cover:

- exact result type;
- exact diagnostics type;
- exact DataFrame / index / ordering;
- dtypes, including nullable booleans;
- state vocabulary;
- provenance and model IDs;
- reference-plane labels;
- diagnostics closure;
- rejection of coherent downstream tampering.

The S8/S9 chain deliberately uses this pattern so a caller cannot alter a
seemingly plausible upstream result and still obtain an authoritative downstream
state.

## Level 5 — system equivalence and migration safety

Before replacing a legacy layer in production, demonstrate expected equivalence
under the conditions where the legacy and physical models should agree.
Differences outside those conditions must be explainable from physical
assumptions.

Production migration must explicitly prove:

- no physical loss is applied twice;
- legacy aggregate percentages are removed or bypassed at the correct boundary;
- unresolved physical authority falls back safely and transparently;
- reference planes are aligned;
- production outputs remain deterministic.

A validated dormant physics module is not automatically approved for production
activation.

## Level 6 — site validation

Compare against, where authoritative and aligned:

- SCADA;
- inverter telemetry;
- weather / irradiance sensors;
- the revenue meter;
- commissioning / factory test data;
- PVsyst or another engineering model where appropriate.

Do not tune away structural physics errors with unexplained empirical correction
factors. Site-data fit is evidence, not permission to conceal an incorrect
mechanism.

## Current validated trace

The independently validated electrical trace now includes:

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
```

The current merged checkpoint is:

`ad0828f42d5a5b733d79e70850df800dbc1aa5a2`

Exact-main CI at that checkpoint ran `2565` backend unit tests successfully on
Python 3.13.15 with `pvlib==0.15.2`, with the frontend build also passing.

Always verify the live repository before treating those numbers as current.

## Required invariants for S8/S9

### String / MPPT

- series voltage scales with module count;
- series current does not scale with module count;
- common-voltage aggregation never sums independent MPP powers as the actual
  connected operating point;
- mixed active / zero strings remain unresolved where blocking behaviour is
  unknown.

### Direct DC branch

- explicit zero resistance is a resolved ideal path;
- missing resistance authority is unresolved;
- total loop resistance is not auto-doubled;
- no geometry / ID / aggregate-loss inference is accepted;
- transformed curve follows `V' = V - I R`.

### Shared DC network

Current direct-branch support must not be misrepresented as shared feeder
support. A future shared edge must operate on total junction current and be
validated separately.

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

## Future validation targets

### S9-4A / S9-4B

- equipment authority must be explicit;
- do not infer `Smax` from `Paco` without evidence;
- P/Q/S identities and capability boundaries must close;
- missing Q/PF command or capability authority remains unresolved;
- capability evaluation must not silently dispatch active power.

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

Record exact base SHA, head SHA, synthetic merge SHA, Python version,
dependency version, and pass counts.

## Site and portfolio validation

Validation should progress through:

`component → site → portfolio`

Portfolio validation is a future layer above site validation. A good aggregate
portfolio result must not be used as evidence that individual site models are
correct. Each site's inputs, intermediate states, constraints, confidence, and
losses must remain independently testable and explainable.
