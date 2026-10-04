# Reference Site: Bracon Ash

Bracon Ash is one current reference/onboarded site used during Heliotelligence development. Its values do not define the architecture and must not be copied to another site unless that site's evidence and configuration establish them.

## Known configuration

- Capacity: 28,524 kWp
- Module: JKM570N-72HL4-BDV, nominally 570 W
- Modules per string: 24
- Strings: 2,076
- Inverter: Sungrow SG350HX-15A
- Inverter nominal power: 320 kWac
- Inverter units: 66
- Nominal efficiency: 0.9842
- Grid export limit: 20 MW
- Inverter groups: MQA11 (16), MQA21 (16), MQA22 (17), MQA23 (17)

Current legacy loss assumptions:

- Soiling: 1.0%
- LID: 0.60%
- Mismatch: 1.15%
- DC wiring: 0.48%
- AC wiring: 1.70%

## Known data gaps

- No physical MPPT-to-string map is currently known.
- No string-to-inverter assignment should be inferred from aggregate counts.
- No physical cable layout is established by the current site configuration.
- No transformer or MV/HV collection topology is established by the current site configuration.
- No authoritative shared post-parallel DC collection network is established.
- No explicit S9-4A per-inverter AC capability authority has yet been established for Bracon Ash.

The current repository values `320 kWac`, grid export limit, inverter model name, CEC/SAM fields, and legacy AC wiring percentage do **not** by themselves establish:

- rated apparent power `Smax`;
- AC voltage basis;
- phase configuration;
- fixed reactive-power capability;
- manufacturer P-Q/PF capability.

Do not invent these relationships or use group membership, equipment count, capacity, labels, positions, `Paco`, CEC/SAM `Vac`, or cable-plan assumptions as substitutes for electrical/equipment authority.

## Applicability of the validated S8/S9/S10 chain

Heliotelligence now contains independently validated generic electrical/control contracts through S10C selected inverter AC dispatch state. Their existence does **not** mean Bracon Ash can be run through every high-fidelity stage from current site configuration.

The current generic chain includes:

```text
physical string I-V
→ common-voltage MPPT / physical mismatch
→ explicit direct branch resistance transform
→ MPPT-input operating point
→ inverter CEC/SAM authority
→ inverter DC envelope
→ Sandia conversion
→ pre-Paco potential
→ conversion / clipping / tare accounting
→ static P/Q/S capability
→ temperature-dependent capability
→ explicit active-power dispatch request
→ requested P/Q/S feasibility
→ exact feasible-request selected P/Q/S
```

For Bracon Ash specifically, topology-dependent stages must remain unresolved where required MPPT/string/cable authority is absent. S9-4A requires explicit per-inverter AC capability evidence; S9-4B additionally requires explicit timestamped Q requests; S9-4C requires authoritative inverter thermal-derating evidence; S9-4D additionally requires explicit matching inverter-temperature state; S10A requires explicit timestamped per-inverter active-power request; S10B requires the preceding capability/request evidence; and S10C can establish a selected point only where S10B fully proves the exact request feasible.

Do not back-fill missing authority from total string count, inverter groups, inverter count, 320 kWac nominal power, grid export limit, CEC `Vac`, active-power nameplate, geometry or measured output.

The validated direct-branch resistance model also does not establish Bracon Ash's real shared combiner/homerun network. That still requires as-built electrical evidence before generalized DC collection can be activated.

## S9-4B applicability

S9-4B is implemented generically and evaluates admitted S9-3B active power plus S9-4A static capability authority and an explicit timestamped Q request.

Its existence does **not** make Bracon Ash S9-4B-ready.

For Bracon Ash, S9-4B requires:

- authoritative per-inverter S9-4A voltage/basis/phase/`Smax` authority;
- fixed Q limits where available, with missing limits preserved as partial authority;
- an explicit requested/commanded Q at the evaluated timestamp;
- the project Q sign convention: positive injection, negative absorption.

Do not infer these inputs from 320 kWac nominal power, grid export limit, `Paco`, CEC `Vac`, inverter groups, model labels, MPPT/string counts, or legacy AC wiring percentages.

If fixed-Q capability evidence is unavailable, an Smax-circle pass remains only a partial capability result. If `|P| > Smax`, that known violation can still be preserved. No S9-4B result should be interpreted as dispatch, thermal derating, AC-current state, or site-network validation.

## S9-4C applicability

S9-4C is implemented generically as independent static thermal-derating authority, but no Bracon Ash inverter thermal authority should be invented from site weather, PV module temperature, nominal inverter power, CEC/SAM records, or generic inverter assumptions.

Bracon Ash S9-4C requires authoritative per-inverter evidence for:

- the relevant inverter `temperature_quantity`;
- the supported temperature domain;
- explicit no-derating authority or aligned P/S/Q thermal capability curves;
- provenance and confidence.

Reactive thermal limits use the project convention: positive Q is injection and negative Q is absorption. Manufacturer evidence using another convention must be transformed before authority construction.

Until such evidence is supplied, Bracon Ash thermal authority remains unresolved. S9-4D must not substitute module/cell temperature or ambient temperature unless that exact quantity is the admitted S9-4C authority basis.


## S9-4D applicability

S9-4D is implemented generically, but its existence does **not** make Bracon Ash thermally resolved.

For Bracon Ash, S9-4D requires all upstream S9-4B authority plus:

- resolved S9-4C thermal authority for the physical inverter;
- an explicit timestamped `InverterTemperatureState`;
- exact physical temperature-quantity match to S9-4C;
- a temperature inside the declared inclusive authority domain.

Do not substitute module/cell temperature for inverter temperature. Do not infer heatsink/internal temperature from ambient air unless the admitted manufacturer authority itself uses that exact ambient quantity.

Outside the authority domain S9-4D remains unresolved; it does not clamp or extrapolate. Missing thermal channels remain partial authority. A known upstream or thermal violation remains definitive, but a passing partial result does not become a fully satisfied capability state.

No S9-4D result should be interpreted as controller dispatch, actual inverter output, AC-current state, or site-network validation.


## S10A applicability

S10A is implemented generically, but no Bracon Ash controller request should be inferred from existing configuration.

`grid_limit_kwac` is **not** a timestamped per-inverter dispatch setpoint. A site export limit is also not equivalent to an individual inverter request because allocation across physical inverters requires separate controller authority.

Bracon Ash S10A resolution therefore requires direct explicit evidence such as a PPC/SCADA/OEM per-inverter active-power command at the relevant timestamp and at the `inverter_ac_output` reference plane.

Missing command remains unresolved. Explicit zero is a valid resolved command. S10A does not persist a previous request forward in time. Canonical Q request remains S9-4B-owned.

## S10B applicability

S10B evaluates the exact Bracon Ash requested P/Q/S point only when the upstream evidence exists.

It must not substitute `p_ac_available_w` for a missing P request, synthesize Q=0, allocate the site export limit across inverters, or use measured output as a request. Static and thermal capability evidence remain separately attributable.

A known explicit violation can be definitive under partial information, but a passing partial-authority state must remain partial rather than being promoted to full feasibility.

## S10C applicability

S10C can establish a Bracon Ash selected inverter target only when canonical S10B fully proves the exact requested point feasible.

It must not infer saturation behaviour for an infeasible request. In particular, it must not set `P_selected=min(P_requested,P_available)`, clip Q, project onto an S limit or thermal limit, or infer zero for inactive/missing state.

The S10C selected state is a controller/model target, not proof of actual inverter output. Bracon Ash telemetry reconciliation remains a separate future boundary.

## Legacy compatibility note

The site's current aggregate soiling, LID, mismatch, DC wiring, AC wiring and grid-limit configuration belong to the legacy compatibility path. They must not be combined with newly activated physical/controller replacements without an explicit production migration demonstrating no double counting.

## Capacity arithmetic discrepancy

The configured component counts imply:

`24 modules/string × 2,076 strings × 570 W/module = 28,399.68 kWp`

The documented/configured site capacity is `28,524 kWp`, a difference of `124.32 kWp` (approximately `0.436%`). Both values are recorded in current repository configuration or module data, but the repository does not establish the reason for the difference.

Do not invent an explanation. Resolve the discrepancy only from authoritative as-built, module, or commissioning records, then update configuration and documentation through a separately reviewed change.
