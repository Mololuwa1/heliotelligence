"""Reviewed P2 identity/geographic-anchor binding, separate from configuration.

No equipment, capacity, topology, physics execution or runtime activation is
admitted here. A standalone authority is structurally validated; site admission
also requires exact manifest/authority/SiteConfig binding validation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from numbers import Real
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import yaml  # type: ignore[import-untyped]

from heliotelligence.config.site import SiteConfig
from heliotelligence.engine.site_evidence_manifest import (
    FULL_SUPPORT,
    SiteEvidenceManifest,
    validate_site_evidence_manifest,
)

SITE_PHYSICAL_IDENTITY_AUTHORITY_CONTRACT_ID = (
    "explicit_reviewed_physical_site_identity_authority_v1"
)
SITE_PHYSICAL_IDENTITY_AUTHORITY_MODEL_ID = (
    "reviewed_site_config_identity_and_geographic_anchor_binding_v1"
)
SITE_PHYSICAL_IDENTITY_AUTHORITY_SCOPE = (
    "site_identity_binding_before_site_specific_physical_authority_admission"
)
SITE_PHYSICAL_IDENTITY_AUTHORITY_COVERAGE_SCOPE = (
    "single_site_identity_name_uuid_timezone_and_configured_geographic_anchor_only"
)
SITE_IDENTITY_REQUIREMENT_ID = "site.identity.physical"
_CONFIDENCES = frozenset({"high", "medium", "low", "unknown"})
# Exact database identities, including case, even on case-insensitive filesystems.
_TIMEZONE_IDENTITIES = frozenset(available_timezones())


def _text(value: object) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("expected exact non-empty unpadded identity/provenance string")


def _coordinate(value: object, limit: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("coordinate must be a non-Boolean real number")
    try:
        numeric = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("coordinate must have a finite representation") from exc
    if not math.isfinite(numeric) or not -limit <= numeric <= limit:
        raise ValueError("coordinate outside finite geographic bounds")
    return numeric


def _admit_authority(authority: SitePhysicalIdentityAuthority) -> None:
    for value in (
        authority.site_config_id,
        authority.site_uuid,
        authority.site_name,
        authority.timezone,
        authority.authority_version,
        authority.authority_reference,
        authority.confidence,
    ):
        _text(value)
    if str(UUID(authority.site_uuid)) != authority.site_uuid or authority.site_uuid != str(
        uuid5(NAMESPACE_DNS, authority.site_config_id)
    ):
        raise ValueError("site UUID must match canonical application uuid5 identity")
    if authority.timezone not in _TIMEZONE_IDENTITIES:
        raise ValueError("timezone must use an exact timezone-database identity")
    try:
        ZoneInfo(authority.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("invalid explicit timezone identity") from exc
    if (
        type(authority.evidence_source_references) is not tuple
        or not authority.evidence_source_references
    ):
        raise ValueError("non-empty immutable evidence source references required")
    for reference in authority.evidence_source_references:
        _text(reference)
    if len(set(authority.evidence_source_references)) != len(authority.evidence_source_references):
        raise ValueError("duplicate evidence source reference")
    if authority.confidence not in _CONFIDENCES:
        raise ValueError("unsupported confidence")
    for actual, expected in (
        (authority.contract, SITE_PHYSICAL_IDENTITY_AUTHORITY_CONTRACT_ID),
        (authority.model, SITE_PHYSICAL_IDENTITY_AUTHORITY_MODEL_ID),
        (authority.scope, SITE_PHYSICAL_IDENTITY_AUTHORITY_SCOPE),
        (authority.coverage_scope, SITE_PHYSICAL_IDENTITY_AUTHORITY_COVERAGE_SCOPE),
    ):
        if type(actual) is not str or actual != expected:
            raise ValueError("contradictory fixed identity-authority semantics")


@dataclass(frozen=True, slots=True)
class SitePhysicalIdentityAuthority:
    site_config_id: str
    site_uuid: str
    site_name: str
    configured_latitude_deg: float
    configured_longitude_deg: float
    timezone: str
    authority_version: str
    evidence_source_references: tuple[str, ...]
    authority_reference: str
    confidence: str
    contract: str = field(init=False, default=SITE_PHYSICAL_IDENTITY_AUTHORITY_CONTRACT_ID)
    model: str = field(init=False, default=SITE_PHYSICAL_IDENTITY_AUTHORITY_MODEL_ID)
    scope: str = field(init=False, default=SITE_PHYSICAL_IDENTITY_AUTHORITY_SCOPE)
    coverage_scope: str = field(init=False, default=SITE_PHYSICAL_IDENTITY_AUTHORITY_COVERAGE_SCOPE)

    def __post_init__(self) -> None:
        _admit_authority(self)
        object.__setattr__(
            self, "configured_latitude_deg", _coordinate(self.configured_latitude_deg, 90.0)
        )
        object.__setattr__(
            self, "configured_longitude_deg", _coordinate(self.configured_longitude_deg, 180.0)
        )


def validate_site_physical_identity_authority(authority: SitePhysicalIdentityAuthority) -> None:
    """Independent invariant audit, without constructors, loader or wire helpers.

    Consistent replacement by another valid declaration is not authenticated by
    this format. Admission must also compare the separately supplied parents.
    """
    if type(authority) is not SitePhysicalIdentityAuthority:
        raise ValueError("exact reviewed site-identity authority required")
    for value in (
        authority.site_config_id,
        authority.site_uuid,
        authority.site_name,
        authority.timezone,
        authority.authority_version,
        authority.authority_reference,
        authority.confidence,
    ):
        if type(value) is not str or not value or value.strip() != value:
            raise ValueError("invalid exact authority identifier")
    if str(UUID(authority.site_uuid)) != authority.site_uuid:
        raise ValueError("noncanonical UUID string")
    if authority.site_uuid != str(uuid5(NAMESPACE_DNS, authority.site_config_id)):
        raise ValueError("UUID and configuration identity disagree")
    for coordinate, limit in (
        (authority.configured_latitude_deg, 90.0),
        (authority.configured_longitude_deg, 180.0),
    ):
        if (
            type(coordinate) is not float
            or not math.isfinite(coordinate)
            or coordinate < -limit
            or coordinate > limit
        ):
            raise ValueError("invalid canonical geographic anchor")
    if authority.timezone not in _TIMEZONE_IDENTITIES:
        raise ValueError("timezone must use an exact timezone-database identity")
    try:
        ZoneInfo(authority.timezone)
    except (KeyError, ValueError) as exc:
        raise ValueError("unrecognised timezone identity") from exc
    references = authority.evidence_source_references
    if type(references) is not tuple or not references:
        raise ValueError("invalid immutable source provenance")
    for reference in references:
        if type(reference) is not str or not reference or reference.strip() != reference:
            raise ValueError("invalid evidence source identity")
    if len(set(references)) != len(references):
        raise ValueError("repeated source reference")
    if authority.confidence not in ("high", "medium", "low", "unknown"):
        raise ValueError("invalid categorical confidence")
    if (
        type(authority.contract) is not str
        or authority.contract != SITE_PHYSICAL_IDENTITY_AUTHORITY_CONTRACT_ID
        or type(authority.model) is not str
        or authority.model != SITE_PHYSICAL_IDENTITY_AUTHORITY_MODEL_ID
        or type(authority.scope) is not str
        or authority.scope != SITE_PHYSICAL_IDENTITY_AUTHORITY_SCOPE
        or type(authority.coverage_scope) is not str
        or authority.coverage_scope != SITE_PHYSICAL_IDENTITY_AUTHORITY_COVERAGE_SCOPE
    ):
        raise ValueError("fixed authority semantics mismatch")


def serialize_site_physical_identity_authority(
    authority: SitePhysicalIdentityAuthority,
) -> dict[str, Any]:
    validate_site_physical_identity_authority(authority)
    result = {f.name: getattr(authority, f.name) for f in fields(authority)}
    result["evidence_source_references"] = list(authority.evidence_source_references)
    return result


def deserialize_site_physical_identity_authority(
    payload: Mapping[str, Any],
) -> SitePhysicalIdentityAuthority:
    if not isinstance(payload, Mapping) or set(payload) != {
        f.name for f in fields(SitePhysicalIdentityAuthority)
    }:
        raise ValueError("unknown/missing identity-authority schema fields")
    for key, expected in (
        ("contract", SITE_PHYSICAL_IDENTITY_AUTHORITY_CONTRACT_ID),
        ("model", SITE_PHYSICAL_IDENTITY_AUTHORITY_MODEL_ID),
        ("scope", SITE_PHYSICAL_IDENTITY_AUTHORITY_SCOPE),
        ("coverage_scope", SITE_PHYSICAL_IDENTITY_AUTHORITY_COVERAGE_SCOPE),
    ):
        if type(payload[key]) is not str or payload[key] != expected:
            raise ValueError("invalid serialized authority semantics")
    references = payload["evidence_source_references"]
    if type(references) is not list:
        raise ValueError("serialized evidence references must be an array")
    arguments = {f.name: payload[f.name] for f in fields(SitePhysicalIdentityAuthority) if f.init}
    arguments["evidence_source_references"] = tuple(references)
    authority = SitePhysicalIdentityAuthority(**arguments)
    validate_site_physical_identity_authority(authority)
    return authority


class _UniqueSafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    pass


def _unique_mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError("duplicate YAML authority field")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_site_physical_identity_authority(path: Path) -> SitePhysicalIdentityAuthority:
    """Read exactly one supplied declaration; never generate one from config."""
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    if type(raw) is not dict:
        raise ValueError("authority declaration must be a mapping")
    return deserialize_site_physical_identity_authority(raw)


def validate_site_physical_identity_binding(
    manifest: SiteEvidenceManifest,
    authority: SitePhysicalIdentityAuthority,
    site_config: SiteConfig,
) -> None:
    """Check an explicit proposed/admitted identity binding without mutation.

    Reads only identity/anchor fields from SiteConfig. Capacity, inventory,
    topology and all physical parameter values are deliberately excluded.
    """
    validate_site_evidence_manifest(manifest)
    validate_site_physical_identity_authority(authority)
    if type(site_config) is not SiteConfig:
        raise ValueError("exact SiteConfig identity parent required")
    for value in (site_config.id, site_config.name, site_config.timezone):
        _text(value)
    latitude = _coordinate(site_config.latitude, 90.0)
    longitude = _coordinate(site_config.longitude, 180.0)
    declared_identity = (authority.site_config_id, authority.site_uuid, authority.site_name)
    if declared_identity != (
        manifest.identity.site_config_id,
        manifest.identity.site_uuid,
        manifest.identity.site_name,
    ):
        raise ValueError("manifest identity does not match reviewed authority")
    if declared_identity != (
        site_config.id,
        str(uuid5(NAMESPACE_DNS, site_config.id)),
        site_config.name,
    ):
        raise ValueError("SiteConfig identity does not match reviewed authority")
    if (
        authority.configured_latitude_deg,
        authority.configured_longitude_deg,
        authority.timezone,
    ) != (latitude, longitude, site_config.timezone):
        raise ValueError("configured geographic anchor/timezone differs from reviewed authority")
    matches = tuple(i for i in manifest.items if i.requirement_id == SITE_IDENTITY_REQUIREMENT_ID)
    if len(matches) != 1:
        raise ValueError("binding requires exactly the site.identity.physical requirement")
    item = matches[0]
    if item.physical_scope.scope_type != "site" or item.physical_scope.identifiers != (
        authority.site_config_id,
    ):
        raise ValueError("identity evidence scope disagrees with reviewed site")
    if item.evidence_state != "present" or item.admission_state not in ("admitted", "not_admitted"):
        raise ValueError("site identity evidence is not available for binding")
    if not set(authority.evidence_source_references).issubset(item.source_references):
        raise ValueError("manifest evidence does not cover authority source references")
    if item.admission_state == "admitted" and (
        item.admitted_authority_contract_ids != (SITE_PHYSICAL_IDENTITY_AUTHORITY_CONTRACT_ID,)
        or item.authority_binding_reference != authority.authority_reference
        or item.supported_fidelity != FULL_SUPPORT
        or item.temporal_scope.semantics != "static"
    ):
        raise ValueError("admitted identity item does not identify this reviewed static authority")
