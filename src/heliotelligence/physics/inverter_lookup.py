"""Exact CEC/SAM parameter resolution for the Sandia inverter model."""

from __future__ import annotations

import pandas as pd
import pvlib.pvsystem

from heliotelligence.physics.inverter import (
    ResolvedSandiaInverterModel,
    sandia_parameters_from_mapping,
)


def _load_cec_inverter_database() -> pd.DataFrame:
    """Load pvlib's bundled CEC/SAM inverter parameter database."""
    return pvlib.pvsystem.retrieve_sam("CECInverter")


def resolve_cec_sandia_inverter_model(
    cec_name: str,
) -> ResolvedSandiaInverterModel:
    """Resolve one exact CEC/SAM inverter entry as a Sandia model."""
    if not isinstance(cec_name, str) or not cec_name or cec_name.isspace():
        raise ValueError("cec_name must be a non-empty, non-whitespace string")

    database = _load_cec_inverter_database()
    if cec_name not in database.columns:
        raise ValueError(f"CEC/SAM inverter model not found: {cec_name!r}")

    parameters = sandia_parameters_from_mapping(database[cec_name].to_dict())
    return ResolvedSandiaInverterModel(
        parameters=parameters,
        parameter_source=f"cec_sam:{cec_name}",
        confidence="high",
    )
