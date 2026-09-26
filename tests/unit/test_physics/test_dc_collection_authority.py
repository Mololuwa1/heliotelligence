"""Tests for static string-terminal to MPPT-input DC path authority."""

from __future__ import annotations

import copy
import math
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest
from pydantic import ValidationError

from heliotelligence.config.site import (  # type: ignore[import-untyped]
    DcBranchPathConfig,
    ElectricalTopologyConfig,
    SiteConfig,
)
from heliotelligence.physics.dc_collection import (  # type: ignore[import-untyped]
    DC_BRANCH_PATH_CONTRACT_ID,
    DC_BRANCH_PATH_COVERAGE_SCOPE,
    DC_BRANCH_PATH_MODEL_ID,
    DC_BRANCH_PATH_SCOPE,
    MPPT_INPUT_REFERENCE_PLANE,
    STRING_TERMINAL_REFERENCE_PLANE,
    DcBranchPathAuthorityDiagnostics,
    DcBranchPathAuthorityResult,
    resolve_dc_branch_path_authority,
)

PATH_COLUMNS = (
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


def _branch(
    resistance: float, source: str = "as_built_schedule:test", confidence: str = "high"
) -> dict[str, object]:
    return {
        "series_resistance_ohm": resistance,
        "parameter_source": source,
        "confidence": confidence,
    }


def _topology() -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig.model_validate(
        {
            "inverters": [
                {
                    "id": "INV-B",
                    "mppts": [
                        {
                            "id": "MPPT-01",
                            "strings": [
                                {
                                    "id": "STR-Z",
                                    "modules_per_string": 24,
                                    "zone_id": "misleading-zone",
                                    "dc_branch_path": _branch(0.42),
                                },
                                {
                                    "id": "STR-A",
                                    "modules_per_string": 24,
                                    "zone_id": "misleading-zone",
                                    "dc_branch_path": _branch(
                                        0.0, "ideal_authority:test", "medium"
                                    ),
                                },
                            ],
                        },
                        {"id": "EMPTY", "strings": []},
                    ],
                },
                {
                    "id": "INV-A",
                    "mppts": [
                        {
                            "id": "MPPT-01",
                            "strings": [
                                {
                                    "id": "STR-M",
                                    "modules_per_string": 30,
                                    "zone_id": "misleading-zone",
                                }
                            ],
                        }
                    ],
                },
            ]
        }
    )


def test_mixed_authority_resolves_exact_reference_planes_and_diagnostics() -> None:
    result = resolve_dc_branch_path_authority(_topology())

    assert type(result) is DcBranchPathAuthorityResult
    assert type(result.diagnostics) is DcBranchPathAuthorityDiagnostics
    assert tuple(result.paths.columns) == PATH_COLUMNS
    assert result.paths.index.names == ["inverter_id", "mppt_id", "string_id"]
    assert list(result.paths.index) == [
        ("INV-B", "MPPT-01", "STR-Z"),
        ("INV-B", "MPPT-01", "STR-A"),
        ("INV-A", "MPPT-01", "STR-M"),
    ]

    positive = result.paths.loc[("INV-B", "MPPT-01", "STR-Z")]
    assert positive["source_reference_plane"] == STRING_TERMINAL_REFERENCE_PLANE
    assert positive["sink_reference_plane"] == MPPT_INPUT_REFERENCE_PLANE
    assert positive["branch_path_resolved"] == True  # noqa: E712
    assert positive["branch_path_state"] == "resolved_explicit_series_loop_resistance"
    assert positive["series_resistance_ohm"] == 0.42
    assert positive["parameter_source"] == "as_built_schedule:test"
    assert positive["confidence"] == "high"

    zero = result.paths.loc[("INV-B", "MPPT-01", "STR-A")]
    assert zero["branch_path_resolved"] == True  # noqa: E712
    assert zero["series_resistance_ohm"] == 0.0
    assert zero["branch_path_state"] == "resolved_explicit_series_loop_resistance"

    absent = result.paths.loc[("INV-A", "MPPT-01", "STR-M")]
    assert absent["branch_path_resolved"] == False  # noqa: E712
    assert absent["branch_path_state"] == "unresolved_no_explicit_dc_branch_path"
    assert math.isnan(float(absent["series_resistance_ohm"]))
    assert absent["parameter_source"] == ""
    assert absent["confidence"] == "unknown"

    assert result.diagnostics == DcBranchPathAuthorityDiagnostics(
        inverter_count=2,
        mppt_count=3,
        string_count=3,
        resolved_path_count=2,
        unresolved_path_count=1,
        zero_resistance_path_count=1,
        positive_resistance_path_count=1,
        path_model=DC_BRANCH_PATH_MODEL_ID,
    )


def test_every_row_carries_canonical_provenance() -> None:
    paths = resolve_dc_branch_path_authority(_topology()).paths

    assert set(paths["dc_branch_path_contract"]) == {DC_BRANCH_PATH_CONTRACT_ID}
    assert set(paths["dc_branch_path_model"]) == {DC_BRANCH_PATH_MODEL_ID}
    assert set(paths["dc_branch_path_scope"]) == {DC_BRANCH_PATH_SCOPE}
    assert set(paths["dc_branch_path_coverage_scope"]) == {
        DC_BRANCH_PATH_COVERAGE_SCOPE
    }


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), -float("inf"), True, False])
def test_invalid_resistance_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError, match="series_resistance_ohm"):
        DcBranchPathConfig.model_validate(
            {
                "series_resistance_ohm": value,
                "parameter_source": "test",
                "confidence": "high",
            }
        )


@pytest.mark.parametrize("value", ["", "   ", 42, None])
def test_invalid_parameter_source_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError, match="parameter_source"):
        DcBranchPathConfig.model_validate(
            {
                "series_resistance_ohm": 0.1,
                "parameter_source": value,
                "confidence": "high",
            }
        )


def test_invalid_confidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        DcBranchPathConfig.model_validate(
            {
                "series_resistance_ohm": 0.1,
                "parameter_source": "test",
                "confidence": "forged",
            }
        )


def test_exact_topology_type_is_required() -> None:
    with pytest.raises(TypeError, match="exactly ElectricalTopologyConfig"):
        resolve_dc_branch_path_authority({})


def test_legacy_wiring_loss_and_zone_are_not_authority() -> None:
    site = SiteConfig.model_validate(
        {
            "id": "site",
            "name": "Legacy loss non-authority",
            "latitude": 52.0,
            "longitude": 1.0,
            "timezone": "Europe/London",
            "capacity_kwp": 1000.0,
            "solcast_resource_id": "resource",
            "module": {"wiring_loss_dc_pct": 99.0},
            "electrical_topology": {
                "inverters": [
                    {
                        "id": "INV",
                        "mppts": [
                            {
                                "id": "MPPT",
                                "strings": [
                                    {
                                        "id": "STR",
                                        "modules_per_string": 24,
                                        "zone_id": "MPPT",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        }
    )
    assert site.electrical_topology is not None

    row = resolve_dc_branch_path_authority(site.electrical_topology).paths.iloc[0]

    assert row["branch_path_state"] == "unresolved_no_explicit_dc_branch_path"
    assert math.isnan(float(row["series_resistance_ohm"]))


def test_empty_topology_has_exact_schema_and_counts_empty_mppts() -> None:
    empty = resolve_dc_branch_path_authority(ElectricalTopologyConfig())
    only_empty_mppt = resolve_dc_branch_path_authority(
        ElectricalTopologyConfig.model_validate(
            {"inverters": [{"id": "INV", "mppts": [{"id": "MPPT"}]}]}
        )
    )

    assert empty.paths.empty
    assert tuple(empty.paths.columns) == PATH_COLUMNS
    assert empty.paths.index.names == ["inverter_id", "mppt_id", "string_id"]
    assert empty.diagnostics == DcBranchPathAuthorityDiagnostics(
        inverter_count=0,
        mppt_count=0,
        string_count=0,
        resolved_path_count=0,
        unresolved_path_count=0,
        zero_resistance_path_count=0,
        positive_resistance_path_count=0,
        path_model=DC_BRANCH_PATH_MODEL_ID,
    )
    assert only_empty_mppt.paths.empty
    assert only_empty_mppt.diagnostics.inverter_count == 1
    assert only_empty_mppt.diagnostics.mppt_count == 1
    assert only_empty_mppt.diagnostics.string_count == 0


def test_resolution_is_deterministic_and_does_not_mutate_topology() -> None:
    topology = _topology()
    snapshot = copy.deepcopy(topology)

    first = resolve_dc_branch_path_authority(topology)
    second = resolve_dc_branch_path_authority(topology)

    assert topology == snapshot
    pd.testing.assert_frame_equal(first.paths, second.paths)
    assert first.paths is not second.paths
    assert first.diagnostics == second.diagnostics


def test_result_dataclasses_are_frozen() -> None:
    result = resolve_dc_branch_path_authority(_topology())

    with pytest.raises(AttributeError):
        result.diagnostics = result.diagnostics
    with pytest.raises(AttributeError):
        result.paths = pd.DataFrame()


def test_external_geometry_cannot_affect_topology_only_api() -> None:
    topology = _topology()
    arbitrary_geometry: dict[str, Any] = {"STR-Z": [9999.0, -1234.0]}
    before = resolve_dc_branch_path_authority(topology)
    arbitrary_geometry["STR-Z"] = [0.0, 0.0]
    after = resolve_dc_branch_path_authority(topology)

    pd.testing.assert_frame_equal(before.paths, after.paths)
