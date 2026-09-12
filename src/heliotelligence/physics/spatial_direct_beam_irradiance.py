"""Spatial coupling of receiver raw direct POA to binary beam visibility."""

from __future__ import annotations

from collections.abc import Sequence
from numbers import Real

import numpy as np
import pandas as pd

from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility_map,
)

_GEOMETRY_COLUMNS = [
    "receiver_id",
    "sample_index",
    "sample_u_index",
    "sample_v_index",
    "sample_east_m",
    "sample_north_m",
    "sample_up_m",
    "beam_visible",
    "beam_shaded",
]
_OUTPUT_COLUMNS = [
    *_GEOMETRY_COLUMNS,
    "poa_direct_raw_wm2",
    "poa_direct_visible_wm2",
    "poa_direct_shading_loss_wm2",
    "spatial_beam_irradiance_resolved",
    "spatial_beam_irradiance_state",
]


def calculate_spatial_direct_beam_irradiance(
    poa_direct_raw_wm2_by_receiver: pd.Series,
    *,
    surfaces: Sequence[RectangularSurface3D],
    apparent_solar_zenith_deg: float,
    solar_azimuth_deg: float,
    samples_u: int = 5,
    samples_v: int = 5,
) -> pd.DataFrame:
    """Distribute receiver raw direct POA over R4B visibility samples.

    This is a single-instant, above-horizon primitive.  Each deterministic
    sample represents local irradiance in W/m², so receiver-level equivalence
    is obtained by taking sample means rather than sums.
    """
    raw_values, receiver_ids = _validated_raw_direct(poa_direct_raw_wm2_by_receiver)
    geometry = calculate_direct_beam_visibility_map(
        surfaces,
        receiver_ids,
        solar_zenith_deg=apparent_solar_zenith_deg,
        solar_azimuth_deg=solar_azimuth_deg,
        samples_u=samples_u,
        samples_v=samples_v,
    )

    result = geometry.copy(deep=True)
    samples_per_receiver = int(samples_u) * int(samples_v)
    repeated_raw = np.repeat(raw_values, samples_per_receiver)
    visible = result["beam_visible"].to_numpy(dtype=bool, copy=False)
    resolved = np.isfinite(repeated_raw)

    visible_direct = np.where(visible, repeated_raw, 0.0)
    shading_loss = np.where(visible, 0.0, repeated_raw)
    visible_direct[~resolved] = np.nan
    shading_loss[~resolved] = np.nan

    result["poa_direct_raw_wm2"] = pd.array(repeated_raw, dtype="float64")
    result["poa_direct_visible_wm2"] = pd.array(visible_direct, dtype="float64")
    result["poa_direct_shading_loss_wm2"] = pd.array(shading_loss, dtype="float64")
    result["spatial_beam_irradiance_resolved"] = pd.array(resolved, dtype="bool")
    result["spatial_beam_irradiance_state"] = pd.array(
        np.where(
            resolved,
            "resolved",
            "geometry_resolved_irradiance_unresolved",
        ),
        dtype="string",
    )
    return result.loc[:, _OUTPUT_COLUMNS]


def _validated_raw_direct(value: object) -> tuple[np.ndarray, list[str]]:
    if not isinstance(value, pd.Series):
        raise ValueError("poa_direct_raw_wm2_by_receiver must be a pandas Series")
    receiver_ids = list(value.index)
    if any(not isinstance(receiver_id, str) or not receiver_id for receiver_id in receiver_ids):
        raise ValueError("receiver IDs must be non-empty strings")
    if not value.index.is_unique:
        raise ValueError("receiver IDs must be unique")

    raw_values = np.empty(len(value), dtype=float)
    for position, raw_direct in enumerate(value.array):
        if pd.isna(raw_direct):
            raw_values[position] = np.nan
        elif (
            isinstance(raw_direct, (bool, np.bool_))
            or not isinstance(raw_direct, Real)
            or not np.isfinite(raw_direct)
            or raw_direct < 0.0
        ):
            raise ValueError(
                "present poa_direct_raw_wm2 values must be finite, real, "
                "non-Boolean, and non-negative"
            )
        else:
            raw_values[position] = float(raw_direct)
    return raw_values, receiver_ids
