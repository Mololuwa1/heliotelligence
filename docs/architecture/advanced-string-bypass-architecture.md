# Advanced S8 string-member and bypass architecture

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

Only the topology authority is implemented here. No second DC collection, MPPT
or inverter chain is introduced. Future advanced I-V output must meet the same
physical `string_terminal` boundary before any existing branch transformation.

## Bounded implementation sequence

| Increment | Responsibility | Current status |
| --- | --- | --- |
| Stage4a-1 | Member / bypass-protected-section topology authority | Implemented by this increment, dormant |
| Stage4a-2 | Section electrical authority + reverse-bias I-V | Pending |
| Stage4a-3 | Common-current section/module/string composition + diode clamp | Pending |
| Stage4a-4 | Multi-peak identification and advanced candidate/global operating handoff | Pending |
| Stage4a-5 | Optical/shading-state → section binding, string-class optimisation and Method-B validation | Pending |

Stage 4a is not complete. In particular, A-06 reverse-bias/composition and A-07
multi-peak/global selection remain pending in the
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
