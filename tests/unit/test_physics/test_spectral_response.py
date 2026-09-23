"""Tests for component-resolved S7E-0 spectral response."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]
import pytest
from numpy.typing import NDArray
from pvlib.atmosphere import (  # type: ignore[import-untyped]
    get_absolute_airmass,
    get_relative_airmass,
)
from pvlib.spectrum import spectral_factor_firstsolar  # type: ignore[import-untyped]

import heliotelligence.physics.spectral_response as spectral_response
from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.bifacial_equivalent_irradiance import (
    BifacialEquivalentIrradianceResult,
    calculate_bifacial_electrical_equivalent_irradiance,
)
from heliotelligence.physics.spectral_response import (
    _OUTPUT_COLUMNS,
    AIRMASS_MODEL_ID,
    FIRST_SOLAR_MAX_ABSOLUTE_AIRMASS,
    FIRST_SOLAR_MIN_PW_CM,
    FIRST_SOLAR_MODEL_ID,
    SPECTRAL_RESPONSE_CONTRACT_ID,
    SPECTRAL_RESPONSE_COVERAGE_SCOPE,
    SPECTRAL_RESPONSE_MODEL_ID,
    SPECTRAL_RESPONSE_SCOPE,
    FirstSolarAtmosphere,
    FrontSpectralCorrectionAdmission,
    RearSpectralCorrectionAdmission,
    SpectralResponseResult,
    calculate_spectral_electrical_equivalent_irradiance,
)

s7d_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_bifacial_equivalent_irradiance"
)


def _receivers(
    count: int = 1, *, kind: ReceiverKind = ReceiverKind.FIXED_TABLE
) -> list[PVReceiver]:
    result = cast(list[PVReceiver], s7d_support._receivers(count))
    if kind is ReceiverKind.FIXED_TABLE:
        return result
    return [replace(item, receiver_kind=kind) for item in result]


def _s7d(
    receivers: list[PVReceiver], *, bifacial: bool = True, periods: int = 2
) -> BifacialEquivalentIrradianceResult:
    ids = [item.id for item in receivers]
    return calculate_bifacial_electrical_equivalent_irradiance(
        receivers,
        s7d_support._front(ids, periods=periods),
        bifacial_response_parameters_by_receiver={
            receiver_id: s7d_support._response(0.8) if bifacial else s7d_support._mono()
            for receiver_id in ids
        },
        rear_effective_irradiance=(s7d_support._rear(ids, periods=periods) if bifacial else None),
    )


def _atmosphere(
    index: pd.DatetimeIndex, *, zenith: float = 40.0, pw: float = 2.0, pressure: float = 101325.0
) -> FirstSolarAtmosphere:
    return FirstSolarAtmosphere(
        apparent_solar_zenith_deg=pd.Series(zenith, index=index),
        precipitable_water_cm=pd.Series(pw, index=index),
        pressure_pa=pd.Series(pressure, index=index),
        solar_geometry_source_label="canonical solar position",
        solar_geometry_source_reference="solar-run-1",
        precipitable_water_source_label="measured PW",
        precipitable_water_source_reference="pw-run-1",
        pressure_source_label="measured pressure",
        pressure_source_reference="pressure-run-1",
    )


def _enabled(module_type: str = "monosi") -> FrontSpectralCorrectionAdmission:
    return FrontSpectralCorrectionAdmission(
        activation_state="enabled",
        activation_source_label="project evidence",
        activation_source_reference="spectral-page",
        coefficient_mode="module_type",
        module_type=module_type,  # type: ignore[arg-type]
        coefficient_source_label="explicit coefficient-set admission",
        coefficient_source_reference="module declaration",
    )


def _disabled() -> FrontSpectralCorrectionAdmission:
    return FrontSpectralCorrectionAdmission(
        activation_state="disabled", activation_source_label="project evidence"
    )


def _unknown() -> FrontSpectralCorrectionAdmission:
    return FrontSpectralCorrectionAdmission(
        activation_state="unknown", activation_source_label="missing project evidence"
    )


def _rear(treatment: str = "disabled") -> RearSpectralCorrectionAdmission:
    return RearSpectralCorrectionAdmission(
        treatment=treatment,  # type: ignore[arg-type]
        source_label="rear spectral declaration",
        source_reference="rear-study",
        model_id="rear-model-v1" if treatment == "explicit_factor" else None,
    )


def _calculate(
    receivers: list[PVReceiver],
    upstream: BifacialEquivalentIrradianceResult,
    *,
    front: dict[str, FrontSpectralCorrectionAdmission] | None = None,
    rear: dict[str, RearSpectralCorrectionAdmission] | None = None,
    atmosphere: FirstSolarAtmosphere | None = None,
    factors: pd.Series | None = None,
) -> SpectralResponseResult:
    ids = [item.id for item in receivers]
    if front is None:
        front = {receiver_id: _enabled() for receiver_id in ids}
    if rear is None:
        default_bifacial_ids = (
            ids
            if upstream.irradiance.empty
            and upstream.diagnostics.bifacial_receiver_count == len(ids)
            else []
        )
        rear = {
            receiver_id: _rear()
            for receiver_id in ids
            if receiver_id in default_bifacial_ids
            or bool(
                upstream.irradiance.xs(receiver_id, level="receiver_id")["bifacial_enabled"].iloc[0]
            )
        }
    if atmosphere is None and any(item.activation_state == "enabled" for item in front.values()):
        atmosphere = _atmosphere(
            pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
        )
    return calculate_spectral_electrical_equivalent_irradiance(
        receivers,
        upstream,
        front_spectral_admission_by_receiver=front,
        rear_spectral_admission_by_receiver=rear,
        atmosphere=atmosphere,
        explicit_rear_spectral_factor=factors,
    )


def _set_optical_values(
    result: BifacialEquivalentIrradianceResult, *, front: float, rear: float, phi: float = 0.8
) -> BifacialEquivalentIrradianceResult:
    frame = result.irradiance.copy(deep=True)
    frame.loc[:, "poa_front_effective_optical_wm2"] = front
    frame.loc[:, "poa_rear_effective_optical_wm2"] = rear
    frame.loc[:, "isc_bifaciality_factor"] = phi
    frame.loc[:, "rear_electrical_equivalent_irradiance_wm2"] = phi * rear
    frame.loc[:, "bifacial_electrical_equivalent_irradiance_wm2"] = front + phi * rear
    return replace(result, irradiance=frame)


@pytest.mark.parametrize("module_type", ["monosi", "polysi", "cdte", "cigs"])
def test_firstsolar_module_type_parity_and_provenance(module_type: str) -> None:
    receivers = _receivers()
    upstream = _s7d(receivers)
    index = pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
    atmosphere = _atmosphere(index, zenith=38.0, pw=1.7, pressure=95000.0)
    result = _calculate(
        receivers,
        upstream,
        front={"r0": _enabled(module_type)},
        atmosphere=atmosphere,
    )
    relative = float(get_relative_airmass(38.0, model="kastenyoung1989"))
    absolute = float(get_absolute_airmass(relative, 95000.0))
    expected = float(spectral_factor_firstsolar(1.7, absolute, module_type=module_type)[0])
    row = result.irradiance.iloc[0]
    assert row["relative_airmass"] == pytest.approx(relative)
    assert row["absolute_airmass_input"] == pytest.approx(absolute)
    assert row["front_spectral_mismatch_factor"] == pytest.approx(expected)
    assert row["pvlib_version"] == pvlib.__version__
    assert row["firstsolar_model"] == FIRST_SOLAR_MODEL_ID
    assert row["airmass_model"] == AIRMASS_MODEL_ID
    assert row["spectral_response_contract"] == SPECTRAL_RESPONSE_CONTRACT_ID
    assert row["spectral_response_model"] == SPECTRAL_RESPONSE_MODEL_ID
    assert row["spectral_response_coverage_scope"] == SPECTRAL_RESPONSE_COVERAGE_SCOPE
    assert row["spectral_response_scope"] == SPECTRAL_RESPONSE_SCOPE


def test_receiver_specific_module_types_and_custom_coefficients() -> None:
    receivers = _receivers(2)
    upstream = _s7d(receivers, periods=1)
    index = pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
    atmosphere = _atmosphere(index)
    front = {"r0": _enabled("monosi"), "r1": _enabled("cdte")}
    result = _calculate(receivers, upstream, front=front, atmosphere=atmosphere)
    factors = result.irradiance["front_spectral_mismatch_factor"]
    assert factors.loc[(index[0], "r0")] != pytest.approx(factors.loc[(index[0], "r1")])

    coefficients = (0.86, -0.02, -0.006, 0.12, 0.027, -0.0018)
    custom = FrontSpectralCorrectionAdmission(
        activation_state="enabled",
        activation_source_label="project",
        coefficient_mode="explicit_coefficients",
        coefficients=coefficients,
        coefficient_source_label="QE fit",
    )
    single = _calculate(
        [receivers[0]],
        _s7d([receivers[0]], periods=1),
        front={"r0": custom},
        atmosphere=atmosphere,
    ).irradiance.iloc[0]
    expected = spectral_factor_firstsolar(
        2.0, float(single["absolute_airmass_model"]), coefficients=coefficients
    )[0]
    assert single["front_spectral_mismatch_factor"] == pytest.approx(expected)
    assert tuple(single[f"front_spectral_coefficient_c{i}"] for i in range(1, 7)) == coefficients


def test_front_disabled_unknown_and_zero_input_dominance() -> None:
    receivers = _receivers()
    upstream = _s7d(receivers)
    disabled = _calculate(
        receivers,
        upstream,
        front={"r0": _disabled()},
        atmosphere=None,
    ).irradiance.iloc[0]
    assert disabled["front_spectral_mismatch_factor"] == 1.0
    assert disabled["front_spectral_electrical_equivalent_irradiance_wm2"] == 700.0

    unknown = _calculate(
        receivers,
        upstream,
        front={"r0": _unknown()},
        atmosphere=None,
    ).irradiance.iloc[0]
    assert np.isnan(unknown["front_spectral_mismatch_factor"])
    assert not unknown["front_spectral_electrical_equivalent_resolved"]

    zero_upstream = _set_optical_values(upstream, front=0.0, rear=100.0)
    zero = _calculate(
        receivers,
        zero_upstream,
        front={"r0": _unknown()},
        atmosphere=None,
    ).irradiance.iloc[0]
    assert not zero["front_spectral_factor_resolved"]
    assert zero["front_spectral_electrical_equivalent_irradiance_wm2"] == 0.0
    assert zero["front_spectral_electrical_equivalent_resolved"]


@pytest.mark.parametrize("missing", ["pw", "pressure"])
def test_missing_atmosphere_and_pw_upper_guard(missing: str) -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    index = pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
    atmosphere = _atmosphere(index)
    series = atmosphere.precipitable_water_cm if missing == "pw" else atmosphere.pressure_pa
    series.iloc[0] = np.nan
    row = _calculate(receivers, upstream, atmosphere=atmosphere).irradiance.iloc[0]
    assert row["front_spectral_factor_state"] == "unresolved_missing_atmospheric_input"
    assert not row["front_spectral_electrical_equivalent_resolved"]

    above = _atmosphere(index, pw=8.1)
    row = _calculate(receivers, upstream, atmosphere=above).irradiance.iloc[0]
    assert np.isnan(row["front_spectral_mismatch_factor"])
    assert row["front_spectral_factor_state"] == (
        "unresolved_firstsolar_precipitable_water_above_max"
    )


def test_firstsolar_guards_fit_domain_and_night() -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    index = pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
    low_pw = _calculate(
        receivers, upstream, atmosphere=_atmosphere(index, pw=0.01)
    ).irradiance.iloc[0]
    assert low_pw["precipitable_water_input_cm"] == 0.01
    assert low_pw["precipitable_water_model_cm"] == FIRST_SOLAR_MIN_PW_CM
    assert low_pw["firstsolar_input_adjustment_state"] == "precipitable_water_min_clamped"
    expected = spectral_factor_firstsolar(
        FIRST_SOLAR_MIN_PW_CM,
        float(low_pw["absolute_airmass_model"]),
        module_type="monosi",
    )[0]
    assert low_pw["front_spectral_mismatch_factor"] == pytest.approx(expected)
    assert low_pw["firstsolar_fit_domain_state"] == "outside_published_fit_domain"

    high_am = _calculate(
        receivers,
        upstream,
        atmosphere=_atmosphere(index, zenith=89.5, pressure=101325.0),
    ).irradiance.iloc[0]
    assert high_am["absolute_airmass_input"] > 10.0
    assert high_am["absolute_airmass_model"] == FIRST_SOLAR_MAX_ABSOLUTE_AIRMASS
    assert high_am["firstsolar_input_adjustment_state"] == "absolute_airmass_max_clamped"

    zero = _set_optical_values(upstream, front=0.0, rear=0.0)
    night = _calculate(receivers, zero, atmosphere=_atmosphere(index, zenith=90.0)).irradiance.iloc[
        0
    ]
    assert night["front_spectral_factor_state"] == "not_applicable_no_above_horizon_sun"
    assert not night["front_spectral_factor_resolved"]
    assert night["front_spectral_electrical_equivalent_irradiance_wm2"] == 0.0


def test_firstsolar_legacy_signature_receives_heliotelligence_guarded_airmass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_airmass: list[float] = []

    def legacy_firstsolar(
        precipitable_water: float,
        airmass_absolute: float,
        module_type: str | None = None,
        coefficients: tuple[float, ...] | None = None,
        min_precipitable_water: float = 0.1,
        max_precipitable_water: float = 8.0,
    ) -> NDArray[np.float64]:
        assert precipitable_water == 2.0
        assert module_type == "monosi"
        assert coefficients is None
        assert min_precipitable_water == FIRST_SOLAR_MIN_PW_CM
        assert max_precipitable_water == 8.0
        received_airmass.append(airmass_absolute)
        return np.asarray([1.0])

    monkeypatch.setattr(spectral_response, "spectral_factor_firstsolar", legacy_firstsolar)
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    index = pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
    row = _calculate(
        receivers,
        upstream,
        atmosphere=_atmosphere(index, zenith=89.5, pressure=101325.0),
    ).irradiance.iloc[0]

    assert row["absolute_airmass_input"] > FIRST_SOLAR_MAX_ABSOLUTE_AIRMASS
    assert row["absolute_airmass_model"] == FIRST_SOLAR_MAX_ABSOLUTE_AIRMASS
    assert received_airmass == [FIRST_SOLAR_MAX_ABSOLUTE_AIRMASS]


def test_rear_disabled_explicit_unknown_zero_and_monofacial() -> None:
    receivers = _receivers()
    upstream = _set_optical_values(_s7d(receivers, periods=1), front=800.0, rear=200.0)
    disabled = _calculate(receivers, upstream).irradiance.iloc[0]
    assert disabled["rear_spectral_mismatch_factor"] == 1.0
    assert disabled["poa_rear_spectral_effective_irradiance_wm2"] == 200.0

    factor_index = upstream.irradiance.index
    factors = pd.Series(1.05, index=factor_index, name="rear_factor")
    explicit = _calculate(
        receivers,
        upstream,
        rear={"r0": _rear("explicit_factor")},
        factors=factors,
    ).irradiance.iloc[0]
    assert explicit["poa_rear_spectral_effective_irradiance_wm2"] == pytest.approx(210.0)
    assert explicit["rear_spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(168.0)

    unknown = _calculate(receivers, upstream, rear={"r0": _rear("unknown")}).irradiance.iloc[0]
    assert not unknown["rear_spectral_factor_resolved"]
    assert not unknown["spectral_electrical_equivalent_resolved"]

    zero = _set_optical_values(upstream, front=800.0, rear=0.0)
    zero_row = _calculate(receivers, zero, rear={"r0": _rear("unknown")}).irradiance.iloc[0]
    assert not zero_row["rear_spectral_factor_resolved"]
    assert zero_row["rear_spectral_electrical_equivalent_irradiance_wm2"] == 0.0
    assert zero_row["rear_spectral_electrical_equivalent_resolved"]

    mono_upstream = _s7d(receivers, bifacial=False, periods=1)
    mono = _calculate(
        receivers,
        mono_upstream,
        front={"r0": _disabled()},
        rear={},
        atmosphere=None,
    ).irradiance.iloc[0]
    assert mono["rear_spectral_factor_state"] == "not_applicable_monofacial"
    assert mono["rear_spectral_electrical_equivalent_irradiance_wm2"] == 0.0
    assert mono["spectral_electrical_equivalent_irradiance_wm2"] == 700.0


def test_critical_separate_channel_formula_and_disabled_equivalence() -> None:
    receivers = _receivers()
    upstream = _set_optical_values(_s7d(receivers, periods=1), front=800.0, rear=200.0)
    index = upstream.irradiance.index
    factors = pd.Series(1.05, index=index)
    coefficients = (0.95, 0.0, 0.0, 0.0, 0.0, 0.0)
    front = FrontSpectralCorrectionAdmission(
        activation_state="enabled",
        activation_source_label="test",
        coefficient_mode="explicit_coefficients",
        coefficients=coefficients,
        coefficient_source_label="constant factor",
    )
    row = _calculate(
        receivers,
        upstream,
        front={"r0": front},
        rear={"r0": _rear("explicit_factor")},
        factors=factors,
    ).irradiance.iloc[0]
    assert row["front_spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(760.0)
    assert row["rear_spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(168.0)
    assert row["spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(928.0)
    assert row["spectral_electrical_equivalent_irradiance_wm2"] != pytest.approx(912.0)

    disabled = _calculate(
        receivers,
        upstream,
        front={"r0": _disabled()},
        rear={"r0": _rear("disabled")},
        atmosphere=None,
    ).irradiance
    assert np.allclose(
        disabled["spectral_electrical_equivalent_irradiance_wm2"],
        disabled["bifacial_electrical_equivalent_irradiance_wm2"],
    )


def test_same_factor_algebra_and_channel_independence() -> None:
    receivers = _receivers()
    upstream = _set_optical_values(_s7d(receivers, periods=1), front=800.0, rear=200.0)
    baseline = _calculate(receivers, upstream)
    front_factor = float(baseline.irradiance.iloc[0]["front_spectral_mismatch_factor"])
    same = _calculate(
        receivers,
        upstream,
        rear={"r0": _rear("explicit_factor")},
        factors=pd.Series(front_factor, index=upstream.irradiance.index),
    ).irradiance.iloc[0]
    assert same["spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(
        front_factor * same["bifacial_electrical_equivalent_irradiance_wm2"]
    )

    changed_rear = _calculate(
        receivers,
        upstream,
        rear={"r0": _rear("explicit_factor")},
        factors=pd.Series(1.08, index=upstream.irradiance.index),
    ).irradiance.iloc[0]
    assert changed_rear["front_spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(
        baseline.irradiance.iloc[0]["front_spectral_electrical_equivalent_irradiance_wm2"]
    )
    assert changed_rear["rear_spectral_electrical_equivalent_irradiance_wm2"] != pytest.approx(
        baseline.irradiance.iloc[0]["rear_spectral_electrical_equivalent_irradiance_wm2"]
    )

    changed_front = _calculate(receivers, upstream, front={"r0": _enabled("cdte")}).irradiance.iloc[
        0
    ]
    assert changed_front["rear_spectral_electrical_equivalent_irradiance_wm2"] == pytest.approx(
        baseline.irradiance.iloc[0]["rear_spectral_electrical_equivalent_irradiance_wm2"]
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("bifacial_equivalent_irradiance_contract", "forged"),
        ("bifacial_equivalent_irradiance_model", "forged"),
        ("bifacial_equivalent_irradiance_scope", "forged"),
        ("bifacial_equivalent_irradiance_coverage_scope", "forged"),
        ("isc_bifaciality_factor", 0.7),
        ("rear_electrical_equivalent_irradiance_wm2", 99.0),
        ("bifacial_electrical_equivalent_irradiance_wm2", 999.0),
    ],
)
def test_s7d_row_tamper_is_rejected(column: str, value: object) -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    frame = upstream.irradiance.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc(column)] = value
    with pytest.raises(ValueError):
        _calculate(receivers, replace(upstream, irradiance=frame))


def test_s7d_type_diagnostics_grid_and_monofacial_tamper_are_rejected() -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    with pytest.raises(ValueError, match="BifacialEquivalentIrradianceResult"):
        calculate_spectral_electrical_equivalent_irradiance(
            receivers,
            upstream.irradiance,
            front_spectral_admission_by_receiver={"r0": _disabled()},
            rear_spectral_admission_by_receiver={"r0": _rear()},
            atmosphere=None,
            explicit_rear_spectral_factor=None,
        )
    diagnostics = replace(upstream.diagnostics, row_count=99)
    with pytest.raises(ValueError, match="diagnostics"):
        _calculate(receivers, replace(upstream, diagnostics=diagnostics))
    two_periods = _s7d(receivers, periods=2)
    with pytest.raises(ValueError, match="complete|diagnostics"):
        _calculate(receivers, replace(two_periods, irradiance=two_periods.irradiance.iloc[:-1]))

    mono = _s7d(receivers, bifacial=False, periods=1)
    frame = mono.irradiance.copy(deep=True)
    frame.loc[:, "rear_electrical_equivalent_state"] = "wrong"
    with pytest.raises(ValueError, match="monofacial"):
        _calculate(
            receivers,
            replace(mono, irradiance=frame),
            front={"r0": _disabled()},
            rear={},
            atmosphere=None,
        )


def test_atmosphere_and_explicit_rear_factor_indexes_are_exact() -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=2)
    index = pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
    for bad_index in (
        index.tz_localize(None),
        index + pd.Timedelta(minutes=1),
        index.tz_convert("Europe/London"),
        index.append(index[:1]),
        pd.DatetimeIndex([index[0], pd.NaT], name=index.name),
        index[:1],
    ):
        atmosphere = _atmosphere(index)
        object.__setattr__(
            atmosphere, "apparent_solar_zenith_deg", pd.Series(40.0, index=bad_index)
        )
        with pytest.raises(ValueError, match="atmosphere"):
            _calculate(receivers, upstream, atmosphere=atmosphere)

    admission = {"r0": _rear("explicit_factor")}
    correct = pd.Series(1.08, index=upstream.irradiance.index)
    for bad in (
        correct.iloc[:-1],
        pd.concat((correct, correct.iloc[:1])),
        correct.rename_axis(index=["wrong", "receiver_id"]),
        pd.Series(1.08, index=correct.index.set_levels(index.tz_convert("Europe/London"), level=0)),
    ):
        with pytest.raises(ValueError, match="rear factor"):
            _calculate(receivers, upstream, rear=admission, factors=bad)


def test_admission_validation_and_no_hjt_mapping() -> None:
    with pytest.raises(ValueError):
        _enabled("hjt")
    with pytest.raises(ValueError):
        FrontSpectralCorrectionAdmission(
            activation_state="enabled",
            activation_source_label="source",
            coefficient_mode="explicit_coefficients",
            coefficients=(1.0,) * 5,
            coefficient_source_label="fit",
        )
    with pytest.raises(ValueError):
        FrontSpectralCorrectionAdmission(
            activation_state="enabled",
            activation_source_label="source",
            coefficient_mode="explicit_coefficients",
            coefficients=(1.0, 1.0, 1.0, 1.0, 1.0, True),
            coefficient_source_label="fit",
        )
    with pytest.raises(ValueError):
        RearSpectralCorrectionAdmission(treatment="explicit_factor", source_label="source")
    with pytest.raises(ValueError):
        RearSpectralCorrectionAdmission(
            treatment="disabled", source_label="source", model_id="latent-model"
        )
    with pytest.raises(ValueError):
        _disabled().__class__(activation_state="disabled", activation_source_label=" ")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"activation_state": "invalid", "activation_source_label": "source"},
        {
            "activation_state": "enabled",
            "activation_source_label": "source",
            "coefficient_mode": "invalid",
            "coefficient_source_label": "fit",
        },
        {
            "activation_state": "enabled",
            "activation_source_label": "source",
            "coefficient_mode": "explicit_coefficients",
            "coefficients": (1.0, 1.0, 1.0, 1.0, 1.0, np.nan),
            "coefficient_source_label": "fit",
        },
        {
            "activation_state": "enabled",
            "activation_source_label": "source",
            "coefficient_mode": "explicit_coefficients",
            "coefficients": (1.0, 1.0, 1.0, 1.0, 1.0, np.inf),
            "coefficient_source_label": "fit",
        },
    ],
)
def test_additional_front_admission_rejections(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        FrontSpectralCorrectionAdmission(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("apparent_solar_zenith_deg", True),
        ("apparent_solar_zenith_deg", 181.0),
        ("precipitable_water_cm", -0.1),
        ("precipitable_water_cm", np.inf),
        ("pressure_pa", 0.0),
        ("pressure_pa", np.inf),
        ("pressure_pa", "101325"),
    ],
)
def test_atmospheric_value_validation(field: str, bad: object) -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    index = pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
    atmosphere = _atmosphere(index)
    object.__setattr__(atmosphere, field, pd.Series([bad], index=index))
    with pytest.raises(ValueError):
        _calculate(receivers, upstream, atmosphere=atmosphere)


@pytest.mark.parametrize("bad", [0.0, -0.1, np.inf, True, "1.0"])
def test_explicit_rear_factor_range(bad: object) -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    values = pd.Series([bad], index=upstream.irradiance.index)
    with pytest.raises(ValueError):
        _calculate(
            receivers,
            upstream,
            rear={"r0": _rear("explicit_factor")},
            factors=values,
        )
    valid = pd.Series(1.08, index=upstream.irradiance.index)
    result = _calculate(
        receivers,
        upstream,
        rear={"r0": _rear("explicit_factor")},
        factors=valid,
    )
    assert result.irradiance.iloc[0]["rear_spectral_mismatch_factor"] == 1.08


def test_mapping_receiver_and_atmosphere_requirements() -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    with pytest.raises(ValueError, match="front spectral admission keys"):
        _calculate(receivers, upstream, front={})
    with pytest.raises(ValueError, match="rear spectral admission keys"):
        _calculate(receivers, upstream, rear={})
    with pytest.raises(ValueError, match="requires atmosphere"):
        calculate_spectral_electrical_equivalent_irradiance(
            receivers,
            upstream,
            front_spectral_admission_by_receiver={"r0": _enabled()},
            rear_spectral_admission_by_receiver={"r0": _rear()},
            atmosphere=None,
            explicit_rear_spectral_factor=None,
        )
    with pytest.raises(ValueError, match="MultiIndex Series"):
        _calculate(
            receivers,
            upstream,
            rear={"r0": _rear("explicit_factor")},
            factors=None,
        )
    with pytest.raises(ValueError, match="exactly match bifacial"):
        _calculate(
            receivers,
            upstream,
            rear={"r0": _rear(), "extra": _rear()},
        )
    with pytest.raises(ValueError, match="FIXED_TABLE"):
        _calculate(_receivers(kind=ReceiverKind.MODULE), upstream)


def test_unresolved_upstream_and_no_cross_channel_zero_shortcut() -> None:
    receivers = _receivers()
    upstream = _s7d(receivers, periods=1)
    frame = upstream.irradiance.copy(deep=True)
    frame.loc[:, "poa_front_effective_optical_wm2"] = np.nan
    frame.loc[:, "bifacial_electrical_equivalent_irradiance_wm2"] = np.nan
    frame.loc[:, "bifacial_electrical_equivalent_resolved"] = False
    frame.loc[:, "bifacial_electrical_equivalent_state"] = "unresolved_front_effective_irradiance"
    diagnostics = replace(upstream.diagnostics, resolved_row_count=0, unresolved_row_count=1)
    row = _calculate(
        receivers, replace(upstream, irradiance=frame, diagnostics=diagnostics)
    ).irradiance.iloc[0]
    assert not row["front_spectral_electrical_equivalent_resolved"]
    assert not row["spectral_electrical_equivalent_resolved"]

    rear_frame = upstream.irradiance.copy(deep=True)
    rear_frame.loc[:, "poa_front_effective_optical_wm2"] = 0.0
    rear_frame.loc[:, "poa_rear_effective_optical_wm2"] = np.nan
    rear_frame.loc[:, "rear_electrical_equivalent_irradiance_wm2"] = np.nan
    rear_frame.loc[:, "rear_electrical_equivalent_resolved"] = False
    rear_frame.loc[:, "rear_electrical_equivalent_state"] = "unresolved_rear_effective_irradiance"
    rear_frame.loc[:, "bifacial_electrical_equivalent_irradiance_wm2"] = np.nan
    rear_frame.loc[:, "bifacial_electrical_equivalent_resolved"] = False
    rear_frame.loc[:, "bifacial_electrical_equivalent_state"] = (
        "unresolved_rear_effective_irradiance"
    )
    rear_unresolved = replace(upstream, irradiance=rear_frame, diagnostics=diagnostics)
    rear_row = _calculate(receivers, rear_unresolved).irradiance.iloc[0]
    assert rear_row["front_spectral_electrical_equivalent_irradiance_wm2"] == 0.0
    assert rear_row["front_spectral_electrical_equivalent_resolved"]
    assert not rear_row["rear_spectral_electrical_equivalent_resolved"]
    assert not rear_row["spectral_electrical_equivalent_resolved"]

    zero_front = _set_optical_values(upstream, front=0.0, rear=100.0)
    row = _calculate(
        receivers,
        zero_front,
        front={"r0": _unknown()},
        rear={"r0": _rear("unknown")},
        atmosphere=None,
    ).irradiance.iloc[0]
    assert row["front_spectral_electrical_equivalent_resolved"]
    assert not row["rear_spectral_electrical_equivalent_resolved"]
    assert not row["spectral_electrical_equivalent_resolved"]


def test_empty_determinism_and_input_immutability() -> None:
    receivers = _receivers(2)
    upstream = _s7d(receivers, periods=2)
    timestamps = pd.DatetimeIndex(upstream.irradiance.index.get_level_values(0).unique())
    atmosphere = _atmosphere(timestamps)
    factors = pd.Series(1.05, index=upstream.irradiance.index)
    front = {"r0": _enabled("monosi"), "r1": _enabled("cdte")}
    rear = {"r0": _rear("explicit_factor"), "r1": _rear("explicit_factor")}
    upstream_copy = upstream.irradiance.copy(deep=True)
    atmosphere_copies = (
        atmosphere.apparent_solar_zenith_deg.copy(deep=True),
        atmosphere.precipitable_water_cm.copy(deep=True),
        atmosphere.pressure_pa.copy(deep=True),
    )
    factor_copy = factors.copy(deep=True)
    expected = _calculate(
        receivers, upstream, front=front, rear=rear, atmosphere=atmosphere, factors=factors
    )
    reordered_upstream = replace(upstream, irradiance=upstream.irradiance.iloc[::-1])
    actual = _calculate(
        list(reversed(receivers)),
        reordered_upstream,
        front=dict(reversed(list(front.items()))),
        rear=dict(reversed(list(rear.items()))),
        atmosphere=atmosphere,
        factors=factors.iloc[::-1],
    )
    pd.testing.assert_frame_equal(actual.irradiance, expected.irradiance)
    pd.testing.assert_frame_equal(upstream.irradiance, upstream_copy)
    pd.testing.assert_series_equal(atmosphere.apparent_solar_zenith_deg, atmosphere_copies[0])
    pd.testing.assert_series_equal(atmosphere.precipitable_water_cm, atmosphere_copies[1])
    pd.testing.assert_series_equal(atmosphere.pressure_pa, atmosphere_copies[2])
    pd.testing.assert_series_equal(factors, factor_copy)

    empty_upstream = _s7d(receivers, periods=0)
    empty_index = pd.DatetimeIndex(empty_upstream.irradiance.index.get_level_values(0).unique())
    empty_atmosphere = _atmosphere(empty_index)
    empty = _calculate(
        receivers,
        empty_upstream,
        front=front,
        rear={"r0": _rear(), "r1": _rear()},
        atmosphere=empty_atmosphere,
    )
    assert empty.irradiance.empty
    assert tuple(empty.irradiance.columns) == _OUTPUT_COLUMNS
    assert empty.diagnostics.receiver_count == 2
    assert empty.diagnostics.row_count == 0
    assert empty.diagnostics.spectral_total_resolved_row_count == 0
    assert empty.diagnostics.spectral_response_model == SPECTRAL_RESPONSE_MODEL_ID
