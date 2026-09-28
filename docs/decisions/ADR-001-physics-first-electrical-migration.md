# ADR-001: Physics-first electrical migration

## Status

Accepted and active.

## Context

The legacy system contains useful aggregate percentage losses and provides a
stable production-compatible result. The target digital twin needs
component-resolved mechanisms that explain where energy is converted, limited,
transported, or lost.

Replacing the entire electrical chain simultaneously would couple too many
assumptions and make regressions difficult to attribute. Missing physical
topology and equipment authority also prevent some mechanisms from being
modelled honestly today.

## Decision

Introduce physical layers incrementally:

`module → string → MPPT → DC collection → inverter → controller → AC collection → transformer → meter`

Validate each layer independently before integrating it into the next layer or
the production calculation. Retain legacy aggregate behaviour as a compatibility
path until its physical replacement is validated and a separate production
migration proves no double counting.

The decision applies generically to every onboarded site. Reusable electrical
models must consume each site's explicit equipment and topology rather than
encoding assumptions from any reference site.

Missing authority must remain explicit. An unresolved result is preferable to a
numerically convenient invented value.

## Current implementation consequence

The migration has now produced independently validated contracts through the
inverter AC power-accounting boundary:

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
```

At the 2026-09-28 checkpoint, these stages are merged through commit:

`ad0828f42d5a5b733d79e70850df800dbc1aa5a2`

This implementation progress does not change the ADR's migration principle:
validated capability is not automatically production-active.

## Legacy coexistence rule

The compatibility production path still contains aggregate effects including
static soiling, LID, mismatch, and wiring assumptions. Physical mismatch and
direct-branch resistance now exist as validated independent contracts, but they
must not be layered on top of the legacy percentages in production without an
explicit migration decision.

The same rule applies to future AC cabling, transformer, controller, and network
physics.

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

must not be collapsed into a single generic power state when the distinction
matters to the mechanism being modelled.

A counterfactual accounting quantity, such as Sandia pre-Paco AC potential, must
also be labelled as a model quantity rather than misrepresented as a physical
terminal measurement.

## Shared-network rule

A resistance after parallel combination acts on total shared current and cannot
be duplicated into independent string branches. Generalized DC collection must
therefore use explicit network authority rather than pretending a shared feeder
is another per-string resistance.

## Inverter rule

Independent MPPT voltages must not be averaged. Inverter-level current limits
must not be duplicated to every tracker. One physical inverter must be converted
and limited once.

For AC capability, apparent-power and reactive-power authority must not be
inferred from active-power rating alone.

## Consequences

Positive consequences:

- changes remain traceable;
- regressions can be isolated to a layer;
- losses and limits become physically explainable;
- unsupported topology remains visible rather than silently approximated;
- production migration can proceed safely and incrementally;
- accounting can preserve exact closure across reference planes.

Trade-offs:

- legacy and physical models temporarily coexist;
- more explicit interfaces, provenance, and tests are required;
- migration spans many focused pull requests;
- some sites remain unresolved at higher-fidelity layers until authoritative
  topology/equipment data is supplied.

## Next decision-compatible work

The immediate next electrical increment is S9-4A explicit inverter AC capability
authority, followed by P/Q/S capability evaluation. Physical LV AC collection
should follow only after voltage, phase configuration, and P/Q/S state are
explicit.

## Rejected alternatives

1. Rewrite the whole electrical chain at once.
2. Replace mismatch or wiring with another tuned percentage and call it physics.
3. Invent missing physical topology or equipment capability.
4. Fit unexplained correction factors purely to match PVsyst or SCADA.
5. Average independent MPPT voltages to simplify inverter conversion.
6. Duplicate shared feeder resistance or inverter limits across child branches.
7. Treat available AC, dispatched AC, and meter AC as the same reference plane.
