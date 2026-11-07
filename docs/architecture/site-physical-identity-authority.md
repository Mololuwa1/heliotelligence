# Reviewed physical site identity authority

P2B establishes the first narrow site authority after the P2A inventory. It binds
one reviewed application identity to a configured geographic anchor. It does not
execute a physical model or establish downstream physical evidence.

```text
P2A inventory
↓
reviewed site identity authority
↓
site.identity.physical admitted
↓
remaining P2 evidence / authority bindings
```

The implementation is
[site_physical_identity_authority.py](../../src/heliotelligence/engine/site_physical_identity_authority.py).
Its fixed identifiers are:

```text
contract: explicit_reviewed_physical_site_identity_authority_v1
model: reviewed_site_config_identity_and_geographic_anchor_binding_v1
scope: site_identity_binding_before_site_specific_physical_authority_admission
coverage_scope: single_site_identity_name_uuid_timezone_and_configured_geographic_anchor_only
```

## Reviewed Bracon declaration

The separately reviewed declaration is
[evidence/authorities/bracon-ash/site-identity.yaml](../../evidence/authorities/bracon-ash/site-identity.yaml).
It records:

| Field | Value |
| --- | --- |
| Configuration identity | `site-001` |
| Canonical site UUID | `5ab83b40-553c-5ddd-976f-71f6cb5d490f` |
| Name | `Bracon Ash` |
| Configured latitude / longitude | `52.56` / `1.21` degrees |
| Timezone | `Europe/London` |
| Authority version | `bracon-ash-physical-site-identity-v1` |
| Source evidence | `config/sites.yaml` |
| Authority reference | `evidence/authorities/bracon-ash/site-identity.yaml` |
| Confidence | `unknown` |

Configuration supplies source evidence; its presence does not self-admit. The
checked-in, reviewed authority declaration is the separate binding decision. It
states only: this reviewed Heliotelligence identity corresponds to the configured
Bracon Ash site record and geographic anchor. No external survey, commissioning,
legal/title or ownership evidence is invented.

## Exact immutable admission

`SitePhysicalIdentityAuthority` is a frozen record containing only site ID, UUID,
name, configured coordinates, timezone, explicit version/reference, immutable
source references, categorical confidence and fixed contract semantics. UUID must
use canonical string form and agree with the application's existing
`uuid5(NAMESPACE_DNS, site_config_id)` mapping. No default site/name or UUID is
inferred. The engine type is generic; the reviewed Bracon values are declared in
the authority file, not hard-coded as a universal site.

Identifiers are exact non-empty unpadded strings. Coordinates are finite,
non-Boolean real values within inclusive latitude/longitude bounds, stored as
finite floats. Timezone identity is checked against the timezone database with
exact spelling/case and retained without normalization. References are non-empty,
unique immutable tuples in caller order. Confidence is provenance only and does
not strengthen physical scope or manufacture numerical uncertainty.

The geographic anchor is not a surveyed legal/cadastral boundary or replacement
for module geometry. The schema deliberately excludes capacity, module/string/
table counts, equipment models/inventory, geometry completeness, electrical
connectivity, grid/export limits, cables, transformer/meter identities and loss
percentages. Capacity remains an inventory fact only; it is not consumed by this
authority or used to reconcile module population.

## Loading, serialization and binding

`load_site_physical_identity_authority(path)` reads only the explicitly supplied
UTF-8 YAML file using a safe duplicate-key-rejecting loader. Exact schema and
contract/model/scope/coverage identifiers are mandatory. Unknown, missing,
malformed or excluded fields fail admission. The loader does not read source
files, discover sibling authorities, query services, inspect environment settings
or generate a declaration from SiteConfig.

JSON-safe serialization retains all identity/provenance fields and ordered source
arrays. Deserialization revalidates the schema, coordinates, timezone, UUID and
fixed semantics. The independent validator checks frozen objects without calling
constructors, production admission helpers, loaders or serialization helpers.
Frozen-field tampering cannot bypass the binding/serialization admission checks.

This format is not a signature or cryptographic authentication. A structurally
valid changed declaration must still be checked against its independent parents.
For example, changing a source reference to another valid string is rejected at
site admission if the manifest does not declare that source; changing a valid
coordinate/name/timezone is rejected when it differs from the SiteConfig anchor.
Do not treat standalone structural validation as approval of edited evidence.

`validate_site_physical_identity_binding(manifest, authority, site_config)`
validates the two immutable contracts and requires exact agreement on:

- Manifest and authority site configuration ID, UUID and name.
- Authority and SiteConfig identity, configured coordinates and timezone.
- The exact `site.identity.physical` requirement and its same-site scope.
- Manifest source coverage of the authority's evidence references.
- For admitted identity: this contract ID, exact authority-file reference, full
  support for the identity requirement and static temporal scope.

There is no numerical tolerance or timezone/name normalization. A proposed
present/not-admitted item can be checked without changing it; validation does not
perform admission or write either file. The current committed manifest carries
the explicit reviewed decision. No capacity, module/inverter inventory, layout or
electrical topology is inspected by binding validation.

## P2A history and current P2B coverage

The original P2A baseline had zero admitted requirements: 17 present/not admitted,
48 missing/blocked and one conflicting/blocked. All nine path sections were
blocked. That historical baseline is not rewritten as an identity admission.

The [current Bracon manifest](../../evidence/sites/bracon-ash.yaml) version is
`bracon-ash-site-identity-admitted-v2`. Only `site.identity.physical` is admitted;
its five original inventory source facts remain, including the unconsumed capacity
fact. All other 65 items retain their exact reviewed P2A state/provenance/fidelity.

| Partition | Current counts |
| --- | --- |
| Evidence: present / missing / conflicting / N/A | `17 / 48 / 1 / 0` |
| Admission: admitted / not admitted / blocked / N/A | `1 / 16 / 49 / 0` |
| Active support: full / lower / non-resolving / N/A | `1 / 0 / 65 / 0` |

Because identity is mandatory across all nine sections, their baseline and
full-fidelity labels now read `partially_admitted`. Each still publishes required
blocking IDs and none is fully admitted. This records one cross-cutting identity
prerequisite, not substantive downstream physics readiness. No module, weather,
thermal, inverter/controller, DC/LV/transformer/MV-HV, meter, benchmark policy or
uncertainty authority is admitted by this change.

The 49,824 / 47,448 / 50,736 population representations remain conflicting/blocked,
with no winner. `SiteConfig.electrical_topology` remains `None`; layout groups
remain spatial/application metadata and no inverter/MPPT/string assignments are
inferred. The generated [Bracon matrix](../sites/bracon-ash.md#p2a-controlled-evidence-baseline)
remains a projection of the current manifest, not a second authority table.

The [implementation-delta ledger](physics-implementation-delta.md) Priority A
sub-string/bypass and Priority B cable/conductor derivation remain pending. Identity
provides no evidence for either. Full P2 remains in progress; P3 is inactive. No
P1 output/run/source, writer, runtime adapter, public evidence API, database change
or production source selection is introduced.
