"""P2E configured model-class bifacial applicability; no response coefficients.

Neither a generic bifaciality factor nor applicability establishes canonical Isc
response evidence, receiver coverage, rear geometry/model or runtime activation.
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

SITE_BIFACIAL_APPLICABILITY_AUTHORITY_CONTRACT_ID = (
    "explicit_reviewed_configured_module_class_bifacial_applicability_authority_v1"
)
SITE_BIFACIAL_APPLICABILITY_AUTHORITY_MODEL_ID = (
    "configured_module_class_bifacial_enabled_lower_fidelity_basis_v1"
)
SITE_BIFACIAL_APPLICABILITY_AUTHORITY_SCOPE = (
    "configured_module_class_bifacial_applicability_before_receiver_and_rear_model_binding"
)
SITE_BIFACIAL_APPLICABILITY_AUTHORITY_COVERAGE_SCOPE = (
    "single_site_configured_module_class_bifacial_applicability_only"
)
BIFACIAL_APPLICABILITY_REQUIREMENT_ID = "irradiance.bifacial_applicability"
_FIXED = {
    "contract": SITE_BIFACIAL_APPLICABILITY_AUTHORITY_CONTRACT_ID,
    "model": SITE_BIFACIAL_APPLICABILITY_AUTHORITY_MODEL_ID,
    "scope": SITE_BIFACIAL_APPLICABILITY_AUTHORITY_SCOPE,
    "coverage_scope": SITE_BIFACIAL_APPLICABILITY_AUTHORITY_COVERAGE_SCOPE,
    "supported_fidelity": LOWER_SUPPORT,
    "temporal_semantics": "unknown",
}


def _text(value: object) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("exact non-empty unpadded identifier required")


def _admit(authority: SiteBifacialApplicabilityAuthority) -> None:
    for value in (
        authority.site_config_id,
        authority.site_uuid,
        authority.site_name,
        authority.module_model_label,
        authority.technology,
        authority.authority_version,
        authority.authority_reference,
        authority.confidence,
    ):
        _text(value)
    if str(UUID(authority.site_uuid)) != authority.site_uuid or authority.site_uuid != str(
        uuid5(NAMESPACE_DNS, authority.site_config_id)
    ):
        raise ValueError("canonical UUID/configuration identity mismatch")
    if type(authority.bifacial_enabled) is not bool:
        raise ValueError("bifacial_enabled requires an exact boolean")
    refs = authority.evidence_source_references
    if (
        type(refs) is not tuple
        or len(refs) != 2
        or any(type(r) is not str for r in refs)
        or refs != ("config/sites.yaml", "src/heliotelligence/data/module_library.yaml")
    ):
        raise ValueError("exact configured/library source tuple required")
    if authority.confidence not in ("high", "medium", "low", "unknown"):
        raise ValueError("invalid provenance confidence")
    for name, expected in _FIXED.items():
        actual = getattr(authority, name)
        if type(actual) is not str or actual != expected:
            raise ValueError(
                "contradictory configured lower-fidelity bifacial-applicability semantics"
            )


@dataclass(frozen=True, slots=True)
class SiteBifacialApplicabilityAuthority:
    site_config_id: str
    site_uuid: str
    site_name: str
    module_model_label: str
    technology: str
    bifacial_enabled: bool
    authority_version: str
    evidence_source_references: tuple[str, ...]
    authority_reference: str
    confidence: str
    contract: str = field(init=False, default=SITE_BIFACIAL_APPLICABILITY_AUTHORITY_CONTRACT_ID)
    model: str = field(init=False, default=SITE_BIFACIAL_APPLICABILITY_AUTHORITY_MODEL_ID)
    scope: str = field(init=False, default=SITE_BIFACIAL_APPLICABILITY_AUTHORITY_SCOPE)
    coverage_scope: str = field(
        init=False, default=SITE_BIFACIAL_APPLICABILITY_AUTHORITY_COVERAGE_SCOPE
    )
    supported_fidelity: str = field(init=False, default=LOWER_SUPPORT)
    temporal_semantics: str = field(init=False, default="unknown")

    def __post_init__(self) -> None:
        _admit(self)


def validate_site_bifacial_applicability_authority(
    authority: SiteBifacialApplicabilityAuthority,
) -> None:
    """Independent frozen-record audit; no construction, loader or wire helpers.

    Structural validity does not authenticate a declaration. Separately validate
    the reviewed manifest/config binding before admission; no signature is claimed.
    """
    if type(authority) is not SiteBifacialApplicabilityAuthority:
        raise ValueError("exact configured bifacial-applicability authority required")
    for value in (
        authority.site_config_id,
        authority.site_uuid,
        authority.site_name,
        authority.module_model_label,
        authority.technology,
        authority.authority_version,
        authority.authority_reference,
        authority.confidence,
    ):
        if type(value) is not str or not value or value.strip() != value:
            raise ValueError("invalid exact bifacial-applicability identifier")
    if str(UUID(authority.site_uuid)) != authority.site_uuid or authority.site_uuid != str(
        uuid5(NAMESPACE_DNS, authority.site_config_id)
    ):
        raise ValueError("invalid canonical site identity")
    if type(authority.bifacial_enabled) is not bool:
        raise ValueError("invalid exact boolean applicability")
    refs = authority.evidence_source_references
    if type(refs) is not tuple or len(refs) != 2:
        raise ValueError("invalid immutable source tuple")
    if any(type(r) is not str for r in refs) or refs != (
        "config/sites.yaml",
        "src/heliotelligence/data/module_library.yaml",
    ):
        raise ValueError("unreviewed evidence source tuple")
    if authority.confidence not in ("high", "medium", "low", "unknown"):
        raise ValueError("invalid categorical confidence")
    if (
        type(authority.contract) is not str
        or authority.contract != SITE_BIFACIAL_APPLICABILITY_AUTHORITY_CONTRACT_ID
        or type(authority.model) is not str
        or authority.model != SITE_BIFACIAL_APPLICABILITY_AUTHORITY_MODEL_ID
        or type(authority.scope) is not str
        or authority.scope != SITE_BIFACIAL_APPLICABILITY_AUTHORITY_SCOPE
        or type(authority.coverage_scope) is not str
        or authority.coverage_scope != SITE_BIFACIAL_APPLICABILITY_AUTHORITY_COVERAGE_SCOPE
        or type(authority.supported_fidelity) is not str
        or authority.supported_fidelity != LOWER_SUPPORT
        or type(authority.temporal_semantics) is not str
        or authority.temporal_semantics != "unknown"
    ):
        raise ValueError("invalid fixed lower-fidelity bifacial-applicability semantics")


def serialize_site_bifacial_applicability_authority(
    authority: SiteBifacialApplicabilityAuthority,
) -> dict[str, Any]:
    validate_site_bifacial_applicability_authority(authority)
    result = {f.name: getattr(authority, f.name) for f in fields(authority)}
    result["evidence_source_references"] = list(authority.evidence_source_references)
    return result


def deserialize_site_bifacial_applicability_authority(
    payload: Mapping[str, Any],
) -> SiteBifacialApplicabilityAuthority:
    if not isinstance(payload, Mapping) or set(payload) != {
        f.name for f in fields(SiteBifacialApplicabilityAuthority)
    }:
        raise ValueError("unknown/missing bifacial-applicability authority fields")
    for name, expected in _FIXED.items():
        if type(payload[name]) is not str or payload[name] != expected:
            raise ValueError("contradictory serialized fixed semantics")
    if type(payload["evidence_source_references"]) is not list:
        raise ValueError("serialized references require an array")
    args = {f.name: payload[f.name] for f in fields(SiteBifacialApplicabilityAuthority) if f.init}
    args["evidence_source_references"] = tuple(payload["evidence_source_references"])
    authority = SiteBifacialApplicabilityAuthority(**args)
    validate_site_bifacial_applicability_authority(authority)
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


def load_site_bifacial_applicability_authority(path: Path) -> SiteBifacialApplicabilityAuthority:
    """Read exactly the supplied UTF-8 declaration; never auto-generate authority."""
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    if type(raw) is not dict:
        raise ValueError("authority declaration requires a mapping")
    return deserialize_site_bifacial_applicability_authority(raw)


def validate_site_bifacial_applicability_binding(
    manifest: SiteEvidenceManifest,
    authority: SiteBifacialApplicabilityAuthority,
    site_config: SiteConfig,
    module_library_path: Path,
) -> None:
    """Bind only identity, configured model/technology and bifacial boolean.

    The library path is explicit. No factor, population, geometry, optical,
    environmental or thermal quantity is consumed or inferred.
    """
    validate_site_evidence_manifest(manifest)
    validate_site_bifacial_applicability_authority(authority)
    if type(site_config) is not SiteConfig:
        raise ValueError("exact SiteConfig identity parent required")
    for value in (
        site_config.id,
        site_config.name,
        site_config.module.local_module_name,
        site_config.module.technology,
    ):
        _text(value)
    identity = (authority.site_config_id, authority.site_uuid, authority.site_name)
    if identity != (
        manifest.identity.site_config_id,
        manifest.identity.site_uuid,
        manifest.identity.site_name,
    ) or identity != (site_config.id, str(uuid5(NAMESPACE_DNS, site_config.id)), site_config.name):
        raise ValueError("manifest/config/authority identity mismatch")
    if (
        (site_config.module.local_module_name, site_config.module.technology)
        != (authority.module_model_label, authority.technology)
        or type(site_config.module.bifacial) is not bool
        or site_config.module.bifacial is not authority.bifacial_enabled
    ):
        raise ValueError("configured model/technology/bifacial flag differs from reviewed basis")
    raw = yaml.load(module_library_path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    if type(raw) is not dict or type(raw.get("modules")) is not dict:
        raise ValueError("invalid explicitly supplied module library")
    entry = raw["modules"].get(authority.module_model_label)
    if type(entry) is not dict:
        raise ValueError("reviewed model key unavailable")
    if (
        type(entry.get("model")) is not str
        or entry["model"] != authority.module_model_label
        or type(entry.get("technology")) is not str
        or entry["technology"] != authority.technology
        or type(entry.get("bifacial")) is not bool
        or entry["bifacial"] is not authority.bifacial_enabled
    ):
        raise ValueError("library model/technology/bifacial flag differs from reviewed basis")
    matches = tuple(
        i for i in manifest.items if i.requirement_id == BIFACIAL_APPLICABILITY_REQUIREMENT_ID
    )
    if len(matches) != 1:
        raise ValueError("exact irradiance.bifacial_applicability requirement required")
    item = matches[0]
    flags = tuple(f for f in item.facts if f.fact_id == "bifacial_flag")
    if len(flags) != 1 or flags[0].value != ("true" if authority.bifacial_enabled else "false"):
        raise ValueError("manifest bifacial flag fact disagrees with reviewed applicability")
    if (
        item.evidence_state != "present"
        or item.admission_state != "admitted"
        or item.supported_fidelity != LOWER_SUPPORT
        or item.admitted_authority_contract_ids
        != (SITE_BIFACIAL_APPLICABILITY_AUTHORITY_CONTRACT_ID,)
        or item.authority_binding_reference != authority.authority_reference
        or item.temporal_scope.semantics != "unknown"
        or item.physical_scope.scope_type != "model_class"
        or item.physical_scope.identifiers != (authority.module_model_label,)
        or not set(authority.evidence_source_references).issubset(item.source_references)
    ):
        raise ValueError("manifest does not bind this lower-fidelity model-class applicability")
