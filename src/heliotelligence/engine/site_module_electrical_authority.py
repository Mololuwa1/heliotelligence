"""Reviewed configured Tier-3 raw module basis; no solver or installed inventory.

This does not establish manufacturer certification, as-built/serial population,
module counts/homogeneity/flash variability, routing, substring/bypass layout or
installed-equipment validity. Fitted De Soto coefficients remain runtime-owned.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from numbers import Real
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

SITE_MODULE_ELECTRICAL_AUTHORITY_CONTRACT_ID = (
    "explicit_reviewed_configured_module_electrical_basis_authority_v1"
)
SITE_MODULE_ELECTRICAL_AUTHORITY_MODEL_ID = "tier3_low_fit_datasheet_module_electrical_basis_v1"
SITE_MODULE_ELECTRICAL_AUTHORITY_SCOPE = (
    "configured_site_module_model_and_electrical_parameter_basis_"
    "before_population_and_topology_binding"
)
SITE_MODULE_ELECTRICAL_AUTHORITY_COVERAGE_SCOPE = (
    "single_site_configured_model_class_low_fit_stc_parameter_basis_only"
)
MODULE_REQUIREMENT_IDS = ("site.module.model_label", "module.electrical_parameters")
# Raw library keys only; no fitted coefficients, thermal, optics or population.
_PARAMETER_KEYS = {
    "pnom_wp": "pnom_wp",
    "v_mp_v": "v_mp",
    "i_mp_a": "i_mp",
    "v_oc_v": "v_oc",
    "i_sc_a": "i_sc",
    "alpha_sc_pct_per_c": "alpha_sc",
    "beta_voc_pct_per_c": "beta_voc",
    "gamma_pmp_pct_per_c": "gamma_pmp",
}
_FIXED = {
    "contract": SITE_MODULE_ELECTRICAL_AUTHORITY_CONTRACT_ID,
    "model": SITE_MODULE_ELECTRICAL_AUTHORITY_MODEL_ID,
    "scope": SITE_MODULE_ELECTRICAL_AUTHORITY_SCOPE,
    "coverage_scope": SITE_MODULE_ELECTRICAL_AUTHORITY_COVERAGE_SCOPE,
    "supported_fidelity": LOWER_SUPPORT,
    "temporal_semantics": "unknown",
    "parameter_source": "datasheet_fit",
    "fit_quality": "low",
    "expected_lookup_source": "local_library",
}


def _text(value: object) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("exact non-empty unpadded identifier required")


def _numeric(value: object, *, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("non-Boolean real parameter required")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("unrepresentable raw electrical parameter") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError("invalid finite raw electrical parameter")
    return number


def _admit(authority: SiteModuleElectricalAuthority) -> None:
    for name in (
        "site_config_id",
        "site_uuid",
        "site_name",
        "module_model_label",
        "technology",
        "authority_version",
        "authority_reference",
        "confidence",
    ):
        _text(getattr(authority, name))
    if str(UUID(authority.site_uuid)) != authority.site_uuid or authority.site_uuid != str(
        uuid5(NAMESPACE_DNS, authority.site_config_id)
    ):
        raise ValueError("canonical site UUID/config identity mismatch")
    for name, expected in _FIXED.items():
        actual = getattr(authority, name)
        if type(actual) is not str or actual != expected:
            raise ValueError("contradictory lower-fidelity module authority semantics")
    if type(authority.expected_lookup_tier) is not int or authority.expected_lookup_tier != 3:
        raise ValueError("exact Tier 3 required")
    if type(authority.cells_in_series) is not int or authority.cells_in_series <= 0:
        raise ValueError("positive exact integer cell count required")
    refs = authority.evidence_source_references
    if type(refs) is not tuple or not refs:
        raise ValueError("immutable non-empty source references required")
    for ref in refs:
        _text(ref)
    if len(set(refs)) != len(refs):
        raise ValueError("duplicate source reference")
    if authority.confidence not in ("high", "medium", "low", "unknown"):
        raise ValueError("invalid provenance confidence")
    for name in _PARAMETER_KEYS:
        object.__setattr__(
            authority,
            name,
            _numeric(
                getattr(authority, name),
                positive=name in ("pnom_wp", "v_mp_v", "i_mp_a", "v_oc_v", "i_sc_a"),
            ),
        )
    if authority.v_oc_v < authority.v_mp_v or authority.i_sc_a < authority.i_mp_a:
        raise ValueError("raw STC open-circuit/short-circuit values below MPP")


@dataclass(frozen=True, slots=True)
class SiteModuleElectricalAuthority:
    site_config_id: str
    site_uuid: str
    site_name: str
    module_model_label: str
    technology: str
    parameter_source: str
    fit_quality: str
    expected_lookup_tier: int
    expected_lookup_source: str
    pnom_wp: float
    v_mp_v: float
    i_mp_a: float
    v_oc_v: float
    i_sc_a: float
    alpha_sc_pct_per_c: float
    beta_voc_pct_per_c: float
    gamma_pmp_pct_per_c: float
    cells_in_series: int
    authority_version: str
    evidence_source_references: tuple[str, ...]
    authority_reference: str
    confidence: str
    contract: str = field(init=False, default=SITE_MODULE_ELECTRICAL_AUTHORITY_CONTRACT_ID)
    model: str = field(init=False, default=SITE_MODULE_ELECTRICAL_AUTHORITY_MODEL_ID)
    scope: str = field(init=False, default=SITE_MODULE_ELECTRICAL_AUTHORITY_SCOPE)
    coverage_scope: str = field(init=False, default=SITE_MODULE_ELECTRICAL_AUTHORITY_COVERAGE_SCOPE)
    supported_fidelity: str = field(init=False, default=LOWER_SUPPORT)
    temporal_semantics: str = field(init=False, default="unknown")

    def __post_init__(self) -> None:
        _admit(self)


def validate_site_module_electrical_authority(authority: SiteModuleElectricalAuthority) -> None:
    """Independent frozen-state audit; no construction, wire or runtime lookup.

    This is not a signature. Valid-shaped edits require separate source binding
    validation; a declaration alone cannot authenticate its evidence.
    """
    if type(authority) is not SiteModuleElectricalAuthority:
        raise ValueError("exact module authority required")
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
            raise ValueError("invalid exact module authority identifier")
    if str(UUID(authority.site_uuid)) != authority.site_uuid or authority.site_uuid != str(
        uuid5(NAMESPACE_DNS, authority.site_config_id)
    ):
        raise ValueError("invalid canonical site identity")
    for name, expected in _FIXED.items():
        actual = getattr(authority, name)
        if type(actual) is not str or actual != expected:
            raise ValueError("invalid fixed module authority semantics")
    if type(authority.expected_lookup_tier) is not int or authority.expected_lookup_tier != 3:
        raise ValueError("invalid lookup tier")
    if type(authority.cells_in_series) is not int or authority.cells_in_series <= 0:
        raise ValueError("invalid cell count")
    for parameter in (
        authority.pnom_wp,
        authority.v_mp_v,
        authority.i_mp_a,
        authority.v_oc_v,
        authority.i_sc_a,
        authority.alpha_sc_pct_per_c,
        authority.beta_voc_pct_per_c,
        authority.gamma_pmp_pct_per_c,
    ):
        if type(parameter) is not float or not math.isfinite(parameter):
            raise ValueError("invalid canonical finite parameter")
    if (
        any(
            value <= 0
            for value in (
                authority.pnom_wp,
                authority.v_mp_v,
                authority.i_mp_a,
                authority.v_oc_v,
                authority.i_sc_a,
            )
        )
        or authority.v_oc_v < authority.v_mp_v
        or authority.i_sc_a < authority.i_mp_a
    ):
        raise ValueError("inconsistent raw STC parameters")
    refs = authority.evidence_source_references
    if type(refs) is not tuple or not refs:
        raise ValueError("invalid source tuple")
    for ref in refs:
        if type(ref) is not str or not ref or ref.strip() != ref:
            raise ValueError("invalid source identifier")
    if len(set(refs)) != len(refs):
        raise ValueError("repeated evidence reference")
    if authority.confidence not in ("high", "medium", "low", "unknown"):
        raise ValueError("invalid categorical confidence")


def serialize_site_module_electrical_authority(
    authority: SiteModuleElectricalAuthority,
) -> dict[str, Any]:
    validate_site_module_electrical_authority(authority)
    result = {f.name: getattr(authority, f.name) for f in fields(authority)}
    result["evidence_source_references"] = list(authority.evidence_source_references)
    return result


def deserialize_site_module_electrical_authority(
    payload: Mapping[str, Any],
) -> SiteModuleElectricalAuthority:
    if not isinstance(payload, Mapping) or set(payload) != {
        f.name for f in fields(SiteModuleElectricalAuthority)
    }:
        raise ValueError("unknown/missing module authority fields")
    for name, expected in _FIXED.items():
        if type(payload[name]) is not str or payload[name] != expected:
            raise ValueError("contradictory persisted module authority semantics")
    if type(payload["evidence_source_references"]) is not list:
        raise ValueError("wire source references require an array")
    arguments = {f.name: payload[f.name] for f in fields(SiteModuleElectricalAuthority) if f.init}
    arguments["evidence_source_references"] = tuple(payload["evidence_source_references"])
    authority = SiteModuleElectricalAuthority(**arguments)
    validate_site_module_electrical_authority(authority)
    return authority


class _UniqueSafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    pass


def _unique_mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError("duplicate YAML key")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _read_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    if type(raw) is not dict:
        raise ValueError("explicit evidence file must be a mapping")
    return raw


def load_site_module_electrical_authority(path: Path) -> SiteModuleElectricalAuthority:
    """Read only the supplied UTF-8 declaration; never generate it from config."""
    return deserialize_site_module_electrical_authority(_read_yaml(path))


def validate_site_module_electrical_binding(
    manifest: SiteEvidenceManifest,
    authority: SiteModuleElectricalAuthority,
    site_config: SiteConfig,
    module_library_path: Path,
) -> None:
    """Compare explicitly supplied sources; no physics execution or auto-admission.

    Only config identity, local model label and technology are consumed. The
    explicit library path is controlled by the caller, never package discovery.
    """
    validate_site_evidence_manifest(manifest)
    validate_site_module_electrical_authority(authority)
    if type(site_config) is not SiteConfig:
        raise ValueError("exact SiteConfig required")
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
        raise ValueError("manifest/config/authority site identity mismatch")
    if (site_config.module.local_module_name, site_config.module.technology) != (
        authority.module_model_label,
        authority.technology,
    ):
        raise ValueError("configured module label/technology differs from reviewed basis")
    if authority.evidence_source_references != (
        "config/sites.yaml",
        "src/heliotelligence/data/module_library.yaml",
    ):
        raise ValueError(
            "configured/library evidence references must identify both controlled sources"
        )
    library = _read_yaml(module_library_path)
    modules = library.get("modules")
    if type(modules) is not dict or authority.module_model_label not in modules:
        raise ValueError("reviewed module library key unavailable")
    entry = modules[authority.module_model_label]
    if type(entry) is not dict:
        raise ValueError("invalid raw library entry")
    for key, expected in (
        ("model", authority.module_model_label),
        ("technology", authority.technology),
        ("source", authority.parameter_source),
        ("fit_quality", authority.fit_quality),
    ):
        if type(entry.get(key)) is not str or entry[key] != expected:
            raise ValueError("module library model/source semantics drift")
    for name, key in _PARAMETER_KEYS.items():
        if _numeric(
            entry.get(key), positive=name in ("pnom_wp", "v_mp_v", "i_mp_a", "v_oc_v", "i_sc_a")
        ) != getattr(authority, name):
            raise ValueError("reviewed raw module library parameter drift")
    if (
        type(entry.get("cells_in_series")) is not int
        or entry["cells_in_series"] != authority.cells_in_series
    ):
        raise ValueError("reviewed cell count drift")
    for requirement_id in MODULE_REQUIREMENT_IDS:
        matches = tuple(i for i in manifest.items if i.requirement_id == requirement_id)
        if len(matches) != 1:
            raise ValueError("both reviewed module requirements required")
        item = matches[0]
        if (
            item.evidence_state != "present"
            or item.admission_state != "admitted"
            or item.supported_fidelity != LOWER_SUPPORT
            or item.admitted_authority_contract_ids
            != (SITE_MODULE_ELECTRICAL_AUTHORITY_CONTRACT_ID,)
            or item.authority_binding_reference != authority.authority_reference
            or item.temporal_scope.semantics != "unknown"
            or item.physical_scope.scope_type != "model_class"
            or item.physical_scope.identifiers != (authority.module_model_label,)
            or not set(authority.evidence_source_references).issubset(item.source_references)
        ):
            raise ValueError("module manifest binding must preserve reviewed lower-fidelity scope")
