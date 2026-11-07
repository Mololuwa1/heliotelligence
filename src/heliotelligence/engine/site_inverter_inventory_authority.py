"""P2F configured inverter labels/group membership, not equipment or topology.

No conversion/capability/control authority, electrical connectivity or execution
is inferred. A declaration still requires separate reviewed source binding.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

import yaml  # type: ignore[import-untyped]

from heliotelligence.config.site import SiteConfig
from heliotelligence.engine.site_evidence_manifest import (
    LOWER_SUPPORT,
    SiteEvidenceManifest,
    validate_site_evidence_manifest,
)

SITE_INVERTER_INVENTORY_AUTHORITY_CONTRACT_ID = (
    "explicit_reviewed_configured_inverter_label_inventory_authority_v1"
)
SITE_INVERTER_INVENTORY_AUTHORITY_MODEL_ID = (
    "configured_inverter_ids_and_layout_group_membership_lower_fidelity_basis_v1"
)
SITE_INVERTER_INVENTORY_AUTHORITY_SCOPE = (
    "configured_site_inverter_identity_inventory_before_electrical_topology_and_equipment_binding"
)
SITE_INVERTER_INVENTORY_AUTHORITY_COVERAGE_SCOPE = (
    "single_site_configured_inverter_labels_and_layout_group_membership_only"
)
INVERTER_INVENTORY_REQUIREMENT_ID = "s8.inverter_inventory_binding"
_FIXED = {
    "contract": SITE_INVERTER_INVENTORY_AUTHORITY_CONTRACT_ID,
    "model": SITE_INVERTER_INVENTORY_AUTHORITY_MODEL_ID,
    "scope": SITE_INVERTER_INVENTORY_AUTHORITY_SCOPE,
    "coverage_scope": SITE_INVERTER_INVENTORY_AUTHORITY_COVERAGE_SCOPE,
    "supported_fidelity": LOWER_SUPPORT,
    "temporal_semantics": "unknown",
}


def _text(value: object) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("exact non-empty unpadded identifier required")


@dataclass(frozen=True, slots=True)
class ConfiguredInverterInventoryGroup:
    group_id: str
    inverter_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _admit_group(self)


def _admit_group(group: ConfiguredInverterInventoryGroup) -> None:
    if type(group) is not ConfiguredInverterInventoryGroup:
        raise ValueError("exact configured inventory group required")
    _text(group.group_id)
    if type(group.inverter_ids) is not tuple or not group.inverter_ids:
        raise ValueError("non-empty immutable inverter label tuple required")
    for identifier in group.inverter_ids:
        _text(identifier)
    if len(set(group.inverter_ids)) != len(group.inverter_ids):
        raise ValueError("duplicate inverter label in group")


def _admit(authority: SiteInverterInventoryAuthority) -> None:
    for value in (
        authority.site_config_id,
        authority.site_uuid,
        authority.site_name,
        authority.authority_version,
        authority.authority_reference,
        authority.confidence,
    ):
        _text(value)
    if str(UUID(authority.site_uuid)) != authority.site_uuid or authority.site_uuid != str(
        uuid5(NAMESPACE_DNS, authority.site_config_id)
    ):
        raise ValueError("canonical UUID/configuration identity mismatch")
    if (
        type(authority.configured_inverter_count) is not int
        or authority.configured_inverter_count <= 0
    ):
        raise ValueError("exact positive configured inverter count required")
    if type(authority.groups) is not tuple or not authority.groups:
        raise ValueError("non-empty immutable inventory groups required")
    for group in authority.groups:
        _admit_group(group)
    group_ids = tuple(g.group_id for g in authority.groups)
    labels = tuple(i for g in authority.groups for i in g.inverter_ids)
    if len(set(group_ids)) != len(group_ids) or len(set(labels)) != len(labels):
        raise ValueError("duplicate configured group/inverter label")
    if len(labels) != authority.configured_inverter_count:
        raise ValueError("configured label count does not close")
    refs = authority.evidence_source_references
    if (
        type(refs) is not tuple
        or len(refs) != 1
        or type(refs[0]) is not str
        or refs != ("config/sites.yaml",)
    ):
        raise ValueError("exact config/sites.yaml source tuple required")
    if authority.confidence not in ("high", "medium", "low", "unknown"):
        raise ValueError("invalid provenance confidence")
    for name, expected in _FIXED.items():
        actual = getattr(authority, name)
        if type(actual) is not str or actual != expected:
            raise ValueError("contradictory configured lower-fidelity inverter-inventory semantics")


@dataclass(frozen=True, slots=True)
class SiteInverterInventoryAuthority:
    site_config_id: str
    site_uuid: str
    site_name: str
    configured_inverter_count: int
    groups: tuple[ConfiguredInverterInventoryGroup, ...]
    authority_version: str
    evidence_source_references: tuple[str, ...]
    authority_reference: str
    confidence: str
    contract: str = field(init=False, default=SITE_INVERTER_INVENTORY_AUTHORITY_CONTRACT_ID)
    model: str = field(init=False, default=SITE_INVERTER_INVENTORY_AUTHORITY_MODEL_ID)
    scope: str = field(init=False, default=SITE_INVERTER_INVENTORY_AUTHORITY_SCOPE)
    coverage_scope: str = field(
        init=False, default=SITE_INVERTER_INVENTORY_AUTHORITY_COVERAGE_SCOPE
    )
    supported_fidelity: str = field(init=False, default=LOWER_SUPPORT)
    temporal_semantics: str = field(init=False, default="unknown")

    def __post_init__(self) -> None:
        _admit(self)


def validate_site_inverter_inventory_authority(authority: SiteInverterInventoryAuthority) -> None:
    """Independent frozen-record audit; no construction, loader or wire helpers.

    Structural validity does not authenticate a declaration. Separately validate
    the reviewed manifest/config binding before admission; no signature is claimed.
    """
    if type(authority) is not SiteInverterInventoryAuthority:
        raise ValueError("exact configured inverter-inventory authority required")
    for value in (
        authority.site_config_id,
        authority.site_uuid,
        authority.site_name,
        authority.authority_version,
        authority.authority_reference,
        authority.confidence,
    ):
        if type(value) is not str or not value or value.strip() != value:
            raise ValueError("invalid exact inverter-inventory identifier")
    if str(UUID(authority.site_uuid)) != authority.site_uuid or authority.site_uuid != str(
        uuid5(NAMESPACE_DNS, authority.site_config_id)
    ):
        raise ValueError("invalid canonical site identity")
    count = authority.configured_inverter_count
    if type(count) is not int or count <= 0:
        raise ValueError("invalid exact positive configured count")
    if type(authority.groups) is not tuple or not authority.groups:
        raise ValueError("invalid immutable groups")
    group_ids: list[str] = []
    labels: list[str] = []
    for group in authority.groups:
        if type(group) is not ConfiguredInverterInventoryGroup:
            raise ValueError("invalid exact configured group")
        if (
            type(group.group_id) is not str
            or not group.group_id
            or group.group_id.strip() != group.group_id
        ):
            raise ValueError("invalid group identifier")
        if type(group.inverter_ids) is not tuple or not group.inverter_ids:
            raise ValueError("invalid immutable label tuple")
        for identifier in group.inverter_ids:
            if type(identifier) is not str or not identifier or identifier.strip() != identifier:
                raise ValueError("invalid inverter label")
            labels.append(identifier)
        group_ids.append(group.group_id)
    if len(group_ids) != len(set(group_ids)) or len(labels) != len(set(labels)):
        raise ValueError("duplicate group or globally repeated inverter label")
    if len(labels) != count:
        raise ValueError("label count disagrees with configured total")
    refs = authority.evidence_source_references
    if type(refs) is not tuple or len(refs) != 1:
        raise ValueError("invalid immutable source tuple")
    if type(refs[0]) is not str or refs[0] != "config/sites.yaml":
        raise ValueError("unreviewed evidence source")
    if authority.confidence not in ("high", "medium", "low", "unknown"):
        raise ValueError("invalid categorical confidence")
    if (
        type(authority.contract) is not str
        or authority.contract != SITE_INVERTER_INVENTORY_AUTHORITY_CONTRACT_ID
        or type(authority.model) is not str
        or authority.model != SITE_INVERTER_INVENTORY_AUTHORITY_MODEL_ID
        or type(authority.scope) is not str
        or authority.scope != SITE_INVERTER_INVENTORY_AUTHORITY_SCOPE
        or type(authority.coverage_scope) is not str
        or authority.coverage_scope != SITE_INVERTER_INVENTORY_AUTHORITY_COVERAGE_SCOPE
        or type(authority.supported_fidelity) is not str
        or authority.supported_fidelity != LOWER_SUPPORT
        or type(authority.temporal_semantics) is not str
        or authority.temporal_semantics != "unknown"
    ):
        raise ValueError("invalid fixed lower-fidelity inverter-inventory semantics")


def serialize_site_inverter_inventory_authority(
    authority: SiteInverterInventoryAuthority,
) -> dict[str, Any]:
    validate_site_inverter_inventory_authority(authority)
    result = {f.name: getattr(authority, f.name) for f in fields(authority)}
    result["evidence_source_references"] = list(authority.evidence_source_references)
    result["groups"] = [
        {"group_id": g.group_id, "inverter_ids": list(g.inverter_ids)} for g in authority.groups
    ]
    return result


def deserialize_site_inverter_inventory_authority(
    payload: Mapping[str, Any],
) -> SiteInverterInventoryAuthority:
    if not isinstance(payload, Mapping) or set(payload) != {
        f.name for f in fields(SiteInverterInventoryAuthority)
    }:
        raise ValueError("unknown/missing inverter-inventory authority fields")
    for name, expected in _FIXED.items():
        if type(payload[name]) is not str or payload[name] != expected:
            raise ValueError("contradictory serialized fixed semantics")
    if type(payload["evidence_source_references"]) is not list:
        raise ValueError("serialized references require an array")
    args = {f.name: payload[f.name] for f in fields(SiteInverterInventoryAuthority) if f.init}
    args["evidence_source_references"] = tuple(payload["evidence_source_references"])
    if type(payload["groups"]) is not list:
        raise ValueError("serialized groups require an array")
    groups = []
    for raw in payload["groups"]:
        if type(raw) is not dict or set(raw) != {"group_id", "inverter_ids"}:
            raise ValueError("unknown/missing configured group fields")
        if type(raw["inverter_ids"]) is not list:
            raise ValueError("serialized inverter IDs require an array")
        groups.append(ConfiguredInverterInventoryGroup(raw["group_id"], tuple(raw["inverter_ids"])))
    args["groups"] = tuple(groups)
    authority = SiteInverterInventoryAuthority(**args)
    validate_site_inverter_inventory_authority(authority)
    return authority


class _UniqueSafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    pass


def _unique_mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError("duplicate YAML authority key")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_site_inverter_inventory_authority(path: Path) -> SiteInverterInventoryAuthority:
    """Read exactly the supplied UTF-8 declaration; never auto-generate authority."""
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    if type(raw) is not dict:
        raise ValueError("authority declaration requires a mapping")
    return deserialize_site_inverter_inventory_authority(raw)


def validate_site_inverter_inventory_binding(
    manifest: SiteEvidenceManifest,
    authority: SiteInverterInventoryAuthority,
    site_config: SiteConfig,
) -> None:
    """Compare only source identity, configured count and ordered group labels.

    No model, capability, location, module, topology or controller field is read.
    Binding does not construct topology or authorize physical execution.
    """
    validate_site_evidence_manifest(manifest)
    validate_site_inverter_inventory_authority(authority)
    if type(site_config) is not SiteConfig:
        raise ValueError("exact SiteConfig parent required")
    _text(site_config.id)
    _text(site_config.name)
    identity = (authority.site_config_id, authority.site_uuid, authority.site_name)
    if identity != (
        manifest.identity.site_config_id,
        manifest.identity.site_uuid,
        manifest.identity.site_name,
    ) or identity != (site_config.id, str(uuid5(NAMESPACE_DNS, site_config.id)), site_config.name):
        raise ValueError("manifest/config/authority identity mismatch")
    count = site_config.inverter.num_units
    if type(count) is not int or count <= 0 or count != authority.configured_inverter_count:
        raise ValueError("configured inverter count differs from reviewed inventory")
    if site_config.layout is None:
        raise ValueError("configured label groups unavailable")
    configured = site_config.layout.inverter_groups
    if type(configured) is not list or not configured:
        raise ValueError("non-empty configured label groups required")
    memberships = []
    group_counts = []
    for group in configured:
        _text(group.id)
        if type(group.inverters) is not list or not group.inverters:
            raise ValueError("configured inverter labels must be a non-empty list")
        for identifier in group.inverters:
            _text(identifier)
        if type(group.inverter_count) is not int or group.inverter_count != len(group.inverters):
            raise ValueError("group declared count disagrees with configured list")
        memberships.append((group.id, tuple(group.inverters)))
        group_counts.append(group.inverter_count)
    labels = tuple(i for _, ids in memberships for i in ids)
    if len({g for g, _ in memberships}) != len(memberships) or len(set(labels)) != len(labels):
        raise ValueError("duplicate configured group or inverter label")
    if sum(group_counts) != count or tuple(memberships) != tuple(
        (g.group_id, g.inverter_ids) for g in authority.groups
    ):
        raise ValueError(
            "configured ordered inventory/group membership differs from reviewed basis"
        )
    matches = tuple(
        i for i in manifest.items if i.requirement_id == INVERTER_INVENTORY_REQUIREMENT_ID
    )
    if len(matches) != 1:
        raise ValueError("exact s8.inverter_inventory_binding requirement required")
    item = matches[0]
    facts = {f.fact_id: f.value for f in item.facts}
    if facts.get("configured_inverter_count") != str(count) or facts.get(
        "layout_group_counts"
    ) != "; ".join(f"{group_id}:{len(ids)}" for group_id, ids in memberships):
        raise ValueError("manifest configured inventory facts disagree with reviewed source")
    if (
        item.evidence_state != "present"
        or item.admission_state != "admitted"
        or item.supported_fidelity != LOWER_SUPPORT
        or item.admitted_authority_contract_ids != (SITE_INVERTER_INVENTORY_AUTHORITY_CONTRACT_ID,)
        or item.authority_binding_reference != authority.authority_reference
        or item.temporal_scope.semantics != "unknown"
        or item.physical_scope.scope_type != "asset_set"
        or item.physical_scope.identifiers != labels
        or not set(authority.evidence_source_references).issubset(item.source_references)
    ):
        raise ValueError("manifest does not bind this configured lower-fidelity label inventory")
