"""Single-input composition of inverter DC limits and Sandia conversion.

This module composes the independently validated inverter DC operating envelope
and Sandia conversion primitives for one explicit inverter DC input boundary.
It does not route multiple MPPTs, average independent MPPT voltages, or invent a
constrained operating point.  Rows outside the declared DC envelope retain their
supplied Vdc, Idc, and Pdc while AC availability remains unresolved.

This capability is dormant from production.  Multi-MPPT routing,
tracker-specific limits, constrained upstream I-V re-solving, clipping-energy
accounting, thermal capability, P/Q/S behaviour, alternative inverter models,
AC/DC networks, transformers, and grid control remain required queued work
before formal real-site benchmarking readiness.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from heliotelligence.physics.inverter import (
    ResolvedSandiaInverterModel,
    calculate_sandia_inverter_ac_power,
)
from heliotelligence.physics.inverter_envelope import (
    ResolvedInverterDcOperatingEnvelope,
    evaluate_inverter_dc_operating_envelope,
)

_OUTPUT_COLUMNS = [
    "v_dc_v",
    "i_dc_a",
    "p_dc_available_w",
    "is_active_dc_input",
    "below_mppt_voltage_limit",
    "above_mppt_voltage_limit",
    "above_absolute_dc_voltage_limit",
    "above_dc_current_limit",
    "dc_limits_satisfied",
    "dc_operating_state",
    "conversion_evaluated",
    "p_ac_available_w",
    "ac_to_dc_ratio",
    "at_ac_power_limit",
    "inverter_operating_state",
    "model_used",
    "sandia_parameter_source",
    "sandia_confidence",
    "envelope_parameter_source",
    "envelope_confidence",
]


def evaluate_sandia_inverter_input(
    v_dc_v: pd.Series,
    i_dc_a: pd.Series,
    p_dc_available_w: pd.Series,
    model: ResolvedSandiaInverterModel,
    resolved_envelope: ResolvedInverterDcOperatingEnvelope,
) -> pd.DataFrame:
    """Evaluate one explicit inverter DC input without fabricating constraints.

    The DC envelope is evaluated for every row.  Sandia conversion is evaluated
    only for rows whose supplied DC state satisfies that envelope.  Violating
    rows keep their original electrical state and report unresolved AC power as
    NaN rather than a clamped, curtailed, or otherwise invented value.
    """
    envelope_result = evaluate_inverter_dc_operating_envelope(
        v_dc_v,
        i_dc_a,
        p_dc_available_w,
        resolved_envelope,
    )
    conversion_evaluated = envelope_result["dc_limits_satisfied"].copy()

    conversion_result = calculate_sandia_inverter_ac_power(
        v_dc_v.loc[conversion_evaluated],
        i_dc_a.loc[conversion_evaluated],
        p_dc_available_w.loc[conversion_evaluated],
        model,
    )

    p_ac_available_w = pd.Series(np.nan, index=v_dc_v.index, dtype=float)
    ac_to_dc_ratio = pd.Series(np.nan, index=v_dc_v.index, dtype=float)
    at_ac_power_limit = pd.Series(False, index=v_dc_v.index, dtype=bool)
    inverter_operating_state = envelope_result["dc_operating_state"].copy()

    p_ac_available_w.loc[conversion_evaluated] = conversion_result[
        "p_ac_available_w"
    ]
    ac_to_dc_ratio.loc[conversion_evaluated] = conversion_result["ac_to_dc_ratio"]
    at_ac_power_limit.loc[conversion_evaluated] = conversion_result[
        "at_ac_power_limit"
    ]
    inverter_operating_state.loc[conversion_evaluated] = conversion_result[
        "operating_state"
    ]

    index = v_dc_v.index
    return pd.DataFrame(
        {
            "v_dc_v": envelope_result["v_dc_v"],
            "i_dc_a": envelope_result["i_dc_a"],
            "p_dc_available_w": envelope_result["p_dc_available_w"],
            "is_active_dc_input": envelope_result["is_active_dc_input"],
            "below_mppt_voltage_limit": envelope_result[
                "below_mppt_voltage_limit"
            ],
            "above_mppt_voltage_limit": envelope_result[
                "above_mppt_voltage_limit"
            ],
            "above_absolute_dc_voltage_limit": envelope_result[
                "above_absolute_dc_voltage_limit"
            ],
            "above_dc_current_limit": envelope_result["above_dc_current_limit"],
            "dc_limits_satisfied": envelope_result["dc_limits_satisfied"],
            "dc_operating_state": envelope_result["dc_operating_state"],
            "conversion_evaluated": conversion_evaluated,
            "p_ac_available_w": p_ac_available_w,
            "ac_to_dc_ratio": ac_to_dc_ratio,
            "at_ac_power_limit": at_ac_power_limit,
            "inverter_operating_state": inverter_operating_state,
            "model_used": pd.Series("sandia", index=index, dtype=str),
            "sandia_parameter_source": pd.Series(
                model.parameter_source,
                index=index,
                dtype=str,
            ),
            "sandia_confidence": pd.Series(model.confidence, index=index, dtype=str),
            "envelope_parameter_source": envelope_result[
                "envelope_parameter_source"
            ],
            "envelope_confidence": envelope_result["envelope_confidence"],
        },
        index=index,
        columns=_OUTPUT_COLUMNS,
    )
