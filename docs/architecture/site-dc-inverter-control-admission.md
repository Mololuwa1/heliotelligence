# P2F DC plant + inverter/control admission boundary

P2F is one onboarding boundary: module/string population → configured and verified
inverter inventory → physical string/MPPT/inverter topology → DC branch authority
→ inverter equipment/conversion/capability → controller requests/allocation.
Unfinished evidence updates P2F in place; individual fields do not get new P2 letters.
P2G remains reserved for the consolidated AC network, transformer and revenue-meter
boundary. P2H owns benchmark/uncertainty and P2 closure. P3 remains inactive.

```text
P2F — DC plant + inverter/control boundary
ADMITTED NOW
  configured inverter identity inventory
  existing 24 modules/string lower-fidelity basis
           ↓
UNRESOLVED — EXTERNAL EVIDENCE REQUIRED
  DC topology/population
  inverter equipment/capability
  controller requests/allocation
           ↓
FULL-FIDELITY UPGRADE
  shared DC collection
  advanced conductor authority
  advanced mismatch/member/bypass evidence
```

Configured inverter identity ≠ electrical topology. Model label ≠ exact CEC/SAM
reference. pnom_kwac ≠ Smax. grid_limit_kwac ≠ controller dispatch request.
Legacy loss percentage ≠ physical branch resistance. Capability ≠ site evidence;
evidence ≠ admission; admission ≠ timestamped resolution or runtime activation.

## ADMITTED NOW

Only `s8.inverter_inventory_binding` is newly admitted, at explicit lower fidelity,
as a reviewed **configured inverter-label inventory and layout-group membership
basis**. The existing `s8.string_module_count` basis remains 24 and lower fidelity;
no physical string inventory or topology is implied by either admission.

The [frozen authority implementation](../../src/heliotelligence/engine/site_inverter_inventory_authority.py)
and [reviewed declaration](../../evidence/authorities/bracon-ash/inverter-inventory.yaml)
bind `site-001`, canonical UUID `5ab83b40-553c-5ddd-976f-71f6cb5d490f`, Bracon Ash,
and the exact ordered lists in [config/sites.yaml](../../config/sites.yaml).
There are **66 globally unique configured labels**, in ordered groups MQA11 16,
MQA21 16, MQA22 17 and MQA23 17. This is not verified as-built equipment inventory.
Confidence and installed-equipment temporal applicability remain `unknown`.

| Semantic | Identifier |
| --- | --- |
| Contract | `explicit_reviewed_configured_inverter_label_inventory_authority_v1` |
| Model | `configured_inverter_ids_and_layout_group_membership_lower_fidelity_basis_v1` |
| Scope | `configured_site_inverter_identity_inventory_before_electrical_topology_and_equipment_binding` |
| Coverage | `single_site_configured_inverter_labels_and_layout_group_membership_only` |
| Fidelity | `supports_explicit_lower_fidelity_path` |

Immutable group records contain only group ID and ordered inverter-label tuple.
The authority adds site identity, configured total and explicit provenance/semantics.
It excludes equipment model, CEC/SAM references, conversion/efficiency/nameplate,
P/Q/S/thermal limits, grid cap, losses, coordinates/display labels, module/string
population, MPPT/string IDs, resistance, topology and controller fields.
No ElectricalTopologyConfig or physical equipment authority is constructed.

Strict supplied-path UTF-8 safe YAML rejects duplicate keys, unknown/missing fields,
inconsistent totals and repeated groups/labels. Serialization is deterministic and
JSON-safe; deserialization revalidates nested records. The independent validator
uses no production admission, constructors, loader, wire or binding helpers.
It audits frozen nested records too. Structural validation is not a cryptographic
signature: valid-shaped edits must also pass the separately reviewed source binding.

Binding reads only config ID/name, inverter.num_units and layout group ID/count/
inverter lists. Each declared group count must match its list length, totals must
close, IDs must be globally unique, and exact group/member order must match the
authority. Manifest asset scope contains all 66 labels in source order, with no
wildcard. Source facts remain transcriptions. Guarded access and isolated drift
tests prove excluded model, location, module, topology and capacity values have no
effect. Configuration did not self-admit; the reviewed declaration is the binding.

## UNRESOLVED — EXTERNAL EVIDENCE REQUIRED

Remaining S8 baseline blockers, followed by S9/S10 blockers:

<!-- BEGIN P2F BASELINE BLOCKERS -->
- `s8.direct_branch_resistance`
- `s8.inverter_mppt_mapping`
- `s8.population_residual`
- `s8.string_mppt_mapping`
- `site.geometry.electrical_mapping`
- `site.population.module_count`
- `s10.active_power_request`
- `s10.controller_allocation`
- `s10.reactive_power_request`
- `s10.request_timestamp_semantics`
- `s9.conversion_model`
- `s9.fixed_q_convention`
- `s9.inverter_model_mapping`
- `s9.inverter_temperature_state`
- `s9.static_pq_capability`
- `s9.thermal_capability`
<!-- END P2F BASELINE BLOCKERS -->

The list is drift-tested against the [manifest](../../evidence/sites/bracon-ash.yaml).
Present/not-admitted model evidence and missing/blocked evidence both remain
coverage blockers. Missing means no sufficient supplied package, not proof that
external evidence does not exist. Supply or review the following three bundles.

### 1. DC topology and population

Provide reviewed as-built string schedules, commissioning inventory, electrical
drawings, asset register or other explicit evidence that reconciles physical
module/string population. Keep all three representations separate until then:
2,076 × 24 = **49,824**; 659 × 72 = **47,448**; geometry metadata = **50,736**.
The configured **2,076 strings remains unadmitted**. Do not back-solve inventory
from 28,524 kWp or use the configured inverter-label total to choose a population.

Canonical S8 needs physical inverter, MPPT and string IDs; string→MPPT and
MPPT→inverter membership; and modules/string for each physical string where
applicable. Supply the mapping of physical/electrical assets to spatial evidence
explicitly. Layout groups, proximity, counts and capacity do not establish any
connectivity. The current 66 labels alone cannot populate electrical_topology.

For direct branches, establish the physical string-terminal → parent-MPPT
(`string_terminal` → `mppt_input`) path and explicit validated total loop resistance,
or reviewed evidence for conductor/cable type, length/path, cross-section,
material, temperature basis, parallel conductors and connection/contact assumptions.
**0.48% legacy DC wiring loss is not resistance.** Future Priority B conductor
parameter derivation must feed the existing S8 branch contract, not subtract
another cable-loss estimate beside its solution.

For population residual, the generic bounded mismatch authority exists, but Bracon
still lacks evidence supporting its mechanism, exclusion of already-owned effects,
physical applicability and temporal/operating scope. **1.15% legacy mismatch is not
canonical population-residual authority.** Neither population conflict nor missing
member-level evidence is resolved by a percentage.

Supply combiner/shared-feeder topology where applicable. The full-fidelity-only
`s8.shared_dc_collection_topology` remains blocked. It must not block an
independently valid direct-branch baseline solely because advanced evidence is
absent; no alternative topology is invented here.

### 2. Inverter equipment and capability

Provide verified installed equipment inventory/model evidence and explicit physical
inverter ID → exact CEC/SAM reference binding where that canonical route is intended.
S9-0 contract `topology_inverter_cec_sam_authority_v1` requires exact references for
Sandia conversion parameters and DC operating envelopes. **Sungrow SG350HX-15A is
only a configured model label**, not an exact CEC/SAM reference. Do not fuzzy-match
or auto-promote it. `InverterUnitConfig.model_ref` remains opaque unless separately
reviewed; the canonical resolver requires its own explicit reference mapping.

Configured `pvlib_model: pvwatts`, `eta_nom: 0.9842` and `pnom_kwac: 320.0` belong to
the legacy compatibility runtime. They do not admit S9 conversion or installed
model authority, and canonical S9 is not changed to accommodate them.

Supply DC voltage/current limits and explicit active, apparent and reactive
capability, with voltage/frequency applicability and manufacturer curves where
relevant. **320 kWac is not Smax** and supplies no Q limits. Review external Q sign
semantics and document any transform before admission; canonical downstream uses
positive injection/negative absorption, which must not be assumed to match a
manufacturer, PPC or SCADA source.

For thermal capability and timestamped inverter temperature, provide the
measurement quantity/source, explicit derating curve or reviewed no-derating
authority, validity domain and timestamp semantics. Active nameplate is not a
thermal curve; module temperature is not inverter temperature. No new S9
requirement is admitted by this package.

### 3. Plant controller / PPC

Provide controller identity/modes; active and reactive setpoint channels; units,
signs and reference planes; allocation logic; plant-level versus per-inverter
semantics; timestamps and historical coverage; and any source hold/interpolation
semantics that require reviewed adaptation. Current canonical requests are exact
per timestamp and inverter: do not hold, interpolate or allocate them implicitly.

The aggregate legacy **grid_limit_kwac = 20000** is not a timestamped inverter P
request, controller allocation or per-inverter dispatch setpoint. S10A requires
explicit timestamp, physical inverter ID, absolute active-power setpoint at
`inverter_ac_output`, request semantics, source and confidence. Reactive requests
likewise need explicit canonical Q semantics. Missing request is not zero.
All four S10 requirements remain blocked. No controller mode or allocation rule
is manufactured from an application cap.

## FULL-FIDELITY UPGRADE

Verified installed inventory, shared DC collection, advanced conductor evidence,
member/substring/bypass routing and flash/mismatch evidence may support future
upgrades inside this boundary. Priority A advanced substring/bypass physics and
Priority B conductor derivation remain pending. Neither replaces current S8
reference planes/solvers. Optional advanced evidence must not automatically defeat
an independently valid lower-fidelity baseline.

Current manifest version: `bracon-ash-dc-inverter-control-admission-v6`.
Evidence remains 17/48/1/0; admission becomes 6/11/49/0; active support is
1 full / 5 lower / 60 non-resolving / 0 N/A. Only S8 baseline blockers reduce
7 → 6; full-fidelity blockers remain 9. All other coverage and the other 65
manifest items are unchanged from P2E. Every section still has blockers.

P2F is **implemented as the current reviewed DC/inverter/control admission
package**, not DC/inverter/control readiness for P3. Completion means supplied
evidence has been reviewed, the single defensible configured inventory admitted,
unsupported claims retained unresolved and one consolidated request records the
remaining work. Future DC/inverter/controller evidence updates P2F in place.
P2E upstream evidence remains within P2E. Full P2 is in progress and P3 inactive.
No physics, config, runtime, production source, P1, database, API, frontend or
shadow execution changes occur. electrical_topology remains None; no MPPT IDs,
string IDs or membership mappings are created.
