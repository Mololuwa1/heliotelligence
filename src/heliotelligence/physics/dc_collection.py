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

from dataclasses import dataclass

import numpy as np
import pandas as pd

from heliotelligence.config.site import ElectricalTopologyConfig

DC_BRANCH_PATH_CONTRACT_ID = "string_terminal_to_mppt_input_dc_branch_path_v1"
DC_BRANCH_PATH_MODEL_ID = "explicit_lumped_series_loop_resistance_authority_v1"
DC_BRANCH_PATH_SCOPE = "dc_reference_plane_authority_before_resistive_iv_transform"
DC_BRANCH_PATH_COVERAGE_SCOPE = "direct_string_branch_to_parent_mppt_input"

STRING_TERMINAL_REFERENCE_PLANE = "string_terminal"
MPPT_INPUT_REFERENCE_PLANE = "mppt_input"

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
