"""P2F label inventory governance must not become equipment/topology authority."""

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

from heliotelligence.config.site import (
    InverterConfig,
    InverterGroupConfig,
    SiteConfig,
    SiteLayoutConfig,
    load_sites,
)
from heliotelligence.engine import site_evidence_manifest as m
from heliotelligence.engine import site_inverter_inventory_authority as a

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = "evidence/authorities/bracon-ash/inverter-inventory.yaml"
EXPECTED = tuple(
    (group_id, tuple(f"{group_id}-TB{number}" for number in range(start, end + 1)))
    for group_id, start, end in (
        ("MQA11", 101, 116),
        ("MQA21", 101, 116),
        ("MQA22", 201, 217),
        ("MQA23", 301, 317),
    )
)
EXCLUDED = (
    "model_ref",
    "inverter_model",
    "cec_sam_reference",
    "sandia_coefficients",
    "pvwatts_parameters",
    "eta_nom",
    "pnom_kwac",
    "smax",
    "p_q_limits",
    "thermal_limits",
    "grid_limit_kwac",
    "wiring_loss_ac_pct",
    "mppt_ids",
    "string_ids",
    "string_membership",
    "modules_per_string",
    "branch_resistance",
    "electrical_topology",
    "module_population",
    "centre_lat",
    "centre_lon",
    "label",
    "controller_requests",
    "controller_modes",
    "dispatch_setpoints",
)


@pytest.fixture
def authority() -> a.SiteInverterInventoryAuthority:
    return a.load_site_inverter_inventory_authority(ROOT / REFERENCE)


@pytest.fixture
def manifest() -> m.SiteEvidenceManifest:
    return m.load_site_evidence_manifest(ROOT / "evidence/sites/bracon-ash.yaml")


@pytest.fixture
def site() -> SiteConfig:
    return load_sites(ROOT / "config/sites.yaml")[0]


def test_reviewed_inventory(
    authority: a.SiteInverterInventoryAuthority, manifest: m.SiteEvidenceManifest, site: SiteConfig
) -> None:
    assert (authority.site_config_id, authority.site_uuid, authority.site_name) == (
        "site-001",
        str(uuid5(NAMESPACE_DNS, "site-001")),
        "Bracon Ash",
    )
    assert authority.configured_inverter_count == 66
    assert tuple((g.group_id, g.inverter_ids) for g in authority.groups) == EXPECTED
    assert [len(g.inverter_ids) for g in authority.groups] == [16, 16, 17, 17]
    assert len({g.group_id for g in authority.groups}) == 4
    labels = tuple(i for g in authority.groups for i in g.inverter_ids)
    assert len(labels) == len(set(labels)) == 66
    assert (
        authority.contract == "explicit_reviewed_configured_inverter_label_inventory_authority_v1"
    )
    assert (
        authority.model
        == "configured_inverter_ids_and_layout_group_membership_lower_fidelity_basis_v1"
    )
    assert authority.scope == (
        "configured_site_inverter_identity_inventory_before_"
        "electrical_topology_and_equipment_binding"
    )
    assert (
        authority.coverage_scope
        == "single_site_configured_inverter_labels_and_layout_group_membership_only"
    )
    assert authority.supported_fidelity == m.LOWER_SUPPORT
    assert authority.temporal_semantics == "unknown"
    assert authority.confidence == "unknown"
    assert authority.authority_version == "bracon-ash-configured-inverter-inventory-v1"
    assert authority.authority_reference == REFERENCE
    assert authority.evidence_source_references == ("config/sites.yaml",)
    a.validate_site_inverter_inventory_authority(authority)
    a.validate_site_inverter_inventory_binding(manifest, authority, site)
    assert site.electrical_topology is None


def test_exact_schema_and_frozen(authority: a.SiteInverterInventoryAuthority) -> None:
    assert {f.name for f in fields(authority)} == {
        "site_config_id",
        "site_uuid",
        "site_name",
        "configured_inverter_count",
        "groups",
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
    assert {f.name for f in fields(a.ConfiguredInverterInventoryGroup)} == {
        "group_id",
        "inverter_ids",
    }
    for obj in (authority, authority.groups[0]):
        for f in fields(obj):
            with pytest.raises(FrozenInstanceError):
                setattr(obj, f.name, None)
    with pytest.raises(ValueError):
        a.validate_site_inverter_inventory_authority({})  # type: ignore[arg-type]
    wire = a.serialize_site_inverter_inventory_authority(authority)
    for name in EXCLUDED:
        with pytest.raises(ValueError):
            a.deserialize_site_inverter_inventory_authority(dict(wire, **{name: 1}))
        changed = copy.deepcopy(wire)
        changed["groups"][0][name] = 1
        with pytest.raises(ValueError):
            a.deserialize_site_inverter_inventory_authority(changed)


@pytest.mark.parametrize(
    "bad", [True, False, 0, -1, 66.0, "66", None, float("nan"), float("inf"), 65, 67]
)
def test_invalid_count(authority: a.SiteInverterInventoryAuthority, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, configured_inverter_count=bad)
    wire = a.serialize_site_inverter_inventory_authority(authority)
    wire["configured_inverter_count"] = bad
    with pytest.raises(ValueError):
        a.deserialize_site_inverter_inventory_authority(wire)


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
@pytest.mark.parametrize("bad", ["", " padded", "padded ", True, 1, None])
def test_exact_strings(authority: a.SiteInverterInventoryAuthority, name: str, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, **{name: bad})


@pytest.mark.parametrize(
    "bad", ["site-001", "5AB83B40-553C-5DDD-976F-71F6CB5D490F", str(uuid5(NAMESPACE_DNS, "other"))]
)
def test_uuid(authority: a.SiteInverterInventoryAuthority, bad: str) -> None:
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
        ("other",),
        (1,),
    ],
)
def test_sources(authority: a.SiteInverterInventoryAuthority, bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, evidence_source_references=bad)


@pytest.mark.parametrize(
    "group_id,ids",
    [
        ("", ("A",)),
        (" padded", ("A",)),
        ("G", ()),
        ("G", ["A"]),
        ("G", ("A", "A")),
        ("G", (" A",)),
        ("G", (1,)),
        (None, ("A",)),
    ],
)
def test_invalid_group(group_id: Any, ids: Any) -> None:
    with pytest.raises(ValueError):
        a.ConfiguredInverterInventoryGroup(group_id, ids)


def test_group_inventory_consistency(authority: a.SiteInverterInventoryAuthority) -> None:
    for bad in ((), list(authority.groups), (None,), (*authority.groups, authority.groups[0])):
        with pytest.raises(ValueError):
            replace(authority, groups=bad)  # type: ignore[arg-type]
    first, second, *rest = authority.groups
    repeated_group = replace(second, group_id=first.group_id)
    repeated_label = replace(second, inverter_ids=(first.inverter_ids[0], *second.inverter_ids[1:]))
    for changed in (repeated_group, repeated_label):
        with pytest.raises(ValueError):
            replace(authority, groups=(first, changed, *rest))
    with pytest.raises(ValueError):
        replace(authority, groups=authority.groups[:-1])
    # The generic contract does not hard-code Bracon or 66; the reviewed file/binding does.
    synthetic = replace(
        authority,
        configured_inverter_count=1,
        groups=(a.ConfiguredInverterInventoryGroup("test-group", ("test-inverter",)),),
    )
    a.validate_site_inverter_inventory_authority(synthetic)


def test_confidence_is_provenance(authority: a.SiteInverterInventoryAuthority) -> None:
    for confidence in ("high", "medium", "low", "unknown"):
        changed = replace(authority, confidence=confidence)
        a.validate_site_inverter_inventory_authority(changed)
        assert changed.groups == authority.groups
        assert changed.supported_fidelity == m.LOWER_SUPPORT
    with pytest.raises(ValueError):
        replace(authority, confidence="certain")


def test_roundtrip_and_order(authority: a.SiteInverterInventoryAuthority) -> None:
    wire = a.serialize_site_inverter_inventory_authority(authority)
    assert (
        a.deserialize_site_inverter_inventory_authority(
            json.loads(json.dumps(wire, allow_nan=False))
        )
        == authority
    )
    assert a.serialize_site_inverter_inventory_authority(authority) == wire
    assert (
        a.deserialize_site_inverter_inventory_authority(dict(reversed(tuple(wire.items()))))
        == authority
    )
    for key, value in (
        ("groups", authority.groups),
        ("evidence_source_references", authority.evidence_source_references),
        ("unknown", 1),
    ):
        with pytest.raises(ValueError):
            a.deserialize_site_inverter_inventory_authority(dict(wire, **{key: value}))
    for mutation in ("ids_tuple", "missing", "unknown", "duplicate"):
        changed = copy.deepcopy(wire)
        if mutation == "ids_tuple":
            changed["groups"][0]["inverter_ids"] = authority.groups[0].inverter_ids
        elif mutation == "missing":
            del changed["groups"][0]["group_id"]
        elif mutation == "unknown":
            changed["groups"][0]["extra"] = 1
        else:
            changed["groups"][1]["inverter_ids"][0] = changed["groups"][0]["inverter_ids"][0]
        with pytest.raises(ValueError):
            a.deserialize_site_inverter_inventory_authority(changed)


@pytest.mark.parametrize("name", [f.name for f in fields(a.SiteInverterInventoryAuthority)])
def test_all_public_field_tampering(authority: a.SiteInverterInventoryAuthority, name: str) -> None:
    wire = a.serialize_site_inverter_inventory_authority(authority)
    del wire[name]
    with pytest.raises(ValueError):
        a.deserialize_site_inverter_inventory_authority(wire)
    object.__setattr__(authority, name, None)
    with pytest.raises(ValueError):
        a.validate_site_inverter_inventory_authority(authority)
    with pytest.raises(ValueError):
        a.serialize_site_inverter_inventory_authority(authority)


@pytest.mark.parametrize("name", ["group_id", "inverter_ids"])
def test_nested_frozen_revalidation(authority: a.SiteInverterInventoryAuthority, name: str) -> None:
    object.__setattr__(authority.groups[0], name, None)
    with pytest.raises(ValueError):
        a.validate_site_inverter_inventory_authority(authority)
    with pytest.raises(ValueError):
        a.serialize_site_inverter_inventory_authority(authority)
    with pytest.raises(ValueError):
        replace(authority)


@pytest.mark.parametrize(
    "name",
    ["contract", "model", "scope", "coverage_scope", "supported_fidelity", "temporal_semantics"],
)
def test_fixed_wire_semantics(authority: a.SiteInverterInventoryAuthority, name: str) -> None:
    wire = a.serialize_site_inverter_inventory_authority(authority)
    wire[name] = "forged"
    with pytest.raises(ValueError):
        a.deserialize_site_inverter_inventory_authority(wire)


def test_strict_yaml(authority: a.SiteInverterInventoryAuthority, tmp_path: Path) -> None:
    wire = a.serialize_site_inverter_inventory_authority(authority)
    path = tmp_path / "inventory.yaml"
    for name in (*wire, *EXCLUDED, "unknown"):
        raw = dict(wire)
        if name in wire:
            del raw[name]
        else:
            raw[name] = 1
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError):
            a.load_site_inverter_inventory_authority(path)
    for text in (
        (ROOT / REFERENCE).read_text() + "\nconfigured_inverter_count: 66\n",
        "groups:\n- group_id: A\n  group_id: B",
    ):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate"):
            a.load_site_inverter_inventory_authority(path)
    for text in ("null", "[]", "!!python/object/apply:os.system ['false']"):
        path.write_text(text, encoding="utf-8")
        with pytest.raises((ValueError, yaml.YAMLError)):
            a.load_site_inverter_inventory_authority(path)


def test_independent_validator(
    authority: a.SiteInverterInventoryAuthority, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper called")

    for name in (
        "_admit",
        "_admit_group",
        "_text",
        "_unique_mapping",
        "load_site_inverter_inventory_authority",
        "serialize_site_inverter_inventory_authority",
        "deserialize_site_inverter_inventory_authority",
        "validate_site_inverter_inventory_binding",
    ):
        monkeypatch.setattr(a, name, disabled)
    monkeypatch.setattr(a.SiteInverterInventoryAuthority, "__post_init__", disabled)
    monkeypatch.setattr(a.ConfiguredInverterInventoryGroup, "__post_init__", disabled)
    a.validate_site_inverter_inventory_authority(authority)
    for f in fields(authority):
        changed = copy.deepcopy(authority)
        object.__setattr__(changed, f.name, None)
        with pytest.raises(ValueError):
            a.validate_site_inverter_inventory_authority(changed)
    for name in ("group_id", "inverter_ids"):
        changed = copy.deepcopy(authority)
        object.__setattr__(changed.groups[0], name, None)
        with pytest.raises(ValueError):
            a.validate_site_inverter_inventory_authority(changed)


@pytest.mark.parametrize(
    "kind",
    [
        "id",
        "name",
        "count",
        "group_id",
        "group_count",
        "member",
        "duplicate",
        "group_order",
        "member_order",
        "missing_layout",
    ],
)
def test_config_binding_drift(
    authority: a.SiteInverterInventoryAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    kind: str,
) -> None:
    changed = site.model_copy(deep=True)
    assert changed.layout is not None
    if kind in ("id", "name"):
        setattr(changed, kind, "Other")
    elif kind == "count":
        changed.inverter.num_units = 65
    elif kind == "group_id":
        changed.layout.inverter_groups[0].id = "Other"
    elif kind == "group_count":
        changed.layout.inverter_groups[0].inverter_count = 15
    elif kind == "member":
        changed.layout.inverter_groups[0].inverters[0] = "Other"
    elif kind == "duplicate":
        changed.layout.inverter_groups[1].inverters[0] = changed.layout.inverter_groups[
            0
        ].inverters[0]
    elif kind == "group_order":
        changed.layout.inverter_groups.reverse()
    elif kind == "member_order":
        changed.layout.inverter_groups[0].inverters.reverse()
    else:
        changed.layout = None
    with pytest.raises(ValueError):
        a.validate_site_inverter_inventory_binding(manifest, authority, changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "Other"),
        ("pvlib_model", "sandia"),
        ("pnom_kwac", 1.0),
        ("eta_nom", 0.1),
        ("grid_limit_kwac", 1.0),
        ("wiring_loss_ac_pct", 0.1),
        ("capacity_kwp", 1.0),
        ("module", None),
        ("electrical_topology", "not inventory"),
        ("label", "Other"),
        ("centre_lat", 1.0),
        ("centre_lon", 1.0),
    ],
)
def test_excluded_fields_do_not_affect_binding(
    authority: a.SiteInverterInventoryAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    field: str,
    value: Any,
) -> None:
    if field in ("capacity_kwp", "module", "electrical_topology"):
        changed = site.model_copy(update={field: value})
    elif field in ("label", "centre_lat", "centre_lon"):
        assert site.layout is not None
        groups = [
            site.layout.inverter_groups[0].model_copy(update={field: value}),
            *site.layout.inverter_groups[1:],
        ]
        changed = site.model_copy(
            update={"layout": site.layout.model_copy(update={"inverter_groups": groups})}
        )
    else:
        changed = site.model_copy(
            update={"inverter": site.inverter.model_copy(update={field: value})}
        )
    a.validate_site_inverter_inventory_binding(manifest, authority, changed)


def test_guarded_config_access(
    authority: a.SiteInverterInventoryAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert site.electrical_topology is None
    before = m.serialize_site_evidence_manifest(manifest)
    for cls, allowed in (
        (SiteConfig, {"id", "name", "inverter", "layout", "__class__"}),
        (InverterConfig, {"num_units", "__class__"}),
        (SiteLayoutConfig, {"inverter_groups", "__class__"}),
        (InverterGroupConfig, {"id", "inverters", "inverter_count", "__class__"}),
    ):
        original = cls.__getattribute__

        def guard(
            self: Any, name: str, _allowed: set[str] = allowed, _original: Any = original
        ) -> Any:
            if name not in _allowed:
                raise AssertionError(f"excluded configuration access: {name}")
            return _original(self, name)

        monkeypatch.setattr(cls, "__getattribute__", guard)
    a.validate_site_inverter_inventory_binding(manifest, authority, site)
    assert m.serialize_site_evidence_manifest(manifest) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"supported_fidelity": m.FULL_SUPPORT},
        {"authority_binding_reference": "other"},
        {"admitted_authority_contract_ids": ("other",)},
        {"source_references": ("other",), "facts": ()},
        {"temporal_scope": m.EvidenceTemporalScope("static")},
        {"physical_scope": m.PhysicalEvidenceScope("asset_set", ("MQA11",))},
    ],
)
def test_manifest_binding_drift(
    authority: a.SiteInverterInventoryAuthority,
    manifest: m.SiteEvidenceManifest,
    site: SiteConfig,
    changes: dict[str, Any],
) -> None:
    changed = replace(
        manifest,
        items=tuple(
            replace(i, **changes) if i.requirement_id == a.INVERTER_INVENTORY_REQUIREMENT_ID else i
            for i in manifest.items
        ),
    )
    with pytest.raises(ValueError):
        a.validate_site_inverter_inventory_binding(changed, authority, site)


def test_valid_shaped_edits_require_binding(
    authority: a.SiteInverterInventoryAuthority, manifest: m.SiteEvidenceManifest, site: SiteConfig
) -> None:
    for changed in (
        replace(authority, groups=tuple(reversed(authority.groups))),
        replace(authority, authority_reference="other"),
        replace(authority, site_name="Other"),
    ):
        a.validate_site_inverter_inventory_authority(changed)
        with pytest.raises(ValueError):
            a.validate_site_inverter_inventory_binding(manifest, changed, site)


def test_no_physics_or_topology_construction() -> None:
    tree = ast.parse(
        (ROOT / "src/heliotelligence/engine/site_inverter_inventory_authority.py").read_text()
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
    assert not {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}.intersection(
        {"ElectricalTopologyConfig", "InverterUnitConfig", "MPPTConfig", "StringConfig"}
    )
