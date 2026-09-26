"""Static DC branch-path and electrical reference-plane authority.

This module admits explicit total loop resistance from each physical string's
``string_terminal`` reference plane to its configured parent ``mppt_input``
reference plane.  It deliberately performs no I-squared-R loss calculation,
voltage-drop calculation, I-V transformation, MPPT solve, or inverter physics.

The next physical stage must consume both ``TopologyStringIVResult`` and
``DcBranchPathAuthorityResult``, transform each string I-V curve from
``string_terminal`` to ``mppt_input``, and only then solve the shared MPPT
operating point.  A naive ``V_mppt = V_string - I * R`` transform can produce
negative voltage at low-voltage/high-current points.  That future stage must
define the physical domain and interpolation/crossing treatment explicitly;
it must not silently clamp negative voltage to zero.
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
