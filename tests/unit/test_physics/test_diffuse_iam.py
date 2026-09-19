"""Tests for component-specific Marion diffuse IAM."""

from __future__ import annotations

import pvlib.iam  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics.diffuse_iam import (
    DIFFUSE_IAM_MODEL_ID,
    calculate_diffuse_iam,
)


@pytest.mark.parametrize(
    ("model", "pvlib_model", "parameters"),
    [
        ("physical", "physical", {"n": 1.526, "K": 4.0, "L": 0.002, "n_ar": None}),
        ("ashrae", "ashrae", {"b": 0.05}),
        ("martin-ruiz", "martin_ruiz", {"a_r": 0.16}),
    ],
)
def test_diffuse_iam_matches_pvlib_marion(
    model: str, pvlib_model: str, parameters: dict[str, object]
) -> None:
    result = calculate_diffuse_iam(
        surface_tilt_deg=30.0,
        beam_iam_model=model,  # type: ignore[arg-type]
        model_parameters=parameters,
    )
    expected = pvlib.iam.marion_diffuse(pvlib_model, 30.0, **parameters)
    assert result.diffuse_sky_iam_factor == pytest.approx(expected["sky"], abs=1e-15)
    assert result.diffuse_horizon_iam_factor == pytest.approx(expected["horizon"], abs=1e-15)
    assert result.diffuse_ground_iam_factor == pytest.approx(expected["ground"], abs=1e-15)
    assert result.model == DIFFUSE_IAM_MODEL_ID
    assert result.source_beam_iam_model == model
    assert result.resolved


@pytest.mark.parametrize(
    ("model", "parameters"),
    [
        ("ashrae", {}),
        ("ashrae", {"b": 0.05, "extra": 1.0}),
        ("unsupported", {"b": 0.05}),
        ("ashrae", {"b": float("inf")}),
        ("ashrae", {"b": True}),
    ],
)
def test_diffuse_iam_reuses_canonical_parameter_validation(
    model: str, parameters: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        calculate_diffuse_iam(
            surface_tilt_deg=30.0,
            beam_iam_model=model,  # type: ignore[arg-type]
            model_parameters=parameters,
        )


@pytest.mark.parametrize("tilt", [-1.0, 181.0, float("nan"), True])
def test_diffuse_iam_validates_tilt(tilt: object) -> None:
    with pytest.raises(ValueError, match="surface_tilt_deg"):
        calculate_diffuse_iam(
            surface_tilt_deg=tilt,  # type: ignore[arg-type]
            beam_iam_model="ashrae",
            model_parameters={"b": 0.05},
        )
