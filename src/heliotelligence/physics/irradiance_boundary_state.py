"""Admission/replay of canonical optical irradiance planes, never another loss model.

IAM/shading, bifacial response and spectral response are owned upstream. Front
measurements do not replace modelled front or erase rear. Incident sums are
physical diagnostics, not an admitted thermal calibration basis.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from numbers import Real
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver
from heliotelligence.physics.bifacial_equivalent_irradiance import (
    BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID,
    BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID,
    BifacialEquivalentIrradianceResult,
)
from heliotelligence.physics.effective_irradiance import (
    EFFECTIVE_IRRADIANCE_MODEL_ID,
    FrontEffectiveIrradianceResult,
)
from heliotelligence.physics.optical_state import STATE_CONTRACT_ID, OpticalStateResult
from heliotelligence.physics.solar_geometry_time_alignment import (
    TIME_ALIGNED_SOLAR_GEOMETRY_CONTRACT_ID,
    TIME_ALIGNED_SOLAR_GEOMETRY_MODEL_ID,
    TimeAlignedSolarGeometryResult,
    validate_time_aligned_solar_geometry,
)
from heliotelligence.physics.spectral_response import (
    SPECTRAL_RESPONSE_CONTRACT_ID,
    SPECTRAL_RESPONSE_MODEL_ID,
    SpectralResponseResult,
)
from heliotelligence.physics.weather_time_authority import (
    WEATHER_TIME_AUTHORITY_CONTRACT_ID,
    WEATHER_TIME_AUTHORITY_MODEL_ID,
    Confidence,
    WeatherTimeStateResult,
    _text,
    validate_weather_time_state,
)

IRRADIANCE_BOUNDARY_CONTRACT_ID = (
    "admitted_time_aligned_canonical_optical_bifacial_and_spectral_results_"
    "to_module_irradiance_boundary_v1"
)
IRRADIANCE_BOUNDARY_MODEL_ID = (
    "reference_plane_preserving_incident_optical_and_spectral_irradiance_handoff_v1"
)
IRRADIANCE_BOUNDARY_SCOPE = (
    "observation_receiver_irradiance_admission_before_module_thermal_and_electrical"
)
IRRADIANCE_BOUNDARY_COVERAGE_SCOPE = (
    "canonical_optical_result_replay_without_production_or_site_activation"
)


@dataclass(frozen=True)
class FrontPoaMeasurementAuthority:
    measurement_quantity: str
    parameter_source: str
    confidence: Confidence
    method_reference: str
    measurement_plane_description: str

    def __post_init__(self) -> None:
        for name in (
            "measurement_quantity",
            "parameter_source",
            "confidence",
            "method_reference",
            "measurement_plane_description",
        ):
            _text(getattr(self, name), name)
        if self.measurement_quantity != "front_surface_incident_broadband_poa":
            raise ValueError("measurement quantity must be front_surface_incident_broadband_poa")
        if self.confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError("confidence is unsupported")


@dataclass(frozen=True)
class IrradianceBoundaryDiagnostics:
    receiver_count: int
    timestamp_count: int
    row_count: int
    resolved_row_count: int
    unresolved_row_count: int
    measured_front_present_count: int
    rear_not_applicable_count: int
    rear_unresolved_count: int
    module_electrical_resolved_count: int
    module_thermal_handoff_resolved_count: int
    state_counts: Mapping[str, int]
    contract: str = IRRADIANCE_BOUNDARY_CONTRACT_ID
    model: str = IRRADIANCE_BOUNDARY_MODEL_ID


@dataclass(frozen=True)
class CanonicalIrradianceBoundaryResult:
    states: pd.DataFrame
    diagnostics: IrradianceBoundaryDiagnostics


_FLOAT = (
    "modeled_front_incident_poa_wm2",
    "modeled_rear_incident_poa_wm2",
    "poa_front_global_raw_wm2",
    "poa_rear_global_raw_wm2",
    "front_incident_broadband_poa_wm2",
    "rear_incident_broadband_poa_wm2",
    "total_incident_broadband_both_surfaces_wm2",
    "measured_front_incident_poa_wm2",
    "raw_front_direct_irradiance_wm2",
    "front_optical_effective_direct_irradiance_wm2",
    "front_optical_effective_irradiance_wm2",
    "bifacial_electrical_equivalent_irradiance_wm2",
    "spectral_electrical_equivalent_irradiance_wm2",
    "module_electrical_irradiance_wm2",
    "module_thermal_poa_candidate_front_wm2",
    "module_thermal_poa_candidate_front_plus_rear_wm2",
    "module_thermal_poa_handoff_wm2",
)
_BOOL = (
    "solar_geometry_time_approximation_applied",
    "front_incident_resolved",
    "rear_incident_resolved",
    "bifacial_enabled",
    "measured_front_poa_present",
    "front_optical_effective_resolved",
    "bifacial_electrical_equivalent_resolved",
    "module_electrical_irradiance_resolved",
    "module_thermal_poa_handoff_resolved",
    "iam_already_applied_upstream",
    "shading_already_applied_upstream",
    "bifacial_response_already_applied_upstream",
    "spectral_response_already_applied_upstream",
    "canonical_irradiance_boundary_resolved",
)
_FIXED = MappingProxyType(
    {
        "weather_time_authority_contract": WEATHER_TIME_AUTHORITY_CONTRACT_ID,
        "weather_time_authority_model": WEATHER_TIME_AUTHORITY_MODEL_ID,
        "time_aligned_solar_geometry_contract": TIME_ALIGNED_SOLAR_GEOMETRY_CONTRACT_ID,
        "time_aligned_solar_geometry_model": TIME_ALIGNED_SOLAR_GEOMETRY_MODEL_ID,
        "optical_state_contract": STATE_CONTRACT_ID,
        "front_effective_irradiance_model": EFFECTIVE_IRRADIANCE_MODEL_ID,
        "bifacial_equivalent_irradiance_contract": BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID,
        "bifacial_equivalent_irradiance_model": BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID,
        "spectral_response_contract": SPECTRAL_RESPONSE_CONTRACT_ID,
        "spectral_response_model": SPECTRAL_RESPONSE_MODEL_ID,
        "irradiance_boundary_contract": IRRADIANCE_BOUNDARY_CONTRACT_ID,
        "irradiance_boundary_model": IRRADIANCE_BOUNDARY_MODEL_ID,
        "irradiance_boundary_scope": IRRADIANCE_BOUNDARY_SCOPE,
        "irradiance_boundary_coverage_scope": IRRADIANCE_BOUNDARY_COVERAGE_SCOPE,
    }
)
_TEXT = (
    "receiver_id",
    "weather_value_semantics",
    "weather_timestamp_label",
    "solar_geometry_evaluation_policy",
    "weather_parameter_source",
    "weather_confidence",
    "weather_method_reference",
    "measured_front_parameter_source",
    "measured_front_confidence",
    "measured_front_method_reference",
    "measured_front_measurement_plane_description",
    "measured_front_measurement_quantity",
    "rear_incident_state",
    "module_electrical_irradiance_state",
    "module_thermal_poa_handoff_state",
    "canonical_irradiance_boundary_state",
    "front_effective_irradiance_state",
    "bifacial_electrical_equivalent_state",
    "front_spectral_activation_state",
    "rear_spectral_treatment",
) + tuple(_FIXED)
_TIME = ("observation_timestamp", "solar_geometry_evaluation_time")
_COLUMNS = _TIME + _FLOAT + _BOOL + _TEXT


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be Boolean")
    return bool(value)


def _irradiance(value: Any, resolved: bool, label: str) -> float:
    if not resolved:
        if not pd.isna(value):
            raise ValueError(f"unresolved {label} must remain NaN")
        return math.nan
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"resolved {label} must be finite non-negative real irradiance")
    return float(value)


def _same(left: Any, right: Any, label: str) -> None:
    if pd.isna(left) and pd.isna(right):
        return
    if not math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError(f"contradictory upstream {label}")


def _validate_temporal_parents(
    weather: WeatherTimeStateResult,
    ids: tuple[str, ...],
    optical: pd.DataFrame,
    horizontal: pd.DataFrame,
    fronts: Mapping[str, pd.DataFrame],
    rear: pd.DataFrame | None,
) -> None:
    """Replay physical-time provenance and the raw values actually composed.

    Complete supplied components do not need an Erbs instant. Isotropic rear
    has no extraterrestrial dependency. No optical physics is recalculated.
    """
    times = weather.observation_times
    expected = pd.DatetimeIndex(weather.states["solar_geometry_evaluation_time"])
    if not isinstance(horizontal, pd.DataFrame) or not horizontal.index.identical(times):
        raise ValueError("horizontal temporal parent observation keys differ")
    if set(fronts) != set(ids):
        raise ValueError("front temporal parent receiver keys differ")

    def replay_time(values: pd.Series, mask: pd.Series | None = None) -> None:
        actual = pd.DatetimeIndex(values)
        selected = np.ones(len(times), dtype=bool) if mask is None else mask.to_numpy(dtype=bool)
        if (
            actual.tz is None
            or str(actual.tz) != str(expected.tz)
            or not actual[selected].equals(expected[selected])
            or (mask is not None and actual[~selected].notna().any())
        ):
            raise ValueError("irradiance temporal provenance differs from admitted evaluation time")

    try:
        replay_time(
            horizontal["decomposition_evaluation_time"], horizontal["decomposition_applied"]
        )
        for receiver_id in ids:
            front = fronts[receiver_id]
            if not front.index.identical(times):
                raise ValueError("front temporal parent observation keys differ")
            replay_time(front["extraterrestrial_irradiance_evaluation_time"])
            published = optical.xs(receiver_id, level="receiver_id")
            for column in ("ghi_wm2", "dhi_wm2", "dni_wm2"):
                if not np.allclose(
                    front[column], horizontal[column], rtol=0, atol=0, equal_nan=True
                ):
                    raise ValueError("front does not replay horizontal components")
            for column in ("dni_extra_wm2", "poa_global_raw_wm2", "poa_direct_raw_wm2"):
                if not np.allclose(
                    front[column], published[column], rtol=0, atol=0, equal_nan=True
                ):
                    raise ValueError("optical state does not replay admitted front temporal parent")
        rear_required = optical["rear_irradiance_resolved"].any()
        if rear is None:
            if rear_required:
                raise ValueError("resolved rear requires raw temporal parent")
            return
        if not rear.index.identical(optical.index):
            raise ValueError("rear temporal parent observation/receiver keys differ")
        for receiver_id in ids:
            raw = rear.xs(receiver_id, level="receiver_id")
            published = optical.xs(receiver_id, level="receiver_id")
            haydavies = raw["rear_diffuse_model"].eq("haydavies")
            replay_time(raw["extraterrestrial_irradiance_evaluation_time"], haydavies)
            for column in ("ghi_wm2", "dhi_wm2", "dni_wm2"):
                if not np.allclose(raw[column], horizontal[column], rtol=0, atol=0, equal_nan=True):
                    raise ValueError("rear does not replay horizontal components")
            for column in ("poa_rear_global_raw_wm2", "rear_diffuse_model"):
                if column.endswith("wm2"):
                    if not np.allclose(
                        raw[column], published[column], rtol=0, atol=0, equal_nan=True
                    ):
                        raise ValueError(
                            "optical state does not replay admitted rear temporal parent"
                        )
                elif not raw[column].astype(str).equals(published[column].astype(str)):
                    raise ValueError("rear model provenance differs")
    except (KeyError, TypeError) as exc:
        raise ValueError("missing or invalid irradiance temporal provenance") from exc


def _admit(
    receivers: Sequence[PVReceiver],
    weather_time_state: WeatherTimeStateResult,
    solar_geometry: TimeAlignedSolarGeometryResult,
    optical_state: OpticalStateResult,
    front_effective_irradiance: FrontEffectiveIrradianceResult,
    bifacial_equivalent_irradiance: BifacialEquivalentIrradianceResult,
    spectral_response: SpectralResponseResult,
    horizontal_irradiance_components: pd.DataFrame,
    raw_poa_transposition_by_receiver: Mapping[str, pd.DataFrame],
    raw_rear_irradiance: pd.DataFrame | None,
    measured_front_poa_wm2: pd.Series | None,
    measured_front_authority_by_receiver: Mapping[str, FrontPoaMeasurementAuthority] | None,
) -> tuple[pd.MultiIndex, Mapping[str, FrontPoaMeasurementAuthority]]:
    validate_weather_time_state(weather_time_state)
    validate_time_aligned_solar_geometry(solar_geometry)
    try:
        pd.testing.assert_frame_equal(
            weather_time_state.states, solar_geometry.weather_time_state.states, check_exact=True
        )
    except AssertionError as exc:
        raise ValueError("weather-time and solar alignment parents disagree") from exc
    if (
        not isinstance(receivers, Sequence)
        or not receivers
        or any(type(r) is not PVReceiver for r in receivers)
    ):
        raise ValueError("receivers must explicitly identify canonical PVReceiver objects")
    ids = tuple(sorted(r.id for r in receivers))
    if len(set(ids)) != len(ids):
        raise ValueError("receiver IDs must be unique")
    for receiver_id in ids:
        _text(receiver_id, "receiver ID")
    times = weather_time_state.observation_times
    index = pd.MultiIndex.from_product([times, ids], names=[times.name, "receiver_id"])
    parents = (
        (optical_state, OpticalStateResult, "state"),
        (front_effective_irradiance, FrontEffectiveIrradianceResult, "irradiance"),
        (bifacial_equivalent_irradiance, BifacialEquivalentIrradianceResult, "irradiance"),
        (spectral_response, SpectralResponseResult, "irradiance"),
    )
    for parent, kind, attribute in parents:
        if type(parent) is not kind:
            raise TypeError("parent must be the exact canonical result type")
        frame = getattr(parent, attribute)
        if (
            type(frame) is not pd.DataFrame
            or not frame.index.identical(index)
            or not frame.columns.is_unique
        ):
            raise ValueError("parent timestamp/receiver/timezone/order must match exactly")
        for name, expected in (
            ("receiver_count", len(ids)),
            ("timestamp_count", len(times)),
            ("row_count", len(index)),
        ):
            if getattr(parent.diagnostics, name) != expected:
                raise ValueError("parent diagnostics do not match the canonical row universe")
    _validate_temporal_parents(
        weather_time_state,
        ids,
        optical_state.state,
        horizontal_irradiance_components,
        raw_poa_transposition_by_receiver,
        raw_rear_irradiance,
    )
    a, f, b, s = (
        optical_state.state,
        front_effective_irradiance.irradiance,
        bifacial_equivalent_irradiance.irradiance,
        spectral_response.irradiance,
    )
    for frame, column, expected_identity in (
        (a, "optical_state_contract", STATE_CONTRACT_ID),
        (f, "effective_irradiance_model", EFFECTIVE_IRRADIANCE_MODEL_ID),
        (b, "bifacial_equivalent_irradiance_contract", BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID),
        (b, "bifacial_equivalent_irradiance_model", BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID),
        (s, "spectral_response_contract", SPECTRAL_RESPONSE_CONTRACT_ID),
        (s, "spectral_response_model", SPECTRAL_RESPONSE_MODEL_ID),
    ):
        if column not in frame or not frame[column].eq(expected_identity).all():
            raise ValueError(f"wrong upstream contract/model: {column}")
    requirements = (
        (
            a,
            {
                "apparent_solar_zenith_deg",
                "solar_azimuth_deg",
                "poa_global_raw_wm2",
                "poa_direct_raw_wm2",
                "poa_transposition_resolved",
                "beam_iam_factor",
                "front_direct_geometric_visible_fraction",
                "poa_rear_global_raw_wm2",
                "rear_irradiance_resolved",
                "rear_mode",
            },
        ),
        (
            f,
            {
                "poa_front_global_raw_wm2",
                "poa_front_direct_raw_wm2",
                "beam_iam_factor",
                "front_direct_geometric_visible_fraction",
                "poa_front_effective_optical_wm2",
                "poa_front_direct_effective_wm2",
                "front_effective_irradiance_resolved",
                "front_effective_irradiance_state",
                "surface_tilt_deg",
                "surface_azimuth_deg",
            },
        ),
        (
            b,
            {
                "bifacial_enabled",
                "poa_front_effective_optical_wm2",
                "poa_rear_effective_optical_wm2",
                "bifacial_electrical_equivalent_irradiance_wm2",
                "bifacial_electrical_equivalent_resolved",
                "bifacial_electrical_equivalent_state",
                "isc_bifaciality_factor",
                "rear_electrical_equivalent_irradiance_wm2",
                "surface_tilt_deg",
                "surface_azimuth_deg",
            },
        ),
        (
            s,
            {
                "apparent_solar_zenith_deg",
                "bifacial_enabled",
                "poa_front_effective_optical_wm2",
                "poa_rear_effective_optical_wm2",
                "bifacial_electrical_equivalent_irradiance_wm2",
                "isc_bifaciality_factor",
                "rear_electrical_equivalent_irradiance_wm2",
                "surface_tilt_deg",
                "surface_azimuth_deg",
                "front_spectral_activation_state",
                "rear_spectral_treatment",
                "spectral_electrical_equivalent_irradiance_wm2",
                "spectral_electrical_equivalent_resolved",
                "spectral_electrical_equivalent_state",
            },
        ),
    )
    for frame, required_columns in requirements:
        if not required_columns.issubset(frame.columns):
            raise ValueError("upstream canonical schema is incomplete")
    for key in index:
        o, front, bifacial, spectral = a.loc[key], f.loc[key], b.loc[key], s.loc[key]
        geometry = solar_geometry.geometry.loc[key[0]]
        _irradiance(
            o["poa_rear_global_raw_wm2"],
            _bool(bifacial["bifacial_enabled"], "bifacial enabled")
            and _bool(o["rear_irradiance_resolved"], "rear raw resolution"),
            "raw rear",
        )
        for name in ("apparent_solar_zenith_deg", "solar_azimuth_deg"):
            _same(o[name], geometry[name], "solar geometry " + name)
        if pd.notna(spectral["apparent_solar_zenith_deg"]):
            _same(
                spectral["apparent_solar_zenith_deg"],
                geometry["apparent_solar_zenith_deg"],
                "spectral geometry",
            )
        _same(o["poa_global_raw_wm2"], front["poa_front_global_raw_wm2"], "front raw global")
        _same(o["poa_direct_raw_wm2"], front["poa_front_direct_raw_wm2"], "front raw direct")
        _same(o["beam_iam_factor"], front["beam_iam_factor"], "IAM ownership")
        _same(
            o["front_direct_geometric_visible_fraction"],
            front["front_direct_geometric_visible_fraction"],
            "shading ownership",
        )
        for name in ("poa_front_effective_optical_wm2", "surface_tilt_deg", "surface_azimuth_deg"):
            _same(front[name], bifacial[name], "front/bifacial " + name)
        for name in (
            "poa_front_effective_optical_wm2",
            "poa_rear_effective_optical_wm2",
            "bifacial_electrical_equivalent_irradiance_wm2",
            "isc_bifaciality_factor",
            "rear_electrical_equivalent_irradiance_wm2",
            "surface_tilt_deg",
            "surface_azimuth_deg",
        ):
            _same(bifacial[name], spectral[name], "bifacial/spectral " + name)
        bifacial_on = _bool(bifacial["bifacial_enabled"], "bifacial enabled")
        if _bool(spectral["bifacial_enabled"], "spectral bifacial enabled") != bifacial_on:
            raise ValueError("contradictory bifacial identity")
        if not bifacial_on and o["rear_mode"] != "not_applicable":
            raise ValueError("monofacial receiver rear must be not applicable")
        fr = _bool(front["front_effective_irradiance_resolved"], "front resolution")
        br = _bool(bifacial["bifacial_electrical_equivalent_resolved"], "bifacial resolution")
        sr = _bool(spectral["spectral_electrical_equivalent_resolved"], "spectral resolution")
        _irradiance(
            o["poa_global_raw_wm2"],
            _bool(o["poa_transposition_resolved"], "front raw resolution"),
            "raw front",
        )
        _irradiance(front["poa_front_effective_optical_wm2"], fr, "front optical")
        for flag, state in (
            (fr, front["front_effective_irradiance_state"]),
            (br, bifacial["bifacial_electrical_equivalent_state"]),
            (sr, spectral["spectral_electrical_equivalent_state"]),
        ):
            if type(state) is not str or (
                state != "resolved" if flag else not state.startswith("unresolved_")
            ):
                raise ValueError("upstream resolution flags and states disagree")
        _irradiance(
            bifacial["bifacial_electrical_equivalent_irradiance_wm2"], br, "bifacial equivalent"
        )
        _irradiance(
            spectral["spectral_electrical_equivalent_irradiance_wm2"], sr, "spectral equivalent"
        )
        if br and (
            not fr or (bifacial_on and not _bool(o["rear_irradiance_resolved"], "rear resolution"))
        ):
            raise ValueError(
                "resolved bifacial equivalent requires resolved incident/optical parents"
            )
        if sr and not br:
            raise ValueError("spectral handoff cannot repair an unresolved bifacial parent")
        if spectral["front_spectral_activation_state"] not in {"enabled", "disabled", "unknown"}:
            raise ValueError("unsupported spectral admission")
        if (
            spectral["front_spectral_activation_state"] == "unknown"
            and sr
            and float(front["poa_front_effective_optical_wm2"]) > 0
        ):
            raise ValueError("unknown nonzero spectral admission cannot be treated as disabled")
    authorities: dict[str, FrontPoaMeasurementAuthority] = {}
    if measured_front_poa_wm2 is None:
        if measured_front_authority_by_receiver is not None:
            raise ValueError("front measurement authority requires explicit observation Series")
    else:
        if type(
            measured_front_poa_wm2
        ) is not pd.Series or not measured_front_poa_wm2.index.identical(index):
            raise ValueError("front measurements must match the exact timestamp/receiver grid")
        if not isinstance(measured_front_authority_by_receiver, Mapping) or set(
            measured_front_authority_by_receiver
        ) != set(ids):
            raise ValueError("front measurement authority keys must match receivers exactly")
        for receiver_id, authority in measured_front_authority_by_receiver.items():
            if type(authority) is not FrontPoaMeasurementAuthority:
                raise TypeError("front measurement requires exact FrontPoaMeasurementAuthority")
            authorities[receiver_id] = replace(authority)
        for value in measured_front_poa_wm2:
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
                raise ValueError("front measurement must contain non-Boolean real values or NaN")
            if not math.isnan(value) and (not math.isfinite(value) or value < 0):
                raise ValueError("front measurement must be finite non-negative or NaN")
    return index, MappingProxyType(authorities)


def _record(
    key: Any,
    weather: pd.Series,
    optical: pd.Series,
    front: pd.Series,
    bifacial: pd.Series,
    spectral: pd.Series,
    measured: float,
    authority: FrontPoaMeasurementAuthority | None,
) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(_FLOAT, math.nan)
    row.update(dict.fromkeys(_BOOL, False))
    row.update(dict.fromkeys(_TEXT, ""))
    row.update(_FIXED)
    front_ok = bool(optical["poa_transposition_resolved"])
    rear_on = bool(bifacial["bifacial_enabled"])
    rear_ok = rear_on and bool(optical["rear_irradiance_resolved"])
    raw_front = float(optical["poa_global_raw_wm2"])
    raw_rear = _irradiance(optical["poa_rear_global_raw_wm2"], rear_ok, "raw rear")
    front_effective = bool(front["front_effective_irradiance_resolved"])
    eq = bool(bifacial["bifacial_electrical_equivalent_resolved"])
    electrical = bool(spectral["spectral_electrical_equivalent_resolved"])
    total = raw_front + raw_rear if front_ok and rear_ok else math.nan
    resolved = front_ok and electrical and (not rear_on or rear_ok)
    row.update(
        observation_timestamp=key[0],
        receiver_id=key[1],
        solar_geometry_evaluation_time=weather["solar_geometry_evaluation_time"],
        weather_value_semantics=weather["weather_value_semantics"],
        weather_timestamp_label=weather["weather_timestamp_label"],
        solar_geometry_evaluation_policy=weather["solar_geometry_evaluation_policy"],
        solar_geometry_time_approximation_applied=bool(
            weather["solar_geometry_time_approximation_applied"]
        ),
        weather_parameter_source=weather["parameter_source"],
        weather_confidence=weather["confidence"],
        weather_method_reference=weather["method_reference"],
        modeled_front_incident_poa_wm2=raw_front,
        poa_front_global_raw_wm2=raw_front,
        front_incident_broadband_poa_wm2=raw_front,
        front_incident_resolved=front_ok,
        modeled_rear_incident_poa_wm2=raw_rear,
        poa_rear_global_raw_wm2=raw_rear,
        rear_incident_broadband_poa_wm2=raw_rear,
        rear_incident_resolved=rear_ok,
        rear_incident_state="not_applicable_monofacial"
        if not rear_on
        else "resolved"
        if rear_ok
        else "unresolved_rear_incident",
        bifacial_enabled=rear_on,
        total_incident_broadband_both_surfaces_wm2=total,
        measured_front_incident_poa_wm2=measured,
        measured_front_poa_present=math.isfinite(measured),
        raw_front_direct_irradiance_wm2=optical["poa_direct_raw_wm2"],
        front_optical_effective_direct_irradiance_wm2=front["poa_front_direct_effective_wm2"],
        front_optical_effective_irradiance_wm2=front["poa_front_effective_optical_wm2"],
        front_optical_effective_resolved=front_effective,
        front_effective_irradiance_state=front["front_effective_irradiance_state"],
        bifacial_electrical_equivalent_irradiance_wm2=bifacial[
            "bifacial_electrical_equivalent_irradiance_wm2"
        ],
        bifacial_electrical_equivalent_resolved=eq,
        bifacial_electrical_equivalent_state=bifacial["bifacial_electrical_equivalent_state"],
        spectral_electrical_equivalent_irradiance_wm2=spectral[
            "spectral_electrical_equivalent_irradiance_wm2"
        ],
        module_electrical_irradiance_wm2=spectral["spectral_electrical_equivalent_irradiance_wm2"],
        module_electrical_irradiance_resolved=electrical,
        module_electrical_irradiance_state=spectral["spectral_electrical_equivalent_state"],
        front_spectral_activation_state=spectral["front_spectral_activation_state"],
        rear_spectral_treatment=spectral["rear_spectral_treatment"],
        module_thermal_poa_candidate_front_wm2=raw_front,
        module_thermal_poa_candidate_front_plus_rear_wm2=total,
        module_thermal_poa_handoff_state="unresolved_no_explicit_thermal_poa_basis_authority",
        iam_already_applied_upstream=front_effective,
        shading_already_applied_upstream=front_effective,
        bifacial_response_already_applied_upstream=eq,
        spectral_response_already_applied_upstream=electrical,
        canonical_irradiance_boundary_resolved=resolved,
        canonical_irradiance_boundary_state="resolved_canonical_irradiance_boundary"
        if resolved
        else "unresolved_rear_incident"
        if rear_on and not rear_ok
        else "unresolved_module_electrical_irradiance"
        if not electrical
        else "unresolved_front_incident",
    )
    if authority is not None:
        for name in (
            "parameter_source",
            "confidence",
            "method_reference",
            "measurement_plane_description",
            "measurement_quantity",
        ):
            row["measured_front_" + name] = getattr(authority, name)
    return row


def _frame(records: list[dict[str, Any]], index: pd.MultiIndex) -> pd.DataFrame:
    frame = pd.DataFrame(records, index=index.copy(), columns=_COLUMNS)
    for column in _FLOAT + _BOOL + _TEXT:
        frame[column] = frame[column].astype(
            float if column in _FLOAT else bool if column in _BOOL else object
        )
    for column in _TIME:
        frame[column] = pd.Series(
            pd.DatetimeIndex(frame[column], tz=index.levels[0].tz), index=index
        )
    return frame


def _diagnostics(
    frame: pd.DataFrame, receiver_count: int, timestamp_count: int
) -> IrradianceBoundaryDiagnostics:
    counts = Counter(frame["canonical_irradiance_boundary_state"])
    resolved = int(frame["canonical_irradiance_boundary_resolved"].sum())
    return IrradianceBoundaryDiagnostics(
        receiver_count,
        timestamp_count,
        len(frame),
        resolved,
        len(frame) - resolved,
        int(frame["measured_front_poa_present"].sum()),
        int(frame["rear_incident_state"].eq("not_applicable_monofacial").sum()),
        int(frame["rear_incident_state"].eq("unresolved_rear_incident").sum()),
        int(frame["module_electrical_irradiance_resolved"].sum()),
        0,
        MappingProxyType(dict(sorted(counts.items()))),
    )


def resolve_canonical_irradiance_boundary(
    *,
    receivers: Sequence[PVReceiver],
    weather_time_state: WeatherTimeStateResult,
    solar_geometry: TimeAlignedSolarGeometryResult,
    optical_state: OpticalStateResult,
    front_effective_irradiance: FrontEffectiveIrradianceResult,
    bifacial_equivalent_irradiance: BifacialEquivalentIrradianceResult,
    spectral_response: SpectralResponseResult,
    horizontal_irradiance_components: pd.DataFrame,
    raw_poa_transposition_by_receiver: Mapping[str, pd.DataFrame],
    raw_rear_irradiance: pd.DataFrame | None,
    measured_front_poa_wm2: pd.Series | None = None,
    measured_front_authority_by_receiver: Mapping[str, FrontPoaMeasurementAuthority] | None = None,
) -> CanonicalIrradianceBoundaryResult:
    values: dict[str, Any] = dict(
        receivers=receivers,
        weather_time_state=weather_time_state,
        solar_geometry=solar_geometry,
        optical_state=optical_state,
        front_effective_irradiance=front_effective_irradiance,
        bifacial_equivalent_irradiance=bifacial_equivalent_irradiance,
        spectral_response=spectral_response,
        horizontal_irradiance_components=horizontal_irradiance_components,
        raw_poa_transposition_by_receiver=raw_poa_transposition_by_receiver,
        raw_rear_irradiance=raw_rear_irradiance,
        measured_front_poa_wm2=measured_front_poa_wm2,
        measured_front_authority_by_receiver=measured_front_authority_by_receiver,
    )
    index, authorities = _admit(**values)
    records = [
        _record(
            key,
            weather_time_state.states.loc[key[0]],
            optical_state.state.loc[key],
            front_effective_irradiance.irradiance.loc[key],
            bifacial_equivalent_irradiance.irradiance.loc[key],
            spectral_response.irradiance.loc[key],
            float(measured_front_poa_wm2.loc[key])
            if measured_front_poa_wm2 is not None
            else math.nan,
            authorities.get(key[1]),
        )
        for key in index
    ]
    frame = _frame(records, index)
    result = CanonicalIrradianceBoundaryResult(
        frame, _diagnostics(frame, len(receivers), len(weather_time_state.states))
    )
    validate_canonical_irradiance_boundary(result, **values)
    return result


def validate_canonical_irradiance_boundary(
    result: CanonicalIrradianceBoundaryResult,
    *,
    receivers: Sequence[PVReceiver],
    weather_time_state: WeatherTimeStateResult,
    solar_geometry: TimeAlignedSolarGeometryResult,
    optical_state: OpticalStateResult,
    front_effective_irradiance: FrontEffectiveIrradianceResult,
    bifacial_equivalent_irradiance: BifacialEquivalentIrradianceResult,
    spectral_response: SpectralResponseResult,
    horizontal_irradiance_components: pd.DataFrame,
    raw_poa_transposition_by_receiver: Mapping[str, pd.DataFrame],
    raw_rear_irradiance: pd.DataFrame | None,
    measured_front_poa_wm2: pd.Series | None = None,
    measured_front_authority_by_receiver: Mapping[str, FrontPoaMeasurementAuthority] | None = None,
) -> None:
    """Independent field replay/ownership validation, never an optical model solve."""
    if type(result) is not CanonicalIrradianceBoundaryResult:
        raise TypeError("invalid boundary result type")
    index, authorities = _admit(
        receivers,
        weather_time_state,
        solar_geometry,
        optical_state,
        front_effective_irradiance,
        bifacial_equivalent_irradiance,
        spectral_response,
        horizontal_irradiance_components,
        raw_poa_transposition_by_receiver,
        raw_rear_irradiance,
        measured_front_poa_wm2,
        measured_front_authority_by_receiver,
    )
    records = []
    for key in index:
        o = optical_state.state.loc[key]
        f = front_effective_irradiance.irradiance.loc[key]
        b = bifacial_equivalent_irradiance.irradiance.loc[key]
        s = spectral_response.irradiance.loc[key]
        w = weather_time_state.states.loc[key[0]]
        row: dict[str, Any] = {name: math.nan for name in _FLOAT}
        row.update({name: False for name in _BOOL})
        row.update({name: "" for name in _TEXT})
        row.update(_FIXED)
        row["observation_timestamp"], row["receiver_id"] = key
        row["solar_geometry_evaluation_time"] = w["solar_geometry_evaluation_time"]
        for name in (
            "weather_value_semantics",
            "weather_timestamp_label",
            "solar_geometry_evaluation_policy",
            "solar_geometry_time_approximation_applied",
        ):
            row[name] = w[name]
        for name in ("parameter_source", "confidence", "method_reference"):
            row["weather_" + name] = w[name]
        front_ok = bool(o["poa_transposition_resolved"])
        bifacial = bool(b["bifacial_enabled"])
        rear_ok = bifacial and bool(o["rear_irradiance_resolved"])
        for name in (
            "modeled_front_incident_poa_wm2",
            "poa_front_global_raw_wm2",
            "front_incident_broadband_poa_wm2",
            "module_thermal_poa_candidate_front_wm2",
        ):
            row[name] = o["poa_global_raw_wm2"]
        for name in (
            "modeled_rear_incident_poa_wm2",
            "poa_rear_global_raw_wm2",
            "rear_incident_broadband_poa_wm2",
        ):
            row[name] = o["poa_rear_global_raw_wm2"] if rear_ok else math.nan
        combined = (
            float(o["poa_global_raw_wm2"]) + float(o["poa_rear_global_raw_wm2"])
            if front_ok and rear_ok
            else math.nan
        )
        row["total_incident_broadband_both_surfaces_wm2"] = combined
        row["module_thermal_poa_candidate_front_plus_rear_wm2"] = combined
        row["front_incident_resolved"], row["rear_incident_resolved"], row["bifacial_enabled"] = (
            front_ok,
            rear_ok,
            bifacial,
        )
        row["rear_incident_state"] = (
            "not_applicable_monofacial"
            if not bifacial
            else "resolved"
            if rear_ok
            else "unresolved_rear_incident"
        )
        measured = (
            measured_front_poa_wm2.loc[key] if measured_front_poa_wm2 is not None else math.nan
        )
        row["measured_front_incident_poa_wm2"] = measured
        row["measured_front_poa_present"] = not pd.isna(measured)
        if key[1] in authorities:
            authority = authorities[key[1]]
            row.update(
                measured_front_parameter_source=authority.parameter_source,
                measured_front_confidence=authority.confidence,
                measured_front_method_reference=authority.method_reference,
                measured_front_measurement_plane_description=authority.measurement_plane_description,
                measured_front_measurement_quantity=authority.measurement_quantity,
            )
        row.update(
            raw_front_direct_irradiance_wm2=o["poa_direct_raw_wm2"],
            front_optical_effective_direct_irradiance_wm2=f["poa_front_direct_effective_wm2"],
            front_optical_effective_irradiance_wm2=f["poa_front_effective_optical_wm2"],
            front_optical_effective_resolved=f["front_effective_irradiance_resolved"],
            front_effective_irradiance_state=f["front_effective_irradiance_state"],
            bifacial_electrical_equivalent_irradiance_wm2=b[
                "bifacial_electrical_equivalent_irradiance_wm2"
            ],
            bifacial_electrical_equivalent_resolved=b["bifacial_electrical_equivalent_resolved"],
            bifacial_electrical_equivalent_state=b["bifacial_electrical_equivalent_state"],
            spectral_electrical_equivalent_irradiance_wm2=s[
                "spectral_electrical_equivalent_irradiance_wm2"
            ],
            module_electrical_irradiance_wm2=s["spectral_electrical_equivalent_irradiance_wm2"],
            module_electrical_irradiance_resolved=s["spectral_electrical_equivalent_resolved"],
            module_electrical_irradiance_state=s["spectral_electrical_equivalent_state"],
            front_spectral_activation_state=s["front_spectral_activation_state"],
            rear_spectral_treatment=s["rear_spectral_treatment"],
            module_thermal_poa_handoff_state="unresolved_no_explicit_thermal_poa_basis_authority",
            iam_already_applied_upstream=f["front_effective_irradiance_resolved"],
            shading_already_applied_upstream=f["front_effective_irradiance_resolved"],
            bifacial_response_already_applied_upstream=b["bifacial_electrical_equivalent_resolved"],
            spectral_response_already_applied_upstream=s["spectral_electrical_equivalent_resolved"],
        )
        resolved = (
            front_ok
            and bool(s["spectral_electrical_equivalent_resolved"])
            and (not bifacial or rear_ok)
        )
        row["canonical_irradiance_boundary_resolved"] = resolved
        row["canonical_irradiance_boundary_state"] = (
            "resolved_canonical_irradiance_boundary"
            if resolved
            else "unresolved_rear_incident"
            if bifacial and not rear_ok
            else "unresolved_module_electrical_irradiance"
            if not s["spectral_electrical_equivalent_resolved"]
            else "unresolved_front_incident"
        )
        records.append(row)
    expected = pd.DataFrame(records, index=index.copy(), columns=_COLUMNS)
    for name in _FLOAT + _BOOL + _TEXT:
        expected[name] = expected[name].astype(
            float if name in _FLOAT else bool if name in _BOOL else object
        )
    for name in _TIME:
        expected[name] = pd.Series(
            pd.DatetimeIndex(expected[name], tz=index.levels[0].tz), index=index
        )
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except (AssertionError, TypeError, ValueError) as exc:
        raise ValueError("irradiance boundary failed independent replay") from exc
    counts = Counter(r["canonical_irradiance_boundary_state"] for r in records)
    resolved_count = sum(r["canonical_irradiance_boundary_resolved"] for r in records)
    diagnostics = IrradianceBoundaryDiagnostics(
        len(receivers),
        len(weather_time_state.states),
        len(records),
        resolved_count,
        len(records) - resolved_count,
        sum(r["measured_front_poa_present"] for r in records),
        sum(r["rear_incident_state"] == "not_applicable_monofacial" for r in records),
        sum(r["rear_incident_state"] == "unresolved_rear_incident" for r in records),
        sum(r["module_electrical_irradiance_resolved"] for r in records),
        0,
        MappingProxyType(dict(sorted(counts.items()))),
    )
    if result.diagnostics != diagnostics:
        raise ValueError("irradiance boundary diagnostics failed independent replay")
