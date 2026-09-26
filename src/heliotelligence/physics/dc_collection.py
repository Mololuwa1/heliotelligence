"""Canonical DC collection authority and reference-plane physics.

This module admits explicit total loop resistance from each physical string's
``string_terminal`` reference plane to its configured parent ``mppt_input``
reference plane.  S8-3A admits that static authority, S8-3B transforms each
physical string I-V curve to ``mppt_input``, and S8-3C solves the common-voltage
parallel operating point at that sink plane.  Shared feeders, inverter limits,
conversion, and production-pipeline integration remain outside this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import electrical

DC_BRANCH_PATH_CONTRACT_ID = "string_terminal_to_mppt_input_dc_branch_path_v1"
DC_BRANCH_PATH_MODEL_ID = "explicit_lumped_series_loop_resistance_authority_v1"
DC_BRANCH_PATH_SCOPE = "dc_reference_plane_authority_before_resistive_iv_transform"
DC_BRANCH_PATH_COVERAGE_SCOPE = "direct_string_branch_to_parent_mppt_input"

STRING_TERMINAL_REFERENCE_PLANE = "string_terminal"
MPPT_INPUT_REFERENCE_PLANE = "mppt_input"

DC_BRANCH_IV_TRANSFORM_CONTRACT_ID = "string_terminal_iv_to_mppt_input_iv_v1"
DC_BRANCH_IV_TRANSFORM_MODEL_ID = "series_resistance_iv_voltage_drop_transform_v1"
DC_BRANCH_IV_TRANSFORM_SCOPE = (
    "per_string_mppt_input_iv_before_parallel_mppt_aggregation"
)
DC_BRANCH_IV_TRANSFORM_COVERAGE_SCOPE = (
    "explicit_direct_string_branch_series_resistance"
)

MPPT_INPUT_COMMON_VOLTAGE_CONTRACT_ID = (
    "mppt_input_string_iv_to_common_voltage_mppt_v1"
)
MPPT_INPUT_COMMON_VOLTAGE_MODEL_ID = "iv_consistent_common_voltage_mppt_input_v1"
MPPT_INPUT_COMMON_VOLTAGE_SCOPE = (
    "mppt_input_common_voltage_dc_operating_point_before_inverter_envelope"
)
MPPT_INPUT_COMMON_VOLTAGE_COVERAGE_SCOPE = (
    "explicit_parallel_strings_after_direct_branch_resistance"
)

_PATH_COLUMNS = (
    "source_reference_plane",
    "sink_reference_plane",
    "branch_path_resolved",
    "branch_path_state",
    "series_resistance_ohm",
    "parameter_source",
    "confidence",
    "dc_branch_path_contract",
    "dc_branch_path_model",
    "dc_branch_path_scope",
    "dc_branch_path_coverage_scope",
)

_TRANSFORM_STATE_COLUMNS = (
    *electrical._TOPOLOGY_STRING_IV_STATE_COLUMNS,
    "dc_branch_path_resolved",
    "dc_branch_path_state",
    "series_resistance_ohm",
    "parameter_source",
    "confidence",
    "source_reference_plane",
    "sink_reference_plane",
    "mppt_input_iv_resolved",
    "mppt_input_iv_state",
    "dc_branch_path_contract",
    "dc_branch_path_model",
    "dc_branch_path_scope",
    "dc_branch_path_coverage_scope",
    "dc_branch_iv_transform_contract",
    "dc_branch_iv_transform_model",
    "dc_branch_iv_transform_scope",
    "dc_branch_iv_transform_coverage_scope",
)

_MPPT_INPUT_OPERATING_POINT_COLUMNS = (
    "configured_string_count",
    "active_string_count",
    "zero_string_count",
    "unresolved_string_count",
    "unresolved_string_ids",
    "unresolved_string_states",
    "v_mppt_input_v",
    "i_mppt_input_a",
    "p_mppt_input_w",
    "p_independent_mppt_input_w",
    "p_mppt_input_mismatch_w",
    "mppt_input_mismatch_pct",
    "mppt_input_resolved",
    "mppt_input_state",
    "source_reference_plane",
    "sink_reference_plane",
    "dc_branch_iv_transform_contract",
    "dc_branch_iv_transform_model",
    "dc_branch_iv_transform_scope",
    "dc_branch_iv_transform_coverage_scope",
    "mppt_input_common_voltage_contract",
    "mppt_input_common_voltage_model",
    "mppt_input_common_voltage_scope",
    "mppt_input_common_voltage_coverage_scope",
)


@dataclass(frozen=True)
class DcBranchPathAuthorityDiagnostics:
    inverter_count: int
    mppt_count: int
    string_count: int
    resolved_path_count: int
    unresolved_path_count: int
    zero_resistance_path_count: int
    positive_resistance_path_count: int
    path_model: str


@dataclass(frozen=True)
class DcBranchPathAuthorityResult:
    paths: pd.DataFrame
    diagnostics: DcBranchPathAuthorityDiagnostics


@dataclass(frozen=True)
class TopologyMpptInputStringIVDiagnostics:
    """Deterministic summary of string-terminal branch I-V transformation."""

    inverter_count: int
    mppt_count: int
    string_count: int
    timestamp_count: int
    state_row_count: int
    resolved_state_count: int
    unresolved_state_count: int
    zero_string_state_count: int
    zero_resistance_identity_state_count: int
    positive_resistance_transform_state_count: int
    missing_authority_state_count: int
    upstream_unresolved_state_count: int
    no_nonnegative_domain_state_count: int
    input_curve_row_count: int
    output_curve_row_count: int
    inserted_zero_crossing_count: int
    transformed_string_count: int
    transformation_model: str


@dataclass(frozen=True)
class TopologyMpptInputStringIVResult:
    """Per-string I-V curves expressed at the parent MPPT input plane."""

    mppt_input_iv_curves_by_string_id: Mapping[str, pd.DataFrame]
    states: pd.DataFrame
    diagnostics: TopologyMpptInputStringIVDiagnostics


@dataclass(frozen=True)
class TopologyMpptInputOperatingPointDiagnostics:
    """Deterministic summary of MPPT-input common-voltage aggregation."""

    inverter_count: int
    mppt_count: int
    populated_mppt_count: int
    empty_mppt_count: int
    string_count: int
    timestamp_count: int
    state_row_count: int
    resolved_mppt_state_count: int
    unresolved_mppt_state_count: int
    active_mppt_state_count: int
    zero_mppt_state_count: int
    upstream_unresolved_mppt_state_count: int
    mixed_active_zero_unavailable_count: int
    physics_row_count: int
    physics_call_count: int
    common_voltage_model: str


@dataclass(frozen=True)
class TopologyMpptInputOperatingPointResult:
    """Per-MPPT operating points expressed at the MPPT-input plane."""

    operating_points: pd.DataFrame
    diagnostics: TopologyMpptInputOperatingPointDiagnostics


def _empty_paths() -> pd.DataFrame:
    index = pd.MultiIndex.from_arrays(
        [[], [], []], names=["inverter_id", "mppt_id", "string_id"]
    )
    return pd.DataFrame(columns=_PATH_COLUMNS, index=index)


def resolve_dc_branch_path_authority(
    topology: ElectricalTopologyConfig,
) -> DcBranchPathAuthorityResult:
    """Resolve explicit string-terminal to parent-MPPT branch authority.

    Rows retain configured inverter, MPPT, and string traversal order.  An
    absent branch configuration remains unresolved and is never treated as an
    ideal zero-resistance path.
    """

    if type(topology) is not ElectricalTopologyConfig:
        raise TypeError("topology must be exactly ElectricalTopologyConfig")

    records: list[dict[str, object]] = []
    keys: list[tuple[str, str, str]] = []
    resolved_count = 0
    zero_count = 0
    positive_count = 0

    for inverter in topology.inverters:
        for mppt in inverter.mppts:
            for string in mppt.strings:
                keys.append((inverter.id, mppt.id, string.id))
                branch = string.dc_branch_path
                if branch is None:
                    resolved = False
                    state = "unresolved_no_explicit_dc_branch_path"
                    resistance = np.nan
                    source = ""
                    confidence = "unknown"
                else:
                    resolved = True
                    state = "resolved_explicit_series_loop_resistance"
                    resistance = branch.series_resistance_ohm
                    source = branch.parameter_source
                    confidence = branch.confidence
                    resolved_count += 1
                    if resistance == 0.0:
                        zero_count += 1
                    else:
                        positive_count += 1

                records.append(
                    {
                        "source_reference_plane": STRING_TERMINAL_REFERENCE_PLANE,
                        "sink_reference_plane": MPPT_INPUT_REFERENCE_PLANE,
                        "branch_path_resolved": resolved,
                        "branch_path_state": state,
                        "series_resistance_ohm": resistance,
                        "parameter_source": source,
                        "confidence": confidence,
                        "dc_branch_path_contract": DC_BRANCH_PATH_CONTRACT_ID,
                        "dc_branch_path_model": DC_BRANCH_PATH_MODEL_ID,
                        "dc_branch_path_scope": DC_BRANCH_PATH_SCOPE,
                        "dc_branch_path_coverage_scope": DC_BRANCH_PATH_COVERAGE_SCOPE,
                    }
                )

    if records:
        index = pd.MultiIndex.from_tuples(
            keys, names=["inverter_id", "mppt_id", "string_id"]
        )
        paths = pd.DataFrame.from_records(records, columns=_PATH_COLUMNS, index=index)
    else:
        paths = _empty_paths()

    diagnostics = DcBranchPathAuthorityDiagnostics(
        inverter_count=topology.inverter_count,
        mppt_count=topology.mppt_count,
        string_count=topology.string_count,
        resolved_path_count=resolved_count,
        unresolved_path_count=topology.string_count - resolved_count,
        zero_resistance_path_count=zero_count,
        positive_resistance_path_count=positive_count,
        path_model=DC_BRANCH_PATH_MODEL_ID,
    )
    return DcBranchPathAuthorityResult(paths=paths, diagnostics=diagnostics)


def calculate_topology_mppt_input_string_iv(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: DcBranchPathAuthorityResult,
) -> TopologyMpptInputStringIVResult:
    """Transform canonical physical string I-V curves to the MPPT-input plane.

    This function performs only the per-string series-resistance transform.  It
    does not aggregate parallel strings, solve an MPPT operating point, or
    invoke inverter physics.
    """

    ordered_strings = electrical._receiver_string_topology_rows(topology)
    upstream_states, source_curves = electrical._admit_topology_string_iv(
        topology,
        ordered_strings,
        topology_string_iv,
    )
    paths = _admit_dc_branch_path_authority(
        topology,
        ordered_strings,
        branch_authority,
    )

    string_ids = [item[2] for item in ordered_strings]
    output_curves: dict[str, pd.DataFrame] = {
        string_id: pd.DataFrame(columns=electrical._IV_CURVE_COLUMNS)
        for string_id in string_ids
    }
    output_parts: dict[str, list[pd.DataFrame]] = {
        string_id: [] for string_id in string_ids
    }
    output_states = upstream_states.copy(deep=True)
    for column in _TRANSFORM_STATE_COLUMNS[len(electrical._TOPOLOGY_STRING_IV_STATE_COLUMNS) :]:
        output_states[column] = pd.Series(index=output_states.index, dtype="object")

    counters = {
        "resolved": 0,
        "zero_string": 0,
        "zero_resistance": 0,
        "positive_resistance": 0,
        "missing": 0,
        "upstream": 0,
        "no_domain": 0,
        "crossings": 0,
    }
    transformed_strings: set[str] = set()

    for (timestamp, string_id), upstream in upstream_states.iterrows():
        inverter_id = str(upstream["inverter_id"])
        mppt_id = str(upstream["mppt_id"])
        path = paths.loc[(inverter_id, mppt_id, string_id)]
        source_rows = source_curves[string_id].loc[
            source_curves[string_id]["timestamp"].eq(timestamp)
        ].copy(deep=True)
        upstream_resolved = bool(upstream["string_iv_resolved"])
        path_resolved = bool(path["branch_path_resolved"])
        output_resolved = False
        output_state: str
        transformed: pd.DataFrame | None = None

        if not upstream_resolved:
            output_state = str(upstream["string_iv_state"])
            counters["upstream"] += 1
        elif not path_resolved:
            output_state = "unresolved_no_explicit_dc_branch_path"
            counters["missing"] += 1
        elif upstream["string_iv_state"] == "resolved_zero_string_iv":
            output_state = "resolved_zero_string_iv"
            output_resolved = True
            transformed = source_rows
            counters["zero_string"] += 1
        else:
            resistance = float(path["series_resistance_ohm"])
            if resistance == 0.0:
                output_state = "resolved_zero_resistance_identity"
                output_resolved = True
                transformed = source_rows
                counters["zero_resistance"] += 1
            else:
                transformed, inserted = _transform_curve_to_mppt_input(
                    source_rows,
                    resistance,
                )
                if transformed is None:
                    output_state = "unresolved_no_nonnegative_mppt_input_voltage_domain"
                    counters["no_domain"] += 1
                else:
                    output_state = "resolved_resistive_branch_iv"
                    output_resolved = True
                    counters["positive_resistance"] += 1
                    counters["crossings"] += int(inserted)

        if output_resolved:
            if transformed is None:
                raise RuntimeError("resolved branch transformation has no curve")
            output_parts[string_id].append(transformed)
            counters["resolved"] += 1
            transformed_strings.add(string_id)

        authority_values = {
            "dc_branch_path_resolved": path["branch_path_resolved"],
            "dc_branch_path_state": path["branch_path_state"],
            "series_resistance_ohm": path["series_resistance_ohm"],
            "parameter_source": path["parameter_source"],
            "confidence": path["confidence"],
            "source_reference_plane": path["source_reference_plane"],
            "sink_reference_plane": path["sink_reference_plane"],
            "mppt_input_iv_resolved": output_resolved,
            "mppt_input_iv_state": output_state,
            "dc_branch_path_contract": path["dc_branch_path_contract"],
            "dc_branch_path_model": path["dc_branch_path_model"],
            "dc_branch_path_scope": path["dc_branch_path_scope"],
            "dc_branch_path_coverage_scope": path["dc_branch_path_coverage_scope"],
            "dc_branch_iv_transform_contract": DC_BRANCH_IV_TRANSFORM_CONTRACT_ID,
            "dc_branch_iv_transform_model": DC_BRANCH_IV_TRANSFORM_MODEL_ID,
            "dc_branch_iv_transform_scope": DC_BRANCH_IV_TRANSFORM_SCOPE,
            "dc_branch_iv_transform_coverage_scope": (
                DC_BRANCH_IV_TRANSFORM_COVERAGE_SCOPE
            ),
        }
        for column, value in authority_values.items():
            output_states.loc[(timestamp, string_id), column] = value

    for string_id in string_ids:
        if output_parts[string_id]:
            output_curves[string_id] = pd.concat(
                output_parts[string_id], ignore_index=True
            ).loc[:, electrical._IV_CURVE_COLUMNS]

    timestamps = pd.DatetimeIndex(
        upstream_states.index.get_level_values("timestamp").unique()
    )
    diagnostics = TopologyMpptInputStringIVDiagnostics(
        inverter_count=topology.inverter_count,
        mppt_count=topology.mppt_count,
        string_count=topology.string_count,
        timestamp_count=len(timestamps),
        state_row_count=len(output_states),
        resolved_state_count=counters["resolved"],
        unresolved_state_count=len(output_states) - counters["resolved"],
        zero_string_state_count=counters["zero_string"],
        zero_resistance_identity_state_count=counters["zero_resistance"],
        positive_resistance_transform_state_count=counters["positive_resistance"],
        missing_authority_state_count=counters["missing"],
        upstream_unresolved_state_count=counters["upstream"],
        no_nonnegative_domain_state_count=counters["no_domain"],
        input_curve_row_count=sum(len(curve) for curve in source_curves.values()),
        output_curve_row_count=sum(len(curve) for curve in output_curves.values()),
        inserted_zero_crossing_count=counters["crossings"],
        transformed_string_count=len(transformed_strings),
        transformation_model=DC_BRANCH_IV_TRANSFORM_MODEL_ID,
    )
    _validate_transform_result(output_curves, output_states, diagnostics)
    return TopologyMpptInputStringIVResult(
        mppt_input_iv_curves_by_string_id=output_curves,
        states=output_states.loc[:, _TRANSFORM_STATE_COLUMNS],
        diagnostics=diagnostics,
    )


def calculate_topology_mppt_input_operating_points(
    topology: ElectricalTopologyConfig,
    mppt_input_string_iv: TopologyMpptInputStringIVResult,
) -> TopologyMpptInputOperatingPointResult:
    """Solve one common-voltage operating point per populated MPPT.

    Input curves already include the direct branch-resistance transform and
    are expressed at ``mppt_input``.  This function applies no additional
    resistance, loss percentage, inverter constraint, or conversion.
    """

    ordered_strings = electrical._receiver_string_topology_rows(topology)
    states, curves = _admit_topology_mppt_input_string_iv(
        topology,
        ordered_strings,
        mppt_input_string_iv,
    )
    timestamps = pd.DatetimeIndex(states.index.get_level_values("timestamp").unique())
    populated_mppts = [
        (inverter.id, mppt.id, [string.id for string in mppt.strings])
        for inverter in topology.inverters
        for mppt in inverter.mppts
        if mppt.strings
    ]
    empty_mppt_count = sum(
        not mppt.strings for inverter in topology.inverters for mppt in inverter.mppts
    )
    records: list[dict[str, object]] = []
    keys: list[tuple[pd.Timestamp, str, str]] = []
    active_timestamps_by_mppt: dict[tuple[str, str], list[pd.Timestamp]] = {
        (inverter_id, mppt_id): []
        for inverter_id, mppt_id, _ in populated_mppts
    }

    for timestamp in timestamps:
        for inverter_id, mppt_id, string_ids in populated_mppts:
            rows = [states.loc[(timestamp, string_id)] for string_id in string_ids]
            member_states = [str(row["mppt_input_iv_state"]) for row in rows]
            unresolved_ids = [
                string_id
                for string_id, row in zip(string_ids, rows, strict=True)
                if not bool(row["mppt_input_iv_resolved"])
            ]
            unresolved_states = sorted(
                {
                    state
                    for state in member_states
                    if state
                    not in {
                        "resolved_zero_resistance_identity",
                        "resolved_resistive_branch_iv",
                        "resolved_zero_string_iv",
                    }
                }
            )
            active_count = sum(
                state
                in {"resolved_zero_resistance_identity", "resolved_resistive_branch_iv"}
                for state in member_states
            )
            zero_count = member_states.count("resolved_zero_string_iv")
            unresolved_count = len(unresolved_ids)
            numeric = {
                "v_mppt_input_v": np.nan,
                "i_mppt_input_a": np.nan,
                "p_mppt_input_w": np.nan,
                "p_independent_mppt_input_w": np.nan,
                "p_mppt_input_mismatch_w": np.nan,
                "mppt_input_mismatch_pct": np.nan,
            }
            if unresolved_count:
                resolved = False
                state = "unresolved_member_mppt_input_iv"
            elif active_count and zero_count:
                resolved = False
                state = "unresolved_mixed_active_zero_requires_blocking_model"
            elif zero_count == len(string_ids):
                resolved = True
                state = "resolved_zero_mppt_input_common_voltage"
                numeric = {name: 0.0 for name in numeric}
            else:
                resolved = True
                state = "resolved_mppt_input_common_voltage"
                active_timestamps_by_mppt[(inverter_id, mppt_id)].append(timestamp)

            keys.append((timestamp, inverter_id, mppt_id))
            records.append(
                {
                    "configured_string_count": len(string_ids),
                    "active_string_count": active_count,
                    "zero_string_count": zero_count,
                    "unresolved_string_count": unresolved_count,
                    "unresolved_string_ids": ",".join(unresolved_ids),
                    "unresolved_string_states": ",".join(unresolved_states),
                    **numeric,
                    "mppt_input_resolved": resolved,
                    "mppt_input_state": state,
                    "source_reference_plane": STRING_TERMINAL_REFERENCE_PLANE,
                    "sink_reference_plane": MPPT_INPUT_REFERENCE_PLANE,
                    "dc_branch_iv_transform_contract": DC_BRANCH_IV_TRANSFORM_CONTRACT_ID,
                    "dc_branch_iv_transform_model": DC_BRANCH_IV_TRANSFORM_MODEL_ID,
                    "dc_branch_iv_transform_scope": DC_BRANCH_IV_TRANSFORM_SCOPE,
                    "dc_branch_iv_transform_coverage_scope": (
                        DC_BRANCH_IV_TRANSFORM_COVERAGE_SCOPE
                    ),
                    "mppt_input_common_voltage_contract": (
                        MPPT_INPUT_COMMON_VOLTAGE_CONTRACT_ID
                    ),
                    "mppt_input_common_voltage_model": (
                        MPPT_INPUT_COMMON_VOLTAGE_MODEL_ID
                    ),
                    "mppt_input_common_voltage_scope": MPPT_INPUT_COMMON_VOLTAGE_SCOPE,
                    "mppt_input_common_voltage_coverage_scope": (
                        MPPT_INPUT_COMMON_VOLTAGE_COVERAGE_SCOPE
                    ),
                }
            )

    output = pd.DataFrame(
        records,
        index=pd.MultiIndex.from_tuples(
            keys, names=["timestamp", "inverter_id", "mppt_id"]
        ),
        columns=_MPPT_INPUT_OPERATING_POINT_COLUMNS,
    )
    physics_calls = 0
    physics_rows = 0
    for inverter_id, mppt_id, string_ids in populated_mppts:
        active_timestamps = active_timestamps_by_mppt[(inverter_id, mppt_id)]
        if not active_timestamps:
            continue
        submitted = [
            curves[string_id].loc[
                curves[string_id]["timestamp"].isin(active_timestamps)
            ].copy(deep=True)
            for string_id in string_ids
        ]
        physics = electrical.calculate_physical_mismatch(submitted)
        electrical._validate_s8_mppt_physics(
            physics,
            active_timestamps,
            len(string_ids),
        )
        physics_calls += 1
        physics_rows += len(active_timestamps)
        physics_by_timestamp = physics.set_index("timestamp")
        for timestamp in active_timestamps:
            result = physics_by_timestamp.loc[timestamp]
            output.loc[
                (timestamp, inverter_id, mppt_id),
                [
                    "v_mppt_input_v",
                    "i_mppt_input_a",
                    "p_mppt_input_w",
                    "p_independent_mppt_input_w",
                    "p_mppt_input_mismatch_w",
                    "mppt_input_mismatch_pct",
                ],
            ] = result[
                [
                    "v_common_mppt_v",
                    "i_common_mppt_a",
                    "p_common_mppt_w",
                    "p_independent_mp_w",
                    "p_mismatch_w",
                    "mismatch_pct",
                ]
            ].to_numpy(dtype=float)

    resolved_count = int(output["mppt_input_resolved"].sum()) if len(output) else 0
    active_count = int(
        (output["mppt_input_state"] == "resolved_mppt_input_common_voltage").sum()
    )
    zero_count = int(
        (output["mppt_input_state"] == "resolved_zero_mppt_input_common_voltage").sum()
    )
    member_unresolved = int(
        (output["mppt_input_state"] == "unresolved_member_mppt_input_iv").sum()
    )
    mixed_unavailable = int(
        (
            output["mppt_input_state"]
            == "unresolved_mixed_active_zero_requires_blocking_model"
        ).sum()
    )
    diagnostics = TopologyMpptInputOperatingPointDiagnostics(
        inverter_count=topology.inverter_count,
        mppt_count=topology.mppt_count,
        populated_mppt_count=len(populated_mppts),
        empty_mppt_count=empty_mppt_count,
        string_count=topology.string_count,
        timestamp_count=len(timestamps),
        state_row_count=len(output),
        resolved_mppt_state_count=resolved_count,
        unresolved_mppt_state_count=len(output) - resolved_count,
        active_mppt_state_count=active_count,
        zero_mppt_state_count=zero_count,
        upstream_unresolved_mppt_state_count=member_unresolved,
        mixed_active_zero_unavailable_count=mixed_unavailable,
        physics_row_count=physics_rows,
        physics_call_count=physics_calls,
        common_voltage_model=MPPT_INPUT_COMMON_VOLTAGE_MODEL_ID,
    )
    _validate_mppt_input_operating_point_result(output, diagnostics)
    return TopologyMpptInputOperatingPointResult(output, diagnostics)


def _admit_topology_mppt_input_string_iv(
    topology: ElectricalTopologyConfig,
    ordered_strings: list[tuple[str, str, str]],
    value: object,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Replay complete S8-3B authority before common-voltage physics."""

    if type(value) is not TopologyMpptInputStringIVResult:
        raise ValueError(
            "mppt_input_string_iv must be an exact TopologyMpptInputStringIVResult"
        )
    if type(value.diagnostics) is not TopologyMpptInputStringIVDiagnostics:
        raise ValueError("MPPT-input string-I-V diagnostics type is invalid")
    states = value.states
    if not isinstance(states, pd.DataFrame) or not isinstance(states.index, pd.MultiIndex):
        raise ValueError("MPPT-input string-I-V states must use a MultiIndex")
    if states.index.nlevels != 2 or states.index.names != ["timestamp", "string_id"]:
        raise ValueError("MPPT-input string-I-V index must be timestamp/string_id")
    if tuple(states.columns) != _TRANSFORM_STATE_COLUMNS:
        raise ValueError("MPPT-input string-I-V state schema is not canonical")
    timestamp_values = states.index.get_level_values("timestamp")
    if len(states) and (
        not isinstance(timestamp_values, pd.DatetimeIndex) or timestamp_values.tz is None
    ):
        raise ValueError("MPPT-input string-I-V timestamps must be timezone-aware")
    if timestamp_values.hasnans or states.index.has_duplicates:
        raise ValueError("MPPT-input string-I-V state index contains NaT or duplicates")
    timestamps = (
        pd.DatetimeIndex(timestamp_values.unique()).sort_values()
        if len(states)
        else pd.DatetimeIndex([])
    )
    string_ids = [item[2] for item in ordered_strings]
    expected_index = pd.MultiIndex.from_tuples(
        [(timestamp, string_id) for timestamp in timestamps for string_id in string_ids],
        names=["timestamp", "string_id"],
    )
    if len(states) != len(expected_index) or set(states.index) != set(expected_index):
        raise ValueError("MPPT-input string-I-V states must contain the complete grid")
    canonical = states.reindex(expected_index).copy(deep=True)

    topology_identity = {
        string.id: (inverter.id, mppt.id, string)
        for inverter in topology.inverters
        for mppt in inverter.mppts
        for string in mppt.strings
    }
    transform_provenance = {
        "dc_branch_path_contract": DC_BRANCH_PATH_CONTRACT_ID,
        "dc_branch_path_model": DC_BRANCH_PATH_MODEL_ID,
        "dc_branch_path_scope": DC_BRANCH_PATH_SCOPE,
        "dc_branch_path_coverage_scope": DC_BRANCH_PATH_COVERAGE_SCOPE,
        "dc_branch_iv_transform_contract": DC_BRANCH_IV_TRANSFORM_CONTRACT_ID,
        "dc_branch_iv_transform_model": DC_BRANCH_IV_TRANSFORM_MODEL_ID,
        "dc_branch_iv_transform_scope": DC_BRANCH_IV_TRANSFORM_SCOPE,
        "dc_branch_iv_transform_coverage_scope": (
            DC_BRANCH_IV_TRANSFORM_COVERAGE_SCOPE
        ),
    }
    for (_, string_id), row in canonical.iterrows():
        inverter_id, mppt_id, string = topology_identity[string_id]
        if (row["inverter_id"], row["mppt_id"]) != (inverter_id, mppt_id):
            raise ValueError("MPPT-input string-I-V topology ownership is stale")
        electrical._replay_receiver_string_module_iv_state(row)
        electrical._replay_topology_string_iv_state(row)
        for column, expected in transform_provenance.items():
            if row[column] != expected:
                raise ValueError(f"MPPT-input string-I-V {column} provenance is invalid")
        if row["source_reference_plane"] != STRING_TERMINAL_REFERENCE_PLANE:
            raise ValueError("MPPT-input string-I-V source reference plane is invalid")
        if row["sink_reference_plane"] != MPPT_INPUT_REFERENCE_PLANE:
            raise ValueError("MPPT-input string-I-V sink reference plane is invalid")
        _replay_mppt_input_string_state(row, string.dc_branch_path)

    curves = _admit_mppt_input_curves(
        string_ids,
        timestamps,
        canonical,
        value.mppt_input_iv_curves_by_string_id,
    )
    _replay_mppt_input_diagnostics(topology, canonical, curves, value.diagnostics)
    return canonical, curves


def _replay_mppt_input_string_state(row: pd.Series, configured_path: object) -> None:
    upstream_resolved = electrical._handoff_bool(
        row["string_iv_resolved"], "string_iv_resolved"
    )
    output_resolved = electrical._handoff_bool(
        row["mppt_input_iv_resolved"], "mppt_input_iv_resolved"
    )
    path_resolved = electrical._handoff_bool(
        row["dc_branch_path_resolved"], "dc_branch_path_resolved"
    )
    output_state = row["mppt_input_iv_state"]
    upstream_state = row["string_iv_state"]

    if configured_path is None:
        expected_path = (False, "unresolved_no_explicit_dc_branch_path", "", "unknown")
        if not pd.isna(row["series_resistance_ohm"]):
            raise ValueError("missing branch resistance must remain NaN")
    else:
        expected_path = (
            True,
            "resolved_explicit_series_loop_resistance",
            configured_path.parameter_source,
            configured_path.confidence,
        )
        resistance = _nonnegative_finite(
            row["series_resistance_ohm"], "series_resistance_ohm"
        )
        if resistance != configured_path.series_resistance_ohm:
            raise ValueError("MPPT-input branch resistance is stale")
    if (
        path_resolved,
        row["dc_branch_path_state"],
        row["parameter_source"],
        row["confidence"],
    ) != expected_path:
        raise ValueError("MPPT-input branch authority state is contradictory")

    if not upstream_resolved:
        expected_output = (False, upstream_state)
    elif not path_resolved:
        expected_output = (False, "unresolved_no_explicit_dc_branch_path")
    elif upstream_state == "resolved_zero_string_iv":
        expected_output = (True, "resolved_zero_string_iv")
    else:
        resistance = float(row["series_resistance_ohm"])
        if resistance == 0.0:
            expected_output = (True, "resolved_zero_resistance_identity")
        elif output_state == "unresolved_no_nonnegative_mppt_input_voltage_domain":
            expected_output = (False, output_state)
        else:
            expected_output = (True, "resolved_resistive_branch_iv")
    if (output_resolved, output_state) != expected_output:
        raise ValueError("MPPT-input string-I-V resolution state is contradictory")


def _admit_mppt_input_curves(
    string_ids: list[str],
    timestamps: pd.DatetimeIndex,
    states: pd.DataFrame,
    supplied: object,
) -> dict[str, pd.DataFrame]:
    if not isinstance(supplied, Mapping) or set(supplied) != set(string_ids):
        raise ValueError("MPPT-input curve keys must exactly match topology")
    canonical: dict[str, pd.DataFrame] = {}
    for string_id in string_ids:
        value = supplied[string_id]
        if not isinstance(value, pd.DataFrame) or tuple(value.columns) != tuple(
            electrical._IV_CURVE_COLUMNS
        ):
            raise ValueError("MPPT-input curve schema is not canonical")
        curve = value.copy(deep=True)
        if len(curve):
            curve_timestamps = pd.DatetimeIndex(curve["timestamp"])
            if curve_timestamps.tz is None or curve_timestamps.hasnans:
                raise ValueError("MPPT-input curve timestamps are invalid")
            if str(curve_timestamps.tz) != str(timestamps.tz):
                raise ValueError("MPPT-input curve timezone is inconsistent")
            if not set(curve_timestamps).issubset(set(timestamps)):
                raise ValueError("MPPT-input curve contains an unexpected timestamp")
        curve = curve.sort_values(["timestamp", "curve_point"], kind="stable").reset_index(
            drop=True
        )
        if curve.duplicated(["timestamp", "curve_point"]).any():
            raise ValueError("MPPT-input curve contains duplicate points")
        for timestamp in timestamps:
            state = states.loc[(timestamp, string_id)]
            rows = curve.loc[curve["timestamp"].eq(timestamp)]
            resolved = bool(state["mppt_input_iv_resolved"])
            if resolved != bool(len(rows)):
                raise ValueError("MPPT-input curve/state resolution does not close")
            if len(rows) and rows["curve_point"].tolist() != list(range(len(rows))):
                raise ValueError("MPPT-input curve-point grid is not canonical")
            for _, point in rows.iterrows():
                values = {
                    name: electrical._handoff_finite(point[name], f"MPPT-input {name}")
                    for name in (
                        "voltage_v",
                        "current_a",
                        "power_w",
                        "effective_irradiance_wm2",
                    )
                }
                if any(
                    value < -electrical._NUMERICAL_NEGATIVE_TOLERANCE
                    for value in values.values()
                ):
                    raise ValueError("MPPT-input curve values must be non-negative")
                if not electrical._handoff_close(
                    values["power_w"], values["voltage_v"] * values["current_a"]
                ):
                    raise ValueError("MPPT-input curve power closure failed")
                if not electrical._handoff_close(
                    values["effective_irradiance_wm2"],
                    float(state["spectral_electrical_equivalent_irradiance_wm2"]),
                ):
                    raise ValueError("MPPT-input curve irradiance is stale")
                if (
                    point["tier_used"] != state["tier_used"]
                    or point["fit_quality"] != state["fit_quality"]
                ):
                    raise ValueError("MPPT-input curve module identity is stale")
            if state["mppt_input_iv_state"] == "resolved_zero_string_iv" and len(rows):
                if not rows[
                    ["voltage_v", "current_a", "power_w", "effective_irradiance_wm2"]
                ].eq(0.0).all().all():
                    raise ValueError("resolved zero MPPT-input curve must be exact zero")
            elif state["mppt_input_iv_state"] in {
                "resolved_zero_resistance_identity",
                "resolved_resistive_branch_iv",
            }:
                electrical._validated_common_mppt_curve(curve, timestamp, 0)
                if (
                    float(rows["current_a"].max()) <= 0.0
                    or float(rows["power_w"].max()) <= 0.0
                ):
                    raise ValueError("resolved MPPT-input curve must contain positive power")
        canonical[string_id] = curve.loc[:, electrical._IV_CURVE_COLUMNS]
    return canonical


def _replay_mppt_input_diagnostics(
    topology: ElectricalTopologyConfig,
    states: pd.DataFrame,
    curves: Mapping[str, pd.DataFrame],
    diagnostics: TopologyMpptInputStringIVDiagnostics,
) -> None:
    names = (
        "inverter_count",
        "mppt_count",
        "string_count",
        "timestamp_count",
        "state_row_count",
        "resolved_state_count",
        "unresolved_state_count",
        "zero_string_state_count",
        "zero_resistance_identity_state_count",
        "positive_resistance_transform_state_count",
        "missing_authority_state_count",
        "upstream_unresolved_state_count",
        "no_nonnegative_domain_state_count",
        "input_curve_row_count",
        "output_curve_row_count",
        "inserted_zero_crossing_count",
        "transformed_string_count",
    )
    counts = {
        name: _nonnegative_integer(getattr(diagnostics, name), name) for name in names
    }
    state_counts = states["mppt_input_iv_state"].value_counts()
    resolved = int(states["mppt_input_iv_resolved"].sum()) if len(states) else 0
    timestamps = pd.DatetimeIndex(states.index.get_level_values("timestamp").unique())
    transformed_strings = len(
        set(
            states.loc[states["mppt_input_iv_resolved"]]
            .index.get_level_values("string_id")
        )
    )
    expected = (
        topology.inverter_count,
        topology.mppt_count,
        topology.string_count,
        len(timestamps),
        len(states),
        resolved,
        len(states) - resolved,
        int(state_counts.get("resolved_zero_string_iv", 0)),
        int(state_counts.get("resolved_zero_resistance_identity", 0)),
        int(state_counts.get("resolved_resistive_branch_iv", 0)),
        int(state_counts.get("unresolved_no_explicit_dc_branch_path", 0)),
        int((~states["string_iv_resolved"]).sum()) if len(states) else 0,
        int(state_counts.get("unresolved_no_nonnegative_mppt_input_voltage_domain", 0)),
        sum(len(curve) for curve in curves.values()),
        transformed_strings,
        DC_BRANCH_IV_TRANSFORM_MODEL_ID,
    )
    actual = (
        counts["inverter_count"],
        counts["mppt_count"],
        counts["string_count"],
        counts["timestamp_count"],
        counts["state_row_count"],
        counts["resolved_state_count"],
        counts["unresolved_state_count"],
        counts["zero_string_state_count"],
        counts["zero_resistance_identity_state_count"],
        counts["positive_resistance_transform_state_count"],
        counts["missing_authority_state_count"],
        counts["upstream_unresolved_state_count"],
        counts["no_nonnegative_domain_state_count"],
        counts["output_curve_row_count"],
        counts["transformed_string_count"],
        diagnostics.transformation_model,
    )
    if actual != expected:
        raise ValueError("MPPT-input string-I-V diagnostics are stale")
    if (
        counts["input_curve_row_count"]
        < counts["output_curve_row_count"] - counts["inserted_zero_crossing_count"]
        or counts["inserted_zero_crossing_count"]
        > counts["positive_resistance_transform_state_count"]
    ):
        raise ValueError("MPPT-input transform diagnostic counts are impossible")


def _validate_mppt_input_operating_point_result(
    output: pd.DataFrame,
    diagnostics: TopologyMpptInputOperatingPointDiagnostics,
) -> None:
    if tuple(output.columns) != _MPPT_INPUT_OPERATING_POINT_COLUMNS:
        raise RuntimeError("MPPT-input operating-point schema is invalid")
    if not isinstance(output.index, pd.MultiIndex) or output.index.names != [
        "timestamp",
        "inverter_id",
        "mppt_id",
    ]:
        raise RuntimeError("MPPT-input operating-point index is invalid")
    if output.index.has_duplicates:
        raise RuntimeError("MPPT-input operating-point index contains duplicates")
    if diagnostics.mppt_count != diagnostics.populated_mppt_count + diagnostics.empty_mppt_count:
        raise RuntimeError("MPPT-input population counts do not close")
    if diagnostics.state_row_count != (
        diagnostics.resolved_mppt_state_count + diagnostics.unresolved_mppt_state_count
    ):
        raise RuntimeError("MPPT-input resolution counts do not close")
    if diagnostics.resolved_mppt_state_count != (
        diagnostics.active_mppt_state_count + diagnostics.zero_mppt_state_count
    ):
        raise RuntimeError("resolved MPPT-input counts do not close")
    if diagnostics.unresolved_mppt_state_count != (
        diagnostics.upstream_unresolved_mppt_state_count
        + diagnostics.mixed_active_zero_unavailable_count
    ):
        raise RuntimeError("unresolved MPPT-input counts do not close")
    if diagnostics.physics_row_count != diagnostics.active_mppt_state_count:
        raise RuntimeError("MPPT-input physics row counts do not close")
    if diagnostics.state_row_count != (
        diagnostics.timestamp_count * diagnostics.populated_mppt_count
    ):
        raise RuntimeError("MPPT-input output grid does not close")
    if diagnostics.physics_call_count > diagnostics.populated_mppt_count:
        raise RuntimeError("MPPT-input physics call count is invalid")
    if diagnostics.common_voltage_model != MPPT_INPUT_COMMON_VOLTAGE_MODEL_ID:
        raise RuntimeError("MPPT-input common-voltage model is invalid")
    numeric_columns = (
        "v_mppt_input_v",
        "i_mppt_input_a",
        "p_mppt_input_w",
        "p_independent_mppt_input_w",
        "p_mppt_input_mismatch_w",
        "mppt_input_mismatch_pct",
    )
    provenance = {
        "source_reference_plane": STRING_TERMINAL_REFERENCE_PLANE,
        "sink_reference_plane": MPPT_INPUT_REFERENCE_PLANE,
        "dc_branch_iv_transform_contract": DC_BRANCH_IV_TRANSFORM_CONTRACT_ID,
        "dc_branch_iv_transform_model": DC_BRANCH_IV_TRANSFORM_MODEL_ID,
        "dc_branch_iv_transform_scope": DC_BRANCH_IV_TRANSFORM_SCOPE,
        "dc_branch_iv_transform_coverage_scope": (
            DC_BRANCH_IV_TRANSFORM_COVERAGE_SCOPE
        ),
        "mppt_input_common_voltage_contract": (
            MPPT_INPUT_COMMON_VOLTAGE_CONTRACT_ID
        ),
        "mppt_input_common_voltage_model": MPPT_INPUT_COMMON_VOLTAGE_MODEL_ID,
        "mppt_input_common_voltage_scope": MPPT_INPUT_COMMON_VOLTAGE_SCOPE,
        "mppt_input_common_voltage_coverage_scope": (
            MPPT_INPUT_COMMON_VOLTAGE_COVERAGE_SCOPE
        ),
    }
    state_resolution = {
        "resolved_mppt_input_common_voltage": True,
        "resolved_zero_mppt_input_common_voltage": True,
        "unresolved_member_mppt_input_iv": False,
        "unresolved_mixed_active_zero_requires_blocking_model": False,
    }
    for _, row in output.iterrows():
        for column, expected in provenance.items():
            if row[column] != expected:
                raise RuntimeError(f"MPPT-input {column} provenance is invalid")
        if row["configured_string_count"] != (
            row["active_string_count"]
            + row["zero_string_count"]
            + row["unresolved_string_count"]
        ):
            raise RuntimeError("MPPT-input classification counts do not close")
        resolved = electrical._handoff_bool(
            row["mppt_input_resolved"], "mppt_input_resolved"
        )
        state = row["mppt_input_state"]
        if state not in state_resolution or resolved is not state_resolution[state]:
            raise RuntimeError("MPPT-input operating-point state is contradictory")
        if resolved:
            values = {
                column: _nonnegative_finite(row[column], column)
                for column in numeric_columns
            }
            if not electrical._handoff_close(
                values["p_mppt_input_w"],
                values["v_mppt_input_v"] * values["i_mppt_input_a"],
            ):
                raise RuntimeError("MPPT-input common power closure failed")
            if not electrical._handoff_close(
                values["p_mppt_input_mismatch_w"],
                values["p_independent_mppt_input_w"] - values["p_mppt_input_w"],
            ):
                raise RuntimeError("MPPT-input mismatch closure failed")
            if (
                values["p_mppt_input_w"]
                > values["p_independent_mppt_input_w"]
                + electrical._NUMERICAL_NEGATIVE_TOLERANCE
            ):
                raise RuntimeError("MPPT-input common power exceeds independent power")
            expected_pct = (
                100.0
                * values["p_mppt_input_mismatch_w"]
                / values["p_independent_mppt_input_w"]
                if values["p_independent_mppt_input_w"] > 0.0
                else 0.0
            )
            if not electrical._handoff_close(
                values["mppt_input_mismatch_pct"], expected_pct
            ) or not (
                -electrical._NUMERICAL_NEGATIVE_TOLERANCE
                <= values["mppt_input_mismatch_pct"]
                <= 100.0 + electrical._NUMERICAL_NEGATIVE_TOLERANCE
            ):
                raise RuntimeError("MPPT-input mismatch percentage closure failed")
            if state == "resolved_zero_mppt_input_common_voltage" and any(values.values()):
                raise RuntimeError("resolved zero MPPT-input values must be exact zero")
        elif not all(pd.isna(row[column]) for column in numeric_columns):
            raise RuntimeError("unresolved MPPT-input values must be NaN")


def _admit_dc_branch_path_authority(
    topology: ElectricalTopologyConfig,
    ordered_strings: list[tuple[str, str, str]],
    value: object,
) -> pd.DataFrame:
    if type(value) is not DcBranchPathAuthorityResult:
        raise ValueError("branch_authority must be an exact DcBranchPathAuthorityResult")
    if type(value.diagnostics) is not DcBranchPathAuthorityDiagnostics:
        raise ValueError("branch authority diagnostics type is invalid")
    paths = value.paths
    if not isinstance(paths, pd.DataFrame) or not isinstance(paths.index, pd.MultiIndex):
        raise ValueError("branch authority paths must use a MultiIndex")
    if paths.index.nlevels != 3 or paths.index.names != [
        "inverter_id",
        "mppt_id",
        "string_id",
    ]:
        raise ValueError("branch authority index is not canonical")
    if tuple(paths.columns) != _PATH_COLUMNS or paths.index.has_duplicates:
        raise ValueError("branch authority schema is not canonical")
    expected_index = pd.MultiIndex.from_tuples(
        ordered_strings,
        names=["inverter_id", "mppt_id", "string_id"],
    )
    if not paths.index.equals(expected_index):
        raise ValueError("branch authority topology identity or order is stale")
    canonical = paths.copy(deep=True)

    resolved_count = 0
    zero_count = 0
    positive_count = 0
    provenance = {
        "dc_branch_path_contract": DC_BRANCH_PATH_CONTRACT_ID,
        "dc_branch_path_model": DC_BRANCH_PATH_MODEL_ID,
        "dc_branch_path_scope": DC_BRANCH_PATH_SCOPE,
        "dc_branch_path_coverage_scope": DC_BRANCH_PATH_COVERAGE_SCOPE,
    }
    for _, row in canonical.iterrows():
        if row["source_reference_plane"] != STRING_TERMINAL_REFERENCE_PLANE:
            raise ValueError("branch authority source reference plane is invalid")
        if row["sink_reference_plane"] != MPPT_INPUT_REFERENCE_PLANE:
            raise ValueError("branch authority sink reference plane is invalid")
        for column, expected in provenance.items():
            if row[column] != expected:
                raise ValueError(f"branch authority {column} provenance is invalid")
        resolved = _strict_bool(row["branch_path_resolved"], "branch_path_resolved")
        if resolved:
            resistance = _nonnegative_finite(
                row["series_resistance_ohm"], "series_resistance_ohm"
            )
            source = row["parameter_source"]
            confidence = row["confidence"]
            if (
                row["branch_path_state"]
                != "resolved_explicit_series_loop_resistance"
                or type(source) is not str
                or not source.strip()
                or confidence not in {"high", "medium", "low", "unknown"}
            ):
                raise ValueError("resolved branch authority is contradictory")
            resolved_count += 1
            if resistance == 0.0:
                zero_count += 1
            else:
                positive_count += 1
        elif (
            row["branch_path_state"] != "unresolved_no_explicit_dc_branch_path"
            or not pd.isna(row["series_resistance_ohm"])
            or row["parameter_source"] != ""
            or row["confidence"] != "unknown"
        ):
            raise ValueError("unresolved branch authority is contradictory")

    diagnostics = value.diagnostics
    count_names = (
        "inverter_count",
        "mppt_count",
        "string_count",
        "resolved_path_count",
        "unresolved_path_count",
        "zero_resistance_path_count",
        "positive_resistance_path_count",
    )
    counts = {
        name: _nonnegative_integer(getattr(diagnostics, name), name)
        for name in count_names
    }
    expected_diagnostics = (
        topology.inverter_count,
        topology.mppt_count,
        topology.string_count,
        resolved_count,
        topology.string_count - resolved_count,
        zero_count,
        positive_count,
        DC_BRANCH_PATH_MODEL_ID,
    )
    actual_diagnostics = (
        counts["inverter_count"],
        counts["mppt_count"],
        counts["string_count"],
        counts["resolved_path_count"],
        counts["unresolved_path_count"],
        counts["zero_resistance_path_count"],
        counts["positive_resistance_path_count"],
        diagnostics.path_model,
    )
    if actual_diagnostics != expected_diagnostics:
        raise ValueError("branch authority diagnostics are stale")
    return canonical


def _transform_curve_to_mppt_input(
    source: pd.DataFrame,
    resistance_ohm: float,
) -> tuple[pd.DataFrame | None, bool]:
    """Apply the series drop and admit only the non-negative voltage domain."""

    transformed_voltage = (
        source["voltage_v"].to_numpy(dtype=float)
        - source["current_a"].to_numpy(dtype=float) * resistance_ohm
    )
    nonnegative = np.flatnonzero(transformed_voltage >= 0.0)
    if not len(nonnegative):
        return None, False
    first = int(nonnegative[0])
    if np.any(transformed_voltage[first:] < 0.0):
        raise ValueError("transformed MPPT-input voltage domain is not contiguous")

    admitted = source.iloc[first:].copy(deep=True).reset_index(drop=True)
    admitted["voltage_v"] = transformed_voltage[first:]
    admitted["power_w"] = admitted["voltage_v"] * admitted["current_a"]
    inserted = False
    if first > 0 and transformed_voltage[first] > 0.0:
        lower_voltage = float(transformed_voltage[first - 1])
        upper_voltage = float(transformed_voltage[first])
        if lower_voltage >= 0.0 or upper_voltage <= lower_voltage:
            raise ValueError("transformed voltage does not bracket a valid zero crossing")
        lower_current = float(source.iloc[first - 1]["current_a"])
        upper_current = float(source.iloc[first]["current_a"])
        fraction = -lower_voltage / (upper_voltage - lower_voltage)
        crossing = source.iloc[[first]].copy(deep=True)
        crossing.loc[:, "voltage_v"] = 0.0
        crossing.loc[:, "current_a"] = lower_current + fraction * (
            upper_current - lower_current
        )
        crossing.loc[:, "power_w"] = 0.0
        admitted = pd.concat([crossing, admitted], ignore_index=True)
        inserted = True
    admitted["curve_point"] = np.arange(len(admitted))
    if len(admitted) > 1 and not np.all(np.diff(admitted["voltage_v"].to_numpy()) > 0.0):
        raise ValueError("transformed MPPT-input voltage samples must be strictly increasing")
    return admitted.loc[:, electrical._IV_CURVE_COLUMNS], inserted


def _validate_transform_result(
    curves: Mapping[str, pd.DataFrame],
    states: pd.DataFrame,
    diagnostics: TopologyMpptInputStringIVDiagnostics,
) -> None:
    if diagnostics.state_row_count != (
        diagnostics.resolved_state_count + diagnostics.unresolved_state_count
    ):
        raise RuntimeError("branch transform resolution counts do not close")
    if diagnostics.resolved_state_count != (
        diagnostics.zero_string_state_count
        + diagnostics.zero_resistance_identity_state_count
        + diagnostics.positive_resistance_transform_state_count
    ):
        raise RuntimeError("resolved branch transform state counts do not close")
    if diagnostics.unresolved_state_count != (
        diagnostics.missing_authority_state_count
        + diagnostics.upstream_unresolved_state_count
        + diagnostics.no_nonnegative_domain_state_count
    ):
        raise RuntimeError("unresolved branch transform state counts do not close")
    if diagnostics.output_curve_row_count != sum(len(curve) for curve in curves.values()):
        raise RuntimeError("branch transform output curve counts do not close")
    if diagnostics.transformation_model != DC_BRANCH_IV_TRANSFORM_MODEL_ID:
        raise RuntimeError("branch transform model provenance is invalid")
    for (timestamp, string_id), state in states.iterrows():
        count = int(curves[string_id]["timestamp"].eq(timestamp).sum())
        if bool(state["mppt_input_iv_resolved"]) != (count > 0):
            raise RuntimeError("branch transform curve/state closure failed")


def _strict_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be Boolean")
    return value


def _nonnegative_finite(value: object, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a real non-Boolean number")
    result = float(value)
    if not np.isfinite(result) or result < 0.0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{label} must be an integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result
