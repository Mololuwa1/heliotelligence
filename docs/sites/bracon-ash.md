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

Heliotelligence now contains independently validated generic electrical contracts through S9-4A static inverter AC capability authority. Their existence does **not** mean Bracon Ash can be run through every high-fidelity stage from current site configuration.

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
```

For Bracon Ash specifically, topology-dependent stages must remain unresolved where the required MPPT/string/cable authority is absent. S9-4A must likewise remain unresolved until an explicit per-inverter AC capability authority is supplied from authoritative equipment evidence.

Do not back-fill missing authority from the known total string count, inverter groups, inverter count, 320 kWac nominal power, grid export limit, CEC `Vac`, or any active-power nameplate value.

The validated direct-branch resistance model also does not establish Bracon Ash's real shared combiner / homerun network. That requires as-built electrical information before generalized DC collection can be activated defensibly.

## S9-4B applicability

S9-4B, once implemented, will evaluate requested inverter P/Q/S capability using admitted S9-3B active power plus S9-4A static authority.

For Bracon Ash it must not be activated merely because the generic S9-4B model exists. It requires, at minimum, the authoritative S9-4A fields and an explicit requested/commanded Q input with a defined sign convention.

If fixed Q/PF capability evidence is unavailable, the model must not present the apparent-power circle alone as complete manufacturer reactive-power capability.

## Legacy compatibility note

The site's current aggregate soiling, LID, mismatch, DC wiring, and AC wiring percentages belong to the legacy compatibility path. They must not be combined with newly activated physical replacements without an explicit production migration demonstrating no double counting.

## Capacity arithmetic discrepancy

The configured component counts imply:

`24 modules/string × 2,076 strings × 570 W/module = 28,399.68 kWp`

The documented/configured site capacity is `28,524 kWp`, a difference of `124.32 kWp` (approximately `0.436%`). Both values are recorded in current repository configuration or module data, but the repository does not establish the reason for the difference.

Do not invent an explanation. Resolve the discrepancy only from authoritative as-built, module, or commissioning records, then update configuration and documentation through a separately reviewed change.
