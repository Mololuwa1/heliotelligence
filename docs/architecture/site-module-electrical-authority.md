# Reviewed configured module electrical basis

P2C admits a configured **lower-fidelity** model-class and raw electrical basis,
not verified installed equipment. The [frozen authority implementation](../../src/heliotelligence/engine/site_module_electrical_authority.py)
and [reviewed Bracon declaration](../../evidence/authorities/bracon-ash/module-electrical-basis.yaml)
remain dormant governance inputs. No runtime consumes them automatically.

```text
configured model label + local Tier-3 parameter evidence
        ↓
reviewed lower-fidelity authority
        ↓
module-model + raw parameter basis admitted at lower fidelity
        ↓
population / topology / thermal / optics remain separate
```

## Contract and controlled evidence

| Semantic | Identifier |
| --- | --- |
| Contract | `explicit_reviewed_configured_module_electrical_basis_authority_v1` |
| Model | `tier3_low_fit_datasheet_module_electrical_basis_v1` |
| Scope | `configured_site_module_model_and_electrical_parameter_basis_before_population_and_topology_binding` |
| Coverage | `single_site_configured_model_class_low_fit_stc_parameter_basis_only` |
| Fidelity | `supports_explicit_lower_fidelity_path` |
| Installed-equipment temporal applicability | `unknown` |

The separate reviewed declaration binds `site-001`, canonical UUID
`5ab83b40-553c-5ddd-976f-71f6cb5d490f`, Bracon Ash, configured model
`JKM570N-72HL4-BDV` and technology `mono_si`. Sources are exactly
[config/sites.yaml](../../config/sites.yaml) and
[the local module library](../../src/heliotelligence/data/module_library.yaml).
Configuration and library presence did not self-admit the site.

The local entry declares `source: datasheet_fit`, `fit_quality: low`. Its note about
the earlier inconsistent `i_sc` and correction to 14.36 A is repository evidence,
not independently supplied manufacturer certification. Confidence remains
`unknown`; technical fit quality and categorical provenance confidence are
separate. Neither supplies numerical uncertainty.

| Reviewed raw quantity | Value | Unit |
| --- | --- | --- |
| Nominal STC power | 570.0 | Wp |
| MPP voltage / current | 41.64 / 13.69 | V / A |
| Open-circuit voltage / short-circuit current | 50.60 / 14.36 | V / A |
| Short-circuit current temperature coefficient | 0.045 | %/°C |
| Open-circuit voltage temperature coefficient | -0.25 | %/°C |
| Maximum-power temperature coefficient | -0.29 | %/°C |
| Series cells | 144 | count within the model |

## Ownership and limits

The canonical lookup hierarchy is unchanged: explicit CEC, automatic CEC match,
local library, inline datasheet, then PVWatts. Tests use the real pinned lookup and
require Bracon to resolve as **Tier 3 / local_library / low**. A future CEC/dependency
change must trigger review rather than silently forcing Tier 3.

This authority persists raw STC values only. Existing electrical runtime owns
`fit_desoto_batzelis` → `calcparams_desoto` → `singlediode`, including fitted
coefficients. P2C neither calls that solver nor creates another one.

This is not manufacturer-certified, CEC high-quality, as-built/BOM, serial-number
inventory, flash-population or measured I-V evidence. It establishes no installed
module count, population homogeneity/variability, physical string membership,
routing, geometry, substring/bypass layout or historical installed-equipment
validity. Bifaciality, thermal parameters, loss percentages and topology are
excluded. Unknown temporal applicability stays unknown despite static files.

## Admission, validation and persistence

The [manifest](../../evidence/sites/bracon-ash.yaml) admits only two new items:
`site.module.model_label` and `module.electrical_parameters`, both at lower fidelity.
The original P2A baseline had zero admissions; P2B admitted identity alone at full
support. Current P2C version is
`bracon-ash-module-electrical-lower-fidelity-admitted-v3`: evidence 17/48/1/0,
admission 3/14/49/0, active support 1 full / 2 lower / 63 non-resolving / 0 N/A.

Module-electrical baseline blockers reduce from 10 to 9; full-fidelity blockers
remain 10 because the raw basis does not meet full fidelity. All other section
coverage is unchanged. All nine sections remain partially admitted with blockers.
The optional model-label admission removes no unrelated mandatory blocker.
Population counts **49,824 / 47,448 / 50,736** remain conflicting and blocked;
`electrical_topology` remains absent. Full P2 remains in progress and P3 inactive.

The strict supplied-path UTF-8 YAML loader rejects duplicate keys, unknown/missing
fields and contradictory fixed semantics. JSON-safe serialization preserves all
identity, raw parameters and provenance; deserialization revalidates them. The
independent frozen-state validator calls no constructors, loader, wire helpers or
runtime lookup. This format does not claim cryptographic authenticity: structurally
valid edits must also pass the separate evidence binding check.

`validate_site_module_electrical_binding` checks the manifest, authority, SiteConfig
and explicitly supplied library path. It compares exact identity/model/technology,
library key/model/source/fit and every reviewed raw parameter. Both manifest items
must identify this lower-fidelity authority, model-class scope, unknown temporal
semantics and source coverage. Config access is guarded in tests to exclude
capacity, population, layout, topology, thermal, optics, loss and inverter fields.
It does not infer authority or silently mutate the manifest.

No physics, library/config value, expected-energy storage/source, P1, writer,
database, API, frontend or execution path changes. No physical source is chosen.
Advanced substring/bypass and cable-parameter derivation remain pending; this
model-class basis supplies neither route's missing evidence.
