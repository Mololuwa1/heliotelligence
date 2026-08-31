# Physics Development Roadmap

This roadmap describes dependency order, not a fixed pull-request numbering
scheme. PR numbers after the completed foundations are indicative and may
change as evidence and review boundaries evolve.

## Foundation completed

- PR #1 — environment and CI foundation
- PR #2 — electrical topology foundation
- PR #3 — module operating points
- PR #4 — string states and independent-MPPT aggregation

## Electrical migration sequence

Recommended sequence:

A. Voltage-dependent module I-V representation

B. String I-V representation for homogeneous strings

C. Common-voltage MPPT aggregation

D. Physically derived mismatch

E. Integration into the topology-aware Stage 4 DC path

F. Physical DC cable and combiner network

G. Higher-fidelity inverter behaviour and MPPT limits

H. AC network and transformer modelling

Each step should expose a narrow contract and remain outside the production
path until its lower-level physics and equivalence tests pass.

## Optical/irradiance enhancements

- Geometry-aware shading
- Incidence-angle modifier validation and refinement
- Rear/bifacial irradiance refinement
- Spectral refinement where evidence shows it is needed
- Time-varying physical or measured soiling

## Electrical enhancements

- Bypass-diode modelling
- Partial-shading electrical behaviour
- Multiple local maxima
- MPPT tracking behaviour
- DC clipping and inverter input constraints
- Physical cable losses
- Inverter active/reactive/apparent power (`P/Q/S`)
- AC collection network
- Transformer losses
- Grid export constraints and controls

## Validation milestones

Every physical increment should include, as applicable:

- focused unit physics tests;
- limiting-case tests;
- conservation and equivalence checks;
- comparison with pvlib or another reference calculation;
- synthetic topology tests; and
- only later, comparison with site SCADA and PVsyst.

A site-data fit must not be used to hide incorrect physics. When a reference
and the model disagree, first isolate whether the cause is inputs, topology,
model assumptions, implementation, or measurement quality.

## Multi-site and portfolio layer

Multi-site onboarding and portfolio management are future platform layers that
sit above independently validated site-level physics. They must not be mixed
into the current Stage 4 electrical migration.

Future capabilities may include:

- multiple independently configured sites;
- portfolio membership;
- portfolio expected-energy aggregation;
- portfolio actual-versus-expected performance;
- cross-site ranking;
- portfolio loss attribution;
- portfolio availability;
- fleet-wide anomaly detection; and
- portfolio financial or revenue aggregation where appropriate.

The repository already models physics in a site-scoped form, but it does not
currently establish a `PortfolioConfig`, organisation hierarchy, portfolio
dashboard, or portfolio aggregation implementation.
