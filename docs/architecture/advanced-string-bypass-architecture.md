# Advanced S8 string-member and bypass architecture

Current reviewed checkpoint: PR #143 merge `8148299f632f8cb5f97ce2b9940bfb5d6aababc0`.

## Ownership and current boundary

Stage 4a from the external `Stage_4a_-_String_Aggregation_and_Bypass_Diode_Model.docx`
is a conceptual engineering reference. These bounded implementation increments
belong to **S8**, not new canonical S-stages. Stage4a-1 implements connectivity
only in [string_member_topology_authority.py](../../src/heliotelligence/physics/string_member_topology_authority.py).
It does not execute physics or select a fidelity path.

The homogeneous `homogeneous_series_module_iv_scaling_v1` and
`receiver_string_module_iv_to_physical_string_iv_v1` path remains unchanged.
So do `iv_consistent_common_voltage_physical_mismatch_v1`, direct DC branch loss
and the bounded module-population residual. Missing advanced authority leaves the
advanced path unavailable; it does not invalidate an independently valid baseline.

```text
upstream module electrical state
        ↓
advanced member / bypass-section state
        ↓
reverse-bias section I-V
        ↓
common-current member/string composition
        ↓
advanced physical string_terminal I-V
        ↓
EXISTING S8 direct DC branch transform
        ↓
EXISTING S8 common-voltage shared-MPPT solve
        ↓
EXISTING S9 inverter
```

Topology authority, isolated section Bishop I-V, explicit bypass/common-current
composition and complete piecewise-linear candidate/global analysis are implemented. No second DC collection, MPPT
or inverter chain is introduced. Future advanced I-V output must meet the same
physical `string_terminal` boundary before any existing branch transformation.

## Bounded implementation sequence

| Increment | Responsibility | Current status |
| --- | --- | --- |
| Stage4a-1 | Member / bypass-protected-section topology authority | COMPLETE, dormant |
| Stage4a-2 | Explicit reverse-breakdown authority + isolated Bishop reverse/forward section I-V | COMPLETE, dormant; PR #142 |
| Stage4a-3 | Explicit bypass-diode authority/clamp + common-current section/module/string composition | COMPLETE, dormant; PR #143 |
| Stage4a-4 | Complete piecewise-linear multi-peak candidates/global selection and canonical curve handoff | COMPLETE BY THIS PR, dormant |
| Stage4a-5 | Optical/shading-state → section binding, string-class optimisation and Method-B validation | Pending |

Stage 4a is not complete. A-06 now has explicit reverse, diode clamp and
common-current composition coverage; A-07 now has exact piecewise-linear candidate/global selection in the
[implementation-delta ledger](physics-implementation-delta.md). Geometry/shading
binding remains pending within A-05; connectivity authority is its first slice.

## Exact authority representation

Fixed identifiers:

```text
contract: explicit_string_member_bypass_section_topology_authority_v1
model: ordered_physical_module_members_and_bypass_protected_sections_v1
scope: advanced_s8_string_member_electrical_topology_before_section_iv_resolution
coverage: explicit_existing_physical_strings_with_complete_ordered_member_and_bypass_section_topology
```

Three frozen record levels carry explicit evidence:

- `StringMemberTopologyAuthority`: exact existing string ID, ordered module tuple,
  parameter source, confidence, method reference and applicability description.
- `PhysicalModuleMember`: globally unique physical module ID, `series_index`,
  opaque physical-position reference and ordered bypass-protected-section tuple.
- `BypassProtectedSection`: module-local section ID, positive exact integer
  `series_cells_per_branch` and `parallel_cell_branches`.

Module tuple order must agree exactly with **zero-based contiguous electrical
indexes 0..N-1**. The section tuple declares electrical section order; IDs do not
imply order. Section identity is `(module_id, section_id)`, so identical local
section labels in different modules are valid. A physical module ID cannot
appear twice within one string or across the supplied string authority package.

A section explicitly distinguishes one branch from several parallel cell branches
protected by one bypass diode. This can describe full-cell and half-cut designs
without assuming either arrangement. It does not declare branch-specific cell
routing or solve cell I-V. All sections, branch counts and cell counts must be
supplied; there is no default of three bypass diodes or standard module layout.

Position references are opaque evidence pointers, not coordinates. Confidence
uses `high`, `medium`, `low`, `unknown` as provenance only; it changes no counts,
connectivity or numerical behavior. All IDs/provenance are exact unpadded,
non-empty strings. Counts/indexes are exact integers; booleans are rejected.

## Binding, partial coverage and hardening

`resolve_topology_string_member_authority` accepts an existing
`ElectricalTopologyConfig` plus explicit authority keyed by physical `string_id`.
Each supplied string must exist and its module count must equal **that physical
`StringConfig.modules_per_string`**, never an aggregate site configuration value.
Neither configuration class is extended or populated by this authority.

Coverage may be partial or empty. Output contains an immutable, detached mapping
`authorities_by_string_id`, `advanced_resolved_string_ids`,
`advanced_unavailable_string_ids` and frozen diagnostics. All follow existing
inverter → MPPT → string traversal order, independent of input mapping insertion
order. Nested records are copied so later caller mutation cannot alter output.
“Resolved” here means static topology authority only, not a timestamped solution.
No dispatch or fallback is performed.

Diagnostics close exactly:

```text
topology_string_count
  = advanced_authority_string_count + advanced_unavailable_string_count
module_member_count
  = sum(explicit module members over admitted advanced strings)
bypass_protected_section_count
  = sum(explicit sections over admitted advanced module members)
```

No readiness percentage is published. The independent
`validate_topology_string_member_authority` traverses physical topology, nested
records, global module identities, ordering, provenance and diagnostics without
calling builders, constructors or admission helpers. Public resolution validates
input records and its detached output, including deliberately forged frozen state.

## Stage4a-2 — explicit reverse-breakdown authority and section I-V

The [reverse authority](../../src/heliotelligence/physics/string_section_reverse_breakdown_authority.py)
consumes the existing Stage4a-1 result, never independent SiteConfig topology.
`BypassSectionIdentity(module_id, section_id)` is the canonical immutable key;
no concatenation or string-derived identity is introduced. Partial/empty coverage
is valid. Detached immutable output retains parent traversal order, resolved and
unavailable section identities and exact diagnostics:
`topology_section_count = reverse_authority_section_count +
reverse_authority_unavailable_section_count`, plus `avalanche_enabled_section_count`.

```text
contract: explicit_bypass_section_reverse_breakdown_authority_v1
model: bishop88_explicit_section_reverse_breakdown_parameters_v1
scope: advanced_s8_section_reverse_breakdown_before_diode_clamp_and_series_composition
coverage: explicit_stage4a1_bypass_sections_with_reviewed_reverse_breakdown_parameters
```

Every supplied section requires explicit finite non-Boolean real
`breakdown_factor` in [0, 1], negative `breakdown_voltage_v` and positive
`breakdown_exponent`. None has a default. Explicit factor zero means no avalanche
term, not missing authority. Exact parameter source, categorical confidence,
method reference and applicability are retained. Confidence changes no numerical
result. The independent validator checks all reconstructible parent invariants,
section identities, parameters, fixed metadata, order, partitions and counts
without constructors or admission builders. Stage4a-1 remains responsible for
its original physical StringConfig count binding; no substitute topology is built.
Validation is not cryptographic evidence authentication.

The [section kernel](../../src/heliotelligence/physics/string_section_reverse_iv.py)
requires an explicit frozen `SectionSingleDiodeOperatingState`: state reference,
effective irradiance, cell temperature, photocurrent, saturation current, series
resistance, shunt resistance and nNsVth. These are already-resolved **section**
parameters. Irradiance and temperature are context, not inputs to a new parameter
fit or photocurrent calculation. No module Rs/Rsh/nNsVth is divided by section
count, and module IL/I0 is not copied into sections. Connectivity cell/branch
counts alone cannot justify a transformation from an aggregate fitted module SDM,
especially for half-cut/parallel branches. A later reviewed binding owns that work.

```text
contract: bypass_section_single_diode_reverse_iv_v1
model: pvlib_bishop88_explicit_reverse_breakdown_section_iv_v1
scope: advanced_s8_bypass_section_iv_before_bypass_diode_clamp
```

The kernel calls pinned **pvlib 0.15.2** public `bishop88` and
`bishop88_v_from_i`, not copied equations or existing forward-only electrical
helpers. Open circuit uses the same explicit parameters and Newton method,
required by pvlib for nonzero breakdown. Newton tolerance is 1e-10 V with up to
100 iterations. A returned endpoint must have current magnitude no greater than
1e-8 A + 1e-9 × photocurrent; this is numerical acceptance, not evidence uncertainty.
Solver errors, nonfinite curves and failed endpoint checks raise contextual
errors containing section identity and state reference. No zero/forward-only or
alternate-model fallback exists.

The explicit breakdown voltage belongs to this **section-equivalent Bishop
element**. It is not multiplied by cell count or divided from a module value.
The fixed `REVERSE_BREAKDOWN_GRID_GUARD_FRACTION = 0.99` samples minimum diode
voltage at 0.99 × the negative breakdown voltage (for example -14.85 V for -15 V).
This guard is numerical sampling, not site evidence or a physical diode parameter.
The singular breakdown boundary is never sampled. The deterministic grid has
exact requested length (exact integer >= 3, default 401): the first half of
intervals runs from the guard to exact diode voltage zero, then the remaining
intervals run to Bishop open circuit. A zero-photocurrent state has a degenerate
zero forward endpoint; no fictitious illuminated forward region is created.
Grid density is numerical resolution, not an evidence fidelity claim.

Output is a fresh owned DataFrame plus detached immutable state/authority metadata,
including both layers' contract IDs and exact source parameters. Columns are
`curve_point`, `diode_voltage_v`, `voltage_v`, `current_a`, `power_w`, `reverse_bias`.
Power is exactly terminal voltage × current. Negative terminal voltage and power
are physically valid here and remain unclipped. `reverse_bias` means strictly
**diode_voltage_v < 0**; it is not terminal-voltage sign or bypass conduction.
No bypass forward voltage or `max(V, -Vf)` clamp exists in the Stage4a-2 kernel. Stage4a-3 owns explicit
diode authority/clamping and common-current composition; no module/string curve
or MPPT candidate is produced by Stage4a-2.

Coverage explicitly fixes `d2mutau = 0`, `NsVbi = infinity`: no PVsyst thin-film
recombination term. CdTe/a-Si recombination would need a separately reviewed
extension; this kernel makes no universal-technology claim. Test-only Bishop
fixtures such as factor 0.002, voltage -15 V and exponent 3 are numerical references,
never site defaults or inferred JKM570 evidence.

## Stage4a-3 — explicit diode and common-current series composition

The [diode authority](../../src/heliotelligence/physics/string_section_bypass_diode_authority.py)
requires a positive finite non-Boolean forward-voltage magnitude, exact canonical
`BypassSectionIdentity`, source, confidence, method and applicability. There is no
universal forward voltage or inference from technology, counts or breakdown data.
Partial/empty diode coverage is explicit, ordered and immutable. Its independent
validator inspects frozen fields, identities, parent coverage and closing counts.
Binding takes both canonical parent results: Stage4a-1 topology plus Stage4a-2
reverse authority. The existing public Stage4a-2 validator verifies their integrity;
reverse evidence may be empty, and diode coverage may include sections whose
reverse evidence is unavailable. This reuses parent validation without rebuilding
configuration or weakening either earlier contract.

```text
contract: explicit_bypass_section_diode_authority_v1
model: constant_forward_voltage_bypass_diode_v1
scope: advanced_s8_section_bypass_diode_before_common_current_composition
coverage: explicit_stage4a1_bypass_sections_with_reviewed_diode_forward_voltage
```

The [isolated clamp](../../src/heliotelligence/physics/string_section_bypass_clamp.py)
uses public pinned Bishop `bishop88_i_from_v(-Vf)` with the explicit Stage4a-2
state/parameters and Newton solving to obtain the PV-branch transition current.
It verifies the inverse using public `bishop88`; no equations are copied.
For imposed current below transition, `bishop88_v_from_i` supplies the raw PV
terminal voltage. At transition the terminal is exactly `-Vf`, with zero bypass
current and bypass-active false. Above transition it remains exactly `-Vf`:
PV-branch current is the transition current, and bypass current is imposed current
minus that PV current. Thus the current split closes by construction, up to
floating-point addition roundoff. Bypass-active means strictly positive excess
current, not negative voltage or Stage4a-2 reverse bias.

The unconstrained PV voltage at *excess imposed current* is deliberately not
solved: it is `NaN`, with `raw_voltage_evaluated = false` and
`raw_voltage_state = not_evaluated_bypass_active`. This is explicit audit
unavailability, not a numerical fallback or zero. Such a solve is unnecessary
for the parallel diode/PV circuit and may leave the required Bishop domain.
The actual PV-branch voltage/current remain finite and published at the clamp.
Below transition the raw PV voltage remains separately available. Stage4a-2's
unclamped reverse curves and negative powers remain unchanged.

The clamp verifies transition and non-bypassed solutions in the valid Bishop
diode-voltage domain. Numerical acceptance uses 1e-8 A + 1e-9 × max(1 A,
transition current), and 1e-8 V + 1e-9 × Vf; only boundary roundoff within this
voltage tolerance may be raised to `-Vf` on the non-bypassed branch. These are
solver checks, not physical uncertainty/evidence coefficients. Solver failures,
nonfinite values and invalid domains raise contextual errors; no fallback exists.

```text
contract: explicit_bypass_section_common_current_clamp_v1
model: bishop88_transition_and_constant_forward_voltage_ideal_bypass_clamp_v1
scope: advanced_s8_section_terminal_response_before_series_composition
coverage: explicit_section_sdm_reverse_breakdown_and_bypass_diode_authority
```

The [composer](../../src/heliotelligence/physics/string_common_current_composition.py)
accepts an exact non-empty tuple of finite non-Boolean, nonnegative, strictly
increasing common-current samples. It rejects duplicates/reversal; it never sorts,
adds samples, refines a sweep, interpolates onto a search grid or selects peaks.
This is caller-controlled deterministic numerical evaluation, not Stage4a-4.
The grid evaluates each string independently; it neither connects strings nor
sums their currents.

Every composed string requires complete topology, operating state, reverse
breakdown and diode evidence for **every** owned section. Missing one item
withholds the entire advanced string and publishes the missing section identities
and evidence kinds. No baseline/advanced hybrid, copied neighbor, dropped section
or inferred parameter is allowed. Explicit invalid inputs fail closed; numerical
failure raises instead of being relabelled missing evidence. The independent
homogeneous S8 path remains valid but is not dispatched by this composer.

Each current is imposed identically across all sections. `math.fsum` in physical
order gives each module's section-voltage sum, then each string's module-voltage
sum. Power is string voltage × common current. Section audit rows retain module
series index, section index, position reference, current, raw-voltage availability,
PV/bypass currents, terminal voltage, transition and Vf. Owned module/string frames
and detached frozen topology/state/authority snapshots permit reconstruction.
Mapping insertion order cannot change physical order. Repeated results share no
mutable frames or caller provenance records.

Stage4a-1-unavailable strings have a separate ordered partition: the parent does
not retain their interleaving with advanced candidates, so no order is invented.
Candidate resolved/unavailable partitions retain parent candidate order.
Diagnostics close topology = candidate + topology-unavailable, candidate =
composed + unavailable-candidate, and section/module/string sample counts.
No maturity percentage is produced.

```text
contract: explicit_topology_common_current_section_module_string_iv_v1
model: ordered_series_voltage_sum_with_explicit_section_bypass_clamps_v1
scope: advanced_s8_physical_string_terminal_iv_before_dc_branch_and_mppt
coverage: complete_per_string_section_sdm_reverse_breakdown_and_bypass_diode_authority
reference plane: string_terminal
```

Output curves retain caller current order and may include negative terminal
voltage/power. They describe the existing physical `string_terminal` plane;
no downstream adapter, branch loss, MPPT solve or S9 execution is invoked.
Stage4a-4 owns the explicit piecewise-linear candidate/global handoff. Stage4a-5 will own
optical mapping/optimisation and validated Method B. No diode failure/degradation
state, module-parameter splitting, cell-voltage scaling or site authority is added.

## Stage4a-4 — complete piecewise-linear candidates and global handoff

The [canonical S8 electrical owner](../../src/heliotelligence/physics/electrical.py)
now publishes `calculate_common_voltage_mppt_candidates`. The existing
`calculate_common_voltage_mppt` and the audit API delegate to the same complete
vectorized numerical candidate core; the selected-point schema is unchanged.
Only explicit audit requests materialize full candidate tables, avoiding overhead
in deeply replayed downstream parents. The exact guarantee is **all local candidates and the global maximum
over the admitted piecewise-linear I-V representation**, not an analytical
maximum of continuous Bishop physics. Curve resolution remains a modelling
choice; it is not hidden evidence uncertainty.

For each interval, `I(V) = aV + b`, so `P(V) = aV² + bV`. Its maximum must be at
an interval boundary or a strictly interior stationary point `V* = -b/(2a)`
when `a < 0`. The solver enumerates both, without a dense-grid heuristic or
optimiser. Machine-unrepresentable nonconstant interval slopes (overflow or
subnormal/underflow) fail closed rather than being treated as flat; this is a
numerical-range check, not a site evidence threshold. Parallel strings use the
sorted union of breakpoints inside the
unchanged `0 <= V <= min(sampled Voc)` overlap, sum interpolated currents using
`math.fsum`, and apply this same quadratic logic. There is no extrapolation,
blocking-diode model or real-device tracking behavior.

```text
contract: common_voltage_piecewise_linear_peak_candidates_v1
model: exact_piecewise_linear_current_quadratic_power_stationary_points_v1
scope: s8_common_voltage_candidate_enumeration_before_selected_mppt_operating_point
coverage: validated_nonnegative_piecewise_linear_string_iv_common_voltage_overlap
```

The audit retains timestamp, ordered candidate index, voltage/current/power,
per-input-string currents, candidate origin, supporting interval indices, local
maximum and selected-global flags, string count and interpolation/search basis.
One breakpoint voltage has one canonical row with adjacent-interval provenance;
no distinct physical input string is dropped. Every exact tied global maximum
selects its lowest voltage. Local flags are weak maxima among the complete
candidate sequence; flat zero-power endpoints are explicit degenerate candidates,
not an invented positive peak. Mixed active/night parallel inputs still require
an explicit blocking/reverse-current model and remain rejected; all-zero selected
output stays zero.

`calculate_physical_mismatch` now uses this same complete candidate owner for
each independent string in its own voltage domain, then sums their maxima.
The common/independent closure tolerance is unchanged. The independent
counterfactual is never a weaker endpoint-only optimiser. Existing
[DC collection](../../src/heliotelligence/physics/dc_collection.py) MPPT callers
inherit this through their existing call chain, without another MPPT engine.

### Advanced source validation and search completeness

The [advanced handoff](../../src/heliotelligence/physics/string_multi_peak_candidates.py)
requires explicit Stage4a-1 topology, Stage4a-2 reverse authority, Stage4a-3 diode
and operating-state inputs, the Stage4a-3 result and an exact aware snapshot
label. It replays Stage4a-3 and exact-compares every frozen field type/value,
ordered mapping, diagnostic and owned frame. It never reconstructs or infers
section physics or topology. The timestamp labels this numerical snapshot; it
creates no weather/meter temporal authority or site validity evidence.

An active string must have exact `0 A`, positive zero-current Voc, finite values,
voltage non-increasing with current (numerical check: 1e-8 V + 1e-10 × maximum
voltage magnitude), and a supplied point reaching/crossing `0 V`. Missing zero
current, missing voltage bracket or missing advanced evidence remains explicitly
unavailable with no candidates. Nonfinite, nonmonotonic or forged data fails
closed. A repeated positive voltage would make I(V) ambiguous; it is rejected
rather than silently removing physically distinct states.

All section transition currents within each complete source bracket are added
exactly to the current grid and replayed through the existing Stage4a-3 composer.
These are required physical kinks, not peak-seeking refinement. Positive-domain
transition points remain in the canonical curve. Extra negative-domain replay
points stay upstream and are excluded from the downstream nonnegative domain.
No nearest-sample approximation is used.

The represented `V = 0` boundary is interpolated inside the first positive/negative
bracket in the enriched piecewise-linear V(I). Exact zero samples are retained.
No zero crossing is extrapolated. The final curve reverses that monotonic domain
into strictly increasing voltage from zero to Voc, with explicit timestamp,
curve_point, voltage, current and power. Original Stage4a-3 negative samples remain
unchanged; detached source and transition-enriched replays remain available.
Explicit dark strings publish a resolved-zero curve and zero endpoint, not local
positive peaks. Their mixed-active behavior remains the canonical S8 rule.

```text
contract: advanced_string_terminal_multi_peak_candidates_v1
model: piecewise_linear_string_iv_complete_candidate_enumeration_v1
scope: advanced_s8_string_terminal_multi_peak_analysis_before_dc_branch_transform
coverage: complete_stage4a3_string_iv_with_search_complete_nonnegative_voltage_domain
reference plane: string_terminal
```

Each complete advanced string delegates candidate enumeration to the canonical
S8 owner. At every candidate, ordered bypass-active section identities/counts
follow exactly `candidate_current > clamp_transition_current`, never voltage sign.
The independent-string global flag refers to the represented full curve, which
remains available; it does not replace the curve with one MPP. Diagnostics close
active/zero/unavailable string counts and count inserted transitions, candidates
and local maxima, without a maturity score.

### Downstream ownership and intentional changes

The existing DC-branch owner exposes `transform_string_terminal_iv_to_mppt_input`
as a numerical curve handoff to its **existing** series-resistance transform.
It validates one aware snapshot, core I/V/P columns, the declared terminal plane
where supplied, power closure and explicit finite nonnegative resistance. It
preserves supplied metadata without manufacturing homogeneous-module tier or
irradiance tags. This primitive does not admit path evidence or create topology;
the existing typed branch/path interfaces retain their authority checks. There
is no automatic adapter or production dispatch. Tests explicitly feed an advanced
curve into this existing owner and then the existing common-voltage solver.
The advanced module itself invokes no branch, inverter or optical physics.

Endpoint-only results intentionally change when the represented power maximum
is interior. The existing analytic mismatch fixture changes from independent /
common / mismatch `18 / 14 / 4 W` to `18.125 / 15.125 / 3 W`: common voltage
1.375 V, current 11 A; the low-voltage string independently peaks at 1.125 V.
An old apparent endpoint tie at 1 V and 2 V is correctly superseded by its higher
1.5 V interior maximum. A genuinely tied multi-peak fixture still selects the
lowest voltage. Fixtures whose maximum is already a sampled boundary stay
unchanged. Strict typing additions in the touched legacy module helpers change
no De Soto/module numerical equations.

Stage4a-5, optical/geometry binding, string-class optimisation and Method B remain
pending. No tracking, control, blocking-diode or degradation model is added.
All 53 Bracon baseline blockers and P3 BLOCKED/INACTIVE status remain unchanged.

## Method A before Method B

The complete I-V method (Method A) is the reference implementation. Operating-level
Method B is not implemented here and may be introduced only after Method A exists
and deterministic validation demonstrates its approximation envelope. The source
document's annual/timestep comparison criteria are design targets, not Bracon
evidence or universal production admission policy. No comparison thresholds are
hard-coded by Stage4a-1.

## Explicit exclusions and site gates

No reverse-bias equations, Bishop evaluation, diode forward voltage, reverse
breakdown parameters, diode failure state, clamp, multi-peak solver or electrical
state is part of connectivity authority. Those electrical/equipment decisions
begin in Stage4a-2 and composition in Stage4a-3. No shadow strips, cell-row map,
orientation inference, portrait/landscape assumption, cell pitch, shaded fraction
or PVsyst electrical-table interpretation is introduced. Later optical binding
must supply its own reviewed evidence.

Bracon has no admitted member/string routing evidence. This generic capability
changes no Bracon manifest or authority artifact, reconciles no module population,
and removes none of its **53 unique baseline blockers**. P2 remains complete as
an evidence review phase; physical admission remains incomplete and P3 remains
**BLOCKED and INACTIVE**. See [P2 closure](site-p2-closure.md).

Legacy `mismatch_loss_pct`, expected-energy runtime/source selection, S9 and all
downstream physics remain unchanged. No advanced execution is activated.
