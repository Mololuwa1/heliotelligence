"""P2A controlled evidence inventory; no live services or physics execution."""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, uuid5

import pandas as pd  # type: ignore[import-untyped]
import pytest
import yaml  # type: ignore[import-untyped]

from heliotelligence.config.site import load_sites
from heliotelligence.engine import site_evidence_manifest as m

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "evidence/sites/bracon-ash.yaml"


@pytest.fixture
def manifest() -> m.SiteEvidenceManifest:
    return m.load_site_evidence_manifest(MANIFEST_PATH)


def item(manifest: m.SiteEvidenceManifest, key: str = "s11.lv_topology") -> m.SiteEvidenceItem:
    return next(i for i in manifest.items if i.requirement_id == key)


def update(manifest: m.SiteEvidenceManifest, changed: m.SiteEvidenceItem) -> m.SiteEvidenceManifest:
    return replace(
        manifest,
        items=tuple(
            changed if i.requirement_id == changed.requirement_id else i for i in manifest.items
        ),
    )


def admitted(original: m.SiteEvidenceItem, *, lower: bool = False) -> m.SiteEvidenceItem:
    # Synthetic reviewed binding declaration, not actual Bracon evidence/admission.
    return replace(
        original,
        evidence_state="present",
        admission_state="admitted",
        source_references=("test-only-reviewed-study",),
        source_kind="engineering_study",
        supported_fidelity=m.LOWER_SUPPORT if lower else m.FULL_SUPPORT,
        admitted_authority_contract_ids=(
            "explicit_lv_ac_collection_topology_and_series_impedance_authority_v1",
        ),
        target_authority_contract_ids=(),
        gap_reason_codes=(),
        facts=(),
        authority_binding_reference="test-only-canonical-binding",
    )


def not_applicable(original: m.SiteEvidenceItem) -> m.SiteEvidenceItem:
    return replace(
        original,
        evidence_state="not_applicable",
        admission_state="not_applicable",
        supported_fidelity="not_applicable",
        admitted_authority_contract_ids=(),
        target_authority_contract_ids=(),
        gap_reason_codes=(),
        authority_binding_reference=None,
        applicability_reason="Synthetic explicitly excluded physical path",
    )


def test_contract_and_identity(manifest: m.SiteEvidenceManifest) -> None:
    assert manifest.contract == m.SITE_EVIDENCE_MANIFEST_CONTRACT_ID
    assert manifest.scope == m.SITE_EVIDENCE_MANIFEST_SCOPE
    assert manifest.identity.site_config_id == "site-001"
    assert manifest.identity.site_uuid == "5ab83b40-553c-5ddd-976f-71f6cb5d490f"
    assert manifest.identity.site_uuid == str(uuid5(NAMESPACE_DNS, "site-001"))
    assert manifest.identity.manifest_version == "bracon-ash-repository-baseline-v1"
    m.validate_manifest_against_site_config(manifest, load_sites(ROOT / "config/sites.yaml")[0])


@pytest.mark.parametrize("field", ["site_config_id", "site_name", "manifest_version"])
@pytest.mark.parametrize("value", ["", " padded", "padded ", 1, None])
def test_identity_strict(manifest: m.SiteEvidenceManifest, field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(manifest.identity, **{field: value})


@pytest.mark.parametrize(
    "uuid",
    [
        "site-001",
        "5AB83B40-553C-5DDD-976F-71F6CB5D490F",
        "5ab83b40553c5ddd976f71f6cb5d490f",
        str(uuid5(NAMESPACE_DNS, "another-site")),
        None,
    ],
)
def test_wrong_site_uuid_rejected(manifest: m.SiteEvidenceManifest, uuid: Any) -> None:
    with pytest.raises(ValueError):
        replace(manifest.identity, site_uuid=uuid)


def test_site_cross_check_does_not_admit(manifest: m.SiteEvidenceManifest) -> None:
    site, other = load_sites(ROOT / "config/sites.yaml")
    for mismatch in (
        other,
        site.model_copy(update={"name": "different"}),
        site.model_copy(update={"id": "different"}),
    ):
        with pytest.raises(ValueError):
            m.validate_manifest_against_site_config(manifest, mismatch)
    before = m.serialize_site_evidence_manifest(manifest)
    m.validate_manifest_against_site_config(manifest, site)
    assert m.serialize_site_evidence_manifest(manifest) == before
    assert manifest.diagnostics.admitted_count == 0


def test_catalogue_complete_and_deterministic(manifest: m.SiteEvidenceManifest) -> None:
    ids = tuple(r.requirement_id for r in m.REQUIREMENT_CATALOGUE)
    assert len(ids) == len(set(ids)) == 66
    assert ids == tuple(sorted(ids))
    assert tuple(i.requirement_id for i in manifest.items) == ids
    assert replace(manifest, items=tuple(reversed(manifest.items))) == manifest
    with pytest.raises(ValueError):
        replace(manifest, items=manifest.items[:-1])
    with pytest.raises(ValueError):
        replace(manifest, items=(*manifest.items, manifest.items[0]))
    with pytest.raises(ValueError):
        replace(manifest.items[0], requirement_id="unreviewed.requirement")
    with pytest.raises(ValueError):
        replace(manifest.items[0], domain="controller")
    with pytest.raises(ValueError):
        replace(manifest.items[0], stage_refs=("S15",))
    with pytest.raises(ValueError):
        replace(manifest, items=list(manifest.items))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "state,admission",
    [
        ("missing", "admitted"),
        ("conflicting", "admitted"),
        ("present", "not_applicable"),
        ("not_applicable", "admitted"),
        ("missing", "not_admitted"),
        ("conflicting", "not_admitted"),
        ("present", "blocked"),
    ],
)
def test_invalid_relationships(
    manifest: m.SiteEvidenceManifest, state: str, admission: str
) -> None:
    with pytest.raises(ValueError):
        replace(item(manifest), evidence_state=state, admission_state=admission)


def test_valid_relationships_and_explicit_bindings(manifest: m.SiteEvidenceManifest) -> None:
    missing = item(manifest)
    assert (missing.evidence_state, missing.admission_state) == ("missing", "blocked")
    assert (
        item(manifest, "site.population.module_count").evidence_state,
        item(manifest, "site.population.module_count").admission_state,
    ) == ("conflicting", "blocked")
    present = item(manifest, "site.geometry.module_positions")
    assert present.admission_state == "not_admitted"
    for changed in (admitted(missing), admitted(missing, lower=True), not_applicable(missing)):
        result = update(manifest, changed)
        m.validate_site_evidence_manifest(result)
        assert (
            m.deserialize_site_evidence_manifest(m.serialize_site_evidence_manifest(result))
            == result
        )
    with pytest.raises(ValueError):
        replace(admitted(missing), admitted_authority_contract_ids=())
    with pytest.raises(ValueError):
        replace(admitted(missing), authority_binding_reference=None)
    with pytest.raises(ValueError):
        replace(admitted(missing), supported_fidelity=m.NON_RESOLVING)
    with pytest.raises(ValueError):
        replace(missing, admitted_authority_contract_ids=("forged",))
    with pytest.raises(ValueError):
        replace(not_applicable(missing), applicability_reason=None)
    with pytest.raises(ValueError):
        replace(not_applicable(missing), target_authority_contract_ids=("not-admitted",))


@pytest.mark.parametrize(
    "field",
    [
        "source_references",
        "reference_planes",
        "admitted_authority_contract_ids",
        "target_authority_contract_ids",
        "gap_reason_codes",
    ],
)
@pytest.mark.parametrize(
    "value", [("",), (" padded",), ("duplicate", "duplicate"), ["mutable"], (1,)]
)
def test_identifier_tuples(manifest: m.SiteEvidenceManifest, field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(item(manifest), **{field: value})


@pytest.mark.parametrize(
    "field",
    ["evidence_state", "admission_state", "source_kind", "supported_fidelity", "confidence"],
)
@pytest.mark.parametrize("value", ["unknown-unreviewed", " padded", "", None, 1])
def test_enums(manifest: m.SiteEvidenceManifest, field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(item(manifest), **{field: value})


def test_target_authority_is_not_admitted_authority(manifest: m.SiteEvidenceManifest) -> None:
    blocked = item(manifest, "s8.direct_branch_resistance")
    assert blocked.target_authority_contract_ids
    assert blocked.admitted_authority_contract_ids == ()
    changed = replace(
        blocked,
        source_references=("config/sites.yaml",),
        supported_fidelity=m.FULL_SUPPORT,
        confidence="high",
    )
    result = update(manifest, changed)
    assert result.diagnostics.full_fidelity_support_count == 0
    assert result.diagnostics.admitted_count == 0
    assert result.path_coverage == manifest.path_coverage


@pytest.mark.parametrize(
    "kind,ids",
    [
        ("site", ("site-001",)),
        ("asset_set", ("A", "B")),
        ("zone", ("Z",)),
        ("meter", ("meter-exact",)),
        ("network_path", ("path-exact",)),
        ("model_class", ("model-exact",)),
        ("unknown", ()),
    ],
)
def test_physical_scopes(kind: str, ids: tuple[str, ...]) -> None:
    assert m.PhysicalEvidenceScope(kind, ids).identifiers == ids


@pytest.mark.parametrize(
    "kind,ids",
    [
        ("site", ()),
        ("site", ("",)),
        ("site", ("all",)),
        ("asset_set", ("A", "A")),
        ("unknown", ("invented",)),
        ("unreviewed", ("A",)),
    ],
)
def test_invalid_physical_scopes(kind: str, ids: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        m.PhysicalEvidenceScope(kind, ids)


@pytest.mark.parametrize(
    "scope",
    [
        m.EvidenceTemporalScope("static"),
        m.EvidenceTemporalScope("unknown"),
        m.EvidenceTemporalScope(
            "snapshot", pd.Timestamp("2026-10-25T00:30:00.000000123Z").tz_convert("Europe/London")
        ),
        m.EvidenceTemporalScope(
            "bounded_interval",
            pd.Timestamp("2027-01-01", tz="UTC"),
            pd.Timestamp("2027-01-01 01:00", tz="Europe/London"),
        ),
    ],
)
def test_temporal_roundtrip(
    manifest: m.SiteEvidenceManifest, scope: m.EvidenceTemporalScope
) -> None:
    result = update(manifest, replace(item(manifest), temporal_scope=scope))
    restored = m.deserialize_site_evidence_manifest(
        json.loads(json.dumps(m.serialize_site_evidence_manifest(result)))
    )
    assert restored == result
    assert str(item(restored).temporal_scope.start_timestamp) == str(scope.start_timestamp)
    m.validate_site_evidence_manifest(result)


@pytest.mark.parametrize(
    "semantics,start,end",
    [
        ("static", pd.Timestamp("2027-01-01", tz="UTC"), None),
        ("unknown", None, pd.Timestamp("2027-01-01", tz="UTC")),
        ("snapshot", None, None),
        ("snapshot", pd.Timestamp("2027-01-01"), None),
        ("snapshot", pd.NaT, None),
        (
            "bounded_interval",
            pd.Timestamp("2027-01-02", tz="UTC"),
            pd.Timestamp("2027-01-01", tz="UTC"),
        ),
        ("bounded_interval", pd.Timestamp("2027-01-01", tz="UTC"), pd.Timestamp("2027-01-02")),
        ("bounded_interval", pd.Timestamp("2027-01-01", tz="UTC"), None),
        ("not_reviewed", None, None),
    ],
)
def test_invalid_temporal_scope(semantics: str, start: Any, end: Any) -> None:
    with pytest.raises(ValueError):
        m.EvidenceTemporalScope(semantics, start, end)


def test_path_baseline_and_full_fidelity_are_separate(manifest: m.SiteEvidenceManifest) -> None:
    section = "s12_transformer"
    required_ids = {
        r.requirement_id
        for r in m.REQUIREMENT_CATALOGUE
        if section in r.path_sections and r.requirement_level == m.ANY_PATH
    }
    result = replace(
        manifest,
        items=tuple(
            admitted(i, lower=True) if i.requirement_id in required_ids else i
            for i in manifest.items
        ),
    )
    coverage = next(p for p in result.path_coverage if p.section == section)
    assert coverage.state == "admitted"
    assert coverage.full_fidelity_state == "partially_admitted"
    assert not coverage.blocking_requirement_ids
    assert "s12.construction_component_evidence" in coverage.full_fidelity_blocking_requirement_ids
    assert "s12.harmonic_evidence" not in coverage.full_fidelity_blocking_requirement_ids
    m.validate_site_evidence_manifest(result)
    # Full-fidelity mandatory items admitted; optional advanced harmonic evidence still missing.
    full_ids = {
        r.requirement_id
        for r in m.REQUIREMENT_CATALOGUE
        if section in r.path_sections and r.requirement_level != m.OPTIONAL
    }
    full = replace(
        manifest,
        items=tuple(admitted(i) if i.requirement_id in full_ids else i for i in manifest.items),
    )
    assert (
        next(p for p in full.path_coverage if p.section == section).full_fidelity_state
        == "admitted"
    )
    mixed = update(manifest, admitted(item(manifest, "s12.transformer_equipment")))
    assert (
        next(p for p in mixed.path_coverage if p.section == section).state == "partially_admitted"
    )
    na_ids = {r.requirement_id for r in m.REQUIREMENT_CATALOGUE if section in r.path_sections}
    na = replace(
        manifest,
        items=tuple(not_applicable(i) if i.requirement_id in na_ids else i for i in manifest.items),
    )
    assert next(p for p in na.path_coverage if p.section == section).state == "not_applicable"
    for checked in (full, mixed, na):
        m.validate_site_evidence_manifest(checked)


def test_diagnostics_close_without_maturity_score(manifest: m.SiteEvidenceManifest) -> None:
    d = manifest.diagnostics
    assert (d.total_requirement_count, d.present_count, d.missing_count, d.conflicting_count) == (
        66,
        17,
        48,
        1,
    )
    assert (d.admitted_count, d.not_admitted_count, d.blocked_count) == (0, 17, 49)
    assert (
        d.present_count + d.missing_count + d.conflicting_count + d.not_applicable_count
        == d.total_requirement_count
    )
    assert (
        d.admitted_count + d.not_admitted_count + d.blocked_count + d.admission_not_applicable_count
        == d.total_requirement_count
    )
    assert (
        d.full_fidelity_support_count
        + d.lower_fidelity_support_count
        + d.non_resolving_count
        + d.fidelity_not_applicable_count
        == d.total_requirement_count
    )
    assert sum(n for _, n in d.domain_counts) == 66
    assert d.domain_counts == tuple(sorted(d.domain_counts))
    assert d.stage_counts == tuple(sorted(d.stage_counts))
    assert all(
        n == sum(stage in i.stage_refs for i in manifest.items) for stage, n in d.stage_counts
    )
    assert not any("score" in f.name or "percent" in f.name for f in fields(d))
    result = update(manifest, admitted(item(manifest), lower=True))
    assert result.diagnostics.lower_fidelity_support_count == 1
    assert result.diagnostics.full_fidelity_support_count == 0
    assert (
        replace(result.items[0], confidence="high").supported_fidelity
        == result.items[0].supported_fidelity
    )


def test_bracon_population_facts_and_configuration_unchanged(
    manifest: m.SiteEvidenceManifest,
) -> None:
    config = load_sites(ROOT / "config/sites.yaml")[0]
    surveyed = json.loads((ROOT / "config/geometry/site-001.json").read_text())
    population = item(manifest, "site.population.module_count")
    facts = {f.fact_id: f.value for f in population.facts}
    assert (population.evidence_state, population.admission_state) == ("conflicting", "blocked")
    assert population.gap_reason_codes == ("conflicting_module_population_counts",)
    assert (
        int(facts["configured_string_module_count"])
        == config.module.num_strings * config.module.modules_per_string
        == 49824
    )
    assert config.module.num_tables is not None
    assert (
        int(facts["configured_table_module_count"])
        == config.module.num_tables * config.module.modules_per_table
        == 47448
    )
    assert (
        int(facts["geometry_extracted_module_count"])
        == surveyed["_total_modules_extracted"]
        == 50736
    )
    assert config.capacity_kwp == 28524.0
    assert config.electrical_topology is None
    geometry_facts = {
        f.fact_id: f.value for f in item(manifest, "site.geometry.module_positions").facts
    }
    assert (
        geometry_facts["geometry_source"]
        == surveyed["_source"]
        == "module-cloud reconstruction @174.47"
    )
    assert float(geometry_facts["georef_residual_m"]) == surveyed["_georef_residual_m"] == 0.436


@pytest.mark.parametrize(
    "key",
    [
        "s8.string_mppt_mapping",
        "s11.lv_topology",
        "s12.transformer_terminal_binding",
        "s13.mv_hv_topology",
    ],
)
def test_surveyed_geometry_is_not_electrical_authority(
    manifest: m.SiteEvidenceManifest, key: str
) -> None:
    geometry = item(manifest, "site.geometry.module_positions")
    changed = replace(
        item(manifest, key),
        source_references=geometry.source_references,
        source_kind="surveyed_geometry",
        physical_scope=geometry.physical_scope,
        facts=geometry.facts,
    )
    result = update(manifest, changed)
    assert item(result, key).admission_state == "blocked"
    assert result.path_coverage == manifest.path_coverage
    with pytest.raises(ValueError, match="geometry"):
        replace(
            changed,
            evidence_state="present",
            admission_state="admitted",
            admitted_authority_contract_ids=(
                "explicit_lv_ac_collection_topology_and_series_impedance_authority_v1",
            ),
            supported_fidelity=m.FULL_SUPPORT,
            gap_reason_codes=(),
            authority_binding_reference="geometry-alone-is-not-electrical",
        )


@pytest.mark.parametrize(
    "key",
    [
        "s8.string_mppt_mapping",
        "s8.direct_branch_resistance",
        "s8.population_residual",
        "s9.static_pq_capability",
        "s9.fixed_q_convention",
        "s9.thermal_capability",
        "s9.inverter_temperature_state",
        "s10.active_power_request",
        "s10.reactive_power_request",
        "s11.lv_topology",
        "s11.segment_impedance",
        "s11.exit_voltage",
        "s12.transformer_equipment",
        "s12.factory_loss_evidence",
        "s12.thermal_evidence",
        "s12.harmonic_evidence",
        "s13.mv_hv_topology",
        "s13.grid_boundary_voltage",
        "s13.revenue_meter_binding",
        "s13.revenue_meter_scaling",
        "s13.revenue_meter_measurement_semantics",
        "s14.interval_support_policy",
        "uncertainty.measurement_chain",
        "uncertainty.expected_model",
    ],
)
def test_bracon_required_gaps_stay_blocked(manifest: m.SiteEvidenceManifest, key: str) -> None:
    assert item(manifest, key).admission_state == "blocked"
    assert not item(manifest, key).admitted_authority_contract_ids
    assert all(p.state == "blocked" for p in manifest.path_coverage)


@pytest.mark.parametrize(
    "group,field,value",
    [
        ("module", "mismatch_loss_pct", 5.0),
        ("module", "wiring_loss_dc_pct", 4.0),
        ("inverter", "wiring_loss_ac_pct", 3.0),
        ("inverter", "grid_limit_kwac", 30000.0),
        ("inverter", "pnom_kwac", 999.0),
        ("inverter", "eta_nom", 0.90),
        ("module", "u_c", 100.0),
        ("module", "u_v", 10.0),
    ],
)
def test_legacy_config_never_becomes_authority(
    manifest: m.SiteEvidenceManifest, group: str, field: str, value: float
) -> None:
    config = load_sites(ROOT / "config/sites.yaml")[0]
    before = m.serialize_site_evidence_manifest(manifest)
    nested = getattr(config, group).model_copy(update={field: value})
    changed = config.model_copy(update={group: nested})
    m.validate_manifest_against_site_config(manifest, changed)
    assert m.serialize_site_evidence_manifest(manifest) == before
    assert manifest.diagnostics.admitted_count == 0


def test_generic_capability_and_targets_do_not_admit_site(manifest: m.SiteEvidenceManifest) -> None:
    # Controlled repository contracts exist; availability cannot alter site declarations.
    controlled = [
        "module_thermal_authority.py",
        "dc_collection.py",
        "inverter_ac_authority.py",
        "lv_ac_collection_authority.py",
        "transformer_authority.py",
        "mv_hv_network_authority.py",
        "revenue_meter_measurement_uncertainty.py",
    ]
    assert all((ROOT / "src/heliotelligence/physics" / name).is_file() for name in controlled)
    assert manifest.diagnostics.admitted_count == 0
    assert any(i.target_authority_contract_ids for i in manifest.items)
    assert all(not i.admitted_authority_contract_ids for i in manifest.items)
    assert all(i.temporal_scope.semantics == "unknown" for i in manifest.items)


def test_roundtrip_and_freezing(manifest: m.SiteEvidenceManifest) -> None:
    wire = m.serialize_site_evidence_manifest(manifest)
    assert (
        m.deserialize_site_evidence_manifest(json.loads(json.dumps(wire, allow_nan=False)))
        == manifest
    )
    assert m.serialize_site_evidence_manifest(manifest) == wire
    for obj, field in (
        (manifest, "items"),
        (manifest.identity, "manifest_version"),
        (manifest.items[0], "notes"),
        (manifest.items[0].physical_scope, "scope_type"),
        (manifest.items[0].temporal_scope, "semantics"),
        (manifest.diagnostics, "admitted_count"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, "forged")


def test_yaml_exact_schema_and_duplicate_keys(
    manifest: m.SiteEvidenceManifest, tmp_path: Path
) -> None:
    raw = yaml.safe_load(MANIFEST_PATH.read_text())
    for changed in [
        dict(raw, unknown="value"),
        dict(raw, contract="forged"),
        dict(raw, scope="forged"),
    ]:
        path = tmp_path / "manifest.yaml"
        path.write_text(yaml.safe_dump(changed))
        with pytest.raises(ValueError):
            m.load_site_evidence_manifest(path)
    path.write_text(MANIFEST_PATH.read_text() + "\ncontract: duplicate\n")
    with pytest.raises(ValueError, match="duplicate"):
        m.load_site_evidence_manifest(path)
    for modify in ("missing", "duplicate", "unknown_field", "unknown_requirement"):
        changed = copy.deepcopy(raw)
        if modify == "missing":
            changed["items"].pop()
        elif modify == "duplicate":
            changed["items"].append(changed["items"][0])
        elif modify == "unknown_field":
            changed["items"][0]["inferred_authority"] = True
        else:
            changed["items"][0]["requirement_id"] = "unreviewed"
        path.write_text(yaml.safe_dump(changed))
        with pytest.raises(ValueError):
            m.load_site_evidence_manifest(path)


@pytest.mark.parametrize("field", [f.name for f in fields(m.SiteEvidenceItem)])
def test_every_item_field_tamper(manifest: m.SiteEvidenceManifest, field: str) -> None:
    target = manifest.items[0]
    object.__setattr__(target, field, None if getattr(target, field) is not None else "forged")
    with pytest.raises((ValueError, TypeError, AttributeError)):
        m.validate_site_evidence_manifest(manifest)
    with pytest.raises((ValueError, TypeError, AttributeError)):
        m.serialize_site_evidence_manifest(manifest)


@pytest.mark.parametrize("field", [f.name for f in fields(m.SiteEvidenceManifestIdentity)])
def test_every_identity_field_tamper(manifest: m.SiteEvidenceManifest, field: str) -> None:
    object.__setattr__(manifest.identity, field, "site-slug" if field == "site_uuid" else " padded")
    with pytest.raises(ValueError):
        m.validate_site_evidence_manifest(manifest)


@pytest.mark.parametrize(
    "cls", [m.PhysicalEvidenceScope, m.EvidenceTemporalScope, m.SiteEvidenceFact]
)
def test_nested_scope_fact_tamper(manifest: m.SiteEvidenceManifest, cls: type[Any]) -> None:
    for descriptor in fields(cls):
        cloned = copy.deepcopy(manifest)
        target: Any
        if cls is m.PhysicalEvidenceScope:
            target = cloned.items[0].physical_scope
        elif cls is m.EvidenceTemporalScope:
            target = cloned.items[0].temporal_scope
        else:
            target = next(i.facts[0] for i in cloned.items if i.facts)
        object.__setattr__(
            target,
            descriptor.name,
            None if getattr(target, descriptor.name) is not None else "forged",
        )
        with pytest.raises((ValueError, TypeError, AttributeError)):
            m.validate_site_evidence_manifest(cloned)


@pytest.mark.parametrize("field", [f.name for f in fields(m.SiteEvidenceCoverageDiagnostics)])
def test_every_diagnostic_tamper(manifest: m.SiteEvidenceManifest, field: str) -> None:
    object.__setattr__(manifest.diagnostics, field, () if field.endswith("counts") else 999)
    with pytest.raises(ValueError):
        m.validate_site_evidence_manifest(manifest)


@pytest.mark.parametrize("field", [f.name for f in fields(m.SitePhysicalPathCoverage)])
def test_every_path_field_tamper(manifest: m.SiteEvidenceManifest, field: str) -> None:
    object.__setattr__(manifest.path_coverage[0], field, "forged")
    with pytest.raises(ValueError):
        m.validate_site_evidence_manifest(manifest)


@pytest.mark.parametrize("field", [f.name for f in fields(m.SiteEvidenceManifest)])
def test_every_manifest_field_tamper(manifest: m.SiteEvidenceManifest, field: str) -> None:
    object.__setattr__(manifest, field, "forged")
    with pytest.raises((ValueError, TypeError, AttributeError)):
        m.validate_site_evidence_manifest(manifest)


def test_serialized_tampering_rejected(manifest: m.SiteEvidenceManifest) -> None:
    wire = m.serialize_site_evidence_manifest(manifest)
    for change in (
        "unknown",
        "diagnostics",
        "paths",
        "site_uuid",
        "status",
        "authority",
        "item_unknown",
    ):
        raw = copy.deepcopy(wire)
        if change == "unknown":
            raw["extra"] = True
        elif change == "diagnostics":
            raw["diagnostics"]["admitted_count"] = 66
        elif change == "paths":
            raw["path_coverage"][0]["state"] = "admitted"
        elif change == "site_uuid":
            raw["identity"]["site_uuid"] = str(uuid5(NAMESPACE_DNS, "other-site"))
        elif change == "status":
            raw["items"][0]["admission_state"] = "admitted"
        elif change == "authority":
            raw["items"][0]["admitted_authority_contract_ids"] = ["forged"]
        else:
            raw["items"][0]["extra"] = True
        with pytest.raises(ValueError):
            m.deserialize_site_evidence_manifest(raw)


def test_validator_is_independent(
    manifest: m.SiteEvidenceManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    variations = [
        manifest,
        update(manifest, admitted(item(manifest))),
        update(manifest, admitted(item(manifest), lower=True)),
        update(manifest, not_applicable(item(manifest))),
    ]
    for semantics, start, end in [
        ("static", None, None),
        ("snapshot", pd.Timestamp("2027-01-01", tz="UTC"), None),
        (
            "bounded_interval",
            pd.Timestamp("2027-01-01", tz="UTC"),
            pd.Timestamp("2027-01-02", tz="Europe/London"),
        ),
    ]:
        variations.append(
            update(
                manifest,
                replace(
                    item(manifest), temporal_scope=m.EvidenceTemporalScope(semantics, start, end)
                ),
            )
        )

    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper called")

    for name in (
        "_catalogue",
        "_text",
        "_strings",
        "_enum",
        "_stamp_wire",
        "_admit_item",
        "_coverage",
        "_diagnostics",
        "_wire",
        "_object",
        "_array",
        "_unpack_stamp",
        "_from_input",
        "serialize_site_evidence_manifest",
        "deserialize_site_evidence_manifest",
        "load_site_evidence_manifest",
    ):
        monkeypatch.setattr(m, name, disabled)
    for cls in (
        m.SiteEvidenceManifestIdentity,
        m.PhysicalEvidenceScope,
        m.EvidenceTemporalScope,
        m.SiteEvidenceFact,
        m.SiteEvidenceItem,
        m.SiteEvidenceManifest,
    ):
        monkeypatch.setattr(cls, "__post_init__", disabled)
    for checked in variations:
        m.validate_site_evidence_manifest(checked)


def test_bracon_documentation_is_manifest_projection(manifest: m.SiteEvidenceManifest) -> None:
    document = (ROOT / "docs/sites/bracon-ash.md").read_text()
    block = document.split("<!-- BEGIN P2A MANIFEST COVERAGE -->\n", 1)[1].split(
        "\n<!-- END P2A MANIFEST COVERAGE -->", 1
    )[0]
    assert block == m.render_site_evidence_coverage_markdown(manifest)


def test_site_scope_cannot_point_at_another_site(manifest: m.SiteEvidenceManifest) -> None:
    with pytest.raises(ValueError):
        update(
            manifest,
            replace(
                item(manifest), physical_scope=m.PhysicalEvidenceScope("site", ("other-site",))
            ),
        )
    with pytest.raises(ValueError):
        m.PhysicalEvidenceScope("site", ("site-001", "other-site"))


def test_immutable_inputs_are_readmitted(manifest: m.SiteEvidenceManifest) -> None:
    candidate = copy.deepcopy(manifest)
    object.__setattr__(item(candidate), "admitted_authority_contract_ids", ("forged",))
    with pytest.raises(ValueError):
        replace(candidate)
    candidate = copy.deepcopy(manifest)
    object.__setattr__(candidate.identity, "site_uuid", "site-slug")
    with pytest.raises(ValueError):
        replace(candidate)


def test_no_execution_or_service_dependencies() -> None:
    import ast

    tree = ast.parse((ROOT / "src/heliotelligence/engine/site_evidence_manifest.py").read_text())
    internal_imports = {
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("heliotelligence")
    }
    assert internal_imports == {"heliotelligence.config.site"}


def test_wire_preserves_sources_scopes_and_tuple_order(manifest: m.SiteEvidenceManifest) -> None:
    original = item(manifest)
    updated = replace(
        original,
        source_references=("exact/source-z", "exact/source-a"),
        reference_planes=("inverter_ac_output", "future_explicit_plane"),
        gap_reason_codes=("z_gap", "a_gap"),
    )
    result = update(manifest, updated)
    restored = m.deserialize_site_evidence_manifest(m.serialize_site_evidence_manifest(result))
    assert item(restored) == updated
    assert item(restored).gap_reason_codes == ("z_gap", "a_gap")
    assert item(restored).admission_state == "blocked"
