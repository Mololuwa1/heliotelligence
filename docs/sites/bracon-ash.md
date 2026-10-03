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

## Applicability of the validated S8/S9 chain

Heliotelligence now contains independently validated generic electrical contracts through S9-4D temperature-dependent inverter capability evaluation. Their existence does **not** mean Bracon Ash can be run through every high-fidelity stage from current site configuration.

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

parallel static authority:
→ inverter AC voltage/basis/phase/Smax/optional fixed-Q authority
+
explicit timestamped Q request
→ inverter P/Q/S capability-state evaluation

parallel static authority:
→ explicit inverter thermal-derating authority
+
explicit timestamped inverter-temperature state
→ temperature-dependent inverter capability evaluation
```

For Bracon Ash specifically, topology-dependent stages must remain unresolved where the required MPPT/string/cable authority is absent. S9-4A must remain unresolved until explicit per-inverter AC capability authority is supplied from authoritative equipment evidence; S9-4B therefore cannot produce a fully resolved site capability state without that authority plus explicit timestamped Q requests. S9-4C must independently remain unresolved until authoritative inverter thermal-derating evidence is supplied, and S9-4D additionally requires an explicit timestamped inverter-temperature state whose physical quantity exactly matches the admitted S9-4C authority.

Do not back-fill missing authority from the known total string count, inverter groups, inverter count, 320 kWac nominal power, grid export limit, CEC `Vac`, or any active-power nameplate value.

The validated direct-branch resistance model also does not establish Bracon Ash's real shared combiner / homerun network. That requires as-built electrical information before generalized DC collection can be activated defensibly.



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

## Legacy compatibility note

The site's current aggregate soiling, LID, mismatch, DC wiring, and AC wiring percentages belong to the legacy compatibility path. They must not be combined with newly activated physical replacements without an explicit production migration demonstrating no double counting.

## Capacity arithmetic discrepancy

The configured component counts imply:

`24 modules/string × 2,076 strings × 570 W/module = 28,399.68 kWp`

The documented/configured site capacity is `28,524 kWp`, a difference of `124.32 kWp` (approximately `0.436%`). Both values are recorded in current repository configuration or module data, but the repository does not establish the reason for the difference.

Do not invent an explanation. Resolve the discrepancy only from authoritative as-built, module, or commissioning records, then update configuration and documentation through a separately reviewed change.
