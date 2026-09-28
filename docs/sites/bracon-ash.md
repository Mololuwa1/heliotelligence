# Reference Site: Bracon Ash

Bracon Ash is one current reference/onboarded site used during Heliotelligence
development. Its values do not define the architecture and must not be copied
to another site unless that site's evidence and configuration establish them.

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
- No transformer or MV/HV collection topology is established by the current
  site configuration.
- No authoritative shared post-parallel DC collection network is established.
- No authoritative inverter AC apparent/reactive capability authority has yet
  been established in the canonical S9-4 form.

Do not invent these relationships or use group membership, equipment count,
capacity, labels, positions, or cable-plan assumptions as substitutes for
electrical connectivity.

## Applicability of the validated S8/S9 chain

Heliotelligence now contains independently validated generic electrical
contracts through S9-3B inverter conversion / clipping / tare accounting. Their
existence does **not** mean Bracon Ash can be run through every high-fidelity
stage from current site configuration.

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
```

For Bracon Ash specifically, topology-dependent stages must remain unresolved
where the required MPPT/string/cable authority is absent. Do not back-fill the
missing topology from the known total string count, inverter groups, or inverter
count.

The validated direct-branch resistance model also does not establish Bracon
Ash's real shared combiner / homerun network. That requires as-built electrical
information before generalized DC collection can be activated defensibly.

## Legacy compatibility note

The site's current aggregate soiling, LID, mismatch, DC wiring, and AC wiring
percentages belong to the legacy compatibility path. They must not be combined
with newly activated physical replacements without an explicit production
migration demonstrating no double counting.

## Capacity arithmetic discrepancy

The configured component counts imply:

`24 modules/string × 2,076 strings × 570 W/module = 28,399.68 kWp`

The documented/configured site capacity is `28,524 kWp`, a difference of
`124.32 kWp` (approximately `0.436%`). Both values are recorded in current
repository configuration or module data, but the repository does not establish
the reason for the difference.

Do not invent an explanation. Resolve the discrepancy only from authoritative
as-built, module, or commissioning records, then update configuration and
documentation through a separately reviewed change.
