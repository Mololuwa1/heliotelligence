"""P2B admits only a reviewed site/configured geographic-anchor identity."""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, uuid5

import pytest
import yaml  # type: ignore[import-untyped]

from heliotelligence.config.site import SiteConfig, load_sites
from heliotelligence.engine import site_evidence_manifest as manifest_module
from heliotelligence.engine import site_physical_identity_authority as a

ROOT = Path(__file__).resolve().parents[3]
AUTHORITY_REFERENCE = "evidence/authorities/bracon-ash/site-identity.yaml"
AUTHORITY_PATH = ROOT / AUTHORITY_REFERENCE


@pytest.fixture
def authority() -> a.SitePhysicalIdentityAuthority:
    return a.load_site_physical_identity_authority(AUTHORITY_PATH)


@pytest.fixture
def manifest() -> manifest_module.SiteEvidenceManifest:
    return manifest_module.load_site_evidence_manifest(ROOT / "evidence/sites/bracon-ash.yaml")


@pytest.fixture
def site() -> SiteConfig:
    return load_sites(ROOT / "config/sites.yaml")[0]


def identity_item(
    manifest: manifest_module.SiteEvidenceManifest,
) -> manifest_module.SiteEvidenceItem:
    return next(i for i in manifest.items if i.requirement_id == a.SITE_IDENTITY_REQUIREMENT_ID)


def changed_item(
    manifest: manifest_module.SiteEvidenceManifest, **changes: Any
) -> manifest_module.SiteEvidenceManifest:
    updated = replace(identity_item(manifest), **changes)
    return replace(
        manifest,
        items=tuple(
            updated if i.requirement_id == updated.requirement_id else i for i in manifest.items
        ),
    )


def test_reviewed_bracon_authority(
    authority: a.SitePhysicalIdentityAuthority,
    manifest: manifest_module.SiteEvidenceManifest,
    site: SiteConfig,
) -> None:
    assert (authority.site_config_id, authority.site_name, authority.site_uuid) == (
        "site-001",
        "Bracon Ash",
        "5ab83b40-553c-5ddd-976f-71f6cb5d490f",
    )
    assert authority.site_uuid == str(uuid5(NAMESPACE_DNS, site.id))
    assert (
        authority.configured_latitude_deg,
        authority.configured_longitude_deg,
        authority.timezone,
    ) == (52.56, 1.21, "Europe/London")
    assert authority.evidence_source_references == ("config/sites.yaml",)
    assert authority.authority_reference == AUTHORITY_REFERENCE
    assert authority.authority_version == "bracon-ash-physical-site-identity-v1"
    assert authority.confidence == "unknown"
    assert authority.contract == a.SITE_PHYSICAL_IDENTITY_AUTHORITY_CONTRACT_ID
    assert authority.model == a.SITE_PHYSICAL_IDENTITY_AUTHORITY_MODEL_ID
    assert authority.scope == a.SITE_PHYSICAL_IDENTITY_AUTHORITY_SCOPE
    assert authority.coverage_scope == a.SITE_PHYSICAL_IDENTITY_AUTHORITY_COVERAGE_SCOPE
    a.validate_site_physical_identity_authority(authority)
    a.validate_site_physical_identity_binding(manifest, authority, site)


def test_narrow_exact_schema(authority: a.SitePhysicalIdentityAuthority) -> None:
    names = {f.name for f in fields(authority)}
    assert names == {
        "site_config_id",
        "site_uuid",
        "site_name",
        "configured_latitude_deg",
        "configured_longitude_deg",
        "timezone",
        "authority_version",
        "evidence_source_references",
        "authority_reference",
        "confidence",
        "contract",
        "model",
        "scope",
        "coverage_scope",
    }
    excluded = {
        "capacity_kwp",
        "module_count",
        "table_count",
        "string_count",
        "modules_per_string",
        "module_model",
        "inverter_model",
        "inverter_inventory",
        "electrical_topology",
        "layout",
        "mppt_mapping",
        "string_mapping",
        "cable_data",
        "transformer_data",
        "meter_identity",
        "grid_limit_kwac",
        "mismatch_loss_pct",
        "wiring_loss_dc_pct",
    }
    assert not names & excluded
    wire = a.serialize_site_physical_identity_authority(authority)
    for name in excluded:
        with pytest.raises(ValueError):
            a.deserialize_site_physical_identity_authority(dict(wire, **{name: 1}))


def test_frozen_and_exact_type(authority: a.SitePhysicalIdentityAuthority) -> None:
    for f in fields(authority):
        with pytest.raises(FrozenInstanceError):
            setattr(authority, f.name, "forged")
    with pytest.raises(ValueError):
        a.validate_site_physical_identity_authority({"site_config_id": "site-001"})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "site_config_id",
        "site_name",
        "timezone",
        "authority_version",
        "authority_reference",
        "confidence",
    ],
)
@pytest.mark.parametrize("value", ["", " padded", "padded ", None, 1, True])
def test_exact_strings(authority: a.SitePhysicalIdentityAuthority, field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, **{field: value})


@pytest.mark.parametrize(
    "value",
    [
        "site-001",
        "5AB83B40-553C-5DDD-976F-71F6CB5D490F",
        "5ab83b40553c5ddd976f71f6cb5d490f",
        str(uuid5(NAMESPACE_DNS, "different-site")),
        None,
    ],
)
def test_uuid_rejected(authority: a.SitePhysicalIdentityAuthority, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority, site_uuid=value)


def test_config_id_uuid_drift_and_no_site_hardcoding(
    authority: a.SitePhysicalIdentityAuthority,
) -> None:
    with pytest.raises(ValueError):
        replace(authority, site_config_id="different-site")
    # The generic contract requires explicit identity, never an implicit Bracon default.
    other = replace(
        authority,
        site_config_id="test-only-site",
        site_uuid=str(uuid5(NAMESPACE_DNS, "test-only-site")),
        site_name="Test-only site",
    )
    a.validate_site_physical_identity_authority(other)


@pytest.mark.parametrize(
    "field,limit", [("configured_latitude_deg", 90.0), ("configured_longitude_deg", 180.0)]
)
@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), -float("inf"), True, False, "52.56", None, 10**400]
)
def test_invalid_coordinates(
    authority: a.SitePhysicalIdentityAuthority, field: str, limit: float, bad: Any
) -> None:
    with pytest.raises(ValueError):
        replace(authority, **{field: bad})
    for outside in (limit + 0.00001, -limit - 0.00001):
        changes: dict[str, Any] = {field: outside}
        with pytest.raises(ValueError):
            replace(authority, **changes)


@pytest.mark.parametrize(
    "field,limit", [("configured_latitude_deg", 90), ("configured_longitude_deg", 180)]
)
def test_coordinate_boundaries(
    authority: a.SitePhysicalIdentityAuthority, field: str, limit: int
) -> None:
    for value in (limit, -limit, 0):
        changes: dict[str, Any] = {field: value}
        candidate = replace(authority, **changes)
        assert type(getattr(candidate, field)) is float
        a.validate_site_physical_identity_authority(candidate)


@pytest.mark.parametrize("zone", ["Invalid/Nowhere", "Europe/london", "/etc/passwd", "UTC+01:00"])
def test_invalid_timezone(authority: a.SitePhysicalIdentityAuthority, zone: str) -> None:
    with pytest.raises(ValueError):
        replace(authority, timezone=zone)


@pytest.mark.parametrize(
    "references",
    [
        (),
        ("",),
        (" config/sites.yaml",),
        ("config/sites.yaml", "config/sites.yaml"),
        ["config/sites.yaml"],
        (1,),
    ],
)
def test_invalid_evidence_references(
    authority: a.SitePhysicalIdentityAuthority, references: Any
) -> None:
    with pytest.raises(ValueError):
        replace(authority, evidence_source_references=references)


def test_confidence_is_provenance(authority: a.SitePhysicalIdentityAuthority) -> None:
    for confidence in ("high", "medium", "low", "unknown"):
        updated = replace(authority, confidence=confidence)
        assert updated.configured_latitude_deg == authority.configured_latitude_deg
        a.validate_site_physical_identity_authority(updated)
    with pytest.raises(ValueError):
        replace(authority, confidence="HIGH")


def test_json_roundtrip_and_order(authority: a.SitePhysicalIdentityAuthority) -> None:
    wire = a.serialize_site_physical_identity_authority(authority)
    assert (
        a.deserialize_site_physical_identity_authority(
            json.loads(json.dumps(wire, allow_nan=False))
        )
        == authority
    )
    assert a.serialize_site_physical_identity_authority(authority) == wire
    assert (
        a.deserialize_site_physical_identity_authority(dict(reversed(tuple(wire.items()))))
        == authority
    )
    ordered = replace(authority, evidence_source_references=("source-z", "source-a"))
    assert a.deserialize_site_physical_identity_authority(
        a.serialize_site_physical_identity_authority(ordered)
    ).evidence_source_references == ("source-z", "source-a")


@pytest.mark.parametrize("field", [f.name for f in fields(a.SitePhysicalIdentityAuthority)])
def test_missing_serialized_field(authority: a.SitePhysicalIdentityAuthority, field: str) -> None:
    wire = a.serialize_site_physical_identity_authority(authority)
    del wire[field]
    with pytest.raises(ValueError):
        a.deserialize_site_physical_identity_authority(wire)


@pytest.mark.parametrize("field", ["contract", "model", "scope", "coverage_scope"])
def test_wire_fixed_semantics(authority: a.SitePhysicalIdentityAuthority, field: str) -> None:
    wire = a.serialize_site_physical_identity_authority(authority)
    wire[field] = "forged"
    with pytest.raises(ValueError):
        a.deserialize_site_physical_identity_authority(wire)


def test_wire_other_tampering(authority: a.SitePhysicalIdentityAuthority) -> None:
    wire = a.serialize_site_physical_identity_authority(authority)
    for field, value in [
        ("site_uuid", "site-slug"),
        ("configured_latitude_deg", True),
        ("configured_longitude_deg", float("nan")),
        ("timezone", "invalid"),
        ("evidence_source_references", [" padded"]),
        ("evidence_source_references", ("config/sites.yaml",)),
        ("unknown", True),
    ]:
        with pytest.raises(ValueError):
            a.deserialize_site_physical_identity_authority(dict(wire, **{field: value}))


def test_strict_yaml(authority: a.SitePhysicalIdentityAuthority, tmp_path: Path) -> None:
    wire = a.serialize_site_physical_identity_authority(authority)
    path = tmp_path / "identity.yaml"
    for field in [f.name for f in fields(authority)]:
        raw = dict(wire)
        del raw[field]
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError):
            a.load_site_physical_identity_authority(path)
    for field in ("capacity_kwp", "electrical_topology", "unknown_field"):
        path.write_text(yaml.safe_dump(dict(wire, **{field: 1})), encoding="utf-8")
        with pytest.raises(ValueError):
            a.load_site_physical_identity_authority(path)
    path.write_text(AUTHORITY_PATH.read_text() + "\nsite_name: duplicate\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        a.load_site_physical_identity_authority(path)
    for yaml_text in ("null", "[]", "!!python/object/apply:os.system ['false']"):
        path.write_text(yaml_text, encoding="utf-8")
        with pytest.raises((ValueError, yaml.YAMLError)):
            a.load_site_physical_identity_authority(path)


@pytest.mark.parametrize("field", [f.name for f in fields(a.SitePhysicalIdentityAuthority)])
def test_every_public_field_frozen_tamper(
    authority: a.SitePhysicalIdentityAuthority, field: str
) -> None:
    object.__setattr__(authority, field, None)
    with pytest.raises(ValueError):
        a.validate_site_physical_identity_authority(authority)
    with pytest.raises(ValueError):
        a.serialize_site_physical_identity_authority(authority)


def test_independent_validator(
    authority: a.SitePhysicalIdentityAuthority, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper called")

    for name in (
        "_text",
        "_coordinate",
        "_admit_authority",
        "serialize_site_physical_identity_authority",
        "deserialize_site_physical_identity_authority",
        "load_site_physical_identity_authority",
    ):
        monkeypatch.setattr(a, name, disabled)
    monkeypatch.setattr(a.SitePhysicalIdentityAuthority, "__post_init__", disabled)
    a.validate_site_physical_identity_authority(authority)
    object.__setattr__(authority, "contract", "forged")
    with pytest.raises(ValueError):
        a.validate_site_physical_identity_authority(authority)


@pytest.mark.parametrize(
    "field,value",
    [
        ("site_config_id", "other"),
        ("site_uuid", str(uuid5(NAMESPACE_DNS, "other"))),
        ("site_name", "Another site"),
    ],
)
def test_manifest_identity_drift(
    authority: a.SitePhysicalIdentityAuthority,
    manifest: manifest_module.SiteEvidenceManifest,
    site: SiteConfig,
    field: str,
    value: str,
) -> None:
    forged = copy.deepcopy(manifest)
    object.__setattr__(forged.identity, field, value)
    with pytest.raises(ValueError):
        a.validate_site_physical_identity_binding(forged, authority, site)
    other = replace(
        manifest.identity,
        site_config_id="another-site",
        site_uuid=str(uuid5(NAMESPACE_DNS, "another-site")),
        site_name="Another site",
    )
    # A coherent, separately valid other-site manifest is still not this authority.
    other_items = tuple(
        replace(i, physical_scope=manifest_module.PhysicalEvidenceScope("site", ("another-site",)))
        if i.physical_scope.scope_type == "site"
        else i
        for i in manifest.items
    )
    other_manifest = replace(manifest, identity=other, items=other_items)
    with pytest.raises(ValueError, match="manifest identity"):
        a.validate_site_physical_identity_binding(other_manifest, authority, site)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other"),
        ("name", "Another site"),
        ("latitude", 52.560001),
        ("longitude", 1.210001),
        ("timezone", "UTC"),
        ("latitude", True),
    ],
)
def test_site_config_identity_anchor_drift(
    authority: a.SitePhysicalIdentityAuthority,
    manifest: manifest_module.SiteEvidenceManifest,
    site: SiteConfig,
    field: str,
    value: Any,
) -> None:
    with pytest.raises(ValueError):
        a.validate_site_physical_identity_binding(
            manifest, authority, site.model_copy(update={field: value})
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("site_name", "Another site"),
        ("configured_latitude_deg", 52.560001),
        ("configured_longitude_deg", 1.210001),
        ("timezone", "GB"),
        ("evidence_source_references", ("different-source",)),
        ("authority_reference", "other-reviewed-binding"),
    ],
)
def test_valid_declaration_edits_fail_exact_binding(
    authority: a.SitePhysicalIdentityAuthority,
    manifest: manifest_module.SiteEvidenceManifest,
    site: SiteConfig,
    field: str,
    value: Any,
) -> None:
    wire = a.serialize_site_physical_identity_authority(authority)
    wire[field] = list(value) if field == "evidence_source_references" else value
    changed = a.deserialize_site_physical_identity_authority(wire)
    # The format is not a signature: semantic parent binding detects valid-shaped drift.
    with pytest.raises(ValueError):
        a.validate_site_physical_identity_binding(manifest, changed, site)


@pytest.mark.parametrize(
    "changes",
    [
        {"authority_binding_reference": "different-binding"},
        {"admitted_authority_contract_ids": ("different-contract",)},
        {"source_references": ("different-source",), "facts": ()},
        {"physical_scope": manifest_module.PhysicalEvidenceScope("asset_set", ("site-001",))},
        {"temporal_scope": manifest_module.EvidenceTemporalScope("unknown")},
        {"supported_fidelity": manifest_module.LOWER_SUPPORT},
    ],
)
def test_manifest_binding_details(
    authority: a.SitePhysicalIdentityAuthority,
    manifest: manifest_module.SiteEvidenceManifest,
    site: SiteConfig,
    changes: dict[str, Any],
) -> None:
    changed = changed_item(manifest, **changes)
    with pytest.raises(ValueError):
        a.validate_site_physical_identity_binding(changed, authority, site)


def test_proposed_binding_is_not_automatic_admission(
    authority: a.SitePhysicalIdentityAuthority,
    manifest: manifest_module.SiteEvidenceManifest,
    site: SiteConfig,
) -> None:
    proposed = changed_item(
        manifest,
        admission_state="not_admitted",
        supported_fidelity=manifest_module.NON_RESOLVING,
        admitted_authority_contract_ids=(),
        authority_binding_reference=None,
        gap_reason_codes=("canonical_authority_binding_not_admitted",),
        temporal_scope=manifest_module.EvidenceTemporalScope("unknown"),
    )
    before = manifest_module.serialize_site_evidence_manifest(proposed)
    a.validate_site_physical_identity_binding(proposed, authority, site)
    assert manifest_module.serialize_site_evidence_manifest(proposed) == before
    assert proposed.diagnostics.admitted_count == 0


def test_capacity_topology_not_consumed(
    authority: a.SitePhysicalIdentityAuthority,
    manifest: manifest_module.SiteEvidenceManifest,
    site: SiteConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert site.electrical_topology is None
    modified = site.model_copy(
        update={"capacity_kwp": 1.0, "electrical_topology": {"not": "identity evidence"}}
    )
    original = SiteConfig.__getattribute__

    def guarded(self: SiteConfig, name: str) -> Any:
        if name in {"capacity_kwp", "module", "inverter", "electrical_topology", "layout"}:
            raise AssertionError("identity binding inspected excluded physical/config value")
        return original(self, name)

    monkeypatch.setattr(SiteConfig, "__getattribute__", guarded)
    a.validate_site_physical_identity_binding(manifest, authority, modified)


def test_binding_does_not_reconcile_population(
    authority: a.SitePhysicalIdentityAuthority,
    manifest: manifest_module.SiteEvidenceManifest,
    site: SiteConfig,
) -> None:
    population = next(
        i for i in manifest.items if i.requirement_id == "site.population.module_count"
    )
    before = manifest_module.serialize_site_evidence_manifest(manifest)
    a.validate_site_physical_identity_binding(manifest, authority, site)
    assert manifest_module.serialize_site_evidence_manifest(manifest) == before
    assert (population.evidence_state, population.admission_state) == ("conflicting", "blocked")
    facts = {f.fact_id: f.value for f in population.facts}
    assert [
        facts[k]
        for k in (
            "configured_string_module_count",
            "configured_table_module_count",
            "geometry_extracted_module_count",
        )
    ] == ["49824", "47448", "50736"]
