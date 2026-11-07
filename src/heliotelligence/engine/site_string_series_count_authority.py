"""P2D configured uniform lower-fidelity series-count basis, not string inventory.

Only the configured modules per string are bound. No population arithmetic,
physical string/member identity, topology generation or runtime execution occurs.
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

SITE_STRING_SERIES_COUNT_AUTHORITY_CONTRACT_ID = (
    "explicit_reviewed_configured_uniform_string_series_count_authority_v1"
)
SITE_STRING_SERIES_COUNT_AUTHORITY_MODEL_ID = (
    "configured_uniform_modules_per_string_lower_fidelity_basis_v1"
)
SITE_STRING_SERIES_COUNT_AUTHORITY_SCOPE = (
    "configured_string_series_module_count_before_physical_string_topology_binding"
)
SITE_STRING_SERIES_COUNT_AUTHORITY_COVERAGE_SCOPE = (
    "single_site_uniform_configured_modules_per_string_assumption_only"
)
STRING_SERIES_COUNT_REQUIREMENT_ID = "s8.string_module_count"
_FIXED = {
    "contract": SITE_STRING_SERIES_COUNT_AUTHORITY_CONTRACT_ID,
    "model": SITE_STRING_SERIES_COUNT_AUTHORITY_MODEL_ID,
    "scope": SITE_STRING_SERIES_COUNT_AUTHORITY_SCOPE,
    "coverage_scope": SITE_STRING_SERIES_COUNT_AUTHORITY_COVERAGE_SCOPE,
    "supported_fidelity": LOWER_SUPPORT,
    "temporal_semantics": "unknown",
}


def _text(value: object) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("exact non-empty unpadded identifier required")


def _admit(authority: SiteStringSeriesCountAuthority) -> None:
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
    if type(authority.modules_per_string) is not int or authority.modules_per_string <= 0:
        raise ValueError("modules_per_string requires an exact positive integer")
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
            raise ValueError("contradictory configured lower-fidelity series-count semantics")


@dataclass(frozen=True, slots=True)
class SiteStringSeriesCountAuthority:
    site_config_id: str
    site_uuid: str
    site_name: str
    modules_per_string: int
    authority_version: str
    evidence_source_references: tuple[str, ...]
    authority_reference: str
    confidence: str
    contract: str = field(init=False, default=SITE_STRING_SERIES_COUNT_AUTHORITY_CONTRACT_ID)
    model: str = field(init=False, default=SITE_STRING_SERIES_COUNT_AUTHORITY_MODEL_ID)
    scope: str = field(init=False, default=SITE_STRING_SERIES_COUNT_AUTHORITY_SCOPE)
    coverage_scope: str = field(
        init=False, default=SITE_STRING_SERIES_COUNT_AUTHORITY_COVERAGE_SCOPE
    )
    supported_fidelity: str = field(init=False, default=LOWER_SUPPORT)
    temporal_semantics: str = field(init=False, default="unknown")

    def __post_init__(self) -> None:
        _admit(self)


def validate_site_string_series_count_authority(authority: SiteStringSeriesCountAuthority) -> None:
    """Independent frozen-record audit; no construction, loader or wire helpers.

    Structural validity does not authenticate a declaration. Separately validate
    the reviewed manifest/config binding before admission; no signature is claimed.
    """
    if type(authority) is not SiteStringSeriesCountAuthority:
        raise ValueError("exact configured series-count authority required")
    for value in (
        authority.site_config_id,
        authority.site_uuid,
        authority.site_name,
        authority.authority_version,
        authority.authority_reference,
        authority.confidence,
    ):
        if type(value) is not str or not value or value.strip() != value:
            raise ValueError("invalid exact series-count identifier")
    if str(UUID(authority.site_uuid)) != authority.site_uuid or authority.site_uuid != str(
        uuid5(NAMESPACE_DNS, authority.site_config_id)
    ):
        raise ValueError("invalid canonical site identity")
    count = authority.modules_per_string
    if type(count) is not int or count < 1:
        raise ValueError("invalid exact positive series module count")
    refs = authority.evidence_source_references
    if type(refs) is not tuple or len(refs) != 1:
        raise ValueError("invalid immutable source tuple")
    if type(refs[0]) is not str or refs[0] != "config/sites.yaml":
        raise ValueError("unreviewed evidence source")
    if authority.confidence not in ("high", "medium", "low", "unknown"):
        raise ValueError("invalid categorical confidence")
    if (
        type(authority.contract) is not str
        or authority.contract != SITE_STRING_SERIES_COUNT_AUTHORITY_CONTRACT_ID
        or type(authority.model) is not str
        or authority.model != SITE_STRING_SERIES_COUNT_AUTHORITY_MODEL_ID
        or type(authority.scope) is not str
        or authority.scope != SITE_STRING_SERIES_COUNT_AUTHORITY_SCOPE
        or type(authority.coverage_scope) is not str
        or authority.coverage_scope != SITE_STRING_SERIES_COUNT_AUTHORITY_COVERAGE_SCOPE
        or type(authority.supported_fidelity) is not str
        or authority.supported_fidelity != LOWER_SUPPORT
        or type(authority.temporal_semantics) is not str
        or authority.temporal_semantics != "unknown"
    ):
        raise ValueError("invalid fixed lower-fidelity series-count semantics")


def serialize_site_string_series_count_authority(
    authority: SiteStringSeriesCountAuthority,
) -> dict[str, Any]:
    validate_site_string_series_count_authority(authority)
    result = {f.name: getattr(authority, f.name) for f in fields(authority)}
    result["evidence_source_references"] = list(authority.evidence_source_references)
    return result


def deserialize_site_string_series_count_authority(
    payload: Mapping[str, Any],
) -> SiteStringSeriesCountAuthority:
    if not isinstance(payload, Mapping) or set(payload) != {
        f.name for f in fields(SiteStringSeriesCountAuthority)
    }:
        raise ValueError("unknown/missing series-count authority fields")
    for name, expected in _FIXED.items():
        if type(payload[name]) is not str or payload[name] != expected:
            raise ValueError("contradictory serialized fixed semantics")
    if type(payload["evidence_source_references"]) is not list:
        raise ValueError("serialized references require an array")
    args = {f.name: payload[f.name] for f in fields(SiteStringSeriesCountAuthority) if f.init}
    args["evidence_source_references"] = tuple(payload["evidence_source_references"])
    authority = SiteStringSeriesCountAuthority(**args)
    validate_site_string_series_count_authority(authority)
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


def load_site_string_series_count_authority(path: Path) -> SiteStringSeriesCountAuthority:
    """Read exactly the supplied UTF-8 declaration; never auto-generate authority."""
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    if type(raw) is not dict:
        raise ValueError("authority declaration requires a mapping")
    return deserialize_site_string_series_count_authority(raw)


def validate_site_string_series_count_binding(
    manifest: SiteEvidenceManifest,
    authority: SiteStringSeriesCountAuthority,
    site_config: SiteConfig,
) -> None:
    """Bind only config identity and the configured per-string series count.

    No other module fields, equipment, topology or population are inspected.
    This function neither creates StringConfig objects nor authorizes execution.
    """
    validate_site_evidence_manifest(manifest)
    validate_site_string_series_count_authority(authority)
    if type(site_config) is not SiteConfig:
        raise ValueError("exact SiteConfig identity parent required")
    _text(site_config.id)
    _text(site_config.name)
    identity = (authority.site_config_id, authority.site_uuid, authority.site_name)
    if identity != (
        manifest.identity.site_config_id,
        manifest.identity.site_uuid,
        manifest.identity.site_name,
    ) or identity != (site_config.id, str(uuid5(NAMESPACE_DNS, site_config.id)), site_config.name):
        raise ValueError("manifest/config/authority identity mismatch")
    configured_count = site_config.module.modules_per_string
    if type(configured_count) is not int or configured_count != authority.modules_per_string:
        raise ValueError("configured modules_per_string differs from reviewed series-count basis")
    matches = tuple(
        i for i in manifest.items if i.requirement_id == STRING_SERIES_COUNT_REQUIREMENT_ID
    )
    if len(matches) != 1:
        raise ValueError("exact s8.string_module_count requirement required")
    item = matches[0]
    if (
        item.evidence_state != "present"
        or item.admission_state != "admitted"
        or item.supported_fidelity != LOWER_SUPPORT
        or item.admitted_authority_contract_ids != (SITE_STRING_SERIES_COUNT_AUTHORITY_CONTRACT_ID,)
        or item.authority_binding_reference != authority.authority_reference
        or item.temporal_scope.semantics != "unknown"
        or item.physical_scope.scope_type != "site"
        or item.physical_scope.identifiers != (authority.site_config_id,)
        or not set(authority.evidence_source_references).issubset(item.source_references)
    ):
        raise ValueError("manifest does not bind this configured lower-fidelity series-count basis")
