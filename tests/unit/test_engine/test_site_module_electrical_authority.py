"""Controlled P2C configured basis; no installed-population or runtime admission."""

from __future__ import annotations

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
from heliotelligence.engine import site_module_electrical_authority as a
from heliotelligence.physics.module_lookup import resolve_module_params

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = "evidence/authorities/bracon-ash/module-electrical-basis.yaml"
LIBRARY = ROOT / "src/heliotelligence/data/module_library.yaml"
PARAMETERS = {
    "pnom_wp": ("pnom_wp", 570.0),
    "v_mp_v": ("v_mp", 41.64),
    "i_mp_a": ("i_mp", 13.69),
    "v_oc_v": ("v_oc", 50.60),
    "i_sc_a": ("i_sc", 14.36),
    "alpha_sc_pct_per_c": ("alpha_sc", 0.045),
    "beta_voc_pct_per_c": ("beta_voc", -0.25),
    "gamma_pmp_pct_per_c": ("gamma_pmp", -0.29),
}
EXCLUDED = (
    "bifaciality_factor",
    "u_c",
    "u_v",
    "noct_c",
    "soiling_loss_pct",
    "lid_loss_pct",
    "mismatch_loss_pct",
    "wiring_loss_dc_pct",
    "module_count",
    "num_strings",
    "num_tables",
    "modules_per_string",
    "geometry",
    "electrical_topology",
    "mppt_mapping",
    "flash_distribution",
    "substring_topology",
    "bypass_diode_data",
    "capacity_kwp",
)


@pytest.fixture
def authority() -> a.SiteModuleElectricalAuthority:
    return a.load_site_module_electrical_authority(ROOT / REFERENCE)


@pytest.fixture
def manifest() -> m.SiteEvidenceManifest:
    return m.load_site_evidence_manifest(ROOT / "evidence/sites/bracon-ash.yaml")


@pytest.fixture
def site() -> SiteConfig:
    return load_sites(ROOT / "config/sites.yaml")[0]


def test_reviewed_basis(
    authority: a.SiteModuleElectricalAuthority, manifest: m.SiteEvidenceManifest, site: SiteConfig
) -> None:
    assert (authority.site_config_id, authority.site_uuid, authority.site_name) == (
        "site-001",
        str(uuid5(NAMESPACE_DNS, "site-001")),
        "Bracon Ash",
    )
    assert authority.module_model_label == "JKM570N-72HL4-BDV"
    assert authority.technology == "mono_si"
    assert (authority.parameter_source, authority.fit_quality) == ("datasheet_fit", "low")
    assert (authority.expected_lookup_tier, authority.expected_lookup_source) == (
        3,
        "local_library",
    )
    for name, (_, value) in PARAMETERS.items():
        assert getattr(authority, name) == value
    assert authority.cells_in_series == 144
    assert authority.confidence == "unknown"
    assert authority.authority_version == "bracon-ash-configured-module-electrical-basis-v1"
    assert authority.authority_reference == REFERENCE
    assert authority.evidence_source_references == (
        "config/sites.yaml",
        "src/heliotelligence/data/module_library.yaml",
    )
    assert authority.contract == "explicit_reviewed_configured_module_electrical_basis_authority_v1"
    assert authority.model == "tier3_low_fit_datasheet_module_electrical_basis_v1"
    assert authority.scope == (
        "configured_site_module_model_and_electrical_parameter_basis_before_population_and_topology_binding"
    )
    assert (
        authority.coverage_scope
        == "single_site_configured_model_class_low_fit_stc_parameter_basis_only"
    )
    assert authority.supported_fidelity == m.LOWER_SUPPORT
    assert authority.temporal_semantics == "unknown"
    a.validate_site_module_electrical_authority(authority)
    a.validate_site_module_electrical_binding(manifest, authority, site, LIBRARY)


def test_canonical_runtime_lookup(site: SiteConfig) -> None:
    # Real pinned CEC/library lookup: no monkeypatch forcing Tier 3.
    resolved = resolve_module_params(site.module)
    assert (resolved["tier"], resolved["source"], resolved["fit_quality"]) == (
        3,
        "local_library",
        "low",
    )
    for _, (key, value) in PARAMETERS.items():
        assert resolved["params"][key] == value
    assert resolved["params"]["cells_in_series"] == 144


def test_frozen_exact_type_and_exclusions(authority: a.SiteModuleElectricalAuthority) -> None:
    names = {f.name for f in fields(authority)}
    assert not names.intersection(EXCLUDED)
    for f in fields(authority):
        with pytest.raises(FrozenInstanceError):
            setattr(authority, f.name, None)
    with pytest.raises(ValueError):
        a.validate_site_module_electrical_authority({})  # type: ignore[arg-type]
    for name in EXCLUDED:
        wire = a.serialize_site_module_electrical_authority(authority)
        wire[name] = 1
        with pytest.raises(ValueError):
            a.deserialize_site_module_electrical_authority(wire)


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
        "parameter_source",
        "fit_quality",
        "expected_lookup_source",
    ],
)
@pytest.mark.parametrize("bad", ["", " padded", "padded ", True, 1, None])
def test_invalid_strings(authority: a.SiteModuleElectricalAuthority, name: str, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, **{name: bad})


@pytest.mark.parametrize(
    "bad", ["site-001", "5AB83B40-553C-5DDD-976F-71F6CB5D490F", str(uuid5(NAMESPACE_DNS, "other"))]
)
def test_uuid(authority: a.SiteModuleElectricalAuthority, bad: str) -> None:
    with pytest.raises(ValueError):
        replace(authority, site_uuid=bad)


@pytest.mark.parametrize("name", list(PARAMETERS))
@pytest.mark.parametrize(
    "bad", [True, False, "1", None, float("nan"), float("inf"), -float("inf"), 10**400]
)
def test_invalid_numeric(authority: a.SiteModuleElectricalAuthority, name: str, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, **{name: bad})


@pytest.mark.parametrize("name", ["pnom_wp", "v_mp_v", "i_mp_a", "v_oc_v", "i_sc_a"])
@pytest.mark.parametrize("bad", [0, -1])
def test_positive_stc(authority: a.SiteModuleElectricalAuthority, name: str, bad: int) -> None:
    changes: dict[str, Any] = {name: bad}
    with pytest.raises(ValueError):
        replace(authority, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"v_oc_v": 40.0},
        {"i_sc_a": 13.0},
        {"expected_lookup_tier": True},
        {"expected_lookup_tier": 3.0},
        {"expected_lookup_tier": 2},
        {"parameter_source": "manufacturer"},
        {"fit_quality": "high"},
        {"expected_lookup_source": "cec_auto"},
        {"confidence": "certain"},
    ],
)
def test_inconsistent_semantics(
    authority: a.SiteModuleElectricalAuthority, changes: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        replace(authority, **changes)


@pytest.mark.parametrize("bad", [0, -1, 144.0, True, "144", None])
def test_cells(authority: a.SiteModuleElectricalAuthority, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, cells_in_series=bad)


@pytest.mark.parametrize("bad", [(), ("",), (" padded",), ("x", "x"), ["x"], (1,)])
def test_references(authority: a.SiteModuleElectricalAuthority, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, evidence_source_references=bad)


def test_confidence_not_fit_quality(authority: a.SiteModuleElectricalAuthority) -> None:
    for confidence in ("high", "medium", "low", "unknown"):
        changed = replace(authority, confidence=confidence)
        a.validate_site_module_electrical_authority(changed)
        assert changed.fit_quality == "low"
        assert changed.supported_fidelity == m.LOWER_SUPPORT


def test_roundtrip(authority: a.SiteModuleElectricalAuthority) -> None:
    wire = a.serialize_site_module_electrical_authority(authority)
    assert (
        a.deserialize_site_module_electrical_authority(
            json.loads(json.dumps(wire, allow_nan=False))
        )
        == authority
    )
    assert a.serialize_site_module_electrical_authority(authority) == wire
    assert (
        a.deserialize_site_module_electrical_authority(dict(reversed(tuple(wire.items()))))
        == authority
    )
    wire["evidence_source_references"] = ("config/sites.yaml",)
    with pytest.raises(ValueError):
        a.deserialize_site_module_electrical_authority(wire)


@pytest.mark.parametrize("name", [f.name for f in fields(a.SiteModuleElectricalAuthority)])
def test_wire_missing_and_frozen_tamper(
    authority: a.SiteModuleElectricalAuthority, name: str
) -> None:
    wire = a.serialize_site_module_electrical_authority(authority)
    del wire[name]
    with pytest.raises(ValueError):
        a.deserialize_site_module_electrical_authority(wire)
    object.__setattr__(authority, name, None)
    with pytest.raises(ValueError):
        a.validate_site_module_electrical_authority(authority)
    with pytest.raises(ValueError):
        a.serialize_site_module_electrical_authority(authority)


@pytest.mark.parametrize(
    "name",
    [
        "contract",
        "model",
        "scope",
        "coverage_scope",
        "supported_fidelity",
        "temporal_semantics",
        "parameter_source",
        "fit_quality",
        "expected_lookup_source",
    ],
)
def test_wire_fixed_tamper(authority: a.SiteModuleElectricalAuthority, name: str) -> None:
    wire = a.serialize_site_module_electrical_authority(authority)
    wire[name] = "forged"
    with pytest.raises(ValueError):
        a.deserialize_site_module_electrical_authority(wire)


def test_strict_yaml(authority: a.SiteModuleElectricalAuthority, tmp_path: Path) -> None:
    wire = a.serialize_site_module_electrical_authority(authority)
    path = tmp_path / "authority.yaml"
    for name in (*wire, "unknown", *EXCLUDED):
        raw = dict(wire)
        if name in wire:
            del raw[name]
        else:
            raw[name] = 1
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError):
            a.load_site_module_electrical_authority(path)
    for text in (
        (ROOT / REFERENCE).read_text() + "\nsite_name: duplicate\n",
        "modules:\n  x: 1\n  x: 2\n",
    ):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate"):
            a.load_site_module_electrical_authority(path)
    for text in ("null", "[]", "!!python/object/apply:os.system ['false']"):
        path.write_text(text, encoding="utf-8")
        with pytest.raises((ValueError, yaml.YAMLError)):
            a.load_site_module_electrical_authority(path)


def test_independent_validator(
    authority: a.SiteModuleElectricalAuthority, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production admission called")

    for name in (
        "_admit",
        "_text",
        "_numeric",
        "_read_yaml",
        "load_site_module_electrical_authority",
        "serialize_site_module_electrical_authority",
        "deserialize_site_module_electrical_authority",
    ):
        monkeypatch.setattr(a, name, disabled)
    monkeypatch.setattr(a.SiteModuleElectricalAuthority, "__post_init__", disabled)
    a.validate_site_module_electrical_authority(authority)
    for f in fields(authority):
        forged = copy.deepcopy(authority)
        object.__setattr__(forged, f.name, None)
        with pytest.raises(ValueError):
            a.validate_site_module_electrical_authority(forged)


@pytest.mark.parametrize(
    "name,bad",
    [("id", "other"), ("name", "Other"), ("local_module_name", "other"), ("technology", "poly_si")],
)
def test_config_drift(
    authority: a.SiteModuleElectricalAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    name: str,
    bad: str,
) -> None:
    changed = (
        site.model_copy(update={name: bad})
        if name in ("id", "name")
        else site.model_copy(update={"module": site.module.model_copy(update={name: bad})})
    )
    with pytest.raises(ValueError):
        a.validate_site_module_electrical_binding(manifest, authority, changed, LIBRARY)


@pytest.mark.parametrize(
    "key,bad",
    [
        ("model", "other"),
        ("technology", "poly_si"),
        ("source", "certified"),
        ("fit_quality", "high"),
        ("cells_in_series", 145),
        ("cells_in_series", True),
        *((key, value + 0.001) for key, value in PARAMETERS.values()),
        ("i_sc", True),
    ],
)
def test_library_drift(
    authority: a.SiteModuleElectricalAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    tmp_path: Path,
    key: str,
    bad: Any,
) -> None:
    raw = yaml.safe_load(LIBRARY.read_text())
    raw["modules"][authority.module_model_label][key] = bad
    path = tmp_path / "explicit-library.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        a.validate_site_module_electrical_binding(manifest, authority, site, path)


def test_library_missing_model_and_duplicate(
    authority: a.SiteModuleElectricalAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    tmp_path: Path,
) -> None:
    path = tmp_path / "explicit-library.yaml"
    for text in ("modules: {}", "modules:\n  x: {}\n  x: {}\n"):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            a.validate_site_module_electrical_binding(manifest, authority, site, path)


@pytest.mark.parametrize("key", a.MODULE_REQUIREMENT_IDS)
@pytest.mark.parametrize(
    "changes",
    [
        {"source_references": ("config/sites.yaml",), "facts": ()},
        {"supported_fidelity": m.FULL_SUPPORT},
        {"authority_binding_reference": "other"},
        {"admitted_authority_contract_ids": ("other",)},
        {"temporal_scope": m.EvidenceTemporalScope("static")},
        {"physical_scope": m.PhysicalEvidenceScope("site", ("site-001",))},
        {
            "admission_state": "not_admitted",
            "admitted_authority_contract_ids": (),
            "authority_binding_reference": None,
            "gap_reason_codes": ("not_admitted",),
        },
    ],
)
def test_manifest_binding_details(
    authority: a.SiteModuleElectricalAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    key: str,
    changes: dict[str, Any],
) -> None:
    items = tuple(replace(i, **changes) if i.requirement_id == key else i for i in manifest.items)
    changed = replace(manifest, items=items)
    with pytest.raises(ValueError):
        a.validate_site_module_electrical_binding(changed, authority, site, LIBRARY)


def test_manifest_identity_drift(
    authority: a.SiteModuleElectricalAuthority, manifest: m.SiteEvidenceManifest, site: SiteConfig
) -> None:
    changed = replace(manifest, identity=replace(manifest.identity, site_name="Other"))
    with pytest.raises(ValueError):
        a.validate_site_module_electrical_binding(changed, authority, site, LIBRARY)


@pytest.mark.parametrize(
    "name,value",
    [
        ("pnom_wp", 571.0),
        ("module_model_label", "other"),
        ("evidence_source_references", ("other",)),
        ("site_name", "Other"),
    ],
)
def test_valid_shaped_authority_edits_require_source_binding(
    authority: a.SiteModuleElectricalAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    name: str,
    value: Any,
) -> None:
    # Serialization is structural validation, not cryptographic authentication.
    changed = replace(authority, **{name: value})
    a.validate_site_module_electrical_authority(changed)
    with pytest.raises(ValueError):
        a.validate_site_module_electrical_binding(manifest, changed, site, LIBRARY)


def test_excluded_configuration_not_consumed(
    authority: a.SiteModuleElectricalAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert site.electrical_topology is None
    before = m.serialize_site_evidence_manifest(manifest)
    changed = site.model_copy(update={"capacity_kwp": 1.0, "electrical_topology": "not authority"})
    site_get = SiteConfig.__getattribute__
    module_get = ModuleConfig.__getattribute__

    def guarded_site(self: SiteConfig, name: str) -> Any:
        if name not in {"id", "name", "module", "__class__"}:
            raise AssertionError(f"excluded SiteConfig access: {name}")
        return site_get(self, name)

    def guarded_module(self: ModuleConfig, name: str) -> Any:
        if name not in {"local_module_name", "technology", "__class__"}:
            raise AssertionError(f"excluded module config access: {name}")
        return module_get(self, name)

    monkeypatch.setattr(SiteConfig, "__getattribute__", guarded_site)
    monkeypatch.setattr(ModuleConfig, "__getattribute__", guarded_module)
    a.validate_site_module_electrical_binding(manifest, authority, changed, LIBRARY)
    assert m.serialize_site_evidence_manifest(manifest) == before
    population = next(
        i for i in manifest.items if i.requirement_id == "site.population.module_count"
    )
    assert (population.evidence_state, population.admission_state) == ("conflicting", "blocked")
    assert [f.value for f in population.facts if f.fact_id.endswith("module_count")] == [
        "49824",
        "47448",
        "50736",
    ]


@pytest.mark.parametrize(
    "name,bad",
    [
        ("site_uuid", "site-001"),
        ("pnom_wp", True),
        ("v_oc_v", float("nan")),
        ("i_sc_a", float("inf")),
        ("expected_lookup_tier", 2),
        ("cells_in_series", 144.0),
        ("evidence_source_references", [" padded"]),
        ("unknown", 1),
    ],
)
def test_wire_invalid_values(
    authority: a.SiteModuleElectricalAuthority, name: str, bad: Any
) -> None:
    wire = a.serialize_site_module_electrical_authority(authority)
    wire[name] = bad
    with pytest.raises(ValueError):
        a.deserialize_site_module_electrical_authority(wire)


@pytest.mark.parametrize("key", a.MODULE_REQUIREMENT_IDS)
def test_both_manifest_requirements_required(
    authority: a.SiteModuleElectricalAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    key: str,
) -> None:
    forged = copy.deepcopy(manifest)
    object.__setattr__(forged, "items", tuple(i for i in forged.items if i.requirement_id != key))
    with pytest.raises(ValueError):
        a.validate_site_module_electrical_binding(forged, authority, site, LIBRARY)


def test_no_runtime_or_physics_dependency() -> None:
    import ast

    tree = ast.parse(
        (ROOT / "src/heliotelligence/engine/site_module_electrical_authority.py").read_text()
    )
    internal = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("heliotelligence")
    }
    assert internal == {
        "heliotelligence.config.site",
        "heliotelligence.engine.site_evidence_manifest",
    }
