# Configured uniform lower-fidelity series-count basis

P2D admits one narrow assumption: Bracon's repository configuration declares
**24 series-connected modules per string**. It does not admit physical string
inventory or topology. The [frozen authority](../../src/heliotelligence/engine/site_string_series_count_authority.py)
and [reviewed declaration](../../evidence/authorities/bracon-ash/string-series-count.yaml)
are dormant P2 governance inputs.

```text
configured modules_per_string = 24
        ↓
reviewed lower-fidelity series-count basis
        ↓
NOT a physical string inventory
        ↓
explicit topology still required independently
```

## Authority and evidence

| Semantic | Exact value |
| --- | --- |
| Contract | `explicit_reviewed_configured_uniform_string_series_count_authority_v1` |
| Model | `configured_uniform_modules_per_string_lower_fidelity_basis_v1` |
| Scope | `configured_string_series_module_count_before_physical_string_topology_binding` |
| Coverage | `single_site_uniform_configured_modules_per_string_assumption_only` |
| Supported fidelity | `supports_explicit_lower_fidelity_path` |
| Temporal semantics | `unknown` |

The declaration binds `site-001`, canonical UUID
`5ab83b40-553c-5ddd-976f-71f6cb5d490f`, Bracon Ash and the exact integer 24.
Its sole source is [config/sites.yaml](../../config/sites.yaml). Version:
`bracon-ash-configured-string-series-count-v1`; confidence: `unknown`.
Configuration is source evidence; the separate reviewed declaration is the binding
decision. No as-built drawing, string schedule or commissioning evidence is invented.

The authority excludes string count, total module population, tables, capacity,
module model, inverter/MPPT/string IDs, membership, topology, geometry, branch
resistance and population residual. It neither persists 2076 nor performs population
arithmetic. Temporal applicability stays unknown; a static configuration file does
not establish historical installed-equipment validity.

## Admission and runtime ownership

Only `s8.string_module_count` is newly admitted in the
[manifest](../../evidence/sites/bracon-ash.yaml), at lower fidelity, under
`bracon-ash-string-series-count-lower-fidelity-admitted-v4`. The existing source facts
`configured_modules_per_string = 24` and `configured_string_count = 2076` are retained:
manifest transcription is distinct from selected authority. **2076 is unadmitted**.
Physical string IDs, members and MPPT/inverter assignments remain unknown.

Current evidence counts remain 17 present / 48 missing / 1 conflicting / 0 N/A.
Admission is 4 admitted / 13 not admitted / 49 blocked / 0 N/A. Active support is
1 full / 3 lower / 62 non-resolving / 0 N/A. S8 baseline blockers reduce 8 → 7;
full-fidelity blockers stay 9 because this lower-fidelity basis does not satisfy
full fidelity. Every other section's coverage is unchanged. All sections remain
partially admitted with blockers. Existing P2B/P2C authorities are unchanged.

Canonical S8 still requires an explicit `StringConfig.modules_per_string` for each
physical string. P2D creates no `StringConfig` or topology. The reviewed value may
only be consumed later when an independently admitted topology/binding contract
explicitly permits this lower-fidelity uniform assumption. No automatic fan-out
from aggregate configuration is introduced.

The population conflict **49,824 / 47,448 / 50,736** remains blocked. No total is
selected; configured capacity supplies no reconciliation. Bracon's
`electrical_topology` remains `None`. Electrical mapping, inventory, MPPT/string
mapping, resistance and population-residual evidence remain independently unadmitted.

## Validation and persistence

The supplied-path UTF-8 safe YAML loader rejects duplicate keys, unknown/missing
fields and contradictory fixed semantics. Pure deterministic JSON-safe
serialization preserves all fields; deserialization revalidates them. Exact
positive integers are required, excluding booleans, floats, strings and nonfinite
placeholders. No maximum count is invented. Source references must be the exact
immutable singleton tuple identifying `config/sites.yaml`.

An independent validator audits every frozen field without constructors, loader,
wire or binding helpers. This is structural validation, not a cryptographic
signature: valid-shaped changes also require the separately reviewed source binding.

`validate_site_string_series_count_binding` checks manifest/authority/config
identity and only the configured per-string series count. It requires the exact
admitted requirement, authority ID/reference, lower fidelity, unknown temporal
scope and site scope. Guarded tests permit config access only to `id`, `name`,
`module` and `module.modules_per_string`; changes to string count or capacity do
not affect binding. No population, model, loss, thermal, geometry, inverter or
physical topology field is consumed.

P2 remains in progress. P3 is inactive. No physics, runtime, site configuration,
expected-energy source, writer, database, API, frontend or execution changes occur.
