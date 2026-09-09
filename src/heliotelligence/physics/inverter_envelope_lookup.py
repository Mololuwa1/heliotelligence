"""Exact CEC/SAM lookup for inverter DC operating envelopes."""

from __future__ import annotations

import pandas as pd
import pvlib.pvsystem

from heliotelligence.physics.inverter_envelope import (
    ResolvedInverterDcOperatingEnvelope,
    inverter_dc_operating_envelope_from_mapping,
)


def _load_cec_inverter_database() -> pd.DataFrame:
    """Load pvlib's bundled CEC/SAM inverter parameter database."""
    return pvlib.pvsystem.retrieve_sam("CECInverter")


def resolve_cec_inverter_dc_operating_envelope(
    cec_name: str,
) -> ResolvedInverterDcOperatingEnvelope:
    """Resolve one exact CEC/SAM row into a validated DC operating envelope."""
    if not isinstance(cec_name, str) or not cec_name or cec_name.isspace():
        raise ValueError("cec_name must be a non-empty, non-whitespace string")

    database = _load_cec_inverter_database()
    if cec_name not in database.columns:
        raise ValueError(f"CEC/SAM inverter model not found: {cec_name!r}")

    envelope = inverter_dc_operating_envelope_from_mapping(database[cec_name].to_dict())
    return ResolvedInverterDcOperatingEnvelope(
        envelope=envelope,
        parameter_source=f"cec_sam:{cec_name}",
        confidence="high",
    )
