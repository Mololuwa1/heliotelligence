"""Real canonical optical composition and independent boundary replay."""

from dataclasses import replace
from functools import cache
from typing import Any

import numpy as np
import pandas as pd
import pytest

from heliotelligence.physics import irradiance_boundary_state as module
from heliotelligence.physics.bifacial_equivalent_irradiance import (
    calculate_bifacial_electrical_equivalent_irradiance,
)
from heliotelligence.physics.bifacial_response import resolve_bifacial_response_parameters
from heliotelligence.physics.fixed_bifacial_rear import (
    FixedBifacialRearParameters,
    FixedBifacialRearScene,
    calculate_fixed_bifacial_rear_irradiance,
)
from heliotelligence.physics.fixed_inter_row_shading import FixedRowBlockingPair
from heliotelligence.physics.irradiance_components import resolve_horizontal_irradiance_components
from heliotelligence.physics.rear_effective_irradiance import calculate_rear_effective_irradiance
from heliotelligence.physics.rear_optical_state import calculate_rear_optical_state
from heliotelligence.physics.rear_row_optical_transmission import (
    calculate_rear_row_optical_transmission,
)
from heliotelligence.physics.solar_geometry_time_alignment import (
    calculate_time_aligned_solar_geometry,
)
from heliotelligence.physics.spectral_response import (
    FrontSpectralCorrectionAdmission,
    RearSpectralCorrectionAdmission,
    calculate_spectral_electrical_equivalent_irradiance,
)
from heliotelligence.physics.weather_time_authority import resolve_weather_time_state
from tests.unit.test_physics import test_bifacial_equivalent_irradiance as bifacial_support
from tests.unit.test_physics import test_effective_irradiance as front_support
from tests.unit.test_physics.test_weather_time_authority import authority


@cache
def parents(
    *,
    bifacial: bool = False,
    unknown_spectral: bool = False,
    missing_rear: bool = False,
    visibility: float = 0.6,
    missing_front: bool = False,
    cross_date: bool = False,
) -> dict[str, Any]:
    """Use canonical primitives throughout; scaling drivers admits rear=120, not a fake result."""
    receivers = [
        replace(r, normal_enu=(float(np.sin(np.radians(30))), 0.0, float(np.cos(np.radians(30)))))
        for r in bifacial_support._receivers(2)
    ]
    times = pd.date_range("2026-06-01 09:00", periods=2, freq="h", tz="UTC", name="time")
    if cross_date:
        times = pd.date_range(
            "2027-01-01 00:00", periods=2, freq="h", tz="Europe/London", name="time"
        )
    weather = resolve_weather_time_state(times, authority())
    geometry = calculate_time_aligned_solar_geometry(
        weather,
        latitude_deg=-20 if cross_date else 52.56,
        longitude_deg=180 if cross_date else 1.21,
        altitude_m=47,
    )
    calculation_times = pd.DatetimeIndex(weather.states.solar_geometry_evaluation_time)
    zenith, azimuth = (
        geometry.geometry.apparent_solar_zenith_deg,
        geometry.geometry.solar_azimuth_deg,
    )
    horizontal = resolve_horizontal_irradiance_components(
        pd.Series(800.0, index=times),
        pd.Series(120.0, index=times),
        pd.Series(700.0, index=times),
        geometry.geometry.solar_zenith_deg,
        solar_model_times=calculation_times,
    )
    rows = tuple(
        front_support.FixedRowDefinition(f"row-{i}", (r.id,), 30, 2)
        for i, r in enumerate(receivers)
    )
    array = front_support.FixedRowArrayDefinition(
        "array", 0.0, 0.0, rows, (FixedRowBlockingPair("row-0", "row-1", 4, 0),)
    )
    rear_scene = FixedBifacialRearScene(
        receivers, [array], [FixedBifacialRearParameters("array", 1.5, 0.2)], view_factor_points=20
    )
    drivers = [horizontal[c].copy() for c in ("ghi_wm2", "dhi_wm2", "dni_wm2")]
    if bifacial and not missing_rear:
        rear = calculate_fixed_bifacial_rear_irradiance(
            *drivers,
            zenith,
            azimuth,
            scene=rear_scene,
            model="haydavies" if cross_date else "isotropic",
            solar_model_times=calculation_times,
        )
        scale = 120 / float(rear.poa_rear_global_raw_wm2.iloc[0])
        drivers = [driver * scale for driver in drivers]
    if missing_front:
        for driver in drivers:
            driver[:] = np.nan
    rear = (
        calculate_fixed_bifacial_rear_irradiance(
            *drivers,
            zenith,
            azimuth,
            scene=rear_scene,
            model="haydavies" if cross_date else "isotropic",
            solar_model_times=calculation_times,
        )
        if bifacial and not missing_rear
        else None
    )
    transposition = {
        r.id: front_support.calculate_raw_poa_transposition(
            *drivers,
            zenith,
            azimuth,
            surface_tilt_deg=30,
            surface_azimuth_deg=90,
            albedo=0.2,
            model="perez-driesse",
            solar_model_times=calculation_times,
        )
        for r in receivers
    }
    parameters = front_support.resolve_beam_iam_parameters(
        model="ashrae",
        method="direct",
        source_label="explicit optical parameters",
        model_parameters={"b": 0.05},
    )
    beam = {
        r.id: front_support.calculate_beam_iam(
            transposition[r.id].aoi_deg, model="ashrae", model_parameters={"b": 0.05}
        )
        for r in receivers
    }
    raw = pd.DataFrame({r.id: transposition[r.id].poa_direct_raw_wm2 for r in receivers})
    terrain = front_support.calculate_terrain_horizon_direct_beam_shading(
        raw, zenith, azimuth, scene=front_support.TerrainHorizonScene(receivers, [])
    )
    fixed = front_support.calculate_fixed_inter_row_direct_beam_shading(
        raw, zenith, azimuth, scene=front_support.FixedInterRowScene(receivers, [array])
    )
    near = front_support.calculate_near_object_direct_beam_shading(
        raw,
        zenith,
        azimuth,
        scene=front_support.NearObjectBeamScene(receivers, [], samples_per_receiver=4),
    )
    near_authority, horizon_authority = front_support._authorities(
        receivers, terrain, fixed, near, zenith, azimuth, near_transmission=visibility
    )
    diffuse = front_support.DiffuseSkyScene(
        receivers, samples_per_receiver=2, sky_direction_count=32, max_rays_per_batch=31
    )
    optical = front_support.assemble_receiver_optical_state(
        receivers,
        transposition,
        beam,
        terrain,
        fixed,
        near,
        diffuse.calculate_visibility(),
        near_shading_authority=near_authority,
        far_horizon_authority=horizon_authority,
        rear_mode_by_receiver={
            r.id: "fixed_bifacial_rear" if rear is not None else "not_applicable" for r in receivers
        },
        rear_irradiance=rear,
    )
    diffuse_components = diffuse.calculate_component_optical_transmission(
        horizon_zenith_count=2,
        horizon_azimuth_count=36,
        ground_direction_count=2048,
        ground_plane_z_m=0.0,
        beam_iam_model_by_receiver={r.id: "ashrae" for r in receivers},
        model_parameters_by_receiver={r.id: {"b": 0.05} for r in receivers},
    )
    front = front_support.calculate_front_effective_irradiance(
        receivers,
        optical,
        diffuse_components,
        beam_iam_parameters_by_receiver={r.id: parameters for r in receivers},
    )
    rear_effective = None
    if rear is not None:
        rear_state = calculate_rear_optical_state(
            receivers,
            rear,
            rear_beam_iam_parameters_by_receiver={r.id: parameters for r in receivers},
        )
        transmission = calculate_rear_row_optical_transmission(
            rear_state,
            scene=rear_scene,
            rear_beam_iam_parameters_by_receiver={r.id: parameters for r in receivers},
            row_position_count=32,
            sky_direction_count=2048,
            ground_direction_count=2048,
        )
        rear_effective = calculate_rear_effective_irradiance(receivers, rear_state, transmission)
    if bifacial and missing_rear:
        # A partial rear contract, with no physical irradiance evidence. The
        # bifacial primitive requires this explicit unresolved result, not None.
        rear_effective = bifacial_support._rear(
            [r.id for r in receivers], periods=2, resolved=False
        )
        absent = rear_effective.irradiance.copy()
        absent.index = optical.state.index.copy()
        rear_effective = replace(rear_effective, irradiance=absent)
    equivalent = calculate_bifacial_electrical_equivalent_irradiance(
        receivers,
        front,
        bifacial_response_parameters_by_receiver={
            r.id: resolve_bifacial_response_parameters(
                bifacial_enabled=bifacial,
                method="direct" if bifacial else "monofacial_declared",
                source_label="explicit module declaration",
                **({"isc_bifaciality_factor": 0.8} if bifacial else {}),
            )
            for r in receivers
        },
        rear_effective_irradiance=rear_effective,
    )
    spectral = calculate_spectral_electrical_equivalent_irradiance(
        receivers,
        equivalent,
        front_spectral_admission_by_receiver={
            r.id: FrontSpectralCorrectionAdmission(
                "unknown" if unknown_spectral else "disabled", "explicit spectral admission"
            )
            for r in receivers
        },
        rear_spectral_admission_by_receiver={
            r.id: RearSpectralCorrectionAdmission("disabled", "explicit rear declaration")
            for r in receivers
            if bifacial
        },
        atmosphere=None,
        explicit_rear_spectral_factor=None,
    )
    horizontal = resolve_horizontal_irradiance_components(
        *drivers, geometry.geometry.solar_zenith_deg, solar_model_times=calculation_times
    )
    return dict(
        receivers=receivers,
        weather_time_state=weather,
        solar_geometry=geometry,
        optical_state=optical,
        front_effective_irradiance=front,
        bifacial_equivalent_irradiance=equivalent,
        spectral_response=spectral,
        horizontal_irradiance_components=horizontal,
        raw_poa_transposition_by_receiver=transposition,
        raw_rear_irradiance=rear,
    )


def measurement() -> module.FrontPoaMeasurementAuthority:
    return module.FrontPoaMeasurementAuthority(
        "front_surface_incident_broadband_poa",
        "calibrated front sensor",
        "high",
        "measurement method",
        "explicit front receiver plane",
    )


def test_iam_and_shading_owned_once_in_real_canonical_chain() -> None:
    values = parents()
    result = module.resolve_canonical_irradiance_boundary(**values)
    front = values["front_effective_irradiance"].irradiance
    assert front.beam_iam_factor.between(0, 1, inclusive="neither").all()
    assert (front.front_direct_geometric_visible_fraction == 0.6).all()
    np.testing.assert_allclose(
        front.poa_front_direct_effective_wm2,
        front.poa_front_direct_raw_wm2 * 0.6 * front.beam_iam_factor,
        rtol=0,
        atol=1e-9,
    )
    assert (front.poa_front_direct_effective_wm2 < front.poa_front_direct_raw_wm2).all()
    pd.testing.assert_series_equal(
        result.states.front_optical_effective_direct_irradiance_wm2,
        front.poa_front_direct_effective_wm2,
        check_names=False,
    )
    pd.testing.assert_series_equal(
        result.states.module_electrical_irradiance_wm2,
        values["spectral_response"].irradiance.spectral_electrical_equivalent_irradiance_wm2,
        check_names=False,
    )
    assert result.states.canonical_irradiance_boundary_resolved.all()
    for name in ("iam", "shading", "bifacial_response", "spectral_response"):
        assert result.states[name + "_already_applied_upstream"].all()


def test_nonzero_rear_survives_measured_front_without_selecting_thermal_or_electrical_basis() -> (
    None
):
    values = dict(parents(bifacial=True))
    index = values["optical_state"].state.index
    values.update(
        measured_front_poa_wm2=pd.Series(800.0, index=index),
        measured_front_authority_by_receiver={r.id: measurement() for r in values["receivers"]},
    )
    result = module.resolve_canonical_irradiance_boundary(**values)
    row = result.states.iloc[0]
    assert row.measured_front_incident_poa_wm2 == 800
    assert row.modeled_rear_incident_poa_wm2 == pytest.approx(120, abs=1e-10)
    assert row.modeled_front_incident_poa_wm2 != 800
    assert (
        row.module_electrical_irradiance_wm2
        == values["spectral_response"]
        .irradiance.iloc[0]
        .spectral_electrical_equivalent_irradiance_wm2
    )
    assert not row.module_thermal_poa_handoff_resolved
    assert np.isnan(row.module_thermal_poa_handoff_wm2)
    assert (
        row.module_thermal_poa_handoff_state == "unresolved_no_explicit_thermal_poa_basis_authority"
    )
    assert (
        row.total_incident_broadband_both_surfaces_wm2
        == row.modeled_front_incident_poa_wm2 + row.modeled_rear_incident_poa_wm2
    )
    assert row.total_incident_broadband_both_surfaces_wm2 != 920
    assert row.measured_front_parameter_source == "calibrated front sensor"


@pytest.mark.parametrize("unknown", [False, True])
def test_explicit_spectral_disabled_versus_unknown(unknown: bool) -> None:
    values = parents(unknown_spectral=unknown)
    result = module.resolve_canonical_irradiance_boundary(**values)
    assert result.states.module_electrical_irradiance_resolved.eq(not unknown).all()
    if unknown:
        assert result.states.module_electrical_irradiance_wm2.isna().all()
        assert result.states.bifacial_electrical_equivalent_irradiance_wm2.notna().all()
    else:
        assert result.states.module_electrical_irradiance_wm2.equals(
            result.states.bifacial_electrical_equivalent_irradiance_wm2
        )


def test_monofacial_is_not_missing_rear_and_bifacial_missing_rear_is_not_zero() -> None:
    mono = module.resolve_canonical_irradiance_boundary(**parents()).states
    assert mono.rear_incident_state.eq("not_applicable_monofacial").all()
    assert mono.modeled_rear_incident_poa_wm2.isna().all()
    assert mono.module_electrical_irradiance_resolved.all()
    missing = module.resolve_canonical_irradiance_boundary(
        **parents(bifacial=True, missing_rear=True)
    ).states
    assert missing.rear_incident_state.eq("unresolved_rear_incident").all()
    assert missing.modeled_rear_incident_poa_wm2.isna().all()
    assert not missing.module_electrical_irradiance_resolved.any()
    assert not missing.canonical_irradiance_boundary_resolved.any()


def test_measurement_does_not_repair_missing_optical_authority() -> None:
    values = dict(parents(missing_front=True))
    index = values["optical_state"].state.index
    values.update(
        measured_front_poa_wm2=pd.Series(800.0, index=index),
        measured_front_authority_by_receiver={r.id: measurement() for r in values["receivers"]},
    )
    result = module.resolve_canonical_irradiance_boundary(**values)
    assert result.states.measured_front_poa_present.all()
    assert not result.states.module_electrical_irradiance_resolved.any()


@pytest.mark.parametrize(
    "parent,attribute",
    [
        ("optical_state", "state"),
        ("front_effective_irradiance", "irradiance"),
        ("bifacial_equivalent_irradiance", "irradiance"),
        ("spectral_response", "irradiance"),
    ],
)
@pytest.mark.parametrize("change", ["timestamp", "timezone", "receiver", "order"])
def test_exact_parent_key_matching(parent: str, attribute: str, change: str) -> None:
    values = dict(parents())
    frame = getattr(values[parent], attribute).copy()
    times = frame.index.get_level_values(0)
    ids = frame.index.get_level_values(1)
    if change == "order":
        frame = frame.iloc[::-1]
    elif change == "timezone":
        frame.index = pd.MultiIndex.from_arrays(
            [times.tz_convert("Europe/London"), ids], names=frame.index.names
        )
    elif change == "timestamp":
        frame.index = pd.MultiIndex.from_arrays(
            [times + pd.Timedelta(seconds=1), ids], names=frame.index.names
        )
    else:
        frame.index = pd.MultiIndex.from_arrays(
            [times, ["other"] * len(ids)], names=frame.index.names
        )
    values[parent] = replace(values[parent], **{attribute: frame})
    with pytest.raises(ValueError, match="match exactly"):
        module.resolve_canonical_irradiance_boundary(**values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("module_electrical_irradiance_wm2", 1),
        ("modeled_front_incident_poa_wm2", 1),
        ("modeled_rear_incident_poa_wm2", 0),
        ("measured_front_incident_poa_wm2", 5),
        ("iam_already_applied_upstream", False),
        ("module_thermal_poa_handoff_resolved", True),
        ("rear_incident_state", "not_applicable_monofacial"),
        ("irradiance_boundary_contract", "wrong"),
    ],
)
def test_boundary_tamper_rejection(field: str, value: Any) -> None:
    values = parents(bifacial=True)
    result = module.resolve_canonical_irradiance_boundary(**values)
    frame = result.states.copy()
    frame.loc[frame.index[0], field] = value
    with pytest.raises(ValueError, match="independent replay"):
        module.validate_canonical_irradiance_boundary(replace(result, states=frame), **values)


def test_validator_independent_of_boundary_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    values = parents(bifacial=True)
    result = module.resolve_canonical_irradiance_boundary(**values)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("builder called")

    for name in ["_record", "_frame", "_diagnostics", "resolve_canonical_irradiance_boundary"]:
        monkeypatch.setattr(module, name, fail)
    module.validate_canonical_irradiance_boundary(result, **values)
    with pytest.raises(ValueError, match="diagnostics"):
        module.validate_canonical_irradiance_boundary(
            replace(result, diagnostics=replace(result.diagnostics, resolved_row_count=999)),
            **values,
        )


@pytest.mark.parametrize("bad", [-1, np.inf, True, "800"])
def test_invalid_measured_front_values_rejected(bad: Any) -> None:
    values = dict(parents())
    values.update(
        measured_front_poa_wm2=pd.Series(bad, index=values["optical_state"].state.index),
        measured_front_authority_by_receiver={r.id: measurement() for r in values["receivers"]},
    )
    with pytest.raises(ValueError):
        module.resolve_canonical_irradiance_boundary(**values)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("measurement_quantity", "poa_total"),
        ("parameter_source", " padded"),
        ("method_reference", ""),
        ("measurement_plane_description", "front "),
        ("confidence", "HIGH"),
    ],
)
def test_measurement_authority_is_explicit(field: str, bad: str) -> None:
    with pytest.raises(ValueError):
        replace(measurement(), **{field: bad})


@pytest.mark.parametrize(
    "parent,column",
    [
        ("front_effective_irradiance", "poa_front_global_raw_wm2"),
        ("front_effective_irradiance", "beam_iam_factor"),
        ("bifacial_equivalent_irradiance", "poa_front_effective_optical_wm2"),
        ("spectral_response", "poa_front_effective_optical_wm2"),
    ],
)
def test_contradictory_parent_replay_is_rejected(parent: str, column: str) -> None:
    values = dict(parents())
    frame = values[parent].irradiance.copy()
    frame.loc[frame.index[0], column] += 0.1
    values[parent] = replace(values[parent], irradiance=frame)
    with pytest.raises(ValueError, match="contradictory"):
        module.resolve_canonical_irradiance_boundary(**values)


@pytest.mark.parametrize("change", ["order", "timezone", "timestamp", "receiver"])
def test_measured_front_must_have_exact_receiver_observation_keys(change: str) -> None:
    values = dict(parents())
    index = values["optical_state"].state.index
    series = pd.Series(800.0, index=index)
    if change == "order":
        series = series.iloc[::-1]
    else:
        times, ids = index.get_level_values(0), index.get_level_values(1)
        if change == "timezone":
            times = times.tz_convert("Europe/London")
        elif change == "timestamp":
            times = times + pd.Timedelta(seconds=1)
        else:
            ids = ["other"] * len(ids)
        series.index = pd.MultiIndex.from_arrays([times, ids], names=index.names)
    values.update(
        measured_front_poa_wm2=series,
        measured_front_authority_by_receiver={r.id: measurement() for r in values["receivers"]},
    )
    with pytest.raises(ValueError, match="exact timestamp/receiver"):
        module.resolve_canonical_irradiance_boundary(**values)


def test_missing_measurement_is_nan_and_not_an_electrical_fallback() -> None:
    values = dict(parents(unknown_spectral=True))
    values.update(
        measured_front_poa_wm2=pd.Series(np.nan, index=values["optical_state"].state.index),
        measured_front_authority_by_receiver={r.id: measurement() for r in values["receivers"]},
    )
    result = module.resolve_canonical_irradiance_boundary(**values)
    assert not result.states.measured_front_poa_present.any()
    assert result.states.measured_front_incident_poa_wm2.isna().all()
    assert result.states.module_electrical_irradiance_wm2.isna().all()
    assert not result.states.module_electrical_irradiance_resolved.any()


def test_boundary_contract_ids_and_metadata_are_canonical() -> None:
    assert module.IRRADIANCE_BOUNDARY_CONTRACT_ID == (
        "admitted_time_aligned_canonical_optical_bifacial_and_spectral_results_to_module_irradiance_boundary_v1"
    )
    assert module.IRRADIANCE_BOUNDARY_MODEL_ID == (
        "reference_plane_preserving_incident_optical_and_spectral_irradiance_handoff_v1"
    )
    result = module.resolve_canonical_irradiance_boundary(**parents())
    assert result.states.irradiance_boundary_contract.eq(
        module.IRRADIANCE_BOUNDARY_CONTRACT_ID
    ).all()
    assert result.diagnostics.contract == module.IRRADIANCE_BOUNDARY_CONTRACT_ID


@pytest.mark.parametrize("bifacial", [False, True])
def test_receiver_argument_order_is_canonical(bifacial: bool) -> None:
    values = dict(parents(bifacial=bifacial))
    expected = module.resolve_canonical_irradiance_boundary(**values)
    values["receivers"] = list(reversed(values["receivers"]))
    actual = module.resolve_canonical_irradiance_boundary(**values)
    pd.testing.assert_frame_equal(actual.states, expected.states)
    assert actual.diagnostics == expected.diagnostics


def test_cross_year_boundary_and_spa_share_representative_instant() -> None:
    values = parents(bifacial=True, cross_date=True)
    result = module.resolve_canonical_irradiance_boundary(**values)
    physical = values["weather_time_state"].states.solar_geometry_evaluation_time.iloc[0]
    assert physical == pd.Timestamp("2026-12-31 23:30", tz="Europe/London")
    assert result.states.index[0][0] == pd.Timestamp("2027-01-01 00:00", tz="Europe/London")
    assert result.states.canonical_irradiance_boundary_resolved.all()
    from heliotelligence.physics.solar_geometry import calculate_solar_geometry

    reference = calculate_solar_geometry(
        pd.DatetimeIndex([physical]), latitude_deg=-20, longitude_deg=180, altitude_m=47
    )
    assert values["solar_geometry"].geometry.solar_zenith_deg.iloc[0] == pytest.approx(
        reference.solar_zenith_deg.iloc[0], abs=1e-12
    )


@pytest.mark.parametrize("parent", ["front", "rear", "erbs"])
def test_boundary_rejects_observation_label_temporal_provenance(parent: str) -> None:
    values = dict(parents(bifacial=True, cross_date=True))
    times = values["weather_time_state"].observation_times
    if parent == "front":
        frames = {k: v.copy() for k, v in values["raw_poa_transposition_by_receiver"].items()}
        for frame in frames.values():
            frame["extraterrestrial_irradiance_evaluation_time"] = times
        values["raw_poa_transposition_by_receiver"] = frames
    elif parent == "rear":
        rear = values["raw_rear_irradiance"].copy()
        rear["extraterrestrial_irradiance_evaluation_time"] = times.repeat(2)
        values["raw_rear_irradiance"] = rear
    else:
        horizontal = values["horizontal_irradiance_components"].copy()
        horizontal["decomposition_applied"] = True
        horizontal["decomposition_evaluation_time"] = times
        values["horizontal_irradiance_components"] = horizontal
    with pytest.raises(ValueError, match="temporal provenance"):
        module.resolve_canonical_irradiance_boundary(**values)
    valid = module.resolve_canonical_irradiance_boundary(**parents(bifacial=True, cross_date=True))
    with pytest.raises(ValueError, match="temporal provenance"):
        module.validate_canonical_irradiance_boundary(valid, **values)


def test_boundary_rejects_front_actually_computed_at_label_time() -> None:
    values = dict(parents(cross_date=True))
    horizontal = values["horizontal_irradiance_components"]
    geometry = values["solar_geometry"].geometry
    # SPA is correctly shifted, but omitting solar_model_times constructs the
    # previously permitted mixed basis: extra radiation uses the row label.
    values["raw_poa_transposition_by_receiver"] = {
        r.id: front_support.calculate_raw_poa_transposition(
            horizontal.ghi_wm2,
            horizontal.dhi_wm2,
            horizontal.dni_wm2,
            geometry.apparent_solar_zenith_deg,
            geometry.solar_azimuth_deg,
            surface_tilt_deg=30,
            surface_azimuth_deg=90,
            albedo=0.2,
            model="perez-driesse",
        )
        for r in values["receivers"]
    }
    with pytest.raises(ValueError, match="temporal provenance"):
        module.resolve_canonical_irradiance_boundary(**values)
