# Physics Architecture

Heliotelligence targets a component-resolved photovoltaic digital twin. The
architecture should explain energy movement and loss through physical state,
not merely reproduce a final site-level number.

## System modelling hierarchy

The future platform hierarchy is:

`Organisation / Client → Portfolio → Site → Inverter → MPPT → String`

Organisation/client and portfolio management are architectural direction, not
currently implemented platform capabilities.

Physical simulation occurs primarily at site and component level. Portfolio
results should be composed from independently modelled sites, never by treating
multiple sites as one electrical plant. Sites may differ in:

- equipment;
- electrical topology;
- weather;
- timezone;
- grid constraints; and
- available telemetry.

Physics functions should therefore remain site- and equipment-agnostic. Site
configuration selects the applicable inputs and topology; it must not embed a
reference site's assumptions into reusable physics code.

## Target physical chain

```text
WEATHER
↓
IRRADIANCE
├ beam
├ diffuse
├ rear / bifacial
└ spectral
↓
OPTICAL / SURFACE EFFECTS
├ shading
├ soiling
└ IAM
↓
EFFECTIVE IRRADIANCE
↓
THERMAL
↓ Tcell
MODULE ELECTRICAL MODEL
├ parameter resolution
├ De Soto
├ single diode
└ voltage-dependent I-V
↓
STRING ELECTRICAL MODEL
↓
MPPT COMMON-VOLTAGE MODEL
↓
PHYSICAL MISMATCH
↓
DC COLLECTION
├ string cable
├ combiner
└ DC feeder
↓
INVERTER
↓
AC COLLECTION
├ LV cable
├ transformer
├ MV collection
├ main transformer
└ HV/export
↓
GRID / REVENUE METER
```

## Model status

| Layer | Current status | Current approach | Target approach |
|---|---|---|---|
| Organisation/client | planned | Not implemented | Ownership and access boundary above portfolios |
| Portfolio | planned | Not implemented | Composition and analytics across independently modelled sites |
| Weather | implemented | Database-backed weather series with gap handling | Validated multi-source weather inputs |
| POA irradiance | implemented | pvlib transposition | Retain with site validation |
| Beam/diffuse | implemented | Measured inputs or Erbs decomposition | Validated component irradiance |
| Rear/bifacial | partial | pvlib infinite-sheds approximation for bifacial sites | Geometry-validated rear irradiance |
| Spectral correction | implemented | First Solar spectral factor when inputs exist | Validate/refine when site evidence requires it |
| Shading | planned | No physical shading engine | Geometry- and irradiance-resolved shading |
| IAM | implemented | pvlib physical IAM on direct POA | Validate against module/site evidence |
| Soiling | legacy approximation | Static percentage in aggregate DC losses | Time-varying physical or measured model |
| LID | legacy approximation | Static percentage in aggregate DC losses | Validated degradation model or measured state |
| Thermal | implemented | Faiman with measured-module and NOCT fallbacks | Calibrated component thermal behaviour |
| Module parameter lookup | implemented | CEC, local library, datasheet, then fallback tiers | Maintain traceable parameter provenance |
| De Soto | implemented | De Soto parameter calculation | Retain and validate by module class |
| Single diode | implemented | Module MPP through pvlib singlediode | Expose voltage-dependent I-V states |
| PVWatts fallback | implemented | Low-fidelity fallback tier | Retain only as an explicit fallback |
| Module operating point | implemented | Module Pmp/Vmp/Imp and metadata | Extend to voltage-dependent I-V |
| String model | partial | Ideal series scaling and explicit string states | Voltage-dependent string I-V |
| MPPT model | partial | Independent-string Pmp counterfactual only | Common-voltage optimization |
| Mismatch | legacy approximation | Static aggregate percentage | Difference between independent and common-MPPT power |
| Bypass diodes | planned | Not modelled | Module substring/bypass behaviour |
| Partial shading | planned | No electrical interaction model | Irradiance-to-bypass-to-string I-V chain |
| DC cable | legacy approximation | Static DC wiring percentage | Current-dependent I²R network losses |
| Combiner | planned | Not modelled | Physical combiner connectivity and losses |
| Inverter | partial | Aggregate efficiency, capacity clipping, and grid cap | Per-unit efficiency and constraint model |
| Inverter MPPT constraints | planned | Not modelled | Voltage/current windows and tracker behaviour |
| DC clipping | planned | No DC-side clipping; an aggregate AC capacity cap exists | Electrical DC/inverter constraint model |
| Reactive power Q | planned | Not modelled | Inverter and grid-code Q behaviour |
| Apparent power S | planned | Not modelled | P/Q/S capability limits |
| LV cables | legacy approximation | Static aggregate AC wiring percentage | Physical LV network losses |
| Transformers | planned | Not separately modelled | Load/no-load and reactive transformer losses |
| MV collection | planned | Not modelled | Topology-aware MV collection network |
| HV/export network | planned | Not modelled | Physical export network and metering boundary |
| Grid limit | implemented | Aggregate active-power cap | Constraint-aware export control |
| Revenue meter | partial | Ingested data can support comparison | Explicit end-of-chain validation boundary |
| SCADA/digital-twin validation | partial | Ingestion and selected analytics exist | Layer-by-layer and end-to-end validation |

## Mismatch definition

For strings `s` sharing an MPPT:

`P_independent = Σ_s P_mp,s`

`I_MPPT(V) = Σ_s I_s(V)`

`V* = argmax_V [V × I_MPPT(V)]`

`P_actual = V* × I_MPPT(V*)`

`P_mismatch = P_independent - P_actual`

Individual string MPP values are insufficient because connected strings must
operate at a shared MPPT voltage. The actual optimum depends on each string's
current at every candidate common voltage, not only its independent MPP.

## Partial shading target

The intended dependency is:

`module-level irradiance → module I-V → bypass-diode behaviour → string I-V → possible multiple local maxima → MPPT behaviour`

A scalar shading percentage is not the final target mechanism. Shading must
eventually change electrical state through irradiance distribution and device
behaviour.

## Cable target

Physical conductor loss follows:

`P_loss = I²R`

`R = ρL/A`

The current percentage wiring losses are compatibility assumptions. Replace
them only when current, conductor, length, and network-topology information are
available and the physical replacement is independently validated.
