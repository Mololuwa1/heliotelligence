# ADR-001: Physics-first electrical migration

## Status

Accepted and active.

## Context

The legacy system contains useful aggregate percentage losses and provides a stable production-compatible result. The target digital twin needs component-resolved mechanisms that explain where energy is converted, limited, transported, curtailed, or lost.

Replacing the entire electrical chain simultaneously would couple too many assumptions and make regressions difficult to attribute. Missing physical topology and equipment authority also prevent some mechanisms from being modelled honestly today.

## Decision

Introduce physical layers incrementally:

`module → string → MPPT → DC collection → inverter conversion → inverter capability → controller → AC collection → transformer → meter`

Validate each layer independently before integrating it into the next layer or the production calculation. Retain legacy aggregate behaviour as a compatibility path until its physical replacement is validated and a separate production migration proves no double counting.

The decision applies generically to every onboarded site. Reusable electrical models must consume each site's explicit equipment and topology rather than encoding assumptions from any reference site.

Missing authority must remain explicit. An unresolved result is preferable to a numerically convenient invented value.


## Current implementation consequence

The migration has now produced independently validated contracts through inverter P/Q/S capability-state evaluation:

```text
S8-1  physical string I-V
S8-2  common-voltage MPPT / physical mismatch
S8-3A direct branch resistance authority
S8-3B resistive branch I-V transform
S8-3C MPPT-input common-voltage operating point
S9-0  inverter CEC/SAM authority
S9-1  inverter DC envelope classification
S9-2  Sandia inverter conversion
S9-3A Sandia pre-Paco AC potential
S9-3B conversion / clipping / tare accounting
S9-4A explicit static inverter AC capability authority
S9-4B timestamped inverter P/Q/S capability-state evaluation
```

At the 2026-10-03 checkpoint, these stages are merged through commit:

`a39026379df00e5756ac2690977e005b169f920e`

S9-4B preserves explicit Q-request provenance, partial-vs-full capability authority, known violation semantics, inactive not-applicable state, and an evaluation-only boundary.

This implementation progress does not change the ADR's migration principle: validated capability is not automatically production-active.

## Legacy coexistence rule

The compatibility production path still contains aggregate effects including static soiling, LID, mismatch, DC wiring, and legacy AC wiring/grid-cap behaviour.

Physical mismatch and direct-branch resistance now exist as validated independent contracts, but they must not be layered on top of the legacy percentages in production without an explicit migration decision.

The same rule applies to future AC current/cabling, transformer, controller, and network physics.

## Physical reference-plane rule

Electrical quantities must retain their physical location. In particular:

- string-terminal state;
- branch output;
- parallel junction;
- shared feeder output;
- inverter MPPT input;
- inverter AC output;
- future controller-dispatched output;
- downstream AC network / meter boundaries

must not be collapsed into a single generic power state when the distinction matters to the mechanism being modelled.

A counterfactual accounting quantity, such as Sandia pre-Paco AC potential, must be labelled as a model quantity rather than misrepresented as a physical terminal measurement.

Static nameplate/capability authority such as nominal AC voltage, phase or `Smax` is equipment metadata, not an operating reference plane.

## Shared-network rule

A resistance after parallel combination acts on total shared current and cannot be duplicated into independent string branches. Generalized DC collection must therefore use explicit network authority rather than pretending a shared feeder is another per-string resistance.

## Inverter conversion rule

Independent MPPT voltages must not be averaged. Inverter-level current limits must not be duplicated to every tracker. One physical inverter must be converted and limited once.

## Inverter AC capability rule

S9-4A establishes a separate static authority boundary for AC-side capability.

Do not infer:

- `Smax` from `Paco` or active-power rating;
- AC terminal voltage/basis from CEC/SAM `Vac`;
- phase from voltage magnitude;
- Q capability from `Smax` alone;
- inverter capability from grid/export limits;
- equipment capability from model labels, groups, topology position, MPPT count or string count.

Missing Q authority and explicit zero Q capability are different states.

S9-4B now classifies requested P/Q/S operating capability without silently dispatching or curtailing P or Q. It treats positive Q as injection, negative Q as absorption, preserves missing request separately from Q=0, and keeps static full-capability authority independent of request availability.

Capability evaluation and control remain separate layers.

## Consequences

Positive consequences:

- changes remain traceable;
- regressions can be isolated to a layer;
- losses and limits become physically explainable;
- unsupported topology/capability remains visible rather than silently approximated;
- production migration can proceed safely and incrementally;
- accounting can preserve exact closure across reference planes.

Trade-offs:

- legacy and physical models temporarily coexist;
- more explicit interfaces, provenance, and tests are required;
- migration spans many focused pull requests;
- some sites remain unresolved at higher-fidelity layers until authoritative topology/equipment data is supplied.


## Next decision-compatible work

The immediate next inverter increment is **S9-4C explicit inverter thermal-derating authority**.

This stage should establish manufacturer-backed temperature/capability authority before any thermal derating is applied. It should identify the temperature quantity used by the manufacturer, valid temperature range or breakpoints/curve, affected active/apparent/reactive capability, interpolation/boundary semantics, source and confidence.

Do not infer inverter thermal derating from module-cell temperature, ambient temperature alone, `Paco`, `Smax`, model labels, or generic loss percentages.

Temperature-dependent operating capability should then be evaluated in a separate narrow increment if needed. Plant-controller dispatch remains downstream, and physical LV AC collection should consume selected P/Q/S state rather than an unevaluated capability request.

## Rejected alternatives

1. Rewrite the whole electrical chain at once.
2. Replace mismatch or wiring with another tuned percentage and call it physics.
3. Invent missing physical topology or equipment capability.
4. Fit unexplained correction factors purely to match PVsyst or SCADA.
5. Average independent MPPT voltages to simplify inverter conversion.
6. Duplicate shared feeder resistance or inverter limits across child branches.
7. Treat available AC, dispatched AC, and meter AC as the same reference plane.
8. Treat `Paco`, CEC `Vac`, grid limits, or nominal kW as sufficient AC capability authority.
9. Silently curtail P or Q inside a capability-classification stage.
