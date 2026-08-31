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

Do not invent these relationships or use group membership as a substitute for
electrical connectivity.

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
