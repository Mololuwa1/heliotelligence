"""Tests for secure, deterministic PVCollada 2.0 geometry ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from importlib import resources
from pathlib import Path

import numpy as np
import pytest
from lxml import etree  # type: ignore[import-untyped]

from heliotelligence.geometry import ReceiverKind, ShadowRole
from heliotelligence.ingest.pvcollada import (
    PVColladaImportError,
    PVColladaParseError,
    PVColladaResourceLimitError,
    PVColladaUnsupportedError,
    PVColladaValidationError,
    import_pvcollada_2,
    validation,
)
from heliotelligence.ingest.pvcollada.transforms import node_transform

_FIXTURES = Path(__file__).parent / "fixtures" / "pvcollada"
_FIXED = (_FIXTURES / "official_fixed.pvc2").read_bytes()
_TRACKERS = (_FIXTURES / "official_trackers.pvc2").read_bytes()
_COLLADA_NAMESPACE = "http://www.collada.org/2008/03/COLLADASchema"
_C = f"{{{_COLLADA_NAMESPACE}}}"


def _with_instance_graph(
    graph: dict[str, tuple[str, ...]], *, attach_to_table: bool
) -> bytes:
    """Add a small, schema-valid reusable-node graph to the fixed fixture."""
    root = etree.fromstring(_FIXED)
    library = root.find(f"{_C}library_nodes")
    assert library is not None
    for identifier, references in graph.items():
        node = etree.SubElement(library, f"{_C}node", id=identifier)
        for reference in references:
            etree.SubElement(node, f"{_C}instance_node", url=f"#{reference}")

    target: etree._Element
    if attach_to_table:
        found = library.find(f"{_C}node[@id='TableModel1']")
        assert found is not None
        target = found
    else:
        scene = root.find(f"{_C}library_visual_scenes/{_C}visual_scene")
        assert scene is not None
        target = etree.SubElement(scene, f"{_C}node", id="CycleRoot")
    instance = etree.Element(f"{_C}instance_node", url="#B")
    extra = target.find(f"{_C}extra")
    target.insert(target.index(extra), instance) if extra is not None else target.append(instance)
    return bytes(etree.tostring(root))


def test_official_fixed_example_imports_to_canonical_enu_metres() -> None:
    result = import_pvcollada_2(_FIXED, geometry_revision="revision-1")
    site = result.site_geometry
    assert site.coordinate_reference.canonical_frame == "ENU"
    assert site.coordinate_reference.canonical_unit == "m"
    assert site.coordinate_reference.source_unit == "cm"
    assert site.coordinate_reference.source_unit_to_m == 0.01
    assert site.coordinate_reference.source_up_axis == "Z_UP"
    assert site.coordinate_reference.origin_latitude_deg == 46.24
    assert site.coordinate_reference.origin_longitude_deg == 6.11
    assert site.coordinate_reference.origin_altitude_m == 420.0
    assert len(site.terrain_surfaces) == 1
    assert [item.id for item in site.pv_receivers] == [
        "receiver:InstanceTable1",
        "receiver:InstanceTable2",
        "receiver:InstanceTable3",
    ]
    assert all(item.receiver_kind is ReceiverKind.FIXED_TABLE for item in site.pv_receivers)
    assert np.allclose(site.pv_receivers[0].centre_enu_m, (-6.97, -2.3, 1.0))
    assert np.allclose(site.pv_receivers[1].centre_enu_m, (-6.97, -10.3, 1.0))
    assert all(np.isfinite(item.mesh.vertices_enu_m).all() for item in site.pv_receivers)
    assert all(np.isclose(np.linalg.norm(item.normal_enu), 1.0) for item in site.pv_receivers)
    assert result.diagnostics.source_application == "Helios 3D"
    assert result.diagnostics.source_digest == hashlib.sha256(_FIXED).hexdigest()
    assert site.source_provenance.source_application != "PVcase"


def test_official_tracker_example_resolves_hierarchy_and_support_geometry() -> None:
    result = import_pvcollada_2(_TRACKERS, geometry_revision="revision-2")
    site = result.site_geometry
    assert len(site.pv_receivers) == 3
    assert all(item.receiver_kind is ReceiverKind.TRACKER_TABLE for item in site.pv_receivers)
    assert all(item.mesh.faces.shape == (8, 3) for item in site.pv_receivers)
    assert np.allclose(
        [item.centre_enu_m for item in site.pv_receivers],
        [(-2.0, -32.06, 1.5), (-10.0, -32.06, 1.5), (-18.0, -32.06, 1.5)],
    )
    assert len(site.terrain_surfaces) == 1
    assert len(site.shading_objects) == 33
    assert all(item.shadow_role is ShadowRole.UNKNOWN for item in site.shading_objects)
    assert {item.semantic_category for item in site.shading_objects} == {"post", "gap"}
    assert all("RackModel1" not in item.id for item in site.shading_objects)


@pytest.mark.parametrize("source", [_FIXED, _TRACKERS])
def test_import_is_deterministic_and_equal(source: bytes) -> None:
    first = import_pvcollada_2(source, geometry_revision="same")
    second = import_pvcollada_2(source, geometry_revision="same")
    assert first == second


def test_unit_scale_is_applied_exactly() -> None:
    source = _FIXED.replace(b'meter="0.01" name="cm"', b'meter="0.001" name="mm"')
    result = import_pvcollada_2(source, geometry_revision="units")
    assert np.allclose(result.site_geometry.pv_receivers[0].centre_enu_m, (-0.697, -0.23, 0.1))
    assert result.site_geometry.coordinate_reference.source_unit_to_m == 0.001


def test_missing_geolocation_remains_absent() -> None:
    start = _FIXED.index(b"\t\t<coverage>")
    end = _FIXED.index(b"\t\t</coverage>") + len(b"\t\t</coverage>\n")
    result = import_pvcollada_2(_FIXED[:start] + _FIXED[end:], geometry_revision="no-geo")
    reference = result.site_geometry.coordinate_reference
    assert reference.origin_latitude_deg is None
    assert reference.origin_longitude_deg is None
    assert reference.origin_altitude_m is None


def test_ordered_translate_rotate_scale_and_matrix_composition() -> None:
    namespace = "http://www.collada.org/2008/03/COLLADASchema"
    node = etree.fromstring(
        f"""<node xmlns='{namespace}'>
        <translate>10 0 0</translate>
        <rotate>0 0 1 90</rotate>
        <scale>2 3 4</scale>
        <matrix>1 0 0 0 0 1 0 0 0 0 1 0 5 6 7 1</matrix>
        </node>""".encode()
    )
    point = np.array([1.0, 2.0, 3.0, 1.0])
    # Independently apply the listed operations to the column vector:
    # matrix translation -> scale -> rotation -> translation.
    expected = np.array([-14.0, 12.0, 40.0, 1.0])
    assert np.allclose(node_transform(node) @ point, expected)


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (b"", PVColladaParseError),
        (b"<COLLADA>", PVColladaParseError),
        (b"<!DOCTYPE x><x/>", PVColladaParseError),
        (b"<!DOCTYPE x [<!ENTITY y 'z'>]><x>&y;</x>", PVColladaParseError),
        (
            b"<!DOCTYPE x [<!ENTITY y SYSTEM 'https://example.invalid/x'>]><x>&y;</x>",
            PVColladaParseError,
        ),
    ],
)
def test_hostile_or_malformed_xml_is_rejected(source: bytes, error: type[Exception]) -> None:
    with pytest.raises(error):
        import_pvcollada_2(source, geometry_revision="hostile")


def test_oversized_input_is_rejected_before_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validation, "MAX_INPUT_BYTES", 8)
    with pytest.raises(PVColladaResourceLimitError, match="exceeds"):
        import_pvcollada_2(_FIXED, geometry_revision="large")


def test_structural_resource_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validation, "MAX_GEOMETRIES", 1)
    with pytest.raises(PVColladaResourceLimitError, match="geometry"):
        import_pvcollada_2(_FIXED, geometry_revision="many")


def test_nested_table_self_cycle_is_rejected_without_recursing() -> None:
    source = _with_instance_graph({"B": ("B",)}, attach_to_table=True)
    with pytest.raises(PVColladaValidationError, match="cyclic instance_node reference"):
        import_pvcollada_2(source, geometry_revision="self-cycle")


def test_nested_table_multi_node_cycle_is_rejected_without_recursing() -> None:
    source = _with_instance_graph({"B": ("C",), "C": ("B",)}, attach_to_table=True)
    with pytest.raises(PVColladaValidationError, match="cyclic instance_node reference"):
        import_pvcollada_2(source, geometry_revision="multi-cycle")


def test_ordinary_instance_node_cycle_is_rejected_without_recursing() -> None:
    source = _with_instance_graph({"B": ("B",)}, attach_to_table=False)
    with pytest.raises(PVColladaValidationError, match="cyclic instance_node reference"):
        import_pvcollada_2(source, geometry_revision="ordinary-cycle")


def test_resolved_instance_node_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _with_instance_graph({"B": ("C",), "C": ()}, attach_to_table=True)
    monkeypatch.setattr(validation, "MAX_RESOLVED_NODE_INSTANCES", 1)
    with pytest.raises(PVColladaResourceLimitError, match="instance_node count"):
        import_pvcollada_2(source, geometry_revision="node-amplification")


def test_resolved_geometry_instance_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation, "MAX_RESOLVED_GEOMETRY_INSTANCES", 0)
    with pytest.raises(PVColladaResourceLimitError, match="geometry-instance count"):
        import_pvcollada_2(_FIXED, geometry_revision="geometry-amplification")


def test_instance_node_depth_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _with_instance_graph({"B": ("C",), "C": ()}, attach_to_table=True)
    monkeypatch.setattr(validation, "MAX_INSTANCE_DEPTH", 1)
    with pytest.raises(PVColladaResourceLimitError, match="instance_node depth"):
        import_pvcollada_2(source, geometry_revision="instance-depth")


def test_wrong_collada_version_is_rejected() -> None:
    source = _FIXED.replace(b'version="1.5.0"', b'version="1.4.1"', 1)
    with pytest.raises(PVColladaUnsupportedError, match="1.5.0"):
        import_pvcollada_2(source, geometry_revision="legacy")


def test_wrong_pvcollada_profile_is_rejected() -> None:
    source = _FIXED.replace(b'profile="PVCollada-2.0"', b'profile="PVCollada-1.0"')
    with pytest.raises(PVColladaUnsupportedError, match="PVCollada 2.0"):
        import_pvcollada_2(source, geometry_revision="legacy")


def test_schema_violation_is_rejected() -> None:
    source = _FIXED.replace(b"<up_axis>Z_UP</up_axis>", b"<up_axis>INVALID</up_axis>")
    with pytest.raises(PVColladaValidationError, match="XSD"):
        import_pvcollada_2(source, geometry_revision="schema")


def test_broken_pvc_reference_is_rejected_by_schematron() -> None:
    source = _FIXED.replace(b'url="#rackInstance1"', b'url="#missingRack"', 1)
    with pytest.raises(PVColladaValidationError, match="reference Schematron"):
        import_pvcollada_2(source, geometry_revision="reference")


def test_duplicate_source_id_is_rejected() -> None:
    source = _FIXED.replace(b'id="PVnode2"', b'id="PVnode1"', 1)
    with pytest.raises(PVColladaValidationError, match="duplicate source id"):
        import_pvcollada_2(source, geometry_revision="duplicate")


def test_dangling_geometry_reference_is_rejected() -> None:
    source = _FIXED.replace(b'url="#Terrain1"', b'url="#MissingTerrain"', 1)
    with pytest.raises(PVColladaImportError):
        import_pvcollada_2(source, geometry_revision="dangling")


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        (b"2000 -2500 0", b"nan -2500 0", "XSD|non-finite"),
        (
            b'count="4" source="#terrain1FloatArray" stride="3"',
            b'count="9" source="#terrain1FloatArray" stride="3"',
            "accessor",
        ),
        (b"3 1 2 1 3 0", b"9 1 2 1 3 0", "out-of-range"),
    ],
)
def test_malformed_geometry_data_is_rejected(old: bytes, new: bytes, match: str) -> None:
    with pytest.raises(PVColladaValidationError, match=match):
        import_pvcollada_2(_FIXED.replace(old, new, 1), geometry_revision="bad-mesh")


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b'source="#terrain1FloatArray"', b'source="#danglingFloatArray"'),
        (b' source="#terrain1FloatArray"', b""),
        (
            b'source="#terrain1FloatArray"',
            b'source="https://example.invalid/array"',
        ),
        (b'source="#terrain1FloatArray"', b'source="#rack1FloatArray"'),
    ],
)
def test_invalid_accessor_source_reference_is_rejected(old: bytes, new: bytes) -> None:
    source = _FIXED.replace(old, new, 1)
    with pytest.raises(PVColladaValidationError, match="accessor source|attribute 'source'"):
        import_pvcollada_2(source, geometry_revision="bad-accessor-reference")


def test_external_geometry_reference_is_rejected() -> None:
    source = _FIXED.replace(b'url="#Terrain1"', b'url="https://example.invalid/terrain"', 1)
    with pytest.raises((PVColladaUnsupportedError, PVColladaValidationError)):
        import_pvcollada_2(source, geometry_revision="external")


def test_unsafe_non_convex_polygon_is_rejected() -> None:
    source = _FIXED.replace(
        b"2000 -2500 0\n\t\t\t\t\t\t-2000 -2500 0\n"
        b"\t\t\t\t\t\t-2000 2500 0\n\t\t\t\t\t\t2000 2500 0",
        b"2000 -2500 0\n\t\t\t\t\t\t-2000 2500 0\n"
        b"\t\t\t\t\t\t-2000 -2500 0\n\t\t\t\t\t\t2000 2500 0",
        1,
    )
    with pytest.raises(PVColladaUnsupportedError, match="polygon"):
        import_pvcollada_2(source, geometry_revision="non-convex")


def test_unknown_extension_profile_is_diagnostic_not_fatal() -> None:
    insertion = (
        b'<extra><technique profile="Vendor-Extension">'
        b'<vendor xmlns="urn:test"/></technique></extra>'
    )
    source = _FIXED.replace(b"</visual_scene>", insertion + b"</visual_scene>", 1)
    result = import_pvcollada_2(source, geometry_revision="extension")
    assert result.diagnostics.unsupported_extension_profiles == ("Vendor-Extension",)


def test_geometry_revision_is_required() -> None:
    with pytest.raises(PVColladaValidationError, match="geometry_revision"):
        import_pvcollada_2(_FIXED, geometry_revision=" ")


def test_result_and_diagnostics_are_frozen() -> None:
    result = import_pvcollada_2(_FIXED, geometry_revision="frozen")
    with pytest.raises(FrozenInstanceError):
        result.site_geometry = result.site_geometry  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.diagnostics.receiver_count = 0  # type: ignore[misc]


def test_schema_resources_are_discoverable_as_package_data() -> None:
    package = resources.files("heliotelligence.ingest.pvcollada.schemas")
    expected = {
        "collada_schema_1_5.xsd",
        "pvcollada_schema_2.0.xsd",
        "pvcollada_structure_2.0.sch",
        "pvcollada_references_2.0.sch",
        "pvcollada_business_2.0.sch",
        "LICENSE.pvcollada.txt",
    }
    assert all((package / name).is_file() for name in expected)
