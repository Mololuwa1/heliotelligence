"""Tests for the format-neutral canonical geometry contract."""

from dataclasses import FrozenInstanceError

import numpy as np
import numpy.typing as npt
import pytest

from heliotelligence.geometry import (
    CoordinateReference,
    PVReceiver,
    ReceiverKind,
    ShadingObject,
    ShadowRole,
    SiteGeometry,
    SourceProvenance,
    TerrainSurface,
    TriangleMesh,
)


def _mesh() -> TriangleMesh:
    return TriangleMesh(
        vertices_enu_m=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
        faces=np.array([[0, 1, 2]], dtype=np.int64),
    )


def _receiver(identifier: str = "receiver-1") -> PVReceiver:
    return PVReceiver(
        id=identifier,
        mesh=_mesh(),
        centre_enu_m=(1.0, 2.0, 3.0),
        normal_enu=(0.0, 0.0, 1.0),
        receiver_kind=ReceiverKind.FIXED_TABLE,
        provenance=SourceProvenance(source_object_id="source-table-1"),
    )


def test_source_provenance_preserves_optional_unknowns() -> None:
    provenance = SourceProvenance(source_format="pvcollada", source_digest="sha256:abc")
    assert provenance.source_format == "pvcollada"
    assert provenance.source_version is None
    assert provenance.source_object_id is None


@pytest.mark.parametrize("field_name", SourceProvenance.__dataclass_fields__)
def test_source_provenance_rejects_empty_or_whitespace_values(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        SourceProvenance(**{field_name: " "})


def test_coordinate_reference_has_fixed_canonical_invariants() -> None:
    reference = CoordinateReference()
    assert reference.canonical_frame == "ENU"
    assert reference.canonical_unit == "m"
    with pytest.raises(TypeError):
        CoordinateReference(canonical_frame="NED")  # type: ignore[call-arg]


def test_coordinate_reference_preserves_valid_source_metadata_and_transform() -> None:
    transform = np.eye(4)
    reference = CoordinateReference(
        source_unit="cm",
        source_unit_to_m=0.01,
        source_up_axis="Z_UP",
        source_crs="EPSG:4326",
        origin_latitude_deg=52.0,
        origin_longitude_deg=1.0,
        origin_altitude_m=12.0,
        source_to_canonical_transform=transform,
    )
    transform[0, 0] = 99.0
    assert reference.source_to_canonical_transform is not None
    assert reference.source_to_canonical_transform[0, 0] == 1.0
    assert not reference.source_to_canonical_transform.flags.writeable
    with pytest.raises(ValueError):
        reference.source_to_canonical_transform.flags.writeable = True
    with pytest.raises(ValueError, match="read-only"):
        reference.source_to_canonical_transform[0, 0] = 4.0


@pytest.mark.parametrize("scale", [0, -1, np.nan, np.inf, True, "1"])
def test_coordinate_reference_rejects_invalid_scale(scale: object) -> None:
    with pytest.raises(ValueError, match="source_unit_to_m"):
        CoordinateReference(source_unit_to_m=scale)  # type: ignore[arg-type]


def test_coordinate_reference_requires_complete_valid_origin() -> None:
    with pytest.raises(ValueError, match="all required"):
        CoordinateReference(origin_latitude_deg=52.0)
    with pytest.raises(ValueError, match="latitude"):
        CoordinateReference(
            origin_latitude_deg=91.0,
            origin_longitude_deg=1.0,
            origin_altitude_m=0.0,
        )


@pytest.mark.parametrize(
    "transform",
    [
        np.eye(3),
        np.full((4, 4), np.nan),
        np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 1, 1]]),
    ],
)
def test_coordinate_reference_rejects_invalid_affine_transform(
    transform: npt.NDArray[np.generic],
) -> None:
    with pytest.raises(ValueError, match="source_to_canonical_transform"):
        CoordinateReference(source_to_canonical_transform=transform)  # type: ignore[arg-type]


def test_mesh_is_float64_int64_defensive_and_read_only() -> None:
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.int32)
    faces = np.array([[0, 1, 2]], dtype=np.int16)
    mesh = TriangleMesh(vertices, faces)  # type: ignore[arg-type]
    vertices[0, 0] = 20
    faces[0, 0] = 2
    assert mesh.vertices_enu_m.dtype == np.float64
    assert mesh.faces.dtype == np.int64
    assert mesh.vertices_enu_m[0, 0] == 0.0
    assert mesh.faces[0, 0] == 0
    assert not mesh.vertices_enu_m.flags.writeable
    assert not mesh.faces.flags.writeable
    with pytest.raises(ValueError):
        mesh.vertices_enu_m.flags.writeable = True
    with pytest.raises(ValueError):
        mesh.faces.flags.writeable = True
    with pytest.raises(ValueError, match="read-only"):
        mesh.vertices_enu_m[0, 0] = 4.0
    with pytest.raises(ValueError, match="read-only"):
        mesh.faces[0, 0] = 1


def test_empty_mesh_has_stable_shapes() -> None:
    mesh = TriangleMesh(np.empty((0, 3)), np.empty((0, 3), dtype=np.int64))
    assert mesh.vertices_enu_m.shape == (0, 3)
    assert mesh.faces.shape == (0, 3)


@pytest.mark.parametrize(
    ("vertices", "faces", "message"),
    [
        (np.array([0.0, 1.0, 2.0]), np.array([[0, 1, 2]]), "shape"),
        (np.zeros((3, 2)), np.array([[0, 1, 2]]), "shape"),
        (np.array([[0, 0, 0], [1, 0, 0], [0, np.nan, 0]]), np.array([[0, 1, 2]]), "finite"),
        (np.zeros((3, 3)), np.array([0, 1, 2]), "shape"),
        (np.zeros((3, 3)), np.zeros((1, 2), dtype=int), "shape"),
        (np.zeros((3, 3)), np.array([[-1, 1, 2]]), "negative"),
        (np.zeros((3, 3)), np.array([[0, 1, 3]]), "vertex count"),
        (np.zeros((3, 3)), np.array([[0, 1, 1]]), "distinct"),
        (np.zeros((3, 3)), np.array([[0.0, 1.0, 2.0]]), "integers"),
        (np.zeros((3, 3)), np.array([[False, True, True]]), "integers"),
    ],
)
def test_mesh_rejects_malformed_arrays(
    vertices: npt.NDArray[np.generic],
    faces: npt.NDArray[np.generic],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        TriangleMesh(vertices, faces)  # type: ignore[arg-type]


def test_mesh_rejects_mixed_empty_state() -> None:
    with pytest.raises(ValueError, match="both"):
        TriangleMesh(np.zeros((3, 3)), np.empty((0, 3), dtype=int))


def test_mesh_equality_is_array_safe() -> None:
    assert _mesh() == _mesh()
    assert _mesh() != TriangleMesh(
        np.array([[0, 0, 0], [2, 0, 0], [0, 1, 0]], dtype=float),
        np.array([[0, 1, 2]], dtype=int),
    )


@pytest.mark.parametrize("identifier", ["", " "])
def test_receiver_rejects_invalid_id(identifier: str) -> None:
    with pytest.raises(ValueError, match="receiver id"):
        _receiver(identifier)


@pytest.mark.parametrize(
    ("centre", "message"),
    [((0.0, 1.0), "length-3"), ((0.0, np.nan, 1.0), "finite"), ((0.0, True, 1.0), "non-Boolean")],
)
def test_receiver_rejects_invalid_centre(centre: tuple[object, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PVReceiver(
            id="receiver",
            mesh=_mesh(),
            centre_enu_m=centre,  # type: ignore[arg-type]
            normal_enu=(0, 0, 1),
            receiver_kind=ReceiverKind.MODULE,
        )


@pytest.mark.parametrize("normal", [(0, 0, 2), (0, 0, np.inf), (0, False, 1)])
def test_receiver_rejects_invalid_normal(normal: tuple[object, ...]) -> None:
    with pytest.raises(ValueError, match="normal_enu"):
        PVReceiver(
            id="receiver",
            mesh=_mesh(),
            centre_enu_m=(0, 0, 0),
            normal_enu=normal,  # type: ignore[arg-type]
            receiver_kind=ReceiverKind.UNKNOWN,
        )


def test_geometry_objects_are_frozen_and_do_not_infer_semantics() -> None:
    shading = ShadingObject(
        id="mesh-1",
        mesh=_mesh(),
        shadow_role=ShadowRole.UNKNOWN,
        semantic_category=None,
    )
    assert shading.shadow_role is ShadowRole.UNKNOWN
    assert shading.semantic_category is None
    with pytest.raises(FrozenInstanceError):
        shading.id = "changed"  # type: ignore[misc]


def test_valid_minimal_site_geometry_allows_empty_optional_collections() -> None:
    provenance = SourceProvenance(
        source_format="canonical-test",
        source_digest="sha256:test",
        geometry_revision="revision-1",
    )
    site = SiteGeometry(
        geometry_revision="revision-1",
        source_provenance=provenance,
        coordinate_reference=CoordinateReference(),
        pv_receivers=(_receiver(),),
    )
    assert site.coordinate_reference.canonical_frame == "ENU"
    assert site.coordinate_reference.canonical_unit == "m"
    assert site.terrain_surfaces == ()
    assert site.shading_objects == ()


@pytest.mark.parametrize("category", ["receiver", "terrain", "shading", "global"])
def test_site_rejects_duplicate_ids(category: str) -> None:
    receivers: tuple[PVReceiver, ...] = (_receiver("same"),)
    terrains: tuple[TerrainSurface, ...] = ()
    shading: tuple[ShadingObject, ...] = ()
    if category == "receiver":
        receivers = (_receiver("same"), _receiver("same"))
    elif category == "terrain":
        receivers = ()
        terrains = (TerrainSurface("same", _mesh()), TerrainSurface("same", _mesh()))
    elif category == "shading":
        receivers = ()
        shading = (
            ShadingObject("same", _mesh(), ShadowRole.UNKNOWN),
            ShadingObject("same", _mesh(), ShadowRole.OCCLUDER),
        )
    else:
        terrains = (TerrainSurface("same", _mesh()),)

    with pytest.raises(ValueError, match="globally unique"):
        SiteGeometry(
            geometry_revision="r1",
            source_provenance=SourceProvenance(),
            coordinate_reference=CoordinateReference(),
            pv_receivers=receivers,
            terrain_surfaces=terrains,
            shading_objects=shading,
        )


def test_site_preserves_importer_collection_order_and_copies_lists_to_tuples() -> None:
    receivers = [_receiver("z"), _receiver("a")]
    site = SiteGeometry(
        geometry_revision="r1",
        source_provenance=SourceProvenance(),
        coordinate_reference=CoordinateReference(),
        pv_receivers=receivers,  # type: ignore[arg-type]
    )
    receivers.reverse()
    assert tuple(receiver.id for receiver in site.pv_receivers) == ("z", "a")


def test_site_rejects_revision_mismatch() -> None:
    with pytest.raises(ValueError, match="must match"):
        SiteGeometry(
            geometry_revision="r1",
            source_provenance=SourceProvenance(geometry_revision="r2"),
            coordinate_reference=CoordinateReference(),
        )


def test_no_external_format_or_electrical_fields_leak_into_contract() -> None:
    fields = set(SiteGeometry.__dataclass_fields__)
    assert fields == {
        "geometry_revision",
        "source_provenance",
        "coordinate_reference",
        "pv_receivers",
        "terrain_surfaces",
        "shading_objects",
    }
    leaked = {"inverter", "mppt", "string", "collada", "pvcase", "frontend", "api"}
    assert not any(term in field.lower() for field in fields for term in leaked)
