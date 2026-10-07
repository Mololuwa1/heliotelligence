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

The physics-first migration now has validated dormant electrical/control contracts through S11C:

- S8 resolves physical string, MPPT mismatch and explicit direct-branch electrical behaviour;
- S9 resolves inverter authority, conversion/accounting, static P/Q/S capability and explicit thermal capability;
- S10A admits explicit active-power request authority;
- S10B evaluates the exact requested P/Q/S point;
- S10C selects only an exact request that is fully proven feasible.
- S11A admits explicit balanced radial LV topology, terminal bindings and direct per-phase R+jX;
- S11B admits exact timestamped collection-exit line-to-line RMS voltage;
- S11C solves the balanced constant-PQ radial operating state and intrinsic instantaneous series losses.

Canonical checkpoint: `6f6dbb34027f9e648fe8623aab37b14341f193c7`.

These contracts do not automatically replace legacy production calculations. Activation still requires explicit migration evidence showing reference-plane consistency and no double counting.

## Legacy coexistence rule

The compatibility production path still contains aggregate effects including static soiling, LID, mismatch, DC wiring, and legacy AC wiring/grid-cap behaviour.

Physical mismatch and direct-branch resistance now exist as validated independent contracts, but they must not be layered on top of the legacy percentages in production without an explicit migration decision.

Physical S11C AC current/cabling now exists as dormant generic physics, but legacy `wiring_loss_ac_pct` remains compatibility logic. Production must never apply both to the same path without an explicit migration proving no double counting. The same rule applies to future transformer and network physics.

## Physical reference-plane rule

Electrical quantities must retain their physical location. In particular:

- string-terminal state;
- branch output;
- parallel junction;
- shared feeder output;
- inverter MPPT input;
- inverter AC output;
- selected/controller target and S11A terminal at `inverter_ac_output`;
- S11C-solved LV internal nodes;
- `lv_ac_collection_exit` at the end of S11;
- future transformer / MV / HV / meter boundaries

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

Proceed to S12 transformer authority from the explicit `lv_ac_collection_exit` boundary. Begin with equipment/topology and reference-plane authority; add operating transformer physics only after the necessary winding bases, ratings, ratio, impedance/loss, loading, and any tap/control evidence are explicit.

Do not equate `lv_ac_collection_exit` with a transformer LV winding unless future topology authority proves that physical identity. Do not infer transformer evidence from exit voltage, CEC `Vac`, nominal voltage, capacities, labels, geometry, or current site configuration.

S11 demonstrates the decision pattern: S11A established static authority, S11B established an operating boundary, and only S11C performed the solve. S11 remains dormant from production and distinct from measured telemetry, energy integration, curtailment accounting, and plant-export allocation.

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
