"""P2A declared site evidence inventory, separate from config and physics execution.

Admission is an explicit reviewed binding declaration, not inferred from a file's
existence. This module neither constructs nor executes a physics authority.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5
from zoneinfo import ZoneInfo

import pandas as pd  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

from heliotelligence.config.site import SiteConfig

SITE_EVIDENCE_MANIFEST_CONTRACT_ID = "canonical_site_physical_evidence_manifest_v1"
SITE_EVIDENCE_MANIFEST_SCOPE = (
    "site_specific_physical_evidence_inventory_and_authority_readiness_before_shadow_execution"
)
DOMAINS = frozenset(
    {
        "site_identity",
        "spatial_geometry",
        "weather_time",
        "irradiance_optics",
        "module_thermal",
        "module_population",
        "dc_topology",
        "inverter",
        "controller",
        "lv_collection",
        "transformer",
        "mv_hv_network",
        "revenue_meter",
        "benchmark_policy",
        "uncertainty",
    }
)
STAGES = frozenset({"UPSTREAM", "S8", "S9", "S10", "S11", "S12", "S13", "S14", "P1"})
SOURCE_KINDS = frozenset(
    {
        "repository_configuration",
        "surveyed_geometry",
        "scada_channel",
        "meter_record",
        "manufacturer_datasheet",
        "factory_test_report",
        "as_built_drawing",
        "single_line_diagram",
        "cable_schedule",
        "commissioning_record",
        "calibration_certificate",
        "controller_record",
        "engineering_study",
        "source_documentation",
        "external_evidence_not_supplied",
        "mixed_repository_evidence",
    }
)
EVIDENCE_STATES = frozenset({"present", "missing", "conflicting", "not_applicable"})
ADMISSION_STATES = frozenset({"admitted", "not_admitted", "blocked", "not_applicable"})
FULL_SUPPORT = "supports_full_declared_physical_path"
LOWER_SUPPORT = "supports_explicit_lower_fidelity_path"
NON_RESOLVING = "does_not_resolve_physical_path"
FIDELITIES = frozenset({FULL_SUPPORT, LOWER_SUPPORT, NON_RESOLVING, "not_applicable"})
ANY_PATH = "mandatory_for_any_physical_path"
FULL_PATH = "mandatory_for_full_fidelity"
OPTIONAL = "optional_advanced"
PATH_SECTIONS = (
    "upstream_environment",
    "module_electrical_input",
    "s8_dc",
    "s9_s10_inverter_control",
    "s11_lv_collection",
    "s12_transformer",
    "s13_mv_hv_meter",
    "s14_benchmarking",
    "uncertainty",
)


@dataclass(frozen=True, slots=True)
class SiteEvidenceRequirement:
    requirement_id: str
    domain: str
    stage_refs: tuple[str, ...]
    path_sections: tuple[str, ...]
    requirement_level: str


def _catalogue() -> tuple[SiteEvidenceRequirement, ...]:
    # One reviewed catalogue. Sections/levels are evidence decisions, not stages.
    specs = (
        ("site.identity.physical", "site_identity", ("P1",), PATH_SECTIONS, ANY_PATH),
        (
            "site.population.module_count",
            "module_population",
            ("UPSTREAM", "S8"),
            ("module_electrical_input", "s8_dc"),
            ANY_PATH,
        ),
        (
            "site.geometry.module_positions",
            "spatial_geometry",
            ("UPSTREAM",),
            ("upstream_environment",),
            FULL_PATH,
        ),
        ("site.geometry.electrical_mapping", "dc_topology", ("S8",), ("s8_dc",), ANY_PATH),
        (
            "site.module.model_label",
            "module_population",
            ("UPSTREAM", "S8"),
            ("module_electrical_input",),
            OPTIONAL,
        ),
        (
            "site.legacy_compatibility_assumptions",
            "site_identity",
            ("P1",),
            PATH_SECTIONS,
            OPTIONAL,
        ),
        (
            "module.electrical_parameters",
            "module_population",
            ("UPSTREAM", "S8"),
            ("module_electrical_input",),
            ANY_PATH,
        ),
        (
            "weather.source_identifiers",
            "weather_time",
            ("UPSTREAM",),
            ("upstream_environment",),
            OPTIONAL,
        ),
        (
            "weather.temporal_semantics",
            "weather_time",
            ("UPSTREAM",),
            ("upstream_environment",),
            ANY_PATH,
        ),
        (
            "weather.cadence_interval_semantics",
            "weather_time",
            ("UPSTREAM",),
            ("upstream_environment",),
            ANY_PATH,
        ),
        (
            "irradiance.front_source_quantity",
            "irradiance_optics",
            ("UPSTREAM",),
            ("upstream_environment",),
            ANY_PATH,
        ),
        (
            "irradiance.front_measurement_plane",
            "irradiance_optics",
            ("UPSTREAM",),
            ("upstream_environment",),
            ANY_PATH,
        ),
        (
            "irradiance.rear_model_basis",
            "irradiance_optics",
            ("UPSTREAM",),
            ("upstream_environment",),
            ANY_PATH,
        ),
        (
            "irradiance.bifacial_applicability",
            "irradiance_optics",
            ("UPSTREAM",),
            ("upstream_environment",),
            ANY_PATH,
        ),
        (
            "irradiance.shading_geometry",
            "irradiance_optics",
            ("UPSTREAM",),
            ("upstream_environment",),
            ANY_PATH,
        ),
        (
            "irradiance.spectral_admission",
            "irradiance_optics",
            ("UPSTREAM", "S8"),
            ("module_electrical_input",),
            ANY_PATH,
        ),
        (
            "irradiance.thermal_poa_basis",
            "irradiance_optics",
            ("UPSTREAM",),
            ("module_electrical_input",),
            ANY_PATH,
        ),
        (
            "thermal.sensor_quantity",
            "module_thermal",
            ("UPSTREAM",),
            ("module_electrical_input",),
            ANY_PATH,
        ),
        (
            "thermal.sensor_placement_calibration",
            "module_thermal",
            ("UPSTREAM",),
            ("module_electrical_input",),
            ANY_PATH,
        ),
        ("thermal.zones", "module_thermal", ("UPSTREAM",), ("module_electrical_input",), ANY_PATH),
        (
            "thermal.zone_binding",
            "module_thermal",
            ("UPSTREAM",),
            ("module_electrical_input",),
            ANY_PATH,
        ),
        (
            "thermal.model_parameters",
            "module_thermal",
            ("UPSTREAM",),
            ("module_electrical_input",),
            ANY_PATH,
        ),
        (
            "thermal.environmental_inputs",
            "module_thermal",
            ("UPSTREAM",),
            ("module_electrical_input",),
            ANY_PATH,
        ),
        ("s8.inverter_inventory_binding", "dc_topology", ("S8", "S9"), ("s8_dc",), ANY_PATH),
        ("s8.inverter_mppt_mapping", "dc_topology", ("S8",), ("s8_dc",), ANY_PATH),
        ("s8.string_mppt_mapping", "dc_topology", ("S8",), ("s8_dc",), ANY_PATH),
        ("s8.string_module_count", "dc_topology", ("S8",), ("s8_dc",), ANY_PATH),
        ("s8.direct_branch_resistance", "dc_topology", ("S8",), ("s8_dc",), ANY_PATH),
        ("s8.shared_dc_collection_topology", "dc_topology", ("S8",), ("s8_dc",), FULL_PATH),
        ("s8.population_residual", "module_population", ("S8",), ("s8_dc",), ANY_PATH),
        ("s9.inverter_model_mapping", "inverter", ("S9",), ("s9_s10_inverter_control",), ANY_PATH),
        ("s9.conversion_model", "inverter", ("S9",), ("s9_s10_inverter_control",), ANY_PATH),
        ("s9.static_pq_capability", "inverter", ("S9",), ("s9_s10_inverter_control",), ANY_PATH),
        ("s9.fixed_q_convention", "inverter", ("S9",), ("s9_s10_inverter_control",), ANY_PATH),
        ("s9.thermal_capability", "inverter", ("S9",), ("s9_s10_inverter_control",), ANY_PATH),
        (
            "s9.inverter_temperature_state",
            "inverter",
            ("S9",),
            ("s9_s10_inverter_control",),
            ANY_PATH,
        ),
        (
            "s10.active_power_request",
            "controller",
            ("S10",),
            ("s9_s10_inverter_control",),
            ANY_PATH,
        ),
        (
            "s10.reactive_power_request",
            "controller",
            ("S9", "S10"),
            ("s9_s10_inverter_control",),
            ANY_PATH,
        ),
        (
            "s10.controller_allocation",
            "controller",
            ("S10",),
            ("s9_s10_inverter_control",),
            ANY_PATH,
        ),
        (
            "s10.request_timestamp_semantics",
            "controller",
            ("S10",),
            ("s9_s10_inverter_control",),
            ANY_PATH,
        ),
        (
            "s11.inverter_terminal_nodes",
            "lv_collection",
            ("S11",),
            ("s11_lv_collection",),
            ANY_PATH,
        ),
        ("s11.lv_topology", "lv_collection", ("S11",), ("s11_lv_collection",), ANY_PATH),
        ("s11.segment_impedance", "lv_collection", ("S11",), ("s11_lv_collection",), ANY_PATH),
        ("s11.collection_exits", "lv_collection", ("S11",), ("s11_lv_collection",), ANY_PATH),
        ("s11.exit_voltage", "lv_collection", ("S11",), ("s11_lv_collection",), ANY_PATH),
        ("s12.transformer_equipment", "transformer", ("S12",), ("s12_transformer",), ANY_PATH),
        (
            "s12.transformer_terminal_binding",
            "transformer",
            ("S12",),
            ("s12_transformer",),
            ANY_PATH,
        ),
        ("s12.ratio_tapping_impedance", "transformer", ("S12",), ("s12_transformer",), ANY_PATH),
        ("s12.factory_loss_evidence", "transformer", ("S12",), ("s12_transformer",), ANY_PATH),
        (
            "s12.construction_component_evidence",
            "transformer",
            ("S12",),
            ("s12_transformer",),
            FULL_PATH,
        ),
        ("s12.thermal_evidence", "transformer", ("S12",), ("s12_transformer",), FULL_PATH),
        ("s12.harmonic_evidence", "transformer", ("S12",), ("s12_transformer",), OPTIONAL),
        ("s12.lower_fidelity_baseline", "transformer", ("S12",), ("s12_transformer",), ANY_PATH),
        (
            "s13.transformer_network_binding",
            "mv_hv_network",
            ("S13",),
            ("s13_mv_hv_meter",),
            ANY_PATH,
        ),
        ("s13.mv_hv_topology", "mv_hv_network", ("S13",), ("s13_mv_hv_meter",), ANY_PATH),
        ("s13.segment_parameters", "mv_hv_network", ("S13",), ("s13_mv_hv_meter",), ANY_PATH),
        ("s13.grid_boundary", "mv_hv_network", ("S13",), ("s13_mv_hv_meter",), ANY_PATH),
        ("s13.grid_boundary_voltage", "mv_hv_network", ("S13",), ("s13_mv_hv_meter",), ANY_PATH),
        ("s13.revenue_meter_binding", "revenue_meter", ("S13",), ("s13_mv_hv_meter",), ANY_PATH),
        (
            "s13.revenue_meter_sign_conventions",
            "revenue_meter",
            ("S13",),
            ("s13_mv_hv_meter",),
            ANY_PATH,
        ),
        ("s13.revenue_meter_scaling", "revenue_meter", ("S13",), ("s13_mv_hv_meter",), ANY_PATH),
        (
            "s13.revenue_meter_measurement_semantics",
            "revenue_meter",
            ("S13",),
            ("s13_mv_hv_meter",),
            ANY_PATH,
        ),
        (
            "s14.interval_support_policy",
            "benchmark_policy",
            ("S14",),
            ("s14_benchmarking",),
            ANY_PATH,
        ),
        (
            "s14.benchmark_interval_semantics",
            "benchmark_policy",
            ("S13", "S14"),
            ("s14_benchmarking",),
            ANY_PATH,
        ),
        (
            "uncertainty.measurement_chain",
            "uncertainty",
            ("S13", "S14"),
            ("uncertainty",),
            ANY_PATH,
        ),
        ("uncertainty.expected_model", "uncertainty", ("S13", "S14"), ("uncertainty",), ANY_PATH),
    )
    return tuple(
        sorted((SiteEvidenceRequirement(*s) for s in specs), key=lambda r: r.requirement_id)
    )


REQUIREMENT_CATALOGUE = _catalogue()


def _text(value: object) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("expected exact non-empty unpadded string")


def _strings(values: object, *, nonempty: bool = False) -> None:
    if type(values) is not tuple or (nonempty and not values):
        raise ValueError("expected immutable identifier tuple")
    for value in values:
        _text(value)
    if len(set(values)) != len(values):
        raise ValueError("duplicate identifier")


def _enum(value: object, choices: frozenset[str]) -> None:
    _text(value)
    if value not in choices:
        raise ValueError("unreviewed vocabulary value")


def _stamp_wire(value: pd.Timestamp) -> dict[str, Any]:
    if type(value) is not pd.Timestamp or pd.isna(value) or value.tz is None:
        raise ValueError("exact aware non-NaT timestamp required")
    tz = value.tz
    if isinstance(tz, timezone):
        offset = tz.utcoffset(None)
        if offset is None:
            raise ValueError("unrepresentable timezone")
        spec = {"kind": "fixed", "name": str(tz), "seconds": offset.total_seconds()}
    else:
        name = getattr(tz, "key", None) or getattr(tz, "zone", None)
        _text(name)
        assert isinstance(name, str)
        ZoneInfo(name)
        spec = {"kind": "named", "name": name}
    try:
        return {"utc_ns": value.value, "timezone": spec, "iso8601": value.isoformat()}
    except (ValueError, OverflowError) as exc:
        raise ValueError("timestamp must be exactly representable in nanoseconds") from exc


@dataclass(frozen=True, slots=True)
class SiteEvidenceManifestIdentity:
    site_config_id: str
    site_uuid: str
    site_name: str
    manifest_version: str

    def __post_init__(self) -> None:
        for value in (self.site_config_id, self.site_uuid, self.site_name, self.manifest_version):
            _text(value)
        if str(UUID(self.site_uuid)) != self.site_uuid or self.site_uuid != str(
            uuid5(NAMESPACE_DNS, self.site_config_id)
        ):
            raise ValueError("site UUID must match the canonical application uuid5 mapping")


@dataclass(frozen=True, slots=True)
class PhysicalEvidenceScope:
    scope_type: str
    identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        _enum(
            self.scope_type,
            frozenset(
                {"site", "asset_set", "zone", "meter", "network_path", "model_class", "unknown"}
            ),
        )
        _strings(self.identifiers, nonempty=self.scope_type != "unknown")
        if self.scope_type == "site" and len(self.identifiers) != 1:
            raise ValueError("site scope identifies exactly one configuration site")
        if (self.scope_type == "unknown" and self.identifiers) or "all" in self.identifiers:
            raise ValueError(
                "unknown scope has no invented assets; wildcard coverage is not admitted"
            )


@dataclass(frozen=True, slots=True)
class EvidenceTemporalScope:
    semantics: str
    start_timestamp: pd.Timestamp | None = None
    end_timestamp: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        _enum(self.semantics, frozenset({"static", "bounded_interval", "snapshot", "unknown"}))
        if self.semantics in ("static", "unknown"):
            if self.start_timestamp is not None or self.end_timestamp is not None:
                raise ValueError("static/unknown evidence does not invent validity dates")
        else:
            if self.start_timestamp is None:
                raise ValueError("missing evidence timestamp")
            _stamp_wire(self.start_timestamp)
            if self.semantics == "snapshot":
                if self.end_timestamp is not None:
                    raise ValueError("snapshot has exactly one timestamp")
            else:
                if self.end_timestamp is None:
                    raise ValueError("missing evidence interval end")
                _stamp_wire(self.end_timestamp)
                if self.start_timestamp > self.end_timestamp:
                    raise ValueError("inverted evidence validity interval")


@dataclass(frozen=True, slots=True)
class SiteEvidenceFact:
    """An explicitly transcribed source fact; never a selected physics parameter."""

    fact_id: str
    source_reference: str
    value: str

    def __post_init__(self) -> None:
        for value in (self.fact_id, self.source_reference, self.value):
            _text(value)


@dataclass(frozen=True, slots=True)
class SiteEvidenceItem:
    requirement_id: str
    domain: str
    stage_refs: tuple[str, ...]
    evidence_state: str
    admission_state: str
    source_references: tuple[str, ...]
    source_kind: str
    reference_planes: tuple[str, ...]
    physical_scope: PhysicalEvidenceScope
    temporal_scope: EvidenceTemporalScope
    supported_fidelity: str
    admitted_authority_contract_ids: tuple[str, ...]
    target_authority_contract_ids: tuple[str, ...]
    gap_reason_codes: tuple[str, ...]
    notes: str
    facts: tuple[SiteEvidenceFact, ...] = ()
    authority_binding_reference: str | None = None
    applicability_reason: str | None = None
    confidence: str = "unknown"

    def __post_init__(self) -> None:
        _admit_item(self)


def _admit_item(item: SiteEvidenceItem) -> None:
    catalogue = {r.requirement_id: r for r in REQUIREMENT_CATALOGUE}
    _text(item.requirement_id)
    if item.requirement_id not in catalogue:
        raise ValueError("unreviewed requirement ID")
    definition = catalogue[item.requirement_id]
    _enum(item.domain, DOMAINS)
    _strings(item.stage_refs, nonempty=True)
    if (item.domain, item.stage_refs) != (definition.domain, definition.stage_refs):
        raise ValueError("requirement domain/stages disagree with catalogue")
    _enum(item.evidence_state, EVIDENCE_STATES)
    _enum(item.admission_state, ADMISSION_STATES)
    _enum(item.source_kind, SOURCE_KINDS)
    _enum(item.supported_fidelity, FIDELITIES)
    _enum(item.confidence, frozenset({"high", "medium", "low", "unknown"}))
    for values in (
        item.source_references,
        item.reference_planes,
        item.admitted_authority_contract_ids,
        item.target_authority_contract_ids,
        item.gap_reason_codes,
    ):
        _strings(values)
    _text(item.notes)
    if (
        type(item.physical_scope) is not PhysicalEvidenceScope
        or type(item.temporal_scope) is not EvidenceTemporalScope
    ):
        raise ValueError("exact immutable scopes required")
    item.physical_scope.__post_init__()
    item.temporal_scope.__post_init__()
    if type(item.facts) is not tuple or any(type(f) is not SiteEvidenceFact for f in item.facts):
        raise ValueError("immutable source facts required")
    for fact in item.facts:
        fact.__post_init__()
        if fact.source_reference not in item.source_references:
            raise ValueError("fact must identify a declared evidence source")
    if len({f.fact_id for f in item.facts}) != len(item.facts):
        raise ValueError("duplicate source fact ID")
    if item.evidence_state == "not_applicable":
        if item.admission_state != "not_applicable" or item.supported_fidelity != "not_applicable":
            raise ValueError("not-applicable states must agree")
        _text(item.applicability_reason)
        if (
            item.admitted_authority_contract_ids
            or item.target_authority_contract_ids
            or item.authority_binding_reference is not None
            or item.gap_reason_codes
        ):
            raise ValueError("not-applicable requirement cannot claim authority or a gap")
    else:
        if item.applicability_reason is not None or item.supported_fidelity == "not_applicable":
            raise ValueError("unexpected applicability claim")
        if item.evidence_state == "present":
            if (
                not item.source_references
                or item.source_kind == "external_evidence_not_supplied"
                or item.admission_state not in ("admitted", "not_admitted")
            ):
                raise ValueError(
                    "present evidence requires supplied sources and explicit admission decision"
                )
        elif item.evidence_state in ("missing", "conflicting"):
            if item.admission_state != "blocked":
                raise ValueError("missing/conflicting evidence must block admission")
            if item.evidence_state == "conflicting" and (
                not item.source_references
                or (len(item.source_references) < 2 and len(item.facts) < 2)
            ):
                raise ValueError("conflict requires multiple identified representations")
        if item.admission_state == "admitted":
            if not item.admitted_authority_contract_ids or item.supported_fidelity not in (
                FULL_SUPPORT,
                LOWER_SUPPORT,
            ):
                raise ValueError("admission requires authority IDs and physical support")
            _text(item.authority_binding_reference)
            if item.gap_reason_codes:
                raise ValueError("admitted requirement cannot retain unresolved gap reasons")
            if item.source_kind == "surveyed_geometry" and item.domain not in (
                "spatial_geometry",
                "irradiance_optics",
            ):
                raise ValueError("surveyed geometry alone is not electrical authority")
        elif (
            item.admitted_authority_contract_ids
            or item.authority_binding_reference is not None
            or not item.gap_reason_codes
        ):
            raise ValueError("unadmitted evidence requires gaps, not admitted authority claims")


@dataclass(frozen=True, slots=True)
class SitePhysicalPathCoverage:
    section: str
    state: str
    full_fidelity_state: str
    blocking_requirement_ids: tuple[str, ...]
    full_fidelity_blocking_requirement_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SiteEvidenceCoverageDiagnostics:
    total_requirement_count: int
    present_count: int
    missing_count: int
    conflicting_count: int
    not_applicable_count: int
    admitted_count: int
    not_admitted_count: int
    blocked_count: int
    admission_not_applicable_count: int
    full_fidelity_support_count: int
    lower_fidelity_support_count: int
    non_resolving_count: int
    fidelity_not_applicable_count: int
    domain_counts: tuple[tuple[str, int], ...]
    stage_counts: tuple[tuple[str, int], ...]


def _coverage(items: tuple[SiteEvidenceItem, ...]) -> tuple[SitePhysicalPathCoverage, ...]:
    definitions = {r.requirement_id: r for r in REQUIREMENT_CATALOGUE}
    output = []
    for section in PATH_SECTIONS:
        members = tuple(i for i in items if section in definitions[i.requirement_id].path_sections)
        blockers = tuple(
            i.requirement_id
            for i in members
            if definitions[i.requirement_id].requirement_level == ANY_PATH
            and i.admission_state not in ("admitted", "not_applicable")
        )
        full_blockers = tuple(
            i.requirement_id
            for i in members
            if definitions[i.requirement_id].requirement_level != OPTIONAL
            and (
                i.admission_state not in ("admitted", "not_applicable")
                or (i.admission_state == "admitted" and i.supported_fidelity != FULL_SUPPORT)
            )
        )
        states = []
        for full, gaps in ((False, blockers), (True, full_blockers)):
            required = tuple(
                i
                for i in members
                if definitions[i.requirement_id].requirement_level
                in ((ANY_PATH, FULL_PATH) if full else (ANY_PATH,))
            )
            if all(i.admission_state == "not_applicable" for i in members):
                state = "not_applicable"
            elif required and not gaps:
                state = "admitted"
            elif any(i.admission_state == "admitted" for i in required):
                state = "partially_admitted"
            else:
                state = "blocked"
            states.append(state)
        output.append(
            SitePhysicalPathCoverage(section, states[0], states[1], blockers, full_blockers)
        )
    return tuple(output)


def _diagnostics(items: tuple[SiteEvidenceItem, ...]) -> SiteEvidenceCoverageDiagnostics:
    evidence = Counter(i.evidence_state for i in items)
    admission = Counter(i.admission_state for i in items)
    full = sum(
        i.admission_state == "admitted" and i.supported_fidelity == FULL_SUPPORT for i in items
    )
    lower = sum(
        i.admission_state == "admitted" and i.supported_fidelity == LOWER_SUPPORT for i in items
    )
    na = evidence["not_applicable"]
    return SiteEvidenceCoverageDiagnostics(
        len(items),
        evidence["present"],
        evidence["missing"],
        evidence["conflicting"],
        na,
        admission["admitted"],
        admission["not_admitted"],
        admission["blocked"],
        admission["not_applicable"],
        full,
        lower,
        len(items) - full - lower - na,
        na,
        tuple(sorted(Counter(i.domain for i in items).items())),
        tuple(sorted(Counter(s for i in items for s in i.stage_refs).items())),
    )


@dataclass(frozen=True, slots=True)
class SiteEvidenceManifest:
    identity: SiteEvidenceManifestIdentity
    items: tuple[SiteEvidenceItem, ...]
    path_coverage: tuple[SitePhysicalPathCoverage, ...] = field(init=False)
    diagnostics: SiteEvidenceCoverageDiagnostics = field(init=False)
    contract: str = field(init=False, default=SITE_EVIDENCE_MANIFEST_CONTRACT_ID)
    scope: str = field(init=False, default=SITE_EVIDENCE_MANIFEST_SCOPE)

    def __post_init__(self) -> None:
        if type(self.identity) is not SiteEvidenceManifestIdentity or type(self.items) is not tuple:
            raise ValueError("exact immutable manifest identity/items required")
        self.identity.__post_init__()
        for item in self.items:
            if type(item) is not SiteEvidenceItem:
                raise ValueError("exact evidence items required")
            _admit_item(item)
            if item.physical_scope.scope_type == "site" and item.physical_scope.identifiers != (
                self.identity.site_config_id,
            ):
                raise ValueError("evidence scope points at another site")
        ids = tuple(i.requirement_id for i in self.items)
        if len(set(ids)) != len(ids) or set(ids) != {
            r.requirement_id for r in REQUIREMENT_CATALOGUE
        }:
            raise ValueError("catalogue must be complete, unique and reviewed")
        ordered = tuple(sorted(self.items, key=lambda i: i.requirement_id))
        object.__setattr__(self, "items", ordered)
        object.__setattr__(self, "path_coverage", _coverage(ordered))
        object.__setattr__(self, "diagnostics", _diagnostics(ordered))


def validate_manifest_against_site_config(
    manifest: SiteEvidenceManifest, site_config: SiteConfig
) -> None:
    """Check identity only; no configuration value becomes a physics authority."""
    validate_site_evidence_manifest(manifest)
    if type(site_config) is not SiteConfig or (
        manifest.identity.site_config_id,
        manifest.identity.site_uuid,
        manifest.identity.site_name,
    ) != (site_config.id, str(uuid5(NAMESPACE_DNS, site_config.id)), site_config.name):
        raise ValueError("manifest does not identify the supplied site configuration")


def _wire(value: Any) -> Any:
    if type(value) is pd.Timestamp:
        return _stamp_wire(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _wire(getattr(value, f.name)) for f in fields(value)}
    if type(value) is tuple:
        return [_wire(x) for x in value]
    return value


def serialize_site_evidence_manifest(manifest: SiteEvidenceManifest) -> dict[str, Any]:
    validate_site_evidence_manifest(manifest)
    result: dict[str, Any] = _wire(manifest)
    return result


def _object(value: Any, cls: type[Any], *, derived: bool = False) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {f.name for f in fields(cls) if derived or f.init}:
        raise ValueError("unknown/missing manifest schema fields")
    return dict(value)


def _array(value: Any) -> tuple[Any, ...]:
    if type(value) is not list:
        raise ValueError("wire tuples must be JSON/YAML arrays")
    return tuple(value)


def _unpack_stamp(raw: Any) -> pd.Timestamp | None:
    if raw is None:
        return None
    if (
        type(raw) is not dict
        or set(raw) != {"utc_ns", "timezone", "iso8601"}
        or type(raw["utc_ns"]) is not int
    ):
        raise ValueError("invalid evidence timestamp schema")
    spec = raw["timezone"]
    if type(spec) is not dict:
        raise ValueError("invalid timezone descriptor")
    if spec.get("kind") == "named" and set(spec) == {"kind", "name"}:
        _text(spec["name"])
        tz: Any = ZoneInfo(spec["name"])
    elif spec.get("kind") == "fixed" and set(spec) == {"kind", "name", "seconds"}:
        _text(spec["name"])
        if type(spec["seconds"]) not in (float, int):
            raise ValueError("invalid fixed timezone offset")
        tz = timezone(timedelta(seconds=spec["seconds"]), spec["name"])
    else:
        raise ValueError("invalid timezone descriptor")
    timestamp = pd.Timestamp(raw["utc_ns"], tz="UTC").tz_convert(tz)
    if _stamp_wire(timestamp) != raw:
        raise ValueError("inconsistent timestamp persistence")
    return timestamp


def _from_input(raw: Any) -> SiteEvidenceManifest:
    if type(raw) is not dict or set(raw) != {"identity", "items", "contract", "scope"}:
        raise ValueError("unknown/missing manifest input fields")
    data = dict(raw)
    if (
        type(data["contract"]) is not str
        or data["contract"] != SITE_EVIDENCE_MANIFEST_CONTRACT_ID
        or type(data["scope"]) is not str
        or data["scope"] != SITE_EVIDENCE_MANIFEST_SCOPE
    ):
        raise ValueError("unreviewed manifest contract/scope")
    identity = SiteEvidenceManifestIdentity(
        **_object(data["identity"], SiteEvidenceManifestIdentity)
    )
    items = []
    for raw_item in _array(data["items"]):
        row = _object(raw_item, SiteEvidenceItem)
        for key in (
            "stage_refs",
            "source_references",
            "reference_planes",
            "admitted_authority_contract_ids",
            "target_authority_contract_ids",
            "gap_reason_codes",
        ):
            row[key] = _array(row[key])
        physical = _object(row["physical_scope"], PhysicalEvidenceScope)
        physical["identifiers"] = _array(physical["identifiers"])
        row["physical_scope"] = PhysicalEvidenceScope(**physical)
        temporal = _object(row["temporal_scope"], EvidenceTemporalScope)
        for key in ("start_timestamp", "end_timestamp"):
            temporal[key] = _unpack_stamp(temporal[key])
        row["temporal_scope"] = EvidenceTemporalScope(**temporal)
        row["facts"] = tuple(
            SiteEvidenceFact(**_object(f, SiteEvidenceFact)) for f in _array(row["facts"])
        )
        items.append(SiteEvidenceItem(**row))
    return SiteEvidenceManifest(identity, tuple(items))


def deserialize_site_evidence_manifest(payload: Mapping[str, Any]) -> SiteEvidenceManifest:
    """Read exact wire schema; recompute and check stored diagnostics/coverage."""
    data = _object(payload, SiteEvidenceManifest, derived=True)
    manifest = _from_input({key: data[key] for key in ("identity", "items", "contract", "scope")})
    canonical = serialize_site_evidence_manifest(manifest)
    # JSON comparison preserves bool/int distinctions and rejects nonfinite values.
    if json.dumps(data, sort_keys=True, allow_nan=False) != json.dumps(
        canonical, sort_keys=True, allow_nan=False
    ):
        raise ValueError(
            "stored manifest state/diagnostics/schema contradict canonical reconstruction"
        )
    return manifest


class _UniqueSafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    pass


def _unique_mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError("duplicate YAML mapping key")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_site_evidence_manifest(path: Path) -> SiteEvidenceManifest:
    """Load only the supplied YAML inventory; no scanning, services or activation."""
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    manifest = _from_input(raw)
    validate_site_evidence_manifest(manifest)
    return manifest


def render_site_evidence_coverage_markdown(manifest: SiteEvidenceManifest) -> str:
    """Single-source documentation view, with a checked-in drift regression."""
    validate_site_evidence_manifest(manifest)
    lines = ["| Requirement | Evidence | Admission |", "| --- | --- | --- |"]
    lines.extend(
        f"| `{i.requirement_id}` | {i.evidence_state} | {i.admission_state} |"
        for i in manifest.items
    )
    return "\n".join(lines)


def validate_site_evidence_manifest(manifest: SiteEvidenceManifest) -> None:
    """Independently replay the inventory, nested scopes, readiness and counts.

    Does not invoke constructors, production admission/coverage/diagnostic helpers,
    serialization or YAML loading. Canonical catalogue/constants are shared data.
    This validates a binding declaration, not an unavailable physics authority.
    """

    def text(value: object) -> None:
        if type(value) is not str or not value or value.strip() != value:
            raise ValueError("invalid exact identifier")

    def identifiers(value: object, required: bool = False) -> None:
        if type(value) is not tuple or (required and not value):
            raise ValueError("invalid immutable identifier collection")
        for entry in value:
            text(entry)
        if len(set(value)) != len(value):
            raise ValueError("repeated identifier")

    if type(manifest) is not SiteEvidenceManifest:
        raise ValueError("exact manifest required")
    identity = manifest.identity
    if type(identity) is not SiteEvidenceManifestIdentity:
        raise ValueError("invalid identity")
    for value in (
        identity.site_config_id,
        identity.site_uuid,
        identity.site_name,
        identity.manifest_version,
    ):
        text(value)
    if str(UUID(identity.site_uuid)) != identity.site_uuid or identity.site_uuid != str(
        uuid5(NAMESPACE_DNS, identity.site_config_id)
    ):
        raise ValueError("canonical site UUID mismatch")
    if (
        type(manifest.contract) is not str
        or manifest.contract != SITE_EVIDENCE_MANIFEST_CONTRACT_ID
        or type(manifest.scope) is not str
        or manifest.scope != SITE_EVIDENCE_MANIFEST_SCOPE
    ):
        raise ValueError("fixed contract semantics mismatch")
    if type(manifest.items) is not tuple:
        raise ValueError("mutable evidence inventory")
    if tuple(i.requirement_id for i in manifest.items if type(i) is SiteEvidenceItem) != tuple(
        r.requirement_id for r in REQUIREMENT_CATALOGUE
    ):
        raise ValueError("noncanonical catalogue completeness/order")
    evidence_counts: dict[str, int] = {}
    admission_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    full = lower = 0
    for item, definition in zip(manifest.items, REQUIREMENT_CATALOGUE, strict=True):
        if type(item) is not SiteEvidenceItem:
            raise ValueError("invalid evidence item")
        for value in (
            item.requirement_id,
            item.domain,
            item.evidence_state,
            item.admission_state,
            item.source_kind,
            item.supported_fidelity,
            item.notes,
            item.confidence,
        ):
            text(value)
        for sequence in (
            item.stage_refs,
            item.source_references,
            item.reference_planes,
            item.admitted_authority_contract_ids,
            item.target_authority_contract_ids,
            item.gap_reason_codes,
        ):
            identifiers(sequence)
        if item.domain != definition.domain or item.stage_refs != definition.stage_refs:
            raise ValueError("catalogue domain/stage mismatch")
        if (
            item.evidence_state not in EVIDENCE_STATES
            or item.admission_state not in ADMISSION_STATES
            or item.source_kind not in SOURCE_KINDS
            or item.supported_fidelity not in FIDELITIES
            or item.confidence not in ("high", "medium", "low", "unknown")
        ):
            raise ValueError("unreviewed inventory vocabulary")
        physical = item.physical_scope
        if type(physical) is not PhysicalEvidenceScope:
            raise ValueError("invalid physical scope")
        text(physical.scope_type)
        if physical.scope_type not in (
            "site",
            "asset_set",
            "zone",
            "meter",
            "network_path",
            "model_class",
            "unknown",
        ):
            raise ValueError("unknown physical scope type")
        identifiers(physical.identifiers, physical.scope_type != "unknown")
        if physical.scope_type == "site" and physical.identifiers != (identity.site_config_id,):
            raise ValueError("site scope disagrees with manifest identity")
        if "all" in physical.identifiers or (
            physical.scope_type == "unknown" and physical.identifiers
        ):
            raise ValueError("invented/wildcard physical scope")
        temporal = item.temporal_scope
        if type(temporal) is not EvidenceTemporalScope:
            raise ValueError("invalid temporal scope")
        text(temporal.semantics)
        if temporal.semantics in ("static", "unknown"):
            if temporal.start_timestamp is not None or temporal.end_timestamp is not None:
                raise ValueError("invented temporal validity")
        elif temporal.semantics in ("snapshot", "bounded_interval"):
            stamps = (
                (temporal.start_timestamp,)
                if temporal.semantics == "snapshot"
                else (temporal.start_timestamp, temporal.end_timestamp)
            )
            if temporal.semantics == "snapshot" and temporal.end_timestamp is not None:
                raise ValueError("snapshot is not an interval")
            for stamp in stamps:
                if (
                    stamp is None
                    or type(stamp) is not pd.Timestamp
                    or pd.isna(stamp)
                    or stamp.tz is None
                ):
                    raise ValueError("evidence requires exact aware timestamp")
                try:
                    ns = stamp.value
                    zone = stamp.tz
                    if isinstance(zone, timezone):
                        offset = zone.utcoffset(None)
                        if offset is None:
                            raise ValueError("unrepresentable timezone")
                        replay_zone: Any = timezone(offset, str(zone))
                    else:
                        zone_name = getattr(zone, "key", None) or getattr(zone, "zone", None)
                        text(zone_name)
                        assert isinstance(zone_name, str)
                        replay_zone = ZoneInfo(zone_name)
                    replay = pd.Timestamp(ns, tz="UTC").tz_convert(replay_zone)
                    if (
                        replay != stamp
                        or replay.isoformat() != stamp.isoformat()
                        or str(replay.tz) != str(stamp.tz)
                    ):
                        raise ValueError("unrepresentable timestamp persistence")
                except (OverflowError, TypeError) as exc:
                    raise ValueError("invalid evidence timestamp") from exc
            if temporal.semantics == "bounded_interval":
                if temporal.start_timestamp is None or temporal.end_timestamp is None:
                    raise ValueError("missing evidence interval boundary")
                if temporal.start_timestamp > temporal.end_timestamp:
                    raise ValueError("inverted temporal evidence")
        else:
            raise ValueError("invalid temporal semantics")
        if type(item.facts) is not tuple:
            raise ValueError("mutable facts")
        fact_ids = []
        for fact in item.facts:
            if type(fact) is not SiteEvidenceFact:
                raise ValueError("invalid source fact")
            for value in (fact.fact_id, fact.source_reference, fact.value):
                text(value)
            if fact.source_reference not in item.source_references:
                raise ValueError("fact lacks declared source")
            fact_ids.append(fact.fact_id)
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("duplicate fact identity")
        if item.evidence_state == "not_applicable":
            if (
                item.admission_state != "not_applicable"
                or item.supported_fidelity != "not_applicable"
            ):
                raise ValueError("not-applicable state disagreement")
            text(item.applicability_reason)
            if (
                item.admitted_authority_contract_ids
                or item.target_authority_contract_ids
                or item.authority_binding_reference is not None
                or item.gap_reason_codes
            ):
                raise ValueError("not-applicable authority contradiction")
        else:
            if item.applicability_reason is not None or item.supported_fidelity == "not_applicable":
                raise ValueError("unexpected applicability state")
            if item.evidence_state == "present":
                if (
                    not item.source_references
                    or item.source_kind == "external_evidence_not_supplied"
                    or item.admission_state not in ("admitted", "not_admitted")
                ):
                    raise ValueError("invalid present evidence decision")
            elif item.evidence_state in ("missing", "conflicting"):
                if item.admission_state != "blocked":
                    raise ValueError("missing/conflicting evidence cannot be admitted")
                if item.evidence_state == "conflicting" and (
                    not item.source_references
                    or (len(item.source_references) < 2 and len(item.facts) < 2)
                ):
                    raise ValueError("insufficient identified conflicting representations")
            if item.admission_state == "admitted":
                if (
                    not item.admitted_authority_contract_ids
                    or item.supported_fidelity not in (FULL_SUPPORT, LOWER_SUPPORT)
                    or item.gap_reason_codes
                ):
                    raise ValueError("invalid authority admission declaration")
                text(item.authority_binding_reference)
                if item.source_kind == "surveyed_geometry" and item.domain not in (
                    "spatial_geometry",
                    "irradiance_optics",
                ):
                    raise ValueError("spatial evidence is not electrical authority")
            elif (
                item.admitted_authority_contract_ids
                or item.authority_binding_reference is not None
                or not item.gap_reason_codes
            ):
                raise ValueError("unadmitted item claims authority or hides gaps")
        evidence_counts[item.evidence_state] = evidence_counts.get(item.evidence_state, 0) + 1
        admission_counts[item.admission_state] = admission_counts.get(item.admission_state, 0) + 1
        domain_counts[item.domain] = domain_counts.get(item.domain, 0) + 1
        for stage in item.stage_refs:
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        full += int(item.admission_state == "admitted" and item.supported_fidelity == FULL_SUPPORT)
        lower += int(
            item.admission_state == "admitted" and item.supported_fidelity == LOWER_SUPPORT
        )
    if type(manifest.path_coverage) is not tuple or len(manifest.path_coverage) != len(
        PATH_SECTIONS
    ):
        raise ValueError("invalid path coverage schema")
    for section, published in zip(PATH_SECTIONS, manifest.path_coverage, strict=True):
        members = [
            (i, d)
            for i, d in zip(manifest.items, REQUIREMENT_CATALOGUE, strict=True)
            if section in d.path_sections
        ]
        states = []
        blocking = []
        for full_path in (False, True):
            required = [
                (i, d)
                for i, d in members
                if d.requirement_level == ANY_PATH
                or (full_path and d.requirement_level == FULL_PATH)
            ]
            gaps = tuple(
                i.requirement_id
                for i, _ in required
                if i.admission_state not in ("admitted", "not_applicable")
                or (
                    full_path
                    and i.admission_state == "admitted"
                    and i.supported_fidelity != FULL_SUPPORT
                )
            )
            if all(i.admission_state == "not_applicable" for i, _ in members):
                state = "not_applicable"
            elif required and not gaps:
                state = "admitted"
            elif any(i.admission_state == "admitted" for i, _ in required):
                state = "partially_admitted"
            else:
                state = "blocked"
            states.append(state)
            blocking.append(gaps)
        expected_path = (section, states[0], states[1], blocking[0], blocking[1])
        if type(published) is not SitePhysicalPathCoverage:
            raise ValueError("invalid path coverage object")
        for f, expected in zip(fields(published), expected_path, strict=True):
            actual = getattr(published, f.name)
            if type(actual) is not type(expected) or actual != expected:
                raise ValueError("path coverage contradiction")
    total = len(manifest.items)
    na = evidence_counts.get("not_applicable", 0)
    expected_counts: tuple[object, ...] = (
        total,
        *(
            evidence_counts.get(s, 0)
            for s in ("present", "missing", "conflicting", "not_applicable")
        ),
        *(
            admission_counts.get(s, 0)
            for s in ("admitted", "not_admitted", "blocked", "not_applicable")
        ),
        full,
        lower,
        total - full - lower - na,
        na,
        tuple(sorted(domain_counts.items())),
        tuple(sorted(stage_counts.items())),
    )
    diagnostics = manifest.diagnostics
    if type(diagnostics) is not SiteEvidenceCoverageDiagnostics:
        raise ValueError("invalid diagnostics object")
    for f, expected_count in zip(fields(diagnostics), expected_counts, strict=True):
        actual = getattr(diagnostics, f.name)
        if type(actual) is not type(expected_count) or actual != expected_count:
            raise ValueError("diagnostics contradiction")
    for counts in (diagnostics.domain_counts, diagnostics.stage_counts):
        if any(
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not int
            for pair in counts
        ):
            raise ValueError("invalid diagnostic count schema")
