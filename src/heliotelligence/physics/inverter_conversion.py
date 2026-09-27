"""Topology-aware Sandia conversion for one physical inverter.

S9-2 converts admitted S9-1 MPPT-input states without collapsing independent
tracker voltages or currents.  DC power is additive; multi-input conversion is
delegated to the pinned public :func:`pvlib.inverter.sandia_multi` primitive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]
import pvlib.inverter  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics.inverter import calculate_sandia_inverter_ac_power
from heliotelligence.physics.inverter_authority import (
    TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
    TOPOLOGY_INVERTER_AUTHORITY_SCOPE,
    TopologyInverterAuthorityResult,
)
from heliotelligence.physics.inverter_topology import (
    TOPOLOGY_INVERTER_DC_ENVELOPE_CONTRACT_ID,
    TOPOLOGY_INVERTER_DC_ENVELOPE_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID,
    TOPOLOGY_INVERTER_DC_ENVELOPE_SCOPE,
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeDiagnostics,
    TopologyInverterDcEnvelopeResult,
    evaluate_topology_inverter_dc_envelope,
)

TOPOLOGY_SANDIA_INVERTER_AC_CONTRACT_ID = "admitted_mppt_input_dc_to_sandia_inverter_ac_v1"
TOPOLOGY_SANDIA_INVERTER_AC_MODEL_ID = "pvlib_sandia_single_or_multi_mppt_inverter_conversion_v1"
TOPOLOGY_SANDIA_INVERTER_AC_SCOPE = "inverter_ac_available_before_ac_network_and_dispatch"
TOPOLOGY_SANDIA_INVERTER_AC_COVERAGE_SCOPE = (
    "cec_sam_sandia_inverters_with_admitted_mppt_input_states"
)

MPPT_INPUT_REFERENCE_PLANE = "mppt_input"
INVERTER_AC_OUTPUT_REFERENCE_PLANE = "inverter_ac_output"

_COLUMNS = (
    "configured_mppt_count",
    "populated_mppt_count",
    "active_mppt_count",
    "inactive_mppt_count",
    "unresolved_mppt_count",
    "violating_mppt_count",
    "unresolved_mppt_ids",
    "unresolved_mppt_states",
    "violating_mppt_ids",
    "violating_mppt_states",
    "p_dc_inverter_input_w",
    "p_ac_available_w",
    "ac_to_dc_ratio",
    "at_ac_power_limit",
    "inverter_conversion_resolved",
    "inverter_conversion_state",
    "inverter_model_reference",
    "sandia_parameter_source",
    "sandia_confidence",
    "sandia_conversion_path",
    "source_reference_plane",
    "sink_reference_plane",
    "topology_inverter_authority_contract",
    "topology_inverter_authority_model",
    "topology_inverter_authority_scope",
    "topology_inverter_authority_coverage_scope",
    "topology_inverter_dc_envelope_contract",
    "topology_inverter_dc_envelope_model",
    "topology_inverter_dc_envelope_scope",
    "topology_inverter_dc_envelope_coverage_scope",
    "topology_sandia_inverter_ac_contract",
    "topology_sandia_inverter_ac_model",
    "topology_sandia_inverter_ac_scope",
    "topology_sandia_inverter_ac_coverage_scope",
    "pvlib_version",
)


@dataclass(frozen=True)
class TopologySandiaInverterAcDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    empty_inverter_count: int
    populated_mppt_count: int
    timestamp_count: int
    row_count: int
    resolved_conversion_count: int
    unresolved_conversion_count: int
    producing_count: int
    ac_limited_count: int
    night_tare_count: int
    non_producing_count: int
    member_envelope_unresolved_count: int
    member_constraint_violation_count: int
    single_mppt_conversion_row_count: int
    multi_mppt_conversion_row_count: int
    sandia_single_call_count: int
    sandia_multi_call_count: int
    conversion_model: str


@dataclass(frozen=True)
class TopologySandiaInverterAcResult:
    operating_points: pd.DataFrame
    diagnostics: TopologySandiaInverterAcDiagnostics


def calculate_topology_sandia_inverter_ac(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    cec_sam_name_by_inverter_id: Mapping[str, str],
    inverter_authority: TopologyInverterAuthorityResult,
    mppt_current_limit_by_key: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    inverter_dc_envelope: TopologyInverterDcEnvelopeResult,
) -> TopologySandiaInverterAcResult:
    """Convert eligible independent MPPT inputs through one physical inverter."""

    if type(topology) is not ElectricalTopologyConfig:
        raise TypeError("topology must be exactly ElectricalTopologyConfig")
    envelope = _admit_s91(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        cec_sam_name_by_inverter_id,
        inverter_authority,
        mppt_current_limit_by_key,
        inverter_dc_envelope,
    )
    represented = [
        (inverter, [mppt for mppt in inverter.mppts if mppt.strings])
        for inverter in topology.inverters
        if any(mppt.strings for mppt in inverter.mppts)
    ]
    timestamps = pd.DatetimeIndex(envelope.index.get_level_values("timestamp").unique())
    records: list[dict[str, object]] = []
    keys: list[tuple[pd.Timestamp, str]] = []
    eligible_by_inverter: dict[str, list[pd.Timestamp]] = {
        inverter.id: [] for inverter, _ in represented
    }

    for timestamp in timestamps:
        for inverter, mppts in represented:
            rows = [envelope.loc[(timestamp, inverter.id, mppt.id)] for mppt in mppts]
            unresolved = [
                mppt.id
                for mppt, row in zip(mppts, rows, strict=True)
                if not bool(row["dc_envelope_resolved"])
            ]
            violating = [
                mppt.id
                for mppt, row in zip(mppts, rows, strict=True)
                if bool(row["dc_envelope_resolved"]) and not bool(row["dc_limits_satisfied"])
            ]
            active = sum(bool(row["is_active_dc_input"]) for row in rows)
            numeric = {
                "p_dc_inverter_input_w": np.nan,
                "p_ac_available_w": np.nan,
                "ac_to_dc_ratio": np.nan,
                "at_ac_power_limit": False,
            }
            if unresolved:
                resolved = False
                state = "unresolved_member_dc_envelope"
            elif violating:
                resolved = False
                state = "unresolved_member_dc_constraint_violation"
            else:
                resolved = True
                state = "pending_sandia_conversion"
                numeric["p_dc_inverter_input_w"] = sum(float(row["p_mppt_input_w"]) for row in rows)
                eligible_by_inverter[inverter.id].append(timestamp)
            model = inverter_authority.sandia_models_by_inverter_id.get(inverter.id)
            keys.append((timestamp, inverter.id))
            records.append(
                {
                    "configured_mppt_count": len(inverter.mppts),
                    "populated_mppt_count": len(mppts),
                    "active_mppt_count": active,
                    "inactive_mppt_count": len(mppts) - active - len(unresolved) - len(violating),
                    "unresolved_mppt_count": len(unresolved),
                    "violating_mppt_count": len(violating),
                    "unresolved_mppt_ids": ",".join(unresolved),
                    "unresolved_mppt_states": ",".join(
                        sorted(
                            {
                                str(row["dc_envelope_state"])
                                for row in rows
                                if not bool(row["dc_envelope_resolved"])
                            }
                        )
                    ),
                    "violating_mppt_ids": ",".join(violating),
                    "violating_mppt_states": ",".join(
                        sorted(
                            {
                                str(row["dc_envelope_state"])
                                for row in rows
                                if bool(row["dc_envelope_resolved"])
                                and not bool(row["dc_limits_satisfied"])
                            }
                        )
                    ),
                    **numeric,
                    "inverter_conversion_resolved": resolved,
                    "inverter_conversion_state": state,
                    "inverter_model_reference": rows[0]["inverter_model_reference"],
                    "sandia_parameter_source": model.parameter_source if model else "",
                    "sandia_confidence": model.confidence if model else "unknown",
                    "sandia_conversion_path": "not_evaluated",
                    "source_reference_plane": MPPT_INPUT_REFERENCE_PLANE,
                    "sink_reference_plane": INVERTER_AC_OUTPUT_REFERENCE_PLANE,
                    "topology_inverter_authority_contract": TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID,
                    "topology_inverter_authority_model": TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
                    "topology_inverter_authority_scope": TOPOLOGY_INVERTER_AUTHORITY_SCOPE,
                    "topology_inverter_authority_coverage_scope": (
                        TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE
                    ),
                    "topology_inverter_dc_envelope_contract": (
                        TOPOLOGY_INVERTER_DC_ENVELOPE_CONTRACT_ID
                    ),
                    "topology_inverter_dc_envelope_model": TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID,
                    "topology_inverter_dc_envelope_scope": TOPOLOGY_INVERTER_DC_ENVELOPE_SCOPE,
                    "topology_inverter_dc_envelope_coverage_scope": (
                        TOPOLOGY_INVERTER_DC_ENVELOPE_COVERAGE_SCOPE
                    ),
                    "topology_sandia_inverter_ac_contract": TOPOLOGY_SANDIA_INVERTER_AC_CONTRACT_ID,
                    "topology_sandia_inverter_ac_model": TOPOLOGY_SANDIA_INVERTER_AC_MODEL_ID,
                    "topology_sandia_inverter_ac_scope": TOPOLOGY_SANDIA_INVERTER_AC_SCOPE,
                    "topology_sandia_inverter_ac_coverage_scope": (
                        TOPOLOGY_SANDIA_INVERTER_AC_COVERAGE_SCOPE
                    ),
                    "pvlib_version": pvlib.__version__,
                }
            )

    output = pd.DataFrame(
        records,
        index=pd.MultiIndex.from_tuples(keys, names=["timestamp", "inverter_id"]),
        columns=_COLUMNS,
    )
    single_calls = 0
    multi_calls = 0
    for inverter, mppts in represented:
        eligible = eligible_by_inverter[inverter.id]
        if not eligible:
            continue
        model = inverter_authority.sandia_models_by_inverter_id[inverter.id]
        member = [
            envelope.xs((inverter.id, mppt.id), level=("inverter_id", "mppt_id")).loc[eligible]
            for mppt in mppts
        ]
        index = pd.DatetimeIndex(eligible)
        total_power = sum(
            (frame["p_mppt_input_w"] for frame in member), start=pd.Series(0.0, index=index)
        )
        if len(mppts) == 1:
            converted = calculate_sandia_inverter_ac_power(
                member[0]["v_mppt_input_v"],
                member[0]["i_mppt_input_a"],
                member[0]["p_mppt_input_w"],
                model,
            )
            _write_conversion(
                output,
                inverter.id,
                converted["p_ac_available_w"],
                total_power,
                model.parameters.paco_w,
                model.parameters.pso_w,
                "sandia_single_mppt",
            )
            single_calls += 1
        else:
            positive = total_power > 0
            pac = pd.Series(np.nan, index=index, dtype=float)
            if positive.any():
                pac.loc[positive] = pvlib.inverter.sandia_multi(
                    [frame.loc[positive, "v_mppt_input_v"] for frame in member],
                    [frame.loc[positive, "p_mppt_input_w"] for frame in member],
                    model.parameters.to_pvlib_dict(),
                )
                multi_calls += 1
            if (~positive).any():
                zeros = calculate_sandia_inverter_ac_power(
                    member[0].loc[~positive, "v_mppt_input_v"],
                    member[0].loc[~positive, "i_mppt_input_a"],
                    member[0].loc[~positive, "p_mppt_input_w"],
                    model,
                )
                pac.loc[~positive] = zeros["p_ac_available_w"]
                single_calls += 1
            _write_conversion(
                output,
                inverter.id,
                pac,
                total_power,
                model.parameters.paco_w,
                model.parameters.pso_w,
                "sandia_multi_mppt",
            )

    diagnostics = _diagnostics(topology, output, single_calls, multi_calls)
    _validate_result(topology, output, diagnostics, inverter_authority)
    return TopologySandiaInverterAcResult(output.copy(deep=True), diagnostics)


def _write_conversion(
    output: pd.DataFrame,
    inverter_id: str,
    pac: pd.Series,
    pdc: pd.Series,
    paco: float,
    pso: float,
    path: str,
) -> None:
    for timestamp in pac.index:
        key = (timestamp, inverter_id)
        ac = float(pac.loc[timestamp])
        dc = float(pdc.loc[timestamp])
        limited = ac == paco
        ratio = ac / dc if dc > 0 and ac >= 0 and not limited else np.nan
        if dc < 0:  # defensive; canonical upstream is non-negative
            raise RuntimeError("inverter DC power must be non-negative")
        if dc < pso:
            state = "resolved_sandia_night_tare"
        elif limited:
            state = "resolved_sandia_ac_limited"
        elif ac > 0:
            state = "resolved_sandia_producing"
        else:
            state = "resolved_sandia_non_producing"
        output.loc[
            key,
            [
                "p_ac_available_w",
                "ac_to_dc_ratio",
                "at_ac_power_limit",
                "inverter_conversion_state",
                "sandia_conversion_path",
            ],
        ] = [ac, ratio, limited, state, path]


def _admit_s91(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    names: Mapping[str, str],
    authority: TopologyInverterAuthorityResult,
    limits: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologyInverterDcEnvelopeResult:
        raise ValueError("S9-1 result type is invalid")
    if type(supplied.diagnostics) is not TopologyInverterDcEnvelopeDiagnostics:
        raise ValueError("S9-1 diagnostics type is invalid")
    replayed = evaluate_topology_inverter_dc_envelope(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        authority,
        limits,
    )
    try:
        pd.testing.assert_frame_equal(supplied.states, replayed.states, check_exact=True)
    except AssertionError as error:
        raise ValueError("S9-1 states do not match canonical replay") from error
    if supplied.diagnostics != replayed.diagnostics:
        raise ValueError("S9-1 diagnostics do not match canonical replay")
    return replayed.states.copy(deep=True)


def _diagnostics(
    topology: ElectricalTopologyConfig,
    output: pd.DataFrame,
    single_calls: int,
    multi_calls: int,
) -> TopologySandiaInverterAcDiagnostics:
    counts = output["inverter_conversion_state"].value_counts()
    represented = sum(any(mppt.strings for mppt in inv.mppts) for inv in topology.inverters)
    resolved = int(output["inverter_conversion_resolved"].sum()) if len(output) else 0
    return TopologySandiaInverterAcDiagnostics(
        inverter_count=topology.inverter_count,
        represented_inverter_count=represented,
        empty_inverter_count=topology.inverter_count - represented,
        populated_mppt_count=sum(
            bool(mppt.strings) for inv in topology.inverters for mppt in inv.mppts
        ),
        timestamp_count=len(output.index.get_level_values("timestamp").unique())
        if len(output)
        else 0,
        row_count=len(output),
        resolved_conversion_count=resolved,
        unresolved_conversion_count=len(output) - resolved,
        producing_count=int(counts.get("resolved_sandia_producing", 0)),
        ac_limited_count=int(counts.get("resolved_sandia_ac_limited", 0)),
        night_tare_count=int(counts.get("resolved_sandia_night_tare", 0)),
        non_producing_count=int(counts.get("resolved_sandia_non_producing", 0)),
        member_envelope_unresolved_count=int(counts.get("unresolved_member_dc_envelope", 0)),
        member_constraint_violation_count=int(
            counts.get("unresolved_member_dc_constraint_violation", 0)
        ),
        single_mppt_conversion_row_count=int(
            (output["sandia_conversion_path"] == "sandia_single_mppt").sum()
        ),
        multi_mppt_conversion_row_count=int(
            (output["sandia_conversion_path"] == "sandia_multi_mppt").sum()
        ),
        sandia_single_call_count=single_calls,
        sandia_multi_call_count=multi_calls,
        conversion_model=TOPOLOGY_SANDIA_INVERTER_AC_MODEL_ID,
    )


def _validate_result(
    topology: ElectricalTopologyConfig,
    output: pd.DataFrame,
    diagnostics: TopologySandiaInverterAcDiagnostics,
    authority: TopologyInverterAuthorityResult,
) -> None:
    if (
        tuple(output.columns) != _COLUMNS
        or not isinstance(output.index, pd.MultiIndex)
        or output.index.names != ["timestamp", "inverter_id"]
        or output.index.has_duplicates
    ):
        raise RuntimeError("S9-2 output schema or index is invalid")
    if (
        diagnostics.row_count
        != diagnostics.resolved_conversion_count + diagnostics.unresolved_conversion_count
    ):
        raise RuntimeError("S9-2 resolution counts do not close")
    if (
        diagnostics.row_count
        != diagnostics.timestamp_count * diagnostics.represented_inverter_count
    ):
        raise RuntimeError("S9-2 output grid does not close")
    for (_, inverter_id), row in output.iterrows():
        if (
            row["source_reference_plane"] != MPPT_INPUT_REFERENCE_PLANE
            or row["sink_reference_plane"] != INVERTER_AC_OUTPUT_REFERENCE_PLANE
        ):
            raise RuntimeError("S9-2 reference-plane provenance is invalid")
        if bool(row["inverter_conversion_resolved"]):
            if not np.isfinite(row["p_dc_inverter_input_w"]) or not np.isfinite(
                row["p_ac_available_w"]
            ):
                raise RuntimeError("resolved S9-2 power must be finite")
            model = authority.sandia_models_by_inverter_id[inverter_id]
            if float(row["p_ac_available_w"]) > model.parameters.paco_w:
                raise RuntimeError("S9-2 AC power exceeds Paco")
        elif not pd.isna(row["p_ac_available_w"]):
            raise RuntimeError("unresolved S9-2 AC power must be NaN")
