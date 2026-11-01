# P1 physical shadow-output contract

## Purpose and readiness

P1 defines an immutable execution/output boundary around the dormant physical
contracts. It does not execute physics or select an expected-energy source. The
implementation is [physical_shadow_output_contract.py](../../src/heliotelligence/engine/physical_shadow_output_contract.py),
with contract `canonical_physical_shadow_run_output_contract_v1` and scope
`timestamped_site_model_boundary_physical_output_before_shadow_execution_or_production_selection`.

Starting checkpoint: PR #129 merge `f7fbfd177e234becff78b7748576d583bc494e9d`;
main CI #331 passed both full backend and frontend validation on that SHA.

- P0 source isolation — complete.
- Generic physical contracts — complete/dormant.
- Generic revenue-meter uncertainty stack — complete/dormant.
- Platform authorization — complete.
- P1 physical shadow-output contract — implemented by this increment.
- P2 site evidence — still pending.
- P3 shadow execution — not activated.

P1 introduces no database migration, writer, API, scheduler job, runtime adapter or
physical model-source name. Production continues using the legacy `physics_sdm`
path. Bracon Ash receives no new physical-evidence admission.

## Identity and boundaries

`PhysicalShadowRunIdentity` requires caller-supplied canonical lowercase,
hyphenated UUID strings for run and site. Site slugs are not site UUIDs. Exact
non-empty unpadded strings identify model source, model version and code revision.
Code revision need not be a Git SHA; construction does not inspect Git or create
an ID. Source uses existing exact expected-energy source admission, additionally
rejecting reserved legacy `physics_sdm`. P3 will choose/configure a real source.

Source identifies a model series. It does not identify its version, reference
plane, boundary, fidelity or resolved state. Each output supplies its own exact
`reference_plane` and `boundary_id`. Plane vocabulary is deliberately open to
canonical upstream and future boundaries; nothing infers or normalises a plane.
A run can resolve at inverter AC output while its intended revenue-meter output
remains unresolved. These must be separate records.

## Snapshot and electrical state

P1 v1 means `instantaneous_physical_model_state`. The timestamp must be an exact,
aware, non-NaT `pandas.Timestamp`, representable in UTC nanoseconds. There is no
interval, bucket, cadence, nearest measurement, rounding or implicit timezone.
The persistence format supports named IANA timezones and explicit fixed offsets;
an unrepresentable timezone identity is rejected rather than silently lost.
S14B continues to own interval reconstruction.

Each P/Q channel has an exact Boolean resolution flag. Resolved values are finite,
non-Boolean real numbers admitted to finite Python floating-point engineering
units. Units are fixed: active W, reactive var, apparent VA. Zero and signed power
are valid. An unresolved channel requires `None` and one or more reason codes;
zero and NaN cannot stand in for missing physics. P and Q resolve independently.

Overall state is derived: both resolved → `resolved_physical_output`; one resolved
→ `partial_physical_output`; neither → `unresolved_physical_output`. Apparent
power is derived by `hypot(P, Q)` only when both resolve; nonfinite apparent power
is rejected. Otherwise apparent power is `None`. Neither derived field is a
caller argument.

Active/reactive sign conventions and power basis are exact explicit strings.
Representative S13A/S13C meter semantics are `revenue_meter_boundary`,
`positive_plant_to_grid` for P/Q and `three_phase_total`. The downstream Q
convention is positive injection, negative absorption. Source evidence using a
different convention must be transformed before canonical authority construction.
This documentation does not close the S9-4A sign-evidence gate.

## Fidelity, reasons and provenance

Fidelity is independent of channel resolution:

| Class | Required fidelity ID | Constraints |
| --- | --- | --- |
| `full_declared_physical_path` | Explicit non-empty ID | No fallback |
| `explicit_lower_fidelity_physical_path` | Explicit non-empty ID | Underlying physics must independently permit the path |
| `unresolved_physical_path` | `None` | Neither P nor Q may resolve |

An exact Boolean `fallback_applied=True` requires explicit lower fidelity and a
non-empty `fallback_id`. False requires `fallback_id=None`. A fallback ID cannot
be the reserved legacy source. P1 carries existing S12M fidelity IDs, such as
`coupled_advanced_load_loss` and `coupled_s12g_load_loss_fallback`, unchanged. It
does not create fallback physics, switch boundaries or read a legacy value.

Separate P/Q reason-code tuples contain exact non-empty unpadded strings, with
no duplicates. A resolved channel has an empty reason tuple. Supplied tuple order
is retained deterministically, including upstream provenance order; P1 neither
sorts away that information nor diagnoses the cause. Unresolved is not zero
generation or equipment fault.

`PhysicalShadowOutputProvenance` contains immutable tuples of upstream contract
IDs, upstream model IDs and available authority/evidence IDs. Any resolved channel
requires both contract and model provenance. Evidence IDs may be empty; P1 does
not manufacture them. Producers remain responsible for the truth and applicability
of their provenance. P1 does not certify site authority by accepting a string.

## Collections, validation and persistence

`PhysicalShadowOutputBatch` contains an ordered immutable tuple of records. A
batch can include multiple runs, but one run UUID cannot describe conflicting
site/source/version/revision identities. The unique physical output key is
`(run_id, timestamp instant, reference_plane, boundary_id)`; an equivalent instant
expressed in another timezone cannot evade duplicate detection.

Frozen diagnostics count total, resolved/partial/unresolved, full/lower/unresolved
fidelity, fallback and sorted per-plane counts. State and fidelity partitions each
close to the record count. They are coverage diagnostics, not a score.

Pure per-record serialization returns a deterministic JSON-safe mapping. It writes
`timestamp_utc_ns`, a `timestamp_timezone` descriptor (IANA name or explicit
fixed-offset name/seconds), and a redundant exact local ISO/timezone identity.
This preserves nanoseconds, the physical instant, original zone identity and DST
fold. Inconsistent timezone/instant fields fail admission. It is not a signature
or protection against consistent malicious replacement of an entire record.

Immutable tuples become JSON arrays in their original order. Deserialization
requires the exact schema and array shapes, reconstructs frozen objects and
re-runs admission. Stored units, timestamp semantics, apparent power, state,
contract and scope must exactly match canonical derivation. Unknown/missing
fields, contradictions, invalid provenance and injected legacy sources fail
closed. Batches can persist ordered serialized records and reconstruct diagnostics;
stored diagnostics are never an input to batch construction.

Independent record/batch validators reconstruct invariants and diagnostics
without calling constructors or production admission/serialization helpers.
Tests disable those helpers, tamper public fields and nested frozen objects, and
prove JSON serialization/deserialization round-trips including London DST folds.

## Future expected-energy projection gate

`expected_energy` retains its `(time, site_id, source)` identity and legacy column
semantics. This contract is not that table's generic physical schema.

A later P3 projection may write an alternative model series only when the
required production channel resolves at the explicitly intended expected-energy
reference plane and boundary. An upstream resolved output is not a resolved
revenue-meter output. In particular, upstream inverter/LV/transformer power must
never be inserted into `expected_energy.p_ac_kw` while represented as meter-plane
expected power. Units and projection semantics need explicit admission then.
Unresolved rows must remain retained as unresolved; they must never become
`p_ac_kw=0` for storage convenience.

P1 computes no losses and adds no compatibility percentages. It never reads
`physics_sdm` to repair a physical result. P2 evidence and the remaining readiness
gates must close before P3 persistence/execution. See the
[production-integration roadmap](../development/production-integration-roadmap.md).
