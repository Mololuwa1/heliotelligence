# ADR-001: Physics-first electrical migration

## Status

Accepted

## Context

The legacy system contains useful aggregate percentage losses and provides a
stable production-compatible result. The target digital twin, however, needs
component-resolved mechanisms that explain where energy is converted or lost.

Replacing the entire electrical chain simultaneously would couple too many
assumptions and make regressions difficult to attribute. Missing physical
topology also prevents some mechanisms from being modelled honestly today.

## Decision

Introduce physical layers incrementally:

`module → string → MPPT → DC collection → inverter → AC collection`

Validate each layer independently before integrating it into the next layer or
the production calculation. Retain legacy aggregate behaviour as a safe
compatibility path until the physical replacement is validated.

The decision applies generically to every onboarded site. Reusable electrical
models must consume each site's explicit equipment and topology rather than
encoding assumptions from any reference site.

Static mismatch remains temporarily, even though the final target is mismatch
derived from independent-string and actual common-MPPT power.

## Consequences

Positive consequences:

- Changes remain traceable.
- Regressions can be isolated to a layer.
- Losses become physically explainable.
- Production migration can proceed safely and incrementally.

Trade-offs:

- Legacy and physical models temporarily coexist.
- More explicit interfaces and tests are required.
- Migration spans several focused pull requests.

## Rejected alternatives

1. Rewrite the whole Stage 4 chain at once.
2. Replace mismatch with another tuned percentage.
3. Invent missing physical topology.
4. Fit unexplained correction factors purely to match PVsyst or SCADA.
