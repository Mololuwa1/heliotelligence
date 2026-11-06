# P2A site evidence manifest

P2A inventories controlled site evidence before physics authority construction or
execution. Contract: `canonical_site_physical_evidence_manifest_v1`. Scope:
`site_specific_physical_evidence_inventory_and_authority_readiness_before_shadow_execution`.
The [implementation](../../src/heliotelligence/engine/site_evidence_manifest.py)
contains the single reviewed, versioned 66-requirement catalogue.

Starting checkpoint: PR #130 merge `1237d05172d774f3a28ecfa0037363e205a01c3f`.
Main CI #333 succeeded, including the full backend suite and frontend, before
branch creation. P1's output contract is complete. P2A establishes the inventory
and baseline; full P2 admission remains in progress and P3 is not active.

## Evidence, configuration and admission

Keep these distinct:

```text
code capability ≠ site evidence ≠ authority admission ≠ resolved timestamp
                ≠ physical output ≠ production activation
```

Configuration is not authority. Geometry is not electrical topology. Telemetry
presence is not measurement semantics. Generic capability is not site admission.
Missing repository/onboarding evidence does not prove that external evidence does
not exist. Conflicting evidence stays blocked until a reviewed authoritative
resolution is supplied; no count or confidence label selects a winner.

The top-level `evidence/sites/` directory separates reviewed evidence inventories
from compatibility/application `config/sites.yaml`. The initial file is
[Bracon Ash's manifest](../../evidence/sites/bracon-ash.yaml). It is explicitly
declared data, not a scanner or an input to the active runtime. Repository paths
identify source material; their presence is never an admission rule.

`SiteEvidenceManifestIdentity` requires exact unpadded configuration ID, explicit
version and site name. Its canonical UUID must equal the existing application
mapping `uuid5(NAMESPACE_DNS, site.id)`. Both the YAML declaration and optional
`validate_manifest_against_site_config` check detect identity drift; neither
silently repairs it or binds configuration parameters to physics authority.

## Items and relationship rules

Each immutable item has a catalogue requirement ID, bounded domain and exact stage
references. These identify evidence decisions rather than UI pages or new stages.
Source references, reference planes, authority IDs and gap codes are immutable,
unique tuples of exact non-empty unpadded strings. Explicit tuple order is
preserved. Notes explain the decision; gap codes retain machine-readable meaning.
Transcribed `SiteEvidenceFact` records retain separate source facts without
choosing physics parameters. Facts must identify a declared item source.

| Evidence | Admission | Meaning |
| --- | --- | --- |
| present | not_admitted | Identified material exists; no admitted canonical binding |
| present | admitted | Explicit reviewed binding and admitted authority IDs, with physical support |
| missing | blocked | Current package has no sufficient supplied evidence |
| conflicting | blocked | Multiple identified representations disagree; unresolved |
| not_applicable | not_applicable | Explicit excluded applicability with a required reason |

Present evidence requires supplied sources. `external_evidence_not_supplied`
describes a required evidence class, not a claimed external document. Conflicts
require multiple identified source representations. Admission requires explicit
`admitted_authority_contract_ids`, `authority_binding_reference`, and full or lower
physical support with no unresolved gap codes. `target_authority_contract_ids`
identify future ownership only and never count as admitted. Unadmitted items
cannot carry admitted authority IDs or binding references.

Not-applicable items require paired N/A states/fidelity and an applicability
reason; they cannot claim authority IDs, targets or unresolved gaps. Reviewers
must not use N/A to hide missing evidence. Surveyed geometry alone is explicitly
rejected as electrical authority. P2A validates the inventory/binding declaration
and internal consistency; it does not execute/replay an unavailable physics
authority or certify the truth of external evidence. Actual authority construction
and admission review remain separately owned.

Confidence, where declared, is provenance only (`high/medium/low/unknown`). It
cannot override conflict, admit a missing input, or create numerical uncertainty.

## Scope, fidelity and coverage

Physical scopes identify site, asset set, zone, meter, network path or model class.
Unknown scope has no invented asset IDs. Exact identifiers are required for known
scopes; wildcard `all` is rejected. Bracon spatial groups cover surveyed geometry,
not inverter/MPPT/string/cable membership. A model label still needs physical
model/equipment binding.

Temporal scope is `static`, `bounded_interval`, `snapshot` or `unknown`. Static
and unknown have no fabricated dates. Snapshots require one exact aware non-NaT
`pandas.Timestamp`; inclusive bounded intervals require two ordered exact aware
timestamps. UTC nanoseconds, original named/fixed-offset timezone and local ISO
representation are retained during persistence. No calibration date, cadence or
validity is extracted from text. The initial Bracon applicability is unknown,
including values currently present in configuration.

Requirement levels are `mandatory_for_any_physical_path`,
`mandatory_for_full_fidelity` and `optional_advanced`. The catalogue covers site
identity/population/geometry, weather/time, irradiance/optics, thermal/module
input, S8 DC, S9 inverter, S10 requests, S11 LV, S12 transformer, S13 grid/meter,
S14 interval policy and quantitative uncertainty. It does not make every advanced
transformer correction mandatory for a valid baseline.

Evidence-level supported fidelity is full, explicit lower, non-resolving or N/A.
Only admitted items contribute active full/lower support counts. A declared
potential fidelity on blocked/unadmitted evidence does not increase readiness.
Lower fidelity still requires an independently valid canonical physical contract;
this manifest supplies no fallback model.

The nine-section static matrix publishes both baseline and full-fidelity states.
Baseline considers mandatory-any requirements; full fidelity also considers
mandatory-full requirements and requires full support on admitted mandatory items.
Optional advanced requirements do not block a valid baseline. A section is
admitted only when all its mandatory requirements are admitted or explicitly N/A;
at least one required admission with remaining gaps gives partially admitted;
otherwise it is blocked. All section items must be explicitly N/A before the
section is N/A. Each matrix row lists its exact blocking requirement IDs.
This is static evidence readiness, never a promise that every timestamp resolves.

Diagnostics partition evidence state, admission state and active support fidelity;
N/A counts close each partition. Domain counts partition the catalogue. Stage
counts overlap where one requirement affects multiple stages, so their sum need
not equal the item count. Counts are inventory diagnostics, not a readiness
percentage, maturity score or cutover decision.

## Loading, persistence and independent checks

`load_site_evidence_manifest(path)` reads only the supplied UTF-8 YAML using a
safe loader that rejects duplicate mapping keys. The exact human-authored schema
contains contract, scope, identity and every catalogue item. Unknown fields,
unreviewed IDs/vocabularies, duplicates, missing requirements and malformed nested
scopes/facts fail closed. Constructor item ordering is canonical by requirement ID.
No network, database, environment lookup, file discovery or service is involved.

Pure JSON-safe serialization includes derived diagnostics and path coverage.
Deserialization reconstructs all inputs and recomputes those derived values;
contradictory stored counts, states, schema or metadata are rejected. Frozen
records contain no mutable dictionaries. Consistently replaced valid evidence is
not cryptographically authenticated by this format; controlled review/versioning
remains necessary.

The independent validator rebuilds nested invariants, readiness and count
partitions without constructors or production admission/coverage/serialization
helpers. Tests disable those helpers, reject public/nested tampering and check
loader/schema and lossless round trips. The Bracon documentation matrix is a
projection from the manifest, with an exact drift regression rather than a second
hand-maintained authority table.

## Bracon baseline and the Digital Twin

The initial package has 17 present/not-admitted items, 48 missing/blocked items,
one conflicting/blocked item, zero admitted items and no N/A exclusions. All nine
path sections are blocked, at both baseline and full fidelity. Configuration loss
percentages, nameplate values and `u_c/u_v` admit no authority.

Population representations remain separate: 2,076 × 24 = 49,824; 659 × 72 = 47,448;
surveyed metadata = 50,736. Capacity 28,524 kWp is not reconciliation evidence.
Geometry metadata (`module-cloud reconstruction @174.47`, residual 0.436 m) is
retained only as supplied spatial evidence. The geometry API combines coordinates
and some configuration-derived counts; it is not one homogeneous authority.
See the generated matrix in the [Bracon site record](../sites/bracon-ash.md).

The eventual Digital Twin sequence is:

```text
Site Evidence Manifest
        ↓
Admitted canonical authorities
        ↓
Twin Definition + timestamped physical states
        ↓
Twin State
        ↓
UI / map / 3D projection
```

Existing 3D geometry is one evidence layer, not the complete Twin Definition.
P2A creates no P1 outputs, run IDs, model sources, adapter, migration, writer, API,
frontend response or activation. Evidence is operationally sensitive and is not
exposed through an interface here. P2 admission stays in progress; P3, production
source changes and shadow execution remain inactive.
