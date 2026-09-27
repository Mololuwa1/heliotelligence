"""Static topology-aware inverter equipment authority.

S9-0 binds each explicitly referenced physical inverter to the repository's
validated CEC/SAM Sandia conversion model and DC operating envelope.  It does
not consume an electrical operating state, evaluate limits, aggregate MPPTs,
or perform inverter conversion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter import ResolvedSandiaInverterModel
from heliotelligence.physics.inverter_envelope import (
    ResolvedInverterDcOperatingEnvelope,
)

TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID = (
    "topology_inverter_cec_sam_authority_v1"
)
TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID = (
    "exact_cec_sam_sandia_and_dc_envelope_authority_v1"
)
TOPOLOGY_INVERTER_AUTHORITY_SCOPE = (
    "static_inverter_equipment_authority_before_dc_state_evaluation"
)
TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_inverter_id_to_cec_sam_reference"
)

_STATE_COLUMNS = (
    "inverter_model_reference",
    "inverter_authority_resolved",
    "inverter_authority_state",
    "sandia_parameter_source",
    "sandia_confidence",
    "envelope_parameter_source",
    "envelope_confidence",
    "topology_inverter_authority_contract",
    "topology_inverter_authority_model",
    "topology_inverter_authority_scope",
    "topology_inverter_authority_coverage_scope",
)


@dataclass(frozen=True)
class TopologyInverterAuthorityDiagnostics:
    """Deterministic topology inverter-authority count closure."""

    inverter_count: int
    resolved_inverter_count: int
    unresolved_inverter_count: int
    explicit_reference_count: int
    missing_reference_count: int
    unique_explicit_model_count: int
    sandia_lookup_count: int
    envelope_lookup_count: int
    authority_model: str


@dataclass(frozen=True)
class TopologyInverterAuthorityResult:
    """Resolved immutable equipment authority keyed by physical inverter ID."""

    sandia_models_by_inverter_id: Mapping[str, ResolvedSandiaInverterModel]
    dc_envelopes_by_inverter_id: Mapping[
        str, ResolvedInverterDcOperatingEnvelope
    ]
    states: pd.DataFrame
    diagnostics: TopologyInverterAuthorityDiagnostics


def resolve_topology_inverter_authority(
    topology: ElectricalTopologyConfig,
    cec_sam_name_by_inverter_id: Mapping[str, str],
) -> TopologyInverterAuthorityResult:
    """Resolve exact explicit CEC/SAM authority for each topology inverter."""

    if type(topology) is not ElectricalTopologyConfig:
        raise TypeError("topology must be exactly ElectricalTopologyConfig")
    if not isinstance(cec_sam_name_by_inverter_id, Mapping):
        raise TypeError("cec_sam_name_by_inverter_id must be a mapping")

    inverter_ids = [inverter.id for inverter in topology.inverters]
    inverter_id_set = set(inverter_ids)
    unexpected = [
        inverter_id
        for inverter_id in cec_sam_name_by_inverter_id
        if inverter_id not in inverter_id_set
    ]
    if unexpected:
        raise ValueError(f"unexpected inverter model reference IDs: {unexpected!r}")

    explicit_names: dict[str, str] = {}
    for inverter_id in inverter_ids:
        if inverter_id not in cec_sam_name_by_inverter_id:
            continue
        explicit_value = cec_sam_name_by_inverter_id[inverter_id]
        if type(explicit_value) is not str or not explicit_value.strip():
            raise ValueError(
                "every explicit CEC/SAM inverter reference must be a non-empty, "
                "non-whitespace string"
            )
        explicit_names[inverter_id] = explicit_value

    unique_names = list(dict.fromkeys(explicit_names.values()))
    sandia_by_name: dict[str, ResolvedSandiaInverterModel] = {}
    envelope_by_name: dict[str, ResolvedInverterDcOperatingEnvelope] = {}
    for name in unique_names:
        sandia_by_name[name] = inverter_lookup.resolve_cec_sandia_inverter_model(name)
        envelope_by_name[name] = (
            inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope(name)
        )

    sandia_by_inverter: dict[str, ResolvedSandiaInverterModel] = {}
    envelope_by_inverter: dict[str, ResolvedInverterDcOperatingEnvelope] = {}
    records: list[dict[str, object]] = []
    for inverter_id in inverter_ids:
        row_name = explicit_names.get(inverter_id)
        if row_name is None:
            resolved = False
            state = "unresolved_no_explicit_inverter_model_reference"
            reference = ""
            sandia_source = ""
            sandia_confidence = "unknown"
            envelope_source = ""
            envelope_confidence = "unknown"
        else:
            resolved = True
            state = "resolved_cec_sam_sandia_inverter_authority"
            reference = row_name
            sandia = sandia_by_name[row_name]
            envelope = envelope_by_name[row_name]
            sandia_by_inverter[inverter_id] = sandia
            envelope_by_inverter[inverter_id] = envelope
            sandia_source = sandia.parameter_source
            sandia_confidence = sandia.confidence
            envelope_source = envelope.parameter_source
            envelope_confidence = envelope.confidence
        records.append(
            {
                "inverter_model_reference": reference,
                "inverter_authority_resolved": resolved,
                "inverter_authority_state": state,
                "sandia_parameter_source": sandia_source,
                "sandia_confidence": sandia_confidence,
                "envelope_parameter_source": envelope_source,
                "envelope_confidence": envelope_confidence,
                "topology_inverter_authority_contract": (
                    TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID
                ),
                "topology_inverter_authority_model": (
                    TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID
                ),
                "topology_inverter_authority_scope": (
                    TOPOLOGY_INVERTER_AUTHORITY_SCOPE
                ),
                "topology_inverter_authority_coverage_scope": (
                    TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE
                ),
            }
        )

    states = pd.DataFrame.from_records(
        records,
        columns=_STATE_COLUMNS,
        index=pd.Index(inverter_ids, name="inverter_id"),
    )
    states.index.name = "inverter_id"
    diagnostics = TopologyInverterAuthorityDiagnostics(
        inverter_count=topology.inverter_count,
        resolved_inverter_count=len(explicit_names),
        unresolved_inverter_count=topology.inverter_count - len(explicit_names),
        explicit_reference_count=len(explicit_names),
        missing_reference_count=topology.inverter_count - len(explicit_names),
        unique_explicit_model_count=len(unique_names),
        sandia_lookup_count=len(unique_names),
        envelope_lookup_count=len(unique_names),
        authority_model=TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
    )
    _validate_result(
        topology,
        explicit_names,
        sandia_by_inverter,
        envelope_by_inverter,
        states,
        diagnostics,
    )
    return TopologyInverterAuthorityResult(
        sandia_models_by_inverter_id=MappingProxyType(sandia_by_inverter.copy()),
        dc_envelopes_by_inverter_id=MappingProxyType(envelope_by_inverter.copy()),
        states=states.copy(deep=True),
        diagnostics=diagnostics,
    )


def _validate_result(
    topology: ElectricalTopologyConfig,
    explicit_names: Mapping[str, str],
    sandia_models: Mapping[str, ResolvedSandiaInverterModel],
    dc_envelopes: Mapping[str, ResolvedInverterDcOperatingEnvelope],
    states: pd.DataFrame,
    diagnostics: TopologyInverterAuthorityDiagnostics,
) -> None:
    inverter_ids = [inverter.id for inverter in topology.inverters]
    resolved_ids = list(explicit_names)
    if tuple(states.columns) != _STATE_COLUMNS:
        raise RuntimeError("topology inverter authority state schema is invalid")
    if states.index.name != "inverter_id" or states.index.has_duplicates:
        raise RuntimeError("topology inverter authority state index is invalid")
    if states.index.tolist() != inverter_ids or len(states) != topology.inverter_count:
        raise RuntimeError("topology inverter authority ordering is invalid")
    if list(sandia_models) != resolved_ids or list(dc_envelopes) != resolved_ids:
        raise RuntimeError("resolved inverter authority mapping identity is inconsistent")

    provenance = {
        "topology_inverter_authority_contract": (
            TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID
        ),
        "topology_inverter_authority_model": TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
        "topology_inverter_authority_scope": TOPOLOGY_INVERTER_AUTHORITY_SCOPE,
        "topology_inverter_authority_coverage_scope": (
            TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE
        ),
    }
    for inverter_id, row in states.iterrows():
        for column, expected_value in provenance.items():
            if row[column] != expected_value:
                raise RuntimeError(f"topology inverter authority {column} is invalid")
        if inverter_id in explicit_names:
            name = explicit_names[inverter_id]
            sandia = sandia_models[inverter_id]
            envelope = dc_envelopes[inverter_id]
            expected_source = f"cec_sam:{name}"
            expected_state = (
                name,
                True,
                "resolved_cec_sam_sandia_inverter_authority",
                expected_source,
                sandia.confidence,
                expected_source,
                envelope.confidence,
            )
            if sandia.parameter_source != expected_source:
                raise RuntimeError("Sandia source does not match explicit reference")
            if envelope.parameter_source != expected_source:
                raise RuntimeError("envelope source does not match explicit reference")
        else:
            expected_state = (
                "",
                False,
                "unresolved_no_explicit_inverter_model_reference",
                "",
                "unknown",
                "",
                "unknown",
            )
        actual = tuple(
            row[column]
            for column in (
                "inverter_model_reference",
                "inverter_authority_resolved",
                "inverter_authority_state",
                "sandia_parameter_source",
                "sandia_confidence",
                "envelope_parameter_source",
                "envelope_confidence",
            )
        )
        if actual != expected_state:
            raise RuntimeError("topology inverter authority state is contradictory")

    resolved_count = int(states["inverter_authority_resolved"].sum())
    expected_diagnostics = TopologyInverterAuthorityDiagnostics(
        inverter_count=topology.inverter_count,
        resolved_inverter_count=resolved_count,
        unresolved_inverter_count=len(states) - resolved_count,
        explicit_reference_count=len(explicit_names),
        missing_reference_count=topology.inverter_count - len(explicit_names),
        unique_explicit_model_count=len(set(explicit_names.values())),
        sandia_lookup_count=len(set(explicit_names.values())),
        envelope_lookup_count=len(set(explicit_names.values())),
        authority_model=TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
    )
    if diagnostics != expected_diagnostics:
        raise RuntimeError("topology inverter authority diagnostics are inconsistent")
