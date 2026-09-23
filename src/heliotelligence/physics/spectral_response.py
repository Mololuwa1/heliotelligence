"""Component-resolved spectral response before module electrical conversion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]
from pvlib.atmosphere import (  # type: ignore[import-untyped]
    get_absolute_airmass,
    get_relative_airmass,
)
from pvlib.spectrum import spectral_factor_firstsolar  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.bifacial_equivalent_irradiance import (
    BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID,
    BIFACIAL_EQUIVALENT_IRRADIANCE_COVERAGE_SCOPE,
    BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID,
    BIFACIAL_EQUIVALENT_IRRADIANCE_SCOPE,
    BifacialEquivalentIrradianceResult,
)
from heliotelligence.physics.bifacial_response import (
    BIFACIAL_RESPONSE_COEFFICIENT_KIND,
    BIFACIAL_RESPONSE_CONTRACT_ID,
    BIFACIAL_RESPONSE_MODEL_ID,
    BIFACIAL_RESPONSE_SCOPE,
    BIFACIAL_RESPONSE_STANDARD_BASIS,
)

SPECTRAL_RESPONSE_CONTRACT_ID = "component_resolved_spectral_electrical_equivalent_irradiance_v1"
SPECTRAL_RESPONSE_MODEL_ID = "front_firstsolar_explicit_rear_then_phi_isc_v1"
FIRST_SOLAR_MODEL_ID = "pvlib_spectral_factor_firstsolar_v1"
AIRMASS_MODEL_ID = "kastenyoung1989_pressure_adjusted_v1"
SPECTRAL_RESPONSE_COVERAGE_SCOPE = "fixed_table_front_rear_receiver_resolved"
SPECTRAL_RESPONSE_SCOPE = "spectral_mismatch_before_module_iv"

FIRST_SOLAR_MIN_PW_CM = 0.1
FIRST_SOLAR_MAX_PW_CM = 8.0
FIRST_SOLAR_MIN_ABSOLUTE_AIRMASS = 0.58
FIRST_SOLAR_MAX_ABSOLUTE_AIRMASS = 10.0
FIRST_SOLAR_FIT_MIN_PW_CM = 0.5
FIRST_SOLAR_FIT_MAX_PW_CM = 5.0
FIRST_SOLAR_FIT_MIN_ABSOLUTE_AIRMASS = 1.0
FIRST_SOLAR_FIT_MAX_ABSOLUTE_AIRMASS = 5.0

SpectralActivationState = Literal["enabled", "disabled", "unknown"]
FirstSolarCoefficientMode = Literal["module_type", "explicit_coefficients"]
FirstSolarModuleType = Literal["cdte", "monosi", "xsi", "multisi", "polysi", "cigs", "asi"]
RearSpectralTreatment = Literal["disabled", "explicit_factor", "unknown"]

_ACTIVATION_STATES = {"enabled", "disabled", "unknown"}
_COEFFICIENT_MODES = {"module_type", "explicit_coefficients"}
_MODULE_TYPES = {"cdte", "monosi", "xsi", "multisi", "polysi", "cigs", "asi"}
_REAR_TREATMENTS = {"disabled", "explicit_factor", "unknown"}
_ATOL = 1e-9
_RTOL = 1e-12


@dataclass(frozen=True)
class FrontSpectralCorrectionAdmission:
    activation_state: SpectralActivationState
    activation_source_label: str
    activation_source_reference: str | None = None
    coefficient_mode: FirstSolarCoefficientMode | None = None
    module_type: FirstSolarModuleType | None = None
    coefficients: tuple[float, ...] | None = None
    coefficient_source_label: str | None = None
    coefficient_source_reference: str | None = None

    def __post_init__(self) -> None:
        _validate_front_admission(self)


@dataclass(frozen=True)
class FirstSolarAtmosphere:
    apparent_solar_zenith_deg: pd.Series
    precipitable_water_cm: pd.Series
    pressure_pa: pd.Series
    solar_geometry_source_label: str
    solar_geometry_source_reference: str | None
    precipitable_water_source_label: str
    precipitable_water_source_reference: str | None
    pressure_source_label: str
    pressure_source_reference: str | None

    def __post_init__(self) -> None:
        _nonempty(self.solar_geometry_source_label, "solar_geometry_source_label")
        _optional_text(self.solar_geometry_source_reference, "solar_geometry_source_reference")
        _nonempty(self.precipitable_water_source_label, "precipitable_water_source_label")
        _optional_text(
            self.precipitable_water_source_reference, "precipitable_water_source_reference"
        )
        _nonempty(self.pressure_source_label, "pressure_source_label")
        _optional_text(self.pressure_source_reference, "pressure_source_reference")
        for value, label in (
            (self.apparent_solar_zenith_deg, "apparent_solar_zenith_deg"),
            (self.precipitable_water_cm, "precipitable_water_cm"),
            (self.pressure_pa, "pressure_pa"),
        ):
            if not isinstance(value, pd.Series):
                raise ValueError(f"{label} must be a pandas Series")


@dataclass(frozen=True)
class RearSpectralCorrectionAdmission:
    treatment: RearSpectralTreatment
    source_label: str
    source_reference: str | None = None
    model_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.treatment, str) or self.treatment not in _REAR_TREATMENTS:
            raise ValueError("rear spectral treatment is invalid")
        _nonempty(self.source_label, "source_label")
        _optional_text(self.source_reference, "source_reference")
        if self.treatment == "explicit_factor":
            _nonempty(self.model_id, "model_id")
        elif self.model_id is not None:
            raise ValueError("disabled or unknown rear treatment requires model_id=None")


@dataclass(frozen=True)
class SpectralResponseDiagnostics:
    receiver_count: int
    bifacial_receiver_count: int
    monofacial_receiver_count: int
    timestamp_count: int
    row_count: int
    front_enabled_receiver_count: int
    front_disabled_receiver_count: int
    front_unknown_receiver_count: int
    rear_disabled_receiver_count: int
    rear_explicit_receiver_count: int
    rear_unknown_receiver_count: int
    front_factor_resolved_row_count: int
    front_factor_unresolved_row_count: int
    rear_factor_resolved_row_count: int
    rear_factor_unresolved_row_count: int
    rear_factor_not_applicable_row_count: int
    spectral_total_resolved_row_count: int
    spectral_total_unresolved_row_count: int
    spectral_response_model: str


@dataclass(frozen=True)
class SpectralResponseResult:
    irradiance: pd.DataFrame
    diagnostics: SpectralResponseDiagnostics


_UPSTREAM_COLUMNS = (
    "surface_tilt_deg",
    "surface_azimuth_deg",
    "poa_front_effective_optical_wm2",
    "poa_rear_effective_optical_wm2",
    "bifacial_enabled",
    "isc_bifaciality_factor",
    "bifaciality_coefficient_kind",
    "resolution_method",
    "source_label",
    "source_reference",
    "is_fallback",
    "rear_electrical_equivalent_irradiance_wm2",
    "rear_electrical_equivalent_resolved",
    "rear_electrical_equivalent_state",
    "bifacial_electrical_equivalent_irradiance_wm2",
    "bifacial_electrical_equivalent_resolved",
    "bifacial_electrical_equivalent_state",
    "bifacial_response_contract",
    "bifacial_response_model",
    "bifacial_response_standard_basis",
    "bifacial_response_scope",
    "bifacial_equivalent_irradiance_contract",
    "bifacial_equivalent_irradiance_model",
    "bifacial_equivalent_irradiance_coverage_scope",
    "bifacial_equivalent_irradiance_scope",
)
_OUTPUT_COLUMNS = (
    "surface_tilt_deg",
    "surface_azimuth_deg",
    "poa_front_effective_optical_wm2",
    "poa_rear_effective_optical_wm2",
    "bifacial_enabled",
    "isc_bifaciality_factor",
    "rear_electrical_equivalent_irradiance_wm2",
    "bifacial_electrical_equivalent_irradiance_wm2",
    "apparent_solar_zenith_deg",
    "precipitable_water_input_cm",
    "precipitable_water_model_cm",
    "pressure_pa",
    "relative_airmass",
    "absolute_airmass_input",
    "absolute_airmass_model",
    "firstsolar_input_adjustment_state",
    "firstsolar_fit_domain_state",
    "airmass_model",
    "front_spectral_activation_state",
    "front_spectral_coefficient_mode",
    "front_spectral_module_type",
    "front_spectral_coefficient_c1",
    "front_spectral_coefficient_c2",
    "front_spectral_coefficient_c3",
    "front_spectral_coefficient_c4",
    "front_spectral_coefficient_c5",
    "front_spectral_coefficient_c6",
    "front_spectral_mismatch_factor",
    "front_spectral_factor_resolved",
    "front_spectral_factor_state",
    "front_spectral_electrical_equivalent_irradiance_wm2",
    "front_spectral_electrical_equivalent_resolved",
    "front_spectral_electrical_equivalent_state",
    "front_spectral_activation_source_label",
    "front_spectral_activation_source_reference",
    "front_spectral_coefficient_source_label",
    "front_spectral_coefficient_source_reference",
    "rear_spectral_treatment",
    "rear_spectral_mismatch_factor",
    "rear_spectral_factor_resolved",
    "rear_spectral_factor_state",
    "poa_rear_spectral_effective_irradiance_wm2",
    "rear_spectral_effective_resolved",
    "rear_spectral_effective_state",
    "rear_spectral_electrical_equivalent_irradiance_wm2",
    "rear_spectral_electrical_equivalent_resolved",
    "rear_spectral_electrical_equivalent_state",
    "rear_spectral_source_label",
    "rear_spectral_source_reference",
    "rear_spectral_model_id",
    "spectral_electrical_equivalent_irradiance_wm2",
    "spectral_electrical_equivalent_resolved",
    "spectral_electrical_equivalent_state",
    "solar_geometry_source_label",
    "solar_geometry_source_reference",
    "precipitable_water_source_label",
    "precipitable_water_source_reference",
    "pressure_source_label",
    "pressure_source_reference",
    "pvlib_version",
    "firstsolar_model",
    "spectral_response_contract",
    "spectral_response_model",
    "spectral_response_coverage_scope",
    "spectral_response_scope",
)


def calculate_spectral_electrical_equivalent_irradiance(
    receivers: Sequence[PVReceiver],
    bifacial_equivalent_irradiance: BifacialEquivalentIrradianceResult,
    *,
    front_spectral_admission_by_receiver: Mapping[str, FrontSpectralCorrectionAdmission],
    rear_spectral_admission_by_receiver: Mapping[str, RearSpectralCorrectionAdmission],
    atmosphere: FirstSolarAtmosphere | None,
    explicit_rear_spectral_factor: pd.Series | None,
) -> SpectralResponseResult:
    """Apply separate front/rear spectral response, then rear phi_Isc equivalence."""
    receiver_ids = _receivers(receivers)
    front_admissions = _front_admissions(front_spectral_admission_by_receiver, receiver_ids)
    upstream = _upstream(bifacial_equivalent_irradiance, receiver_ids)
    bifacial_ids = (
        tuple(
            receiver_id
            for receiver_id in receiver_ids
            if bool(upstream.xs(receiver_id, level="receiver_id")["bifacial_enabled"].iloc[0])
        )
        if len(upstream)
        else tuple(sorted(rear_spectral_admission_by_receiver))
    )
    if len(bifacial_ids) != bifacial_equivalent_irradiance.diagnostics.bifacial_receiver_count:
        raise ValueError("empty S7D-1 bifacial identity conflicts with rear admissions")
    rear_admissions = _rear_admissions(rear_spectral_admission_by_receiver, bifacial_ids)
    timestamps = pd.DatetimeIndex(upstream.index.get_level_values(0).unique())
    atmosphere_frame = _atmosphere(
        atmosphere,
        timestamps,
        any(item.activation_state == "enabled" for item in front_admissions.values()),
    )
    explicit_ids = tuple(
        receiver_id
        for receiver_id in bifacial_ids
        if rear_admissions[receiver_id].treatment == "explicit_factor"
    )
    rear_factors = _rear_factors(explicit_rear_spectral_factor, timestamps, explicit_ids)

    rows: list[dict[str, object]] = []
    for key, source in upstream.iterrows():
        timestamp, receiver_id = key
        atmosphere_row = atmosphere_frame.loc[timestamp] if atmosphere_frame is not None else None
        rows.append(
            _compose_row(
                source,
                front_admissions[str(receiver_id)],
                rear_admissions.get(str(receiver_id)),
                atmosphere,
                atmosphere_row,
                rear_factors,
                key,
            )
        )
    output = _typed(pd.DataFrame(rows, index=upstream.index, columns=_OUTPUT_COLUMNS))
    if tuple(output.columns) != _OUTPUT_COLUMNS:
        raise RuntimeError("spectral response output schema changed unexpectedly")
    front_factor_resolved = (
        int(output["front_spectral_factor_resolved"].sum()) if len(output) else 0
    )
    rear_factor_resolved = int(output["rear_spectral_factor_resolved"].sum()) if len(output) else 0
    rear_not_applicable = (
        int((output["rear_spectral_factor_state"] == "not_applicable_monofacial").sum())
        if len(output)
        else 0
    )
    total_resolved = (
        int(output["spectral_electrical_equivalent_resolved"].sum()) if len(output) else 0
    )
    diagnostics = SpectralResponseDiagnostics(
        receiver_count=len(receiver_ids),
        bifacial_receiver_count=len(bifacial_ids),
        monofacial_receiver_count=len(receiver_ids) - len(bifacial_ids),
        timestamp_count=len(timestamps),
        row_count=len(output),
        front_enabled_receiver_count=sum(
            item.activation_state == "enabled" for item in front_admissions.values()
        ),
        front_disabled_receiver_count=sum(
            item.activation_state == "disabled" for item in front_admissions.values()
        ),
        front_unknown_receiver_count=sum(
            item.activation_state == "unknown" for item in front_admissions.values()
        ),
        rear_disabled_receiver_count=sum(
            item.treatment == "disabled" for item in rear_admissions.values()
        ),
        rear_explicit_receiver_count=len(explicit_ids),
        rear_unknown_receiver_count=sum(
            item.treatment == "unknown" for item in rear_admissions.values()
        ),
        front_factor_resolved_row_count=front_factor_resolved,
        front_factor_unresolved_row_count=len(output) - front_factor_resolved,
        rear_factor_resolved_row_count=rear_factor_resolved,
        rear_factor_unresolved_row_count=len(output) - rear_factor_resolved - rear_not_applicable,
        rear_factor_not_applicable_row_count=rear_not_applicable,
        spectral_total_resolved_row_count=total_resolved,
        spectral_total_unresolved_row_count=len(output) - total_resolved,
        spectral_response_model=SPECTRAL_RESPONSE_MODEL_ID,
    )
    return SpectralResponseResult(output, diagnostics)


def _validate_front_admission(value: FrontSpectralCorrectionAdmission) -> None:
    if (
        not isinstance(value.activation_state, str)
        or value.activation_state not in _ACTIVATION_STATES
    ):
        raise ValueError("front spectral activation state is invalid")
    _nonempty(value.activation_source_label, "activation_source_label")
    _optional_text(value.activation_source_reference, "activation_source_reference")
    if value.activation_state != "enabled":
        if any(
            item is not None
            for item in (
                value.coefficient_mode,
                value.module_type,
                value.coefficients,
                value.coefficient_source_label,
                value.coefficient_source_reference,
            )
        ):
            raise ValueError("disabled or unknown front admission cannot carry coefficients")
        return
    if value.coefficient_mode not in _COEFFICIENT_MODES:
        raise ValueError("enabled front admission requires a valid coefficient mode")
    _nonempty(value.coefficient_source_label, "coefficient_source_label")
    _optional_text(value.coefficient_source_reference, "coefficient_source_reference")
    if value.coefficient_mode == "module_type":
        if value.module_type not in _MODULE_TYPES or value.coefficients is not None:
            raise ValueError("module_type mode requires one canonical module type only")
    elif value.module_type is not None or not isinstance(value.coefficients, tuple):
        raise ValueError("explicit_coefficients mode requires a coefficient tuple only")
    else:
        if len(value.coefficients) != 6:
            raise ValueError("First Solar coefficients must contain exactly six values")
        for item in value.coefficients:
            _finite_real(item, "First Solar coefficient")


def _receivers(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ValueError("receivers must be a non-empty sequence")
    if any(not isinstance(item, PVReceiver) for item in value):
        raise ValueError("receivers must contain PVReceiver values")
    ids = tuple(item.id for item in value)
    if len(ids) != len(set(ids)):
        raise ValueError("receiver IDs must be unique")
    for item in value:
        if item.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError("S6C runtime tracker pose is required before spectral response")
        if item.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("spectral response supports FIXED_TABLE receivers only")
    return tuple(sorted(ids))


def _front_admissions(
    value: object, receiver_ids: tuple[str, ...]
) -> dict[str, FrontSpectralCorrectionAdmission]:
    if not isinstance(value, Mapping) or set(value) != set(receiver_ids):
        raise ValueError("front spectral admission keys must exactly match receivers")
    if any(not isinstance(item, FrontSpectralCorrectionAdmission) for item in value.values()):
        raise ValueError("front spectral admissions must use the canonical admission type")
    return {receiver_id: value[receiver_id] for receiver_id in receiver_ids}


def _rear_admissions(
    value: object, receiver_ids: tuple[str, ...]
) -> dict[str, RearSpectralCorrectionAdmission]:
    if not isinstance(value, Mapping) or set(value) != set(receiver_ids):
        raise ValueError("rear spectral admission keys must exactly match bifacial receivers")
    if any(not isinstance(item, RearSpectralCorrectionAdmission) for item in value.values()):
        raise ValueError("rear spectral admissions must use the canonical admission type")
    return {receiver_id: value[receiver_id] for receiver_id in receiver_ids}


def _upstream(value: object, receiver_ids: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(value, BifacialEquivalentIrradianceResult):
        raise ValueError(
            "bifacial_equivalent_irradiance must be BifacialEquivalentIrradianceResult"
        )
    frame = value.irradiance
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("S7D-1 irradiance must use a timestamp/receiver MultiIndex")
    if frame.index.nlevels != 2 or frame.index.names[1] != "receiver_id":
        raise ValueError("S7D-1 index must be timestamp/receiver_id")
    if not set(_UPSTREAM_COLUMNS).issubset(frame.columns):
        raise ValueError("S7D-1 irradiance is missing required columns")
    times = frame.index.get_level_values(0)
    if not isinstance(times, pd.DatetimeIndex) or times.tz is None:
        raise ValueError("S7D-1 timestamps must be timezone-aware")
    if times.hasnans or frame.index.has_duplicates:
        raise ValueError("S7D-1 index contains NaT or duplicate rows")
    unique_times = pd.DatetimeIndex(times.unique()).sort_values()
    expected = pd.MultiIndex.from_product((unique_times, receiver_ids), names=frame.index.names)
    if len(frame) != len(expected) or set(frame.index) != set(expected):
        raise ValueError("S7D-1 must contain a complete timestamp/receiver grid")
    canonical = frame.reindex(expected).copy()
    _replay_diagnostics(value, canonical, receiver_ids, unique_times)
    _constant(
        canonical,
        "bifacial_equivalent_irradiance_contract",
        BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID,
    )
    _constant(
        canonical, "bifacial_equivalent_irradiance_model", BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID
    )
    _constant(
        canonical,
        "bifacial_equivalent_irradiance_coverage_scope",
        BIFACIAL_EQUIVALENT_IRRADIANCE_COVERAGE_SCOPE,
    )
    _constant(
        canonical, "bifacial_equivalent_irradiance_scope", BIFACIAL_EQUIVALENT_IRRADIANCE_SCOPE
    )
    _constant(canonical, "bifacial_response_contract", BIFACIAL_RESPONSE_CONTRACT_ID)
    _constant(canonical, "bifacial_response_model", BIFACIAL_RESPONSE_MODEL_ID)
    _constant(canonical, "bifacial_response_standard_basis", BIFACIAL_RESPONSE_STANDARD_BASIS)
    _constant(canonical, "bifacial_response_scope", BIFACIAL_RESPONSE_SCOPE)
    _constant(canonical, "bifaciality_coefficient_kind", BIFACIAL_RESPONSE_COEFFICIENT_KIND)
    for _, row in canonical.iterrows():
        _replay_row(row)
    return canonical


def _replay_diagnostics(
    value: BifacialEquivalentIrradianceResult,
    frame: pd.DataFrame,
    receiver_ids: tuple[str, ...],
    timestamps: pd.DatetimeIndex,
) -> None:
    diagnostics = value.diagnostics
    if len(frame):
        bifacial_by_receiver = frame.groupby(level="receiver_id")["bifacial_enabled"].first()
        for receiver_id in receiver_ids:
            rows = frame.xs(receiver_id, level="receiver_id")
            flags = [_strict_bool(item, "bifacial_enabled") for item in rows["bifacial_enabled"]]
            if len(set(flags)) != 1:
                raise ValueError("S7D-1 bifacial identity changes across timestamps")
        bifacial_count = int(
            sum(_strict_bool(item, "bifacial_enabled") for item in bifacial_by_receiver)
        )
    else:
        bifacial_count = diagnostics.bifacial_receiver_count
    resolved_count = int(
        sum(
            _strict_bool(item, "S7D total resolved")
            for item in frame["bifacial_electrical_equivalent_resolved"]
        )
    )
    expected = (
        len(receiver_ids),
        bifacial_count,
        len(receiver_ids) - bifacial_count,
        len(timestamps),
        len(frame),
        resolved_count,
        len(frame) - resolved_count,
        BIFACIAL_EQUIVALENT_IRRADIANCE_MODEL_ID,
    )
    actual = (
        diagnostics.receiver_count,
        diagnostics.bifacial_receiver_count,
        diagnostics.monofacial_receiver_count,
        diagnostics.timestamp_count,
        diagnostics.row_count,
        diagnostics.resolved_row_count,
        diagnostics.unresolved_row_count,
        diagnostics.bifacial_equivalent_irradiance_model,
    )
    if actual != expected:
        raise ValueError("S7D-1 diagnostics do not replay the admitted grid")


def _replay_row(row: pd.Series) -> None:
    bifacial = _strict_bool(row["bifacial_enabled"], "bifacial_enabled")
    phi = _finite_nonnegative(row["isc_bifaciality_factor"], "isc_bifaciality_factor")
    front = _optional_nonnegative(row["poa_front_effective_optical_wm2"], "front effective")
    rear = _optional_nonnegative(row["poa_rear_effective_optical_wm2"], "rear effective")
    rear_resolved = _strict_bool(
        row["rear_electrical_equivalent_resolved"], "rear equivalent resolved"
    )
    total_resolved = _strict_bool(
        row["bifacial_electrical_equivalent_resolved"], "S7D total resolved"
    )
    if not bifacial:
        if phi != 0.0 or rear is not None:
            raise ValueError("monofacial S7D-1 row carries rear optical response")
        if (
            not rear_resolved
            or row["rear_electrical_equivalent_state"] != "resolved_monofacial_zero"
            or not _close(row["rear_electrical_equivalent_irradiance_wm2"], 0.0)
        ):
            raise ValueError("monofacial S7D-1 rear closure failed")
    else:
        if phi <= 0.0 or phi > 1.0:
            raise ValueError("bifacial S7D-1 phi_Isc must satisfy 0 < factor <= 1")
    if bifacial:
        if rear_resolved:
            if rear is None or not _close(
                row["rear_electrical_equivalent_irradiance_wm2"], phi * rear
            ):
                raise ValueError("bifacial S7D-1 rear phi_Isc closure failed")
            if row["rear_electrical_equivalent_state"] != "resolved":
                raise ValueError("resolved bifacial S7D-1 rear state is invalid")
        elif not pd.isna(row["rear_electrical_equivalent_irradiance_wm2"]):
            raise ValueError("unresolved S7D-1 rear equivalent must be NaN")
        elif row["rear_electrical_equivalent_state"] != ("unresolved_rear_effective_irradiance"):
            raise ValueError("unresolved bifacial S7D-1 rear state is invalid")
    if total_resolved:
        if front is None or not rear_resolved:
            raise ValueError("resolved S7D-1 total has unresolved components")
        expected_total = front + float(row["rear_electrical_equivalent_irradiance_wm2"])
        if not _close(row["bifacial_electrical_equivalent_irradiance_wm2"], expected_total):
            raise ValueError("S7D-1 total closure failed")
        if row["bifacial_electrical_equivalent_state"] != "resolved":
            raise ValueError("resolved S7D-1 total state is invalid")
    elif not pd.isna(row["bifacial_electrical_equivalent_irradiance_wm2"]):
        raise ValueError("unresolved S7D-1 total must be NaN")
    else:
        expected_state = (
            "unresolved_front_and_rear_effective_irradiance"
            if front is None and not rear_resolved
            else "unresolved_front_effective_irradiance"
            if front is None
            else "unresolved_rear_effective_irradiance"
        )
        if row["bifacial_electrical_equivalent_state"] != expected_state:
            raise ValueError("unresolved S7D-1 total state is invalid")


def _atmosphere(value: object, timestamps: pd.DatetimeIndex, required: bool) -> pd.DataFrame | None:
    if value is None:
        if required:
            raise ValueError("enabled front spectral correction requires atmosphere")
        return None
    if not isinstance(value, FirstSolarAtmosphere):
        raise ValueError("atmosphere must be FirstSolarAtmosphere or None")
    series = (
        value.apparent_solar_zenith_deg,
        value.precipitable_water_cm,
        value.pressure_pa,
    )
    for item in series:
        index = item.index
        if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
            raise ValueError("atmosphere requires timezone-aware DatetimeIndex values")
        if index.hasnans or index.has_duplicates:
            raise ValueError("atmosphere indexes contain NaT or duplicates")
        if (
            not index.equals(timestamps)
            or str(index.tz) != str(timestamps.tz)
            or index.name != timestamps.name
        ):
            raise ValueError("atmosphere index must exactly match canonical timestamps")
    zenith = [_bounded_real(item, "apparent solar zenith", 0.0, 180.0) for item in series[0]]
    pw = [_optional_nonnegative(item, "precipitable water") for item in series[1]]
    pressure = [_optional_positive(item, "pressure") for item in series[2]]
    return pd.DataFrame(
        {
            "zenith": zenith,
            "pw": [np.nan if item is None else item for item in pw],
            "pressure": [np.nan if item is None else item for item in pressure],
        },
        index=timestamps,
    )


def _rear_factors(
    value: object, timestamps: pd.DatetimeIndex, receiver_ids: tuple[str, ...]
) -> pd.Series | None:
    if not receiver_ids:
        if value is not None:
            raise ValueError("explicit rear factor must be None when no receiver uses it")
        return None
    if not isinstance(value, pd.Series) or not isinstance(value.index, pd.MultiIndex):
        raise ValueError("explicit rear spectral factor must be a MultiIndex Series")
    if value.index.nlevels != 2 or value.index.names != [timestamps.name, "receiver_id"]:
        raise ValueError("explicit rear factor index must be timestamp/receiver_id")
    time_level = value.index.get_level_values(0)
    if not isinstance(time_level, pd.DatetimeIndex) or time_level.tz is None:
        raise ValueError("explicit rear factor timestamps must be timezone-aware")
    if time_level.hasnans or value.index.has_duplicates or str(time_level.tz) != str(timestamps.tz):
        raise ValueError("explicit rear factor index is invalid")
    expected = pd.MultiIndex.from_product((timestamps, receiver_ids), names=value.index.names)
    if len(value) != len(expected) or set(value.index) != set(expected):
        raise ValueError("explicit rear factor must contain the exact configured grid")
    result = value.reindex(expected).copy()
    for item in result:
        if pd.isna(item):
            continue
        _positive(item, "explicit rear spectral factor")
    return result


def _compose_row(
    source: pd.Series,
    front_admission: FrontSpectralCorrectionAdmission,
    rear_admission: RearSpectralCorrectionAdmission | None,
    atmosphere: FirstSolarAtmosphere | None,
    atmosphere_row: pd.Series | None,
    explicit_factors: pd.Series | None,
    key: tuple[object, object],
) -> dict[str, object]:
    front_factor = _front_factor(front_admission, atmosphere_row)
    front_input = _optional_nonnegative(
        source["poa_front_effective_optical_wm2"], "front effective"
    )
    front_value, front_resolved, front_state = _contribution(
        front_input,
        front_factor[0],
        front_factor[1],
        zero_state="resolved_zero_front_effective_irradiance",
        unresolved_state="unresolved_front_spectral_factor",
        resolved_state="resolved",
        upstream_state="unresolved_front_effective_irradiance",
    )
    bifacial = _strict_bool(source["bifacial_enabled"], "bifacial_enabled")
    rear_factor, rear_factor_resolved, rear_factor_state = _rear_factor(
        bifacial, rear_admission, explicit_factors, key
    )
    rear_input = _optional_nonnegative(source["poa_rear_effective_optical_wm2"], "rear effective")
    if not bifacial:
        rear_spectral, rear_spectral_resolved, rear_spectral_state = (
            0.0,
            True,
            "resolved_monofacial_zero",
        )
        rear_eq, rear_eq_resolved, rear_eq_state = 0.0, True, "resolved_monofacial_zero"
    else:
        rear_spectral, rear_spectral_resolved, rear_spectral_state = _contribution(
            rear_input,
            rear_factor,
            rear_factor_resolved,
            zero_state="resolved_zero_rear_effective_irradiance",
            unresolved_state="unresolved_rear_spectral_factor",
            resolved_state="resolved",
            upstream_state="unresolved_rear_effective_irradiance",
        )
        if rear_spectral_resolved:
            phi = _positive(source["isc_bifaciality_factor"], "isc_bifaciality_factor")
            rear_eq, rear_eq_resolved, rear_eq_state = (
                phi * rear_spectral,
                True,
                rear_spectral_state,
            )
        else:
            rear_eq, rear_eq_resolved, rear_eq_state = np.nan, False, rear_spectral_state
    total_resolved = front_resolved and rear_eq_resolved
    total = front_value + rear_eq if total_resolved else np.nan
    total_state = (
        "resolved"
        if total_resolved
        else "unresolved_front_and_rear_spectral_response"
        if not front_resolved and not rear_eq_resolved
        else "unresolved_front_spectral_response"
        if not front_resolved
        else "unresolved_rear_spectral_response"
    )
    coefficients = front_admission.coefficients or (np.nan,) * 6
    atmosphere_values = _atmosphere_values(atmosphere, atmosphere_row, front_factor)
    return {
        "surface_tilt_deg": source["surface_tilt_deg"],
        "surface_azimuth_deg": source["surface_azimuth_deg"],
        "poa_front_effective_optical_wm2": source["poa_front_effective_optical_wm2"],
        "poa_rear_effective_optical_wm2": source["poa_rear_effective_optical_wm2"],
        "bifacial_enabled": bifacial,
        "isc_bifaciality_factor": source["isc_bifaciality_factor"],
        "rear_electrical_equivalent_irradiance_wm2": source[
            "rear_electrical_equivalent_irradiance_wm2"
        ],
        "bifacial_electrical_equivalent_irradiance_wm2": source[
            "bifacial_electrical_equivalent_irradiance_wm2"
        ],
        **atmosphere_values,
        "front_spectral_activation_state": front_admission.activation_state,
        "front_spectral_coefficient_mode": front_admission.coefficient_mode,
        "front_spectral_module_type": front_admission.module_type,
        **{
            f"front_spectral_coefficient_c{index + 1}": value
            for index, value in enumerate(coefficients)
        },
        "front_spectral_mismatch_factor": front_factor[0],
        "front_spectral_factor_resolved": front_factor[1],
        "front_spectral_factor_state": front_factor[2],
        "front_spectral_electrical_equivalent_irradiance_wm2": front_value,
        "front_spectral_electrical_equivalent_resolved": front_resolved,
        "front_spectral_electrical_equivalent_state": front_state,
        "front_spectral_activation_source_label": front_admission.activation_source_label,
        "front_spectral_activation_source_reference": front_admission.activation_source_reference,
        "front_spectral_coefficient_source_label": front_admission.coefficient_source_label,
        "front_spectral_coefficient_source_reference": front_admission.coefficient_source_reference,
        "rear_spectral_treatment": rear_admission.treatment
        if rear_admission
        else "not_applicable_monofacial",
        "rear_spectral_mismatch_factor": rear_factor,
        "rear_spectral_factor_resolved": rear_factor_resolved,
        "rear_spectral_factor_state": rear_factor_state,
        "poa_rear_spectral_effective_irradiance_wm2": rear_spectral,
        "rear_spectral_effective_resolved": rear_spectral_resolved,
        "rear_spectral_effective_state": rear_spectral_state,
        "rear_spectral_electrical_equivalent_irradiance_wm2": rear_eq,
        "rear_spectral_electrical_equivalent_resolved": rear_eq_resolved,
        "rear_spectral_electrical_equivalent_state": rear_eq_state,
        "rear_spectral_source_label": rear_admission.source_label if rear_admission else pd.NA,
        "rear_spectral_source_reference": rear_admission.source_reference
        if rear_admission
        else pd.NA,
        "rear_spectral_model_id": rear_admission.model_id if rear_admission else pd.NA,
        "spectral_electrical_equivalent_irradiance_wm2": total,
        "spectral_electrical_equivalent_resolved": total_resolved,
        "spectral_electrical_equivalent_state": total_state,
        "solar_geometry_source_label": atmosphere.solar_geometry_source_label
        if atmosphere
        else pd.NA,
        "solar_geometry_source_reference": atmosphere.solar_geometry_source_reference
        if atmosphere
        else pd.NA,
        "precipitable_water_source_label": atmosphere.precipitable_water_source_label
        if atmosphere
        else pd.NA,
        "precipitable_water_source_reference": atmosphere.precipitable_water_source_reference
        if atmosphere
        else pd.NA,
        "pressure_source_label": atmosphere.pressure_source_label if atmosphere else pd.NA,
        "pressure_source_reference": atmosphere.pressure_source_reference if atmosphere else pd.NA,
        "pvlib_version": pvlib.__version__,
        "firstsolar_model": FIRST_SOLAR_MODEL_ID,
        "spectral_response_contract": SPECTRAL_RESPONSE_CONTRACT_ID,
        "spectral_response_model": SPECTRAL_RESPONSE_MODEL_ID,
        "spectral_response_coverage_scope": SPECTRAL_RESPONSE_COVERAGE_SCOPE,
        "spectral_response_scope": SPECTRAL_RESPONSE_SCOPE,
    }


def _front_factor(
    admission: FrontSpectralCorrectionAdmission, atmosphere: pd.Series | None
) -> tuple[float, bool, str, float, float, float, str, str]:
    if admission.activation_state == "disabled":
        return (
            1.0,
            True,
            "resolved_spectral_correction_disabled",
            np.nan,
            np.nan,
            np.nan,
            "none",
            "not_applicable",
        )
    if admission.activation_state == "unknown":
        return (
            np.nan,
            False,
            "unresolved_spectral_activation_unknown",
            np.nan,
            np.nan,
            np.nan,
            "none",
            "not_applicable",
        )
    assert atmosphere is not None
    zenith, pw, pressure = float(atmosphere["zenith"]), atmosphere["pw"], atmosphere["pressure"]
    if zenith >= 90.0:
        return (
            np.nan,
            False,
            "not_applicable_no_above_horizon_sun",
            np.nan,
            np.nan,
            np.nan,
            "not_applicable_no_above_horizon_sun",
            "not_applicable",
        )
    if pd.isna(pw) or pd.isna(pressure):
        return (
            np.nan,
            False,
            "unresolved_missing_atmospheric_input",
            np.nan,
            np.nan,
            np.nan,
            "unresolved_missing_atmospheric_input",
            "not_applicable",
        )
    pw_input = float(pw)
    if pw_input > FIRST_SOLAR_MAX_PW_CM:
        return (
            np.nan,
            False,
            "unresolved_firstsolar_precipitable_water_above_max",
            np.nan,
            np.nan,
            np.nan,
            "unresolved_precipitable_water_above_max",
            "not_applicable",
        )
    relative = float(get_relative_airmass(zenith, model="kastenyoung1989"))
    absolute_input = float(get_absolute_airmass(relative, float(pressure)))
    pw_model = max(pw_input, FIRST_SOLAR_MIN_PW_CM)
    absolute_model = min(
        max(absolute_input, FIRST_SOLAR_MIN_ABSOLUTE_AIRMASS), FIRST_SOLAR_MAX_ABSOLUTE_AIRMASS
    )
    pw_adjusted = pw_model != pw_input
    am_adjusted = absolute_model != absolute_input
    if pw_adjusted and am_adjusted:
        adjustment = "precipitable_water_and_airmass_adjusted"
    elif pw_adjusted:
        adjustment = "precipitable_water_min_clamped"
    elif absolute_input < FIRST_SOLAR_MIN_ABSOLUTE_AIRMASS:
        adjustment = "absolute_airmass_min_clamped"
    elif absolute_input > FIRST_SOLAR_MAX_ABSOLUTE_AIRMASS:
        adjustment = "absolute_airmass_max_clamped"
    else:
        adjustment = "none"
    kwargs: dict[str, object]
    if admission.coefficient_mode == "module_type":
        kwargs = {"module_type": admission.module_type}
    else:
        kwargs = {"coefficients": admission.coefficients}
    factor = float(
        np.asarray(
            spectral_factor_firstsolar(
                pw_model,
                absolute_model,
                min_precipitable_water=FIRST_SOLAR_MIN_PW_CM,
                max_precipitable_water=FIRST_SOLAR_MAX_PW_CM,
                **kwargs,
            )
        )[0]
    )
    if not np.isfinite(factor) or factor <= 0.0:
        raise RuntimeError("First Solar returned a non-positive or non-finite factor")
    fit = (
        "within_published_fit_domain"
        if FIRST_SOLAR_FIT_MIN_PW_CM <= pw_model <= FIRST_SOLAR_FIT_MAX_PW_CM
        and FIRST_SOLAR_FIT_MIN_ABSOLUTE_AIRMASS
        <= absolute_model
        <= FIRST_SOLAR_FIT_MAX_ABSOLUTE_AIRMASS
        else "outside_published_fit_domain"
    )
    return (
        factor,
        True,
        "resolved_firstsolar",
        relative,
        absolute_input,
        absolute_model,
        adjustment,
        fit,
    )


def _atmosphere_values(
    atmosphere: FirstSolarAtmosphere | None,
    row: pd.Series | None,
    factor: tuple[float, bool, str, float, float, float, str, str],
) -> dict[str, object]:
    if row is None:
        return {
            "apparent_solar_zenith_deg": np.nan,
            "precipitable_water_input_cm": np.nan,
            "precipitable_water_model_cm": np.nan,
            "pressure_pa": np.nan,
            "relative_airmass": np.nan,
            "absolute_airmass_input": np.nan,
            "absolute_airmass_model": np.nan,
            "firstsolar_input_adjustment_state": factor[6],
            "firstsolar_fit_domain_state": factor[7],
            "airmass_model": AIRMASS_MODEL_ID,
        }
    pw = float(row["pw"]) if not pd.isna(row["pw"]) else np.nan
    pw_model = (
        max(pw, FIRST_SOLAR_MIN_PW_CM)
        if factor[2] == "resolved_firstsolar" and np.isfinite(pw) and pw <= FIRST_SOLAR_MAX_PW_CM
        else np.nan
    )
    return {
        "apparent_solar_zenith_deg": row["zenith"],
        "precipitable_water_input_cm": row["pw"],
        "precipitable_water_model_cm": pw_model,
        "pressure_pa": row["pressure"],
        "relative_airmass": factor[3],
        "absolute_airmass_input": factor[4],
        "absolute_airmass_model": factor[5],
        "firstsolar_input_adjustment_state": factor[6],
        "firstsolar_fit_domain_state": factor[7],
        "airmass_model": AIRMASS_MODEL_ID,
    }


def _rear_factor(
    bifacial: bool,
    admission: RearSpectralCorrectionAdmission | None,
    factors: pd.Series | None,
    key: tuple[object, object],
) -> tuple[float, bool, str]:
    if not bifacial:
        return np.nan, False, "not_applicable_monofacial"
    assert admission is not None
    if admission.treatment == "disabled":
        return 1.0, True, "resolved_rear_spectral_correction_disabled"
    if admission.treatment == "unknown":
        return np.nan, False, "unresolved_rear_spectral_treatment_unknown"
    assert factors is not None
    value = factors.loc[key]
    if pd.isna(value):
        return np.nan, False, "unresolved_explicit_rear_spectral_factor"
    return float(value), True, "resolved_explicit_rear_spectral_factor"


def _contribution(
    input_value: float | None,
    factor: float,
    factor_resolved: bool,
    *,
    zero_state: str,
    unresolved_state: str,
    resolved_state: str,
    upstream_state: str,
) -> tuple[float, bool, str]:
    if input_value is None:
        return np.nan, False, upstream_state
    if input_value == 0.0:
        return 0.0, True, zero_state
    if not factor_resolved:
        return np.nan, False, unresolved_state
    return input_value * factor, True, resolved_state


def _constant(frame: pd.DataFrame, column: str, expected: str) -> None:
    if not frame[column].eq(expected).all():
        raise ValueError(f"S7D-1 {column} is not canonical")


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, label)


def _finite_real(value: object, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite non-Boolean real")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _finite_nonnegative(value: object, label: str) -> float:
    result = _finite_real(value, label)
    if result < 0.0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _positive(value: object, label: str) -> float:
    result = _finite_real(value, label)
    if result <= 0.0:
        raise ValueError(f"{label} must be strictly positive")
    return result


def _bounded_real(value: object, label: str, lower: float, upper: float) -> float:
    result = _finite_real(value, label)
    if not lower <= result <= upper:
        raise ValueError(f"{label} must be in [{lower}, {upper}]")
    return result


def _optional_nonnegative(value: object, label: str) -> float | None:
    if pd.isna(value):
        return None
    return _finite_nonnegative(value, label)


def _optional_positive(value: object, label: str) -> float | None:
    if pd.isna(value):
        return None
    return _positive(value, label)


def _strict_bool(value: object, label: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be Boolean")
    return bool(value)


def _close(actual: object, expected: float) -> bool:
    if isinstance(actual, (bool, np.bool_)) or not isinstance(actual, Real):
        return False
    return bool(np.isclose(float(actual), expected, rtol=_RTOL, atol=_ATOL))


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    bool_columns = [column for column in frame if column.endswith("_resolved")]
    bool_columns.append("bifacial_enabled")
    string_columns = [
        column
        for column in frame
        if column.endswith(
            (
                "_state",
                "_label",
                "_reference",
                "_mode",
                "_type",
                "_id",
                "_contract",
                "_scope",
            )
        )
        or column
        in (
            "pvlib_version",
            "airmass_model",
            "firstsolar_model",
            "spectral_response_model",
            "rear_spectral_treatment",
        )
    ]
    for column in bool_columns:
        frame[column] = frame[column].astype(bool)
    for column in string_columns:
        frame[column] = frame[column].astype("string")
    for column in set(frame.columns) - set(bool_columns) - set(string_columns):
        frame[column] = frame[column].astype(float)
    return frame
