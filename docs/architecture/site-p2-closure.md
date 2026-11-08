# P2H benchmark/uncertainty review and final P2 closure

## 1. Purpose

This closes P2 as the review/admission-governance phase for **currently supplied
evidence**, not as physical-path readiness. It adds zero site admissions and
changes no physics, runtime, authority or evidence data. Starting checkpoint:
PR #139 merge `ba0044d39985796dbbf82884b18b53b475e2e620`.
The [Bracon manifest](../../evidence/sites/bracon-ash.yaml) stays unchanged at
`bracon-ash-dc-inverter-control-admission-v6`: evidence 17/48/1/0, admission
6/11/49/0 and support 1 full / 5 lower / 60 non-resolving / 0 N/A.

## 2. P2 completion definition

P2 is complete when P2A–P2H have inventoried and reviewed every required evidence
domain against the supplied package, admitted only defensible evidence, retained
unsupported evidence as explicit blockers and assigned stable future-update
ownership. Completion does not require every evidence requirement to be admitted.
P2A baseline, P2B identity, P2C configured module basis, P2D series-count basis,
P2E upstream review, P2F DC/inverter/control review, P2G downstream review and
P2H benchmark/uncertainty/closure are COMPLETE as review work packages with this
increment. Evidence acquisition and admission continue within those packages.

## 3. Current Bracon decision

```text
P2 REVIEW STATUS = COMPLETE
P2 BASELINE PHYSICAL ADMISSION STATUS = INCOMPLETE
P3_ENTRY_EVIDENCE_STATUS = BLOCKED
P3 EXECUTION STATUS = INACTIVE
reason: 53 unique mandatory baseline requirements remain unresolved
```

The six existing admissions remain exactly: configured bifacial applicability,
module electrical basis, configured inverter-label inventory, configured series
count, site identity and module-model label. Only identity has full support; the
other five have explicit lower support. No S14 or uncertainty site requirement is
admitted. The four direct P2H requirements remain missing/blocked, non-resolving,
with no source, admitted authority or binding reference:

- `s14.benchmark_interval_semantics`
- `s14.interval_support_policy`
- `uncertainty.expected_model`
- `uncertainty.measurement_chain`

## 4. Whole-site baseline blocker matrix

The authoritative machine-readable state is validated
`SiteEvidenceManifest.path_coverage`, not a new readiness engine. All nine baseline
and full-fidelity section states remain `partially_admitted`: the common identity
prerequisite is admitted, but every section still has required physical gaps.

<!-- BEGIN P2H BLOCKER MATRIX -->
| Section | Baseline blockers | Full-fidelity blockers |
| --- | ---: | ---: |
| `upstream_environment` | 6 | 8 |
| `module_electrical_input` | 9 | 10 |
| `s8_dc` | 6 | 9 |
| `s9_s10_inverter_control` | 10 | 10 |
| `s11_lv_collection` | 5 | 5 |
| `s12_transformer` | 5 | 7 |
| `s13_mv_hv_meter` | 9 | 9 |
| `s14_benchmarking` | 2 | 2 |
| `uncertainty` | 2 | 2 |
<!-- END P2H BLOCKER MATRIX -->

There are **54 section-level baseline entries, 53 unique baseline IDs**. Only
`site.population.module_count` appears twice: module-electrical input and S8 DC.
Full fidelity has **62 section-level entries, 61 unique IDs**. These are blocker
inventories, not a maturity score or readiness percentage; requirements have
different physical significance and scopes.

## 5. Blocker ownership by P2E/P2F/P2G/P2H

Every unique baseline blocker below has exactly one future-update owner. The
sets are pairwise disjoint and their union is the exact 53-ID baseline union.
The duplicated section entry for population has only one owner: P2F, never P2E.

### P2E — 14 unique baseline blockers

<!-- BEGIN P2E BASELINE OWNERSHIP -->
- `irradiance.front_measurement_plane`
- `irradiance.front_source_quantity`
- `irradiance.rear_model_basis`
- `irradiance.shading_geometry`
- `irradiance.spectral_admission`
- `irradiance.thermal_poa_basis`
- `thermal.environmental_inputs`
- `thermal.model_parameters`
- `thermal.sensor_placement_calibration`
- `thermal.sensor_quantity`
- `thermal.zone_binding`
- `thermal.zones`
- `weather.cadence_interval_semantics`
- `weather.temporal_semantics`
<!-- END P2E BASELINE OWNERSHIP -->

### P2F — 16 unique baseline blockers

<!-- BEGIN P2F BASELINE OWNERSHIP -->
- `s10.active_power_request`
- `s10.controller_allocation`
- `s10.reactive_power_request`
- `s10.request_timestamp_semantics`
- `s8.direct_branch_resistance`
- `s8.inverter_mppt_mapping`
- `s8.population_residual`
- `s8.string_mppt_mapping`
- `s9.conversion_model`
- `s9.fixed_q_convention`
- `s9.inverter_model_mapping`
- `s9.inverter_temperature_state`
- `s9.static_pq_capability`
- `s9.thermal_capability`
- `site.geometry.electrical_mapping`
- `site.population.module_count`
<!-- END P2F BASELINE OWNERSHIP -->

### P2G — 19 unique baseline blockers

<!-- BEGIN P2G BASELINE OWNERSHIP -->
- `s11.collection_exits`
- `s11.exit_voltage`
- `s11.inverter_terminal_nodes`
- `s11.lv_topology`
- `s11.segment_impedance`
- `s12.factory_loss_evidence`
- `s12.lower_fidelity_baseline`
- `s12.ratio_tapping_impedance`
- `s12.transformer_equipment`
- `s12.transformer_terminal_binding`
- `s13.grid_boundary`
- `s13.grid_boundary_voltage`
- `s13.mv_hv_topology`
- `s13.revenue_meter_binding`
- `s13.revenue_meter_measurement_semantics`
- `s13.revenue_meter_scaling`
- `s13.revenue_meter_sign_conventions`
- `s13.segment_parameters`
- `s13.transformer_network_binding`
<!-- END P2G BASELINE OWNERSHIP -->

### P2H — 4 unique baseline blockers

<!-- BEGIN P2H BASELINE OWNERSHIP -->
- `s14.benchmark_interval_semantics`
- `s14.interval_support_policy`
- `uncertainty.expected_model`
- `uncertainty.measurement_chain`
<!-- END P2H BASELINE OWNERSHIP -->

Owner totals are **14 + 16 + 19 + 4 = 53**. Full-only transformer construction and
thermal requirements stay P2G-owned but are outside that baseline total. Harmonics
remain optional unless required by the selected path. Full-only/advanced upgrades
stay within the appropriate existing physical-boundary package. Generic capability
alone does not admit any missing site evidence.

## 6. P2H benchmark evidence requirements

### Interval semantics

`s14.benchmark_interval_semantics` depends on the P2G meter engineering/measurement
basis, particularly `s13.revenue_meter_measurement_semantics`. P2H cannot bypass
that prerequisite. Supply measurement quantity, snapshot versus interval-average
semantics, interval duration, timestamp position (instant/start/midpoint/end),
timezone, source cadence, historical applicability and the exact relationship
between the measured interval and expected-power support.

Canonical S14B owns `interval_average_ending_at_timestamp` only when explicitly
admitted by measurement authority. Hour-looking timestamps, CSV spacing, register
progression, SCADA conventions or migration code do not establish Bracon's
semantics. The [P2G migration-data decision](site-ac-network-meter-admission.md)
remains unchanged: migration rows are not meter engineering authority.

### Expected support-gap policy

Target contract:
`explicit_revenue_meter_interval_expected_support_maximum_gap_policy_v1`.
Supply explicit positive `maximum_expected_sample_gap_seconds`, policy scope,
parameter source, categorical confidence, method reference and applicability.
Admitted evidence kinds are `validated_sampling_sensitivity_study`,
`explicit_model_cadence_requirement`, `commissioning_validation_study` and
`other_explicit`.

No threshold is supplied here. Do not derive one from nominal/median/observed CSV
cadence, meter interval duration, a fraction of that interval or current model
sampling frequency without an explicit reviewed study/requirement supporting the
exact limit. There is no universal default. Support eligibility is distinct from
numerical reconstruction and quantitative uncertainty.

## 7. Measurement uncertainty requirements

Target contract:
`explicit_revenue_meter_complete_measurement_chain_quantitative_uncertainty_authority_v1`.
Supply an already-combined complete meter/CT/PT/scaling/calibration-chain maximum
symmetric bound at the primary-engineering-unit meter boundary, for at least one
P/Q channel, using explicit relative and/or absolute terms. Relative reference:
`absolute_same_channel_measured_power_in_primary_engineering_units`.

Retain measurement time scope, evidence kind, source, confidence, method,
applicability and explicit valid-from/to where applicable. Optional meter/CT/VT/PT
accuracy descriptions, scaling specifications and calibration references are
provenance. Snapshot validity covers its timestamp; interval-average validity
must cover the complete represented interval when boundaries are supplied,
consistent with the existing contract. No dates are extracted from prose.

Categorical confidence, accuracy-class strings, quality flags, residuals,
historical variance and legacy loss percentages do not manufacture a bound.
Specifications on another reference basis require an explicit external conversion
to a compatible complete-chain bound, with retained provenance. The engine does
not recombine internal components, infer coefficients from calibration metadata,
use RSS or assume statistical independence.

## 8. Expected-model uncertainty requirements

Target contract:
`explicit_complete_expected_model_chain_quantitative_uncertainty_authority_v1`.
Required chain scope:
`complete_expected_model_chain_at_canonical_s13c_revenue_meter_boundary_pq`.
Relative reference:
`absolute_same_channel_expected_power_in_primary_engineering_units`.
Pointwise time semantics:
`instantaneous_steady_state_solution_at_exact_timestamp`.

Supply an already-combined complete expected-model-chain P/Q bound, explicit
relative/absolute terms and channel coverage, validated model/study/version,
method/study reference, operating domain, meter boundary, source, confidence,
applicability and validity period. Nameplate tolerance, categorical confidence,
legacy losses, individual component uncertainties without an externally reviewed
complete-chain budget, historical benchmark errors or measured-minus-expected
residuals are not this authority. The same residual must never manufacture the
envelope against which it is interpreted.

The generic stack is already complete and unchanged: support policy → S14B
benchmark → measurement bounds (PR #124) and pointwise model bounds (#125) → exact
S14B interval propagation (#126) → combined bounds (#127) → eligible deterministic
envelope interpretation (#128). No new mathematics, numerical coefficient or
threshold is implemented. Existing propagation is through the exact discrete
S14B functional, not sparse-support error or continuous-truth uncertainty.
Combined magnitudes do not override support eligibility, and interpretation still
requires an eligible benchmark. No probability, statistical significance, RSS,
covariance or independence assumption is introduced.

## 9. P3 entry rule

For a validated manifest, the baseline evidence gate is exactly:

```python
p3_entry_evidence_ready = all(
    not section.blocking_requirement_ids
    for section in manifest.path_coverage
)
```

Equivalently, every mandatory-for-any-physical-path requirement must be admitted
or explicitly not applicable. Full fidelity is independent:

```python
full_fidelity_ready = all(
    not section.full_fidelity_blocking_requirement_ids
    for section in manifest.path_coverage
)
```

Both booleans are currently false. A valid, explicit lower-fidelity path may
satisfy baseline entry without satisfying full fidelity; full fidelity is not a
universal prerequisite for P3 engineering. N/A requires its existing explicit
applicability evidence and must never hide a missing input.

When the baseline union reaches zero, the status is **eligible to begin P3
shadow-execution engineering**, not production activation or physical-model
validation. P3 still needs implementation, source wiring, validation and an
explicit activation decision. No production readiness engine is added here.

## 10. Future evidence update workflow

No P2I, P2J or P2K is planned, and no additional P2 letter will be created merely
because evidence arrives. Update existing packages in place:

| Evidence supplied | Stable review/admission owner |
| --- | --- |
| Weather/irradiance/thermal timing, quantity or model evidence | [P2E](site-upstream-physical-input-admission.md) |
| Population, string/MPPT drawings, inverter or controller evidence | [P2F](site-dc-inverter-control-admission.md) |
| SLD, LV/transformer/MV-HV/meter evidence | [P2G](site-ac-network-meter-admission.md) |
| Benchmark policy or complete-chain uncertainty studies | P2H, this closure package |

Change the manifest only after genuine reviewed admission, preserve exclusions
and provenance, then rerun the same closure rule and ownership checks. The next
engineering action is acquisition/admission of outstanding evidence within
P2E–P2H. P3 begins only when the mandatory baseline blocker union reaches zero.

The exact-intended-main manually dispatched full backend regression remains
required before P3 activation/release, per the
[validation cadence](../validation/physics-validation-strategy.md#ci-validation-cadence).
An older nightly does not validate later commits. P2 closure while P3 is blocked
requires neither a local full suite nor a manual full-workflow dispatch; neither
is run by this increment.

## 11. What P2 completion does not mean

Review completion does not establish missing site evidence, physical admission,
any timestamped operating solution, successful physical output, benchmark
eligibility, causal loss, commercial impact, production cutover or shadow
activation. Population 49,824 / 47,448 / 50,736 remains conflicting and
`electrical_topology` remains None. The Bracon manifest, all six admissions,
physics, the #124–#128 uncertainty stack, runtime and production source are
unchanged. P3 entry remains BLOCKED and execution INACTIVE.
