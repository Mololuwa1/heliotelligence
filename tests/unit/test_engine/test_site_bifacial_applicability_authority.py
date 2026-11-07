"""P2E applicability evidence cannot become electrical-response/optical authority."""

from __future__ import annotations

import ast
import copy
import json
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, uuid5

import pytest
import yaml  # type: ignore[import-untyped]

from heliotelligence.config.site import ModuleConfig, SiteConfig, load_sites
from heliotelligence.engine import site_bifacial_applicability_authority as a
from heliotelligence.engine import site_evidence_manifest as m

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = "evidence/authorities/bracon-ash/bifacial-applicability.yaml"
LIBRARY = ROOT / "src/heliotelligence/data/module_library.yaml"
EXCLUDED = (
    "bifaciality_factor",
    "isc_bifaciality_factor",
    "phi_isc",
    "front_isc_stc_a",
    "rear_isc_stc_a",
    "resolution_method",
    "rear_model",
    "rear_mode",
    "albedo",
    "pitch",
    "gcr",
    "collector_width",
    "row_height",
    "receiver_ids",
    "row_ids",
    "array_ids",
    "geometry",
    "poa",
    "iam",
    "spectral_parameters",
    "thermal_parameters",
    "module_count",
    "num_strings",
    "modules_per_string",
    "num_tables",
    "capacity_kwp",
    "electrical_topology",
)


@pytest.fixture
def authority() -> a.SiteBifacialApplicabilityAuthority:
    return a.load_site_bifacial_applicability_authority(ROOT / REFERENCE)


@pytest.fixture
def manifest() -> m.SiteEvidenceManifest:
    return m.load_site_evidence_manifest(ROOT / "evidence/sites/bracon-ash.yaml")


@pytest.fixture
def site() -> SiteConfig:
    return load_sites(ROOT / "config/sites.yaml")[0]


def test_reviewed_basis(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
) -> None:
    assert (authority.site_config_id, authority.site_uuid, authority.site_name) == (
        "site-001",
        str(uuid5(NAMESPACE_DNS, "site-001")),
        "Bracon Ash",
    )
    assert authority.module_model_label == "JKM570N-72HL4-BDV"
    assert authority.technology == "mono_si"
    assert authority.bifacial_enabled is True
    assert (
        authority.contract
        == "explicit_reviewed_configured_module_class_bifacial_applicability_authority_v1"
    )
    assert authority.model == "configured_module_class_bifacial_enabled_lower_fidelity_basis_v1"
    assert (
        authority.scope
        == "configured_module_class_bifacial_applicability_before_receiver_and_rear_model_binding"
    )
    assert (
        authority.coverage_scope
        == "single_site_configured_module_class_bifacial_applicability_only"
    )
    assert authority.supported_fidelity == m.LOWER_SUPPORT
    assert authority.temporal_semantics == "unknown"
    assert authority.evidence_source_references == (
        "config/sites.yaml",
        "src/heliotelligence/data/module_library.yaml",
    )
    assert authority.authority_reference == REFERENCE
    assert authority.authority_version == "bracon-ash-configured-bifacial-applicability-v1"
    assert authority.confidence == "unknown"
    item = next(
        i for i in manifest.items if i.requirement_id == a.BIFACIAL_APPLICABILITY_REQUIREMENT_ID
    )
    assert item.physical_scope == m.PhysicalEvidenceScope(
        "model_class", (authority.module_model_label,)
    )
    a.validate_site_bifacial_applicability_authority(authority)
    a.validate_site_bifacial_applicability_binding(manifest, authority, site, LIBRARY)


def test_frozen_exact_schema(authority: a.SiteBifacialApplicabilityAuthority) -> None:
    assert {f.name for f in fields(authority)} == {
        "site_config_id",
        "site_uuid",
        "site_name",
        "module_model_label",
        "technology",
        "bifacial_enabled",
        "authority_version",
        "evidence_source_references",
        "authority_reference",
        "confidence",
        "contract",
        "model",
        "scope",
        "coverage_scope",
        "supported_fidelity",
        "temporal_semantics",
    }
    for f in fields(authority):
        with pytest.raises(FrozenInstanceError):
            setattr(authority, f.name, None)
    for name in EXCLUDED:
        with pytest.raises(ValueError):
            a.deserialize_site_bifacial_applicability_authority(
                dict(a.serialize_site_bifacial_applicability_authority(authority), **{name: 0.8})
            )
    with pytest.raises(ValueError):
        a.validate_site_bifacial_applicability_authority({})  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [1, 0, "true", "false", None, 1.0, float("nan")])
def test_exact_boolean(authority: a.SiteBifacialApplicabilityAuthority, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, bifacial_enabled=bad)
    wire = a.serialize_site_bifacial_applicability_authority(authority)
    wire["bifacial_enabled"] = bad
    with pytest.raises(ValueError):
        a.deserialize_site_bifacial_applicability_authority(wire)


@pytest.mark.parametrize(
    "name",
    [
        "site_config_id",
        "site_uuid",
        "site_name",
        "module_model_label",
        "technology",
        "authority_version",
        "authority_reference",
        "confidence",
    ],
)
@pytest.mark.parametrize("bad", ["", " padded", "padded ", 1, True, None])
def test_exact_strings(
    authority: a.SiteBifacialApplicabilityAuthority, name: str, bad: Any
) -> None:
    with pytest.raises(ValueError):
        replace(authority, **{name: bad})


@pytest.mark.parametrize(
    "bad", ["site-001", "5AB83B40-553C-5DDD-976F-71F6CB5D490F", str(uuid5(NAMESPACE_DNS, "other"))]
)
def test_canonical_uuid(authority: a.SiteBifacialApplicabilityAuthority, bad: str) -> None:
    with pytest.raises(ValueError):
        replace(authority, site_uuid=bad)


@pytest.mark.parametrize(
    "bad",
    [
        (),
        ("config/sites.yaml",),
        ("config/sites.yaml", "config/sites.yaml"),
        (" config/sites.yaml", "src/heliotelligence/data/module_library.yaml"),
        ("different", "different"),
        ["config/sites.yaml"],
        (1, 2),
    ],
)
def test_source_tuple(authority: a.SiteBifacialApplicabilityAuthority, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, evidence_source_references=bad)


def test_confidence_and_wire_roundtrip(authority: a.SiteBifacialApplicabilityAuthority) -> None:
    for confidence in ("high", "medium", "low", "unknown"):
        changed = replace(authority, confidence=confidence)
        wire = a.serialize_site_bifacial_applicability_authority(changed)
        assert (
            a.deserialize_site_bifacial_applicability_authority(json.loads(json.dumps(wire)))
            == changed
        )
        assert a.serialize_site_bifacial_applicability_authority(changed) == wire
        assert changed.bifacial_enabled is True
        assert changed.supported_fidelity == m.LOWER_SUPPORT
    with pytest.raises(ValueError):
        replace(authority, confidence="certain")
    wire["evidence_source_references"] = authority.evidence_source_references
    with pytest.raises(ValueError):
        a.deserialize_site_bifacial_applicability_authority(wire)


@pytest.mark.parametrize("name", [f.name for f in fields(a.SiteBifacialApplicabilityAuthority)])
def test_every_field_missing_and_frozen_tamper(
    authority: a.SiteBifacialApplicabilityAuthority, name: str
) -> None:
    wire = a.serialize_site_bifacial_applicability_authority(authority)
    del wire[name]
    with pytest.raises(ValueError):
        a.deserialize_site_bifacial_applicability_authority(wire)
    object.__setattr__(authority, name, None)
    with pytest.raises(ValueError):
        a.validate_site_bifacial_applicability_authority(authority)
    with pytest.raises(ValueError):
        a.serialize_site_bifacial_applicability_authority(authority)


@pytest.mark.parametrize(
    "name",
    ["contract", "model", "scope", "coverage_scope", "supported_fidelity", "temporal_semantics"],
)
def test_fixed_semantics(authority: a.SiteBifacialApplicabilityAuthority, name: str) -> None:
    wire = a.serialize_site_bifacial_applicability_authority(authority)
    wire[name] = "forged"
    with pytest.raises(ValueError):
        a.deserialize_site_bifacial_applicability_authority(wire)


def test_strict_yaml(authority: a.SiteBifacialApplicabilityAuthority, tmp_path: Path) -> None:
    wire = a.serialize_site_bifacial_applicability_authority(authority)
    path = tmp_path / "authority.yaml"
    for name in (*wire, *EXCLUDED, "unknown"):
        raw = dict(wire)
        if name in wire:
            del raw[name]
        else:
            raw[name] = 0.8
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError):
            a.load_site_bifacial_applicability_authority(path)
    path.write_text(
        (ROOT / REFERENCE).read_text() + "\nbifacial_enabled: false\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        a.load_site_bifacial_applicability_authority(path)
    for text in ("null", "[]", "!!python/object/apply:os.system ['false']"):
        path.write_text(text, encoding="utf-8")
        with pytest.raises((ValueError, yaml.YAMLError)):
            a.load_site_bifacial_applicability_authority(path)


def test_validator_independence(
    authority: a.SiteBifacialApplicabilityAuthority, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper called")

    for name in (
        "_admit",
        "_text",
        "_unique_mapping",
        "load_site_bifacial_applicability_authority",
        "serialize_site_bifacial_applicability_authority",
        "deserialize_site_bifacial_applicability_authority",
        "validate_site_bifacial_applicability_binding",
    ):
        monkeypatch.setattr(a, name, disabled)
    monkeypatch.setattr(a.SiteBifacialApplicabilityAuthority, "__post_init__", disabled)
    a.validate_site_bifacial_applicability_authority(authority)
    for f in fields(authority):
        changed = copy.deepcopy(authority)
        object.__setattr__(changed, f.name, None)
        with pytest.raises(ValueError):
            a.validate_site_bifacial_applicability_authority(changed)


@pytest.mark.parametrize(
    "name,value",
    [
        ("id", "other"),
        ("name", "Other"),
        ("local_module_name", "other"),
        ("technology", "poly_si"),
        ("bifacial", False),
        ("bifacial", 1),
        ("bifacial", "true"),
    ],
)
def test_config_drift(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    name: str,
    value: Any,
) -> None:
    changed = (
        site.model_copy(update={name: value})
        if name in ("id", "name")
        else site.model_copy(update={"module": site.module.model_copy(update={name: value})})
    )
    with pytest.raises(ValueError):
        a.validate_site_bifacial_applicability_binding(manifest, authority, changed, LIBRARY)


@pytest.mark.parametrize(
    "key,value",
    [
        ("model", "other"),
        ("technology", "poly_si"),
        ("bifacial", False),
        ("bifacial", 1),
        ("bifacial", "true"),
        ("bifaciality_factor", 0.17),
    ],
)
def test_library_drift_and_factor_isolation(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    tmp_path: Path,
    key: str,
    value: Any,
) -> None:
    raw = yaml.safe_load(LIBRARY.read_text())
    raw["modules"][authority.module_model_label][key] = value
    path = tmp_path / "explicit-library.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    if key == "bifaciality_factor":
        a.validate_site_bifacial_applicability_binding(manifest, authority, site, path)
    else:
        with pytest.raises(ValueError):
            a.validate_site_bifacial_applicability_binding(manifest, authority, site, path)


def test_library_key_and_duplicate_rejected(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    tmp_path: Path,
) -> None:
    path = tmp_path / "library.yaml"
    for raw in ("modules: {}", "modules:\n  x: {}\n  x: {}", "[]"):
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(ValueError):
            a.validate_site_bifacial_applicability_binding(manifest, authority, site, path)


@pytest.mark.parametrize(
    "changes",
    [
        {"supported_fidelity": m.FULL_SUPPORT},
        {"authority_binding_reference": "other"},
        {"admitted_authority_contract_ids": ("other",)},
        {"source_references": ("config/sites.yaml",), "facts": ()},
        {"temporal_scope": m.EvidenceTemporalScope("static")},
        {"physical_scope": m.PhysicalEvidenceScope("site", ("site-001",))},
    ],
)
def test_manifest_binding_drift(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    changes: dict[str, Any],
) -> None:
    changed = replace(
        manifest,
        items=tuple(
            replace(i, **changes)
            if i.requirement_id == a.BIFACIAL_APPLICABILITY_REQUIREMENT_ID
            else i
            for i in manifest.items
        ),
    )
    with pytest.raises(ValueError):
        a.validate_site_bifacial_applicability_binding(changed, authority, site, LIBRARY)


@pytest.mark.parametrize(
    "name,value",
    [
        ("bifacial_enabled", False),
        ("module_model_label", "other"),
        ("site_name", "Other"),
        ("authority_reference", "other"),
    ],
)
def test_valid_shaped_authority_edits_require_binding(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    name: str,
    value: Any,
) -> None:
    changed = replace(authority, **{name: value})
    a.validate_site_bifacial_applicability_authority(changed)
    with pytest.raises(ValueError):
        a.validate_site_bifacial_applicability_binding(manifest, changed, site, LIBRARY)


def test_guarded_config_factor_and_population_isolation(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert site.electrical_topology is None
    changed = site.model_copy(
        update={
            "capacity_kwp": 1.0,
            "electrical_topology": "unrelated",
            "module": site.module.model_copy(
                update={
                    "bifaciality_factor": 0.17,
                    "num_strings": 1,
                    "modules_per_string": 1,
                    "num_tables": 1,
                }
            ),
        }
    )
    before = m.serialize_site_evidence_manifest(manifest)
    original_site = SiteConfig.__getattribute__
    original_module = ModuleConfig.__getattribute__

    def guarded_site(self: SiteConfig, name: str) -> Any:
        if name not in {"id", "name", "module", "__class__"}:
            raise AssertionError(f"excluded config access: {name}")
        return original_site(self, name)

    def guarded_module(self: ModuleConfig, name: str) -> Any:
        if name not in {"local_module_name", "technology", "bifacial", "__class__"}:
            raise AssertionError(f"excluded module access: {name}")
        return original_module(self, name)

    monkeypatch.setattr(SiteConfig, "__getattribute__", guarded_site)
    monkeypatch.setattr(ModuleConfig, "__getattribute__", guarded_module)
    a.validate_site_bifacial_applicability_binding(manifest, authority, changed, LIBRARY)
    assert m.serialize_site_evidence_manifest(manifest) == before


def test_no_physics_execution_dependency() -> None:
    tree = ast.parse(
        (ROOT / "src/heliotelligence/engine/site_bifacial_applicability_authority.py").read_text()
    )
    imports = {
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("heliotelligence")
    }
    assert imports == {
        "heliotelligence.config.site",
        "heliotelligence.engine.site_evidence_manifest",
    }
    forbidden = {
        "resolve_bifacial_response_parameters",
        "calculate_bifacial_electrical_equivalent_irradiance",
        "FixedBifacialRearScene",
        "assemble_receiver_optical_state",
    }
    assert not {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}.intersection(forbidden)


def test_config_factor_only_isolation(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
) -> None:
    changed = site.model_copy(
        update={"module": site.module.model_copy(update={"bifaciality_factor": 0.17})}
    )
    a.validate_site_bifacial_applicability_binding(manifest, authority, changed, LIBRARY)


@pytest.mark.parametrize(
    "fact_id,value,rejected",
    [
        ("bifacial_flag", "false", True),
        ("bifaciality_factor", "0.17", False),
    ],
)
def test_manifest_flag_agreement_and_factor_separation(
    authority: a.SiteBifacialApplicabilityAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    fact_id: str,
    value: str,
    rejected: bool,
) -> None:
    changed = replace(
        manifest,
        items=tuple(
            replace(
                i,
                facts=tuple(
                    replace(f, value=value) if f.fact_id == fact_id else f for f in i.facts
                ),
            )
            if i.requirement_id == a.BIFACIAL_APPLICABILITY_REQUIREMENT_ID
            else i
            for i in manifest.items
        ),
    )
    if rejected:
        with pytest.raises(ValueError):
            a.validate_site_bifacial_applicability_binding(changed, authority, site, LIBRARY)
    else:
        a.validate_site_bifacial_applicability_binding(changed, authority, site, LIBRARY)
