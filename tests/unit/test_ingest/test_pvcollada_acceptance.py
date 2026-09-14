"""Tests for the private, importer-backed PVCollada acceptance harness."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from scripts.validate_pvcollada_acceptance import main as cli_main

from heliotelligence.geometry import CoordinateReference, ReceiverKind
from heliotelligence.ingest.pvcollada import PVColladaImportResult, import_pvcollada_2
from heliotelligence.ingest.pvcollada.acceptance import (
    AcceptanceStatus,
    BoundingBoxExpectation,
    GeolocationExpectation,
    PVColladaAcceptanceExpectations,
    ReceiverExpectation,
    TerrainElevationExpectation,
    acceptance_report_dict,
    derive_receiver_orientation,
    evaluate_pvcollada_acceptance,
    parse_acceptance_expectations,
    summarize_site_geometry,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "pvcollada"
_FIXED = (_FIXTURES / "official_fixed.pvc2").read_bytes()
_TRACKERS = (_FIXTURES / "official_trackers.pvc2").read_bytes()


def _fixed_result() -> PVColladaImportResult:
    return import_pvcollada_2(_FIXED, geometry_revision="fixed-public-fixture")


def _set_attribute(value: object, name: str, replacement: object) -> None:
    setattr(value, name, replacement)


def test_fixed_fixture_has_deterministic_canonical_summary() -> None:
    summary = summarize_site_geometry(_fixed_result().site_geometry)
    assert summary.source_application == "Helios 3D"
    assert summary.canonical_frame == "ENU"
    assert summary.canonical_unit == "m"
    assert summary.source_unit == "cm"
    assert summary.source_unit_to_m == 0.01
    assert summary.receiver_count == 3
    assert summary.fixed_receiver_count == 3
    assert summary.tracker_receiver_count == 0
    assert summary.terrain_surface_count == 1
    assert summary.shading_object_count == 0
    assert summary.bounding_box is not None
    assert summary.bounding_box.values() == (-20.0, 20.0, -25.0, 25.0, 0.0, 2.0)
    assert [item.receiver_id for item in summary.receivers] == [
        "receiver:InstanceTable1",
        "receiver:InstanceTable2",
        "receiver:InstanceTable3",
    ]


def test_tracker_fixture_has_deterministic_canonical_summary() -> None:
    result = import_pvcollada_2(_TRACKERS, geometry_revision="tracker-public-fixture")
    summary = summarize_site_geometry(result.site_geometry)
    assert summary.receiver_count == 3
    assert summary.fixed_receiver_count == 0
    assert summary.tracker_receiver_count == 3
    assert summary.shading_object_count == 33
    assert summary.semantic_category_counts == (("gap", 9), ("post", 24))
    assert summary.shadow_role_counts == (("unknown", 33),)
    assert summary.bounding_box is not None
    assert summary.bounding_box.values() == (-27.0, 7.5, -70.0, 7.5, 0.0, 1.5)


def test_exact_count_expectations_pass() -> None:
    result = _fixed_result()
    expectations = PVColladaAcceptanceExpectations(
        expected_receiver_count=3,
        expected_fixed_receiver_count=3,
        expected_tracker_receiver_count=0,
        expected_terrain_surface_count=1,
        expected_shading_object_count=0,
    )
    report = evaluate_pvcollada_acceptance(result, expectations)
    assert report.status is AcceptanceStatus.PASS
    assert all(check.status is AcceptanceStatus.PASS for check in report.checks)


def test_count_mismatch_fails() -> None:
    report = evaluate_pvcollada_acceptance(
        _fixed_result(), PVColladaAcceptanceExpectations(expected_receiver_count=4)
    )
    assert report.status is AcceptanceStatus.FAIL
    assert report.checks[0].name == "receiver_count"
    assert report.checks[0].actual == 3


def test_acceptance_contracts_are_frozen() -> None:
    expectations = PVColladaAcceptanceExpectations(expected_receiver_count=3)
    report = evaluate_pvcollada_acceptance(_fixed_result(), expectations)
    with pytest.raises(FrozenInstanceError):
        _set_attribute(expectations, "expected_receiver_count", 4)
    with pytest.raises(FrozenInstanceError):
        _set_attribute(report, "status", AcceptanceStatus.FAIL)


def test_bbox_expectation_passes_with_tolerance() -> None:
    report = evaluate_pvcollada_acceptance(
        _fixed_result(),
        PVColladaAcceptanceExpectations(
            bbox=BoundingBoxExpectation(
                min_east_m=-20.05,
                max_east_m=20.05,
                min_elevation_m=0.05,
                tolerance_m=0.051,
            )
        ),
    )
    assert report.status is AcceptanceStatus.PASS


def test_bbox_expectation_fails_outside_tolerance() -> None:
    report = evaluate_pvcollada_acceptance(
        _fixed_result(),
        PVColladaAcceptanceExpectations(
            bbox=BoundingBoxExpectation(max_north_m=26.0, tolerance_m=0.1)
        ),
    )
    assert report.status is AcceptanceStatus.FAIL


def test_selected_receiver_centre_kind_and_orientation_pass() -> None:
    report = evaluate_pvcollada_acceptance(
        _fixed_result(),
        PVColladaAcceptanceExpectations(
            receivers=(
                ReceiverExpectation(
                    source_object_id="InstanceTable1",
                    centre_enu_m=(-6.97, -2.3, 1.0),
                    centre_tolerance_m=1e-9,
                    receiver_kind=ReceiverKind.FIXED_TABLE,
                    tilt_deg=23.5,
                    tilt_tolerance_deg=0.01,
                    azimuth_deg=180.0,
                    azimuth_tolerance_deg=0.01,
                ),
            )
        ),
    )
    assert report.status is AcceptanceStatus.PASS


def test_missing_expected_receiver_fails_without_nearest_guess() -> None:
    report = evaluate_pvcollada_acceptance(
        _fixed_result(),
        PVColladaAcceptanceExpectations(
            receivers=(ReceiverExpectation(source_object_id="does-not-exist"),)
        ),
    )
    assert report.status is AcceptanceStatus.FAIL
    assert report.checks[0].actual == 0


def test_receiver_kind_mismatch_fails() -> None:
    report = evaluate_pvcollada_acceptance(
        _fixed_result(),
        PVColladaAcceptanceExpectations(
            receivers=(
                ReceiverExpectation(
                    receiver_id="receiver:InstanceTable1",
                    receiver_kind=ReceiverKind.TRACKER_TABLE,
                ),
            )
        ),
    )
    assert report.status is AcceptanceStatus.FAIL


@pytest.mark.parametrize(
    ("normal", "tilt", "azimuth"),
    [
        ((0.0, -0.5, 3**0.5 / 2), 30.0, 180.0),
        ((2**0.5 / 2, 2**0.5 / 2, 0.0), 90.0, 45.0),
    ],
)
def test_receiver_orientation_uses_meteorological_azimuth(
    normal: tuple[float, float, float], tilt: float, azimuth: float
) -> None:
    orientation = derive_receiver_orientation(normal)
    assert orientation.state == "resolved"
    assert orientation.tilt_deg == pytest.approx(tilt)
    assert orientation.azimuth_deg == pytest.approx(azimuth)


def test_horizontal_surface_azimuth_is_explicitly_undefined() -> None:
    orientation = derive_receiver_orientation((0.0, 0.0, 1.0))
    assert orientation.tilt_deg == 0.0
    assert orientation.azimuth_deg is None
    assert orientation.state == "azimuth_undefined"


def test_downward_receiver_normal_is_diagnosed_not_reinterpreted() -> None:
    orientation = derive_receiver_orientation((0.0, 0.0, -1.0))
    assert orientation.tilt_deg is None
    assert orientation.azimuth_deg is None
    assert orientation.state == "downward_normal"


def test_explicit_geolocation_expectation_passes() -> None:
    report = evaluate_pvcollada_acceptance(
        _fixed_result(),
        PVColladaAcceptanceExpectations(
            geolocation=GeolocationExpectation(
                latitude_deg=46.24,
                longitude_deg=6.11,
                altitude_m=420.0,
            )
        ),
    )
    assert report.status is AcceptanceStatus.PASS


def test_required_geolocation_missing_fails() -> None:
    result = _fixed_result()
    site = result.site_geometry
    reference = CoordinateReference(
        source_unit=site.coordinate_reference.source_unit,
        source_unit_to_m=site.coordinate_reference.source_unit_to_m,
        source_up_axis=site.coordinate_reference.source_up_axis,
    )
    result_without_origin = replace(
        result, site_geometry=replace(site, coordinate_reference=reference)
    )
    report = evaluate_pvcollada_acceptance(
        result_without_origin,
        PVColladaAcceptanceExpectations(geolocation=GeolocationExpectation(46.24, 6.11, 420.0)),
    )
    assert report.status is AcceptanceStatus.FAIL
    assert len(report.checks) == 3


def test_selected_terrain_elevation_check_passes() -> None:
    result = _fixed_result()
    terrain = result.site_geometry.terrain_surfaces[0]
    expectation = TerrainElevationExpectation(
        terrain_id=terrain.id,
        min_elevation_m=0.0,
        max_elevation_m=0.0,
    )
    report = evaluate_pvcollada_acceptance(
        result, PVColladaAcceptanceExpectations(terrain_surfaces=(expectation,))
    )
    assert report.status is AcceptanceStatus.PASS


def test_repeat_import_and_acceptance_are_deterministic() -> None:
    expectations = PVColladaAcceptanceExpectations(expected_receiver_count=3)
    first = import_pvcollada_2(_FIXED, geometry_revision="deterministic")
    second = import_pvcollada_2(_FIXED, geometry_revision="deterministic")
    assert first == second
    assert evaluate_pvcollada_acceptance(first, expectations) == evaluate_pvcollada_acceptance(
        second, expectations
    )


@pytest.mark.parametrize(
    "document",
    [
        "not-json",
        "[]",
        '{"unexpected": 1}',
        '{"expected_receiver_count": -1}',
        '{"expected_receiver_count": true}',
        '{"bbox": {"min_east_m": NaN}}',
        '{"bbox": {"min_east_m": 0, "tolerance_m": -1}}',
        '{"receivers": {}}',
        '{"receivers": [{"source_object_id": "x", "centre_enu_m": [1, 2]}]}',
        '{"receivers": [{"source_object_id": "x", "unknown": 1}]}',
        '{"geolocation": {"latitude_deg": 91, "longitude_deg": 0, "altitude_m": 0}}',
    ],
)
def test_json_expectations_reject_malformed_contracts(document: str) -> None:
    with pytest.raises(ValueError):
        parse_acceptance_expectations(document)


def test_json_expectations_reject_duplicate_receiver_selectors() -> None:
    document = json.dumps(
        {
            "receivers": [
                {"source_object_id": "InstanceTable1"},
                {"source_object_id": "InstanceTable1"},
            ]
        }
    )
    with pytest.raises(ValueError, match="unique"):
        parse_acceptance_expectations(document)


def test_json_expectations_parse_strict_typed_contract() -> None:
    expectations = parse_acceptance_expectations(
        json.dumps(
            {
                "expected_receiver_count": 3,
                "expected_semantic_category_counts": {"post": 27},
                "bbox": {"min_east_m": -20.0, "tolerance_m": 0.1},
                "receivers": [
                    {
                        "source_object_id": "InstanceTable1",
                        "receiver_kind": "fixed_table",
                        "centre_enu_m": [-6.97, -2.3, 1.0],
                    }
                ],
            }
        )
    )
    assert expectations.expected_receiver_count == 3
    assert expectations.receivers[0].receiver_kind is ReceiverKind.FIXED_TABLE


def test_report_excludes_source_xml_meshes_and_unrequested_receiver_coordinates() -> None:
    expectations = PVColladaAcceptanceExpectations(expected_receiver_count=3)
    report = evaluate_pvcollada_acceptance(_fixed_result(), expectations)
    payload = acceptance_report_dict(report, expectations, input_label="site.pvc2")
    encoded = json.dumps(payload, sort_keys=True)
    assert "<COLLADA" not in encoded
    assert "vertices" not in encoded
    assert "faces" not in encoded
    assert "centre_enu_m" not in encoded
    assert "/secure/private" not in encoded
    assert payload["input_label"] == "site.pvc2"


def test_report_includes_bbox_only_when_expected() -> None:
    without_bbox = PVColladaAcceptanceExpectations(expected_receiver_count=3)
    report = evaluate_pvcollada_acceptance(_fixed_result(), without_bbox)
    payload = acceptance_report_dict(report, without_bbox)
    assert isinstance(payload["summary"], dict)
    assert "bounding_box" not in payload["summary"]
    with_bbox = PVColladaAcceptanceExpectations(bbox=BoundingBoxExpectation(min_east_m=-20.0))
    report = evaluate_pvcollada_acceptance(_fixed_result(), with_bbox)
    payload = acceptance_report_dict(report, with_bbox)
    assert isinstance(payload["summary"], dict)
    assert "bounding_box" in payload["summary"]


def test_cli_returns_zero_and_writes_bounded_deterministic_pass_report(
    tmp_path: Path,
) -> None:
    source = tmp_path / "private-site.pvc2"
    manifest = tmp_path / "private-expectations.json"
    report = tmp_path / "private-report.json"
    source.write_bytes(_FIXED)
    manifest.write_text('{"expected_receiver_count": 3}', encoding="utf-8")
    arguments = [
        "--input",
        str(source),
        "--geometry-revision",
        "private-revision",
        "--expectations",
        str(manifest),
        "--report",
        str(report),
        "--verify-determinism",
        "--supplied-as",
        "PVcase Ground Mount export",
    ]
    assert cli_main(arguments) == 0
    first = report.read_text(encoding="utf-8")
    assert cli_main(arguments) == 0
    assert report.read_text(encoding="utf-8") == first
    payload = json.loads(first)
    assert payload["status"] == "PASS"
    assert payload["input_label"] == "private-site.pvc2"
    assert payload["supplied_as"] == "PVcase Ground Mount export"
    assert "<COLLADA" not in first
    assert str(tmp_path) not in first


def test_cli_returns_nonzero_for_acceptance_failure(tmp_path: Path) -> None:
    source = tmp_path / "private-site.pvc2"
    manifest = tmp_path / "private-expectations.json"
    report = tmp_path / "private-report.json"
    source.write_bytes(_FIXED)
    manifest.write_text('{"expected_receiver_count": 999}', encoding="utf-8")
    assert (
        cli_main(
            [
                "--input",
                str(source),
                "--geometry-revision",
                "private-revision",
                "--expectations",
                str(manifest),
                "--report",
                str(report),
            ]
        )
        == 1
    )
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "FAIL"


def test_cli_returns_distinct_nonzero_for_import_failure(tmp_path: Path) -> None:
    source = tmp_path / "private-site.pvc2"
    manifest = tmp_path / "private-expectations.json"
    report = tmp_path / "private-report.json"
    source.write_bytes(b"<private customer xml")
    manifest.write_text("{}", encoding="utf-8")
    assert (
        cli_main(
            [
                "--input",
                str(source),
                "--geometry-revision",
                "private-revision",
                "--expectations",
                str(manifest),
                "--report",
                str(report),
            ]
        )
        == 2
    )
    text = report.read_text(encoding="utf-8")
    assert "<private customer xml" not in text
    assert str(tmp_path) not in text
