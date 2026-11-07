# P2E upstream physical-input admission boundary

P2E is the **single upstream onboarding work package**, spanning weather/time,
irradiance quantity/plane, shading/rear and bifacial applicability, spectral
admission, thermal POA, environmental/temperature evidence and module thermal
authority. Future Bracon upstream evidence updates this package in place, rather
than creating a new P2 letter for each field. P2F is reserved for DC plant and
inverter/control authority.

```text
P2E — upstream physical-input boundary
currently admitted:
  configured model-class bifacial applicability
           ↓
remaining evidence packages:
  weather/time
  irradiance/optics
  spectral/thermal model
  thermal sensors/zones
           ↓
canonical upstream path still gated
```

Capability ≠ evidence; evidence ≠ admission; admission ≠ timestamp resolution;
admission ≠ runtime activation. P2E is implemented as the current reviewed upstream
admission package, **not upstream readiness for P3**. Completion of this package
means supplied evidence has been reviewed, defensible authority admitted,
insufficient evidence retained unresolved, and one consolidated request identifies
what must be supplied next. Full P2 remains in progress and P3 inactive.

## ADMITTED NOW

Only `irradiance.bifacial_applicability` is newly admitted, as lower-fidelity
configured **model-class applicability**. The [frozen engine authority](../../src/heliotelligence/engine/site_bifacial_applicability_authority.py)
and [reviewed declaration](../../evidence/authorities/bracon-ash/bifacial-applicability.yaml)
bind `site-001`, UUID `5ab83b40-553c-5ddd-976f-71f6cb5d490f`, Bracon Ash,
`JKM570N-72HL4-BDV`, `mono_si`, and exact boolean `bifacial_enabled: true`.
Sources are [site configuration](../../config/sites.yaml) and
[local module library](../../src/heliotelligence/data/module_library.yaml).
Confidence and installed-equipment temporal applicability remain `unknown`.
No receiver-level installed-module coverage is established.

| Semantic | Identifier |
| --- | --- |
| Contract | `explicit_reviewed_configured_module_class_bifacial_applicability_authority_v1` |
| Model | `configured_module_class_bifacial_enabled_lower_fidelity_basis_v1` |
| Scope | `configured_module_class_bifacial_applicability_before_receiver_and_rear_model_binding` |
| Coverage | `single_site_configured_module_class_bifacial_applicability_only` |
| Fidelity | `supports_explicit_lower_fidelity_path` |

**Applicability is not an electrical bifacial coefficient.** Both sources contain
`bifaciality_factor: 0.80`, retained as an unadmitted manifest/source fact. Neither
source establishes that it is IEC `phi_Isc` or `isc_bifaciality_factor`. Canonical
[bifacial response](../../src/heliotelligence/physics/bifacial_response.py) requires
explicit response evidence; it is not constructed here. Response coefficient,
receiver binding, rear model and rear geometry remain unresolved. The schema
excludes all coefficients, Isc values, response method, receiver/row IDs,
geometry/rear-model parameters, POA/IAM/spectral/thermal inputs and population.

The supplied-path UTF-8 safe YAML loader rejects duplicate, missing and unknown
fields. Strict JSON-safe serialization revalidates exact boolean, UUID, source
tuple and fixed semantics. An independent frozen-state validator uses no
constructors, loaders, wire/binding helpers or physics runtime. This format is
not a signature: valid-shaped edits still require the separate reviewed source
binding. Binding compares only site identity and model/technology/bifacial flag
against the manifest, SiteConfig and explicitly supplied library path. Guarded
config access and factor-only drift regressions prove that 0.80 is not consumed.
No package discovery, database, network or automatic authority generation occurs.

## UNRESOLVED — EXTERNAL EVIDENCE REQUIRED

The six remaining baseline `upstream_environment` blockers are:

<!-- BEGIN P2E BASELINE BLOCKERS -->
- `irradiance.front_measurement_plane`
- `irradiance.front_source_quantity`
- `irradiance.rear_model_basis`
- `irradiance.shading_geometry`
- `weather.cadence_interval_semantics`
- `weather.temporal_semantics`
<!-- END P2E BASELINE BLOCKERS -->

The list is drift-tested against the [manifest](../../evidence/sites/bracon-ash.yaml).
Some requirements have present but unadmitted material, others are missing/blocked;
all remain coverage blockers. Missing means no sufficient supplied package, not
proof that external evidence does not exist. Submit or review the following four
bundles together; they are not separate P2 workstreams.

### 1. Weather/time semantics

For each actual source, identify source identity and historical applicability,
value semantics (`instantaneous_snapshot` or `interval_average`), timestamp label
(`instant`, `interval_start`, `interval_midpoint`, `interval_end`), explicit interval
duration where applicable, representative solar-geometry evaluation policy,
timezone basis, DST treatment and cadence. Evidence must establish the relationship
between source observations, stored labels and the intended canonical state.

Current collector code stores Solcast `period_end` and requests `PT60M`; the SCADA
parser documents local period-START, infers an interval from observed timestamp
differences and stores UTC period-END. These are code conventions, not admitted
source averaging/duration or historical cadence evidence. Do not infer canonical
interval semantics from labels, request strings or parser defaults. Neither
weather temporal requirement is admitted by this package.

### 2. Irradiance/optical geometry and measurement

For front irradiance, provide physical sensor/channel identity, measurement
quantity, front/rear ownership, plane, orientation, representative receiver/array
coverage, calibration status, units/scaling and timestamp relationship.
`SMP10-POA-1 -> poa_wm2` is only a channel mapping. It does not admit
`irradiance.front_source_quantity` or `irradiance.front_measurement_plane`.
Measured front evidence does not erase rear irradiance or establish total,
electrical-effective or thermal irradiance.

For the rear model, establish the chosen model and applicable physical scope:
fixed-row/tracker arrangement, receiver/array assignments, row geometry, collector
width, pitch, height, surface orientation, ground/albedo basis, rear measurement
or model basis and validity assumptions. Tilt, azimuth, GCR and a bifacial flag
alone do not establish fixed-row infinite-sheds applicability.

For shading, provide explicit receiver/row membership, geometry, collector widths,
pitch relationships and blocking-pair topology. The
[reconstruction](../../config/geometry/site-001.json) declares
`_source = module-cloud reconstruction @174.47`, `_georef_residual_m = 0.436` and
`_total_modules_extracted = 50736`, but contains **608 reconstructed panel
coordinate points**: MQA11 133, MQA21 133, MQA22 205 and MQA23 137.
Those points are not one coordinate per physical module. They establish neither
physical receiver IDs, row membership, blocking pairs, collector widths, row pitch
per receiver relationship nor electrical connectivity. Neither shading geometry
nor module-position inventory is admitted here.

Also supply explicit canonical electrical-response coefficient evidence and its
receiver/module-class applicability before electrical bifacial response is bound.
The generic 0.80 field is not that evidence.

### 3. Spectral/thermal modelling

`irradiance.spectral_admission` remains unresolved. Identify the intended site
spectral treatment and required environmental inputs, explicitly enabled, disabled
by reviewed authority, or otherwise explicitly resolved. Missing inputs in the
legacy pipeline do not mean reviewed disabled admission.

`irradiance.thermal_poa_basis` needs an explicit calibration-basis decision about
which **incident broadband** quantity drives the thermal model. Electrical-effective
irradiance after optical/electrical response is a distinct quantity and must not
be silently reused as thermal POA.

`thermal.model_parameters` needs the intended canonical family, native parameter
meanings, source, confidence and wind-speed basis. Configured `u_c = 29.0` and
`u_v = 0.0` are legacy compatibility values. Historically passing them as
Faiman-like `u0/u1` does not admit either native Faiman or PVsyst authority.
No conversion between families is inferred. Identify a reviewed PVsyst or Faiman
path, or explicit direct-temperature evidence as appropriate to the intended path.

### 4. Thermal sensors/zones/environment

Supply ambient-temperature quantity/source; wind-speed quantity and measurement
height/basis; module-back versus cell-temperature quantity; sensor locations,
calibration and aggregation rules; zone definitions and receiver/zone bindings;
and temporal coverage. Channel mappings `WS_AVG -> wind_speed_ms`, `temp_mod_avg_c`
and `temp_amb_c` do not establish these physical semantics.

The following module-electrical upstream requirements remain unresolved within
this same P2E package:

- `irradiance.spectral_admission`
- `irradiance.thermal_poa_basis`
- `thermal.sensor_quantity`
- `thermal.sensor_placement_calibration`
- `thermal.zones`
- `thermal.zone_binding`
- `thermal.model_parameters`
- `thermal.environmental_inputs`

Together with separately unresolved population evidence, these remain the nine
module-electrical baseline blockers. No thermal sensor placement, calibration,
model parameter, environment or zone binding is manufactured.

## OPTIONAL / NON-BASELINE

`weather.source_identifiers` remains unadmitted. The configured Solcast resource
ID `abcd-1234-efgh-5678` is placeholder-shaped; the SCADA directory is an application
path. Neither proves a live source. Reviewed actual source identity is still needed
for the weather/time bundle even though this catalogue inventory item is optional.

`site.geometry.module_positions` remains unadmitted and mandatory only for full
fidelity. The 608-point reconstruction is spatial evidence, not a complete module
inventory. P2E does not force every advanced model before a valid baseline can be
admitted. No lower-fidelity runtime path is invented to bypass missing evidence.

## FUTURE FULL-FIDELITY UPGRADE

Receiver-level installed module coverage, reviewed electrical-response evidence,
physical rear/shading geometry, appropriate measurement/calibration and full
upstream authority bindings remain required. Future evidence should update P2E
in place. Priority A advanced S8 substring/bypass and Priority B conductor
parameter derivation stay pending; this applicability declaration supplies neither.
P2F owns consolidated DC plant plus inverter/control; P2G AC network/meter; P2H
benchmark/uncertainty and P2 closure. Unfinished upstream work stays in P2E.

Current manifest version: `bracon-ash-upstream-physical-input-admission-v5`.
Evidence counts remain 17/48/1/0; admission becomes 5/12/49/0; active support is
1 full / 4 lower / 61 non-resolving / 0 N/A. Only upstream-environment baseline
blockers reduce 7 → 6; full-fidelity blockers remain 8. Every other section and
all 65 other items remain unchanged from P2D. All sections retain blockers.
Prior identity/module/series-count admissions retain their exact fidelity.
Population 49,824 / 47,448 / 50,736 stays unresolved; 2076 strings remains unadmitted
and electrical_topology remains None. No IDs or electrical mappings are created.
No physics, runtime, production source, writer or shadow execution is changed.
