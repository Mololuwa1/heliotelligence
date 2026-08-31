# Physics Validation Strategy

Physics validation progresses from exact local identities to site evidence.
Higher levels do not replace lower-level tests.

## Level 1 — algebra / identities

Examples:

- Series voltage scaling
- Current conservation
- Power identities

## Level 2 — limiting cases

Examples:

- Identical strings on one MPPT should produce approximately zero physical
  mismatch once common-MPPT modelling exists.
- No irradiance should yield zero or near-zero generation.
- Zero cable resistance should yield zero cable loss.

## Level 3 — reference-model comparison

Compare suitable layers against:

- pvlib;
- datasheet operating points; and
- known analytical cases.

## Level 4 — system equivalence

Before replacing a legacy layer, demonstrate expected equivalence under the
conditions where the legacy and physical models should agree. Differences
outside those conditions must be explainable from physical assumptions.

## Level 5 — site validation

Compare against:

- SCADA;
- the revenue meter; and
- PVsyst where appropriate.

Do not tune away structural physics errors with unexplained empirical
correction factors. Site-data fit is evidence, not permission to conceal an
incorrect mechanism.

Every major physical replacement should expose enough intermediate values to
explain where energy was lost. The intended trace includes:

```text
irradiance
Tcell
module Pmp
string state
independent MPPT power
actual MPPT power
mismatch
cable loss
inverter loss
transformer loss
export
```

Values not yet implemented should remain explicitly absent rather than being
filled with invented estimates.

## Validation scope

Validation should progress through:

`component → site → portfolio`

Portfolio validation is a future layer above site validation. A good aggregate
portfolio result must not be used as evidence that its individual site models
are correct, and portfolio aggregation must never mask poor site-level physics.
Each site's inputs, intermediate states, constraints, and losses must remain
independently testable and explainable.
