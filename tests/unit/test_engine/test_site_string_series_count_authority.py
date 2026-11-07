"""P2D configured uniform lower-fidelity series count, never physical inventory."""

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
from heliotelligence.engine import site_evidence_manifest as m
from heliotelligence.engine import site_string_series_count_authority as a

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = "evidence/authorities/bracon-ash/string-series-count.yaml"
EXCLUDED = (
    "num_strings",
    "module_count",
    "modules_per_table",
    "num_tables",
    "capacity_kwp",
    "module_model",
    "inverter_count",
    "inverter_ids",
    "mppt_ids",
    "string_ids",
    "string_member_assignments",
    "electrical_topology",
    "geometry",
    "branch_resistance",
    "population_residual",
)


@pytest.fixture
def authority() -> a.SiteStringSeriesCountAuthority:
    return a.load_site_string_series_count_authority(ROOT / REFERENCE)


@pytest.fixture
def manifest() -> m.SiteEvidenceManifest:
    return m.load_site_evidence_manifest(ROOT / "evidence/sites/bracon-ash.yaml")


@pytest.fixture
def site() -> SiteConfig:
    return load_sites(ROOT / "config/sites.yaml")[0]


def test_reviewed_declaration(
    authority: a.SiteStringSeriesCountAuthority, manifest: m.SiteEvidenceManifest, site: SiteConfig
) -> None:
    assert (authority.site_config_id, authority.site_uuid, authority.site_name) == (
        "site-001",
        "5ab83b40-553c-5ddd-976f-71f6cb5d490f",
        "Bracon Ash",
    )
    assert authority.site_uuid == str(uuid5(NAMESPACE_DNS, site.id))
    assert authority.modules_per_string == 24
    assert authority.authority_version == "bracon-ash-configured-string-series-count-v1"
    assert authority.evidence_source_references == ("config/sites.yaml",)
    assert authority.authority_reference == REFERENCE
    assert authority.confidence == "unknown"
    assert (
        authority.contract
        == "explicit_reviewed_configured_uniform_string_series_count_authority_v1"
    )
    assert authority.model == "configured_uniform_modules_per_string_lower_fidelity_basis_v1"
    assert (
        authority.scope
        == "configured_string_series_module_count_before_physical_string_topology_binding"
    )
    assert (
        authority.coverage_scope
        == "single_site_uniform_configured_modules_per_string_assumption_only"
    )
    assert authority.supported_fidelity == m.LOWER_SUPPORT
    assert authority.temporal_semantics == "unknown"
    a.validate_site_string_series_count_authority(authority)
    a.validate_site_string_series_count_binding(manifest, authority, site)
    assert site.electrical_topology is None


def test_schema_and_freezing(authority: a.SiteStringSeriesCountAuthority) -> None:
    assert {f.name for f in fields(authority)} == {
        "site_config_id",
        "site_uuid",
        "site_name",
        "modules_per_string",
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
    wire = a.serialize_site_string_series_count_authority(authority)
    assert "2076" not in json.dumps(wire)
    for name in EXCLUDED:
        with pytest.raises(ValueError):
            a.deserialize_site_string_series_count_authority(dict(wire, **{name: 1}))
    with pytest.raises(ValueError):
        a.validate_site_string_series_count_authority({})  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [True, False, 24.0, "24", 0, -1, None, float("nan"), float("inf")])
def test_count_rejected(authority: a.SiteStringSeriesCountAuthority, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, modules_per_string=bad)
    wire = a.serialize_site_string_series_count_authority(authority)
    wire["modules_per_string"] = bad
    with pytest.raises(ValueError):
        a.deserialize_site_string_series_count_authority(wire)


def test_no_invented_maximum(authority: a.SiteStringSeriesCountAuthority) -> None:
    for count in (1, 10**100):
        changed = replace(authority, modules_per_string=count)
        a.validate_site_string_series_count_authority(changed)
        assert (
            a.deserialize_site_string_series_count_authority(
                a.serialize_site_string_series_count_authority(changed)
            )
            == changed
        )


@pytest.mark.parametrize(
    "name",
    [
        "site_config_id",
        "site_uuid",
        "site_name",
        "authority_version",
        "authority_reference",
        "confidence",
    ],
)
@pytest.mark.parametrize("bad", ["", " padded", "padded ", 1, True, None])
def test_exact_identifiers(
    authority: a.SiteStringSeriesCountAuthority, name: str, bad: Any
) -> None:
    with pytest.raises(ValueError):
        replace(authority, **{name: bad})


@pytest.mark.parametrize(
    "bad", ["site-001", "5AB83B40-553C-5DDD-976F-71F6CB5D490F", str(uuid5(NAMESPACE_DNS, "other"))]
)
def test_uuid_drift(authority: a.SiteStringSeriesCountAuthority, bad: str) -> None:
    with pytest.raises(ValueError):
        replace(authority, site_uuid=bad)


@pytest.mark.parametrize(
    "bad",
    [
        (),
        ("",),
        (" config/sites.yaml",),
        ("config/sites.yaml", "config/sites.yaml"),
        ["config/sites.yaml"],
        ("different",),
        (1,),
    ],
)
def test_exact_source_tuple(authority: a.SiteStringSeriesCountAuthority, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, evidence_source_references=bad)


def test_confidence_provenance(authority: a.SiteStringSeriesCountAuthority) -> None:
    for confidence in ("high", "medium", "low", "unknown"):
        changed = replace(authority, confidence=confidence)
        a.validate_site_string_series_count_authority(changed)
        assert changed.modules_per_string == 24
        assert changed.supported_fidelity == m.LOWER_SUPPORT
    with pytest.raises(ValueError):
        replace(authority, confidence="certain")


def test_deterministic_roundtrip(authority: a.SiteStringSeriesCountAuthority) -> None:
    wire = a.serialize_site_string_series_count_authority(authority)
    assert a.serialize_site_string_series_count_authority(authority) == wire
    assert (
        a.deserialize_site_string_series_count_authority(
            json.loads(json.dumps(wire, allow_nan=False))
        )
        == authority
    )
    assert (
        a.deserialize_site_string_series_count_authority(dict(reversed(tuple(wire.items()))))
        == authority
    )
    wire["evidence_source_references"] = ("config/sites.yaml",)
    with pytest.raises(ValueError):
        a.deserialize_site_string_series_count_authority(wire)


@pytest.mark.parametrize("name", [f.name for f in fields(a.SiteStringSeriesCountAuthority)])
def test_every_field_missing_and_frozen_tamper(
    authority: a.SiteStringSeriesCountAuthority, name: str
) -> None:
    wire = a.serialize_site_string_series_count_authority(authority)
    del wire[name]
    with pytest.raises(ValueError):
        a.deserialize_site_string_series_count_authority(wire)
    object.__setattr__(authority, name, None)
    with pytest.raises(ValueError):
        a.validate_site_string_series_count_authority(authority)
    with pytest.raises(ValueError):
        a.serialize_site_string_series_count_authority(authority)


@pytest.mark.parametrize(
    "name",
    ["contract", "model", "scope", "coverage_scope", "supported_fidelity", "temporal_semantics"],
)
def test_fixed_semantics_tamper(authority: a.SiteStringSeriesCountAuthority, name: str) -> None:
    wire = a.serialize_site_string_series_count_authority(authority)
    wire[name] = "forged"
    with pytest.raises(ValueError):
        a.deserialize_site_string_series_count_authority(wire)
    object.__setattr__(authority, name, "forged")
    with pytest.raises(ValueError):
        a.validate_site_string_series_count_authority(authority)


def test_strict_yaml(authority: a.SiteStringSeriesCountAuthority, tmp_path: Path) -> None:
    wire = a.serialize_site_string_series_count_authority(authority)
    path = tmp_path / "series.yaml"
    for name in (*wire, *EXCLUDED, "unknown"):
        raw = dict(wire)
        if name in raw:
            del raw[name]
        else:
            raw[name] = 1
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError):
            a.load_site_string_series_count_authority(path)
    path.write_text((ROOT / REFERENCE).read_text() + "\nmodules_per_string: 25\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        a.load_site_string_series_count_authority(path)
    for text in ("null", "[]", "!!python/object/apply:os.system ['false']"):
        path.write_text(text, encoding="utf-8")
        with pytest.raises((ValueError, yaml.YAMLError)):
            a.load_site_string_series_count_authority(path)


def test_validator_independence(
    authority: a.SiteStringSeriesCountAuthority, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper called")

    for name in (
        "_admit",
        "_text",
        "_unique_mapping",
        "load_site_string_series_count_authority",
        "serialize_site_string_series_count_authority",
        "deserialize_site_string_series_count_authority",
        "validate_site_string_series_count_binding",
    ):
        monkeypatch.setattr(a, name, disabled)
    monkeypatch.setattr(a.SiteStringSeriesCountAuthority, "__post_init__", disabled)
    a.validate_site_string_series_count_authority(authority)
    for f in fields(authority):
        forged = copy.deepcopy(authority)
        object.__setattr__(forged, f.name, None)
        with pytest.raises(ValueError):
            a.validate_site_string_series_count_authority(forged)


@pytest.mark.parametrize(
    "name,value",
    [
        ("id", "different"),
        ("name", "Different"),
        ("modules_per_string", 25),
        ("modules_per_string", True),
        ("modules_per_string", 24.0),
    ],
)
def test_config_binding_drift(
    authority: a.SiteStringSeriesCountAuthority,
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
        a.validate_site_string_series_count_binding(manifest, authority, changed)


@pytest.mark.parametrize(
    "changes",
    [
        {"supported_fidelity": m.FULL_SUPPORT},
        {"authority_binding_reference": "different"},
        {"admitted_authority_contract_ids": ("different",)},
        {"source_references": ("different",), "facts": ()},
        {"temporal_scope": m.EvidenceTemporalScope("static")},
        {"physical_scope": m.PhysicalEvidenceScope("model_class", ("different",))},
        {
            "admission_state": "not_admitted",
            "admitted_authority_contract_ids": (),
            "authority_binding_reference": None,
            "gap_reason_codes": ("not_admitted",),
        },
    ],
)
def test_manifest_binding_details(
    authority: a.SiteStringSeriesCountAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    changes: dict[str, Any],
) -> None:
    changed = replace(
        manifest,
        items=tuple(
            replace(i, **changes) if i.requirement_id == a.STRING_SERIES_COUNT_REQUIREMENT_ID else i
            for i in manifest.items
        ),
    )
    with pytest.raises(ValueError):
        a.validate_site_string_series_count_binding(changed, authority, site)


def test_manifest_identity_and_requirement_required(
    authority: a.SiteStringSeriesCountAuthority, manifest: m.SiteEvidenceManifest, site: SiteConfig
) -> None:
    changed = replace(manifest, identity=replace(manifest.identity, site_name="Different"))
    with pytest.raises(ValueError):
        a.validate_site_string_series_count_binding(changed, authority, site)
    changed = copy.deepcopy(manifest)
    object.__setattr__(
        changed,
        "items",
        tuple(i for i in changed.items if i.requirement_id != a.STRING_SERIES_COUNT_REQUIREMENT_ID),
    )
    with pytest.raises(ValueError):
        a.validate_site_string_series_count_binding(changed, authority, site)


@pytest.mark.parametrize(
    "name,value",
    [("modules_per_string", 25), ("site_name", "Different"), ("authority_reference", "different")],
)
def test_valid_shaped_edits_need_binding(
    authority: a.SiteStringSeriesCountAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    name: str,
    value: Any,
) -> None:
    changed = replace(authority, **{name: value})
    a.validate_site_string_series_count_authority(changed)
    with pytest.raises(ValueError):
        a.validate_site_string_series_count_binding(manifest, changed, site)


@pytest.mark.parametrize("field", ["num_strings", "capacity_kwp"])
def test_population_capacity_not_consumed(
    authority: a.SiteStringSeriesCountAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    field: str,
) -> None:
    changed = (
        site.model_copy(update={"capacity_kwp": 1.0})
        if field == "capacity_kwp"
        else site.model_copy(update={"module": site.module.model_copy(update={"num_strings": 1})})
    )
    before = m.serialize_site_evidence_manifest(manifest)
    a.validate_site_string_series_count_binding(manifest, authority, changed)
    assert m.serialize_site_evidence_manifest(manifest) == before
    assert site.electrical_topology is None


def test_guarded_binding(
    authority: a.SiteStringSeriesCountAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = m.serialize_site_evidence_manifest(manifest)
    original_site = SiteConfig.__getattribute__
    original_module = ModuleConfig.__getattribute__

    def guarded_site(self: SiteConfig, name: str) -> Any:
        if name not in {"id", "name", "module", "__class__"}:
            raise AssertionError(f"excluded SiteConfig field read: {name}")
        return original_site(self, name)

    def guarded_module(self: ModuleConfig, name: str) -> Any:
        if name not in {"modules_per_string", "__class__"}:
            raise AssertionError(f"excluded ModuleConfig field read: {name}")
        return original_module(self, name)

    monkeypatch.setattr(SiteConfig, "__getattribute__", guarded_site)
    monkeypatch.setattr(ModuleConfig, "__getattribute__", guarded_module)
    a.validate_site_string_series_count_binding(manifest, authority, site)
    assert m.serialize_site_evidence_manifest(manifest) == before


def test_no_physics_runtime_or_topology_dependency() -> None:
    tree = ast.parse(
        (ROOT / "src/heliotelligence/engine/site_string_series_count_authority.py").read_text()
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
    forbidden = {"StringConfig", "MPPTConfig", "ElectricalTopologyConfig", "InverterUnitConfig"}
    assert not {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}.intersection(forbidden)
