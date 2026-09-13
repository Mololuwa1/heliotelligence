"""Secure, offline PVCollada 2.0 to canonical SiteGeometry adapter."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from lxml import etree  # type: ignore[import-untyped]

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
from heliotelligence.ingest.pvcollada import validation as _limits
from heliotelligence.ingest.pvcollada.mesh import ParsedMesh, parse_geometry
from heliotelligence.ingest.pvcollada.transforms import node_transform, transform_vertices
from heliotelligence.ingest.pvcollada.validation import (
    COLLADA_NAMESPACE,
    PVCOLLADA_NAMESPACE,
    PVCOLLADA_PROFILE,
    PVColladaImportError,
    PVColladaParseError,
    PVColladaResourceLimitError,
    PVColladaUnsupportedError,
    PVColladaValidationError,
    parse_and_validate,
)

_NS = {"c": COLLADA_NAMESPACE, "pv": PVCOLLADA_NAMESPACE}
_PVC_INSTANCE_TAGS = {
    "instance_post": "post",
    "instance_gap": "gap",
    "instance_inverter3d": "inverter3d",
    "instance_combiner_ac3d": "combiner_ac3d",
    "instance_combiner_dc3d": "combiner_dc3d",
    "instance_optimizer3d": "optimizer3d",
    "instance_transformer3d": "transformer3d",
    "instance_cable3d": "cable3d",
}


@dataclass(frozen=True)
class PVColladaDiagnostic:
    """Structured import facts kept outside the canonical geometry domain."""

    source_digest: str
    source_application: str | None
    document_version: str
    receiver_count: int
    terrain_count: int
    shading_object_count: int
    unsupported_extension_profiles: tuple[str, ...]
    ignored_electrical_content_present: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PVColladaImportResult:
    """Complete canonical result and bounded importer diagnostics."""

    site_geometry: SiteGeometry
    diagnostics: PVColladaDiagnostic


@dataclass
class _ExpansionBudget:
    """Bound resolved scene expansion independently of source XML size."""

    node_instances: int = 0
    geometry_instances: int = 0

    def follow_instance(
        self, reference: str, active_instance_stack: tuple[str, ...]
    ) -> tuple[str, ...]:
        if reference in active_instance_stack:
            raise PVColladaValidationError("cyclic instance_node reference")
        next_stack = active_instance_stack + (reference,)
        if len(next_stack) > _limits.MAX_INSTANCE_DEPTH:
            raise PVColladaResourceLimitError(
                f"resolved instance_node depth exceeds {_limits.MAX_INSTANCE_DEPTH}"
            )
        self.node_instances += 1
        if self.node_instances > _limits.MAX_RESOLVED_NODE_INSTANCES:
            raise PVColladaResourceLimitError(
                "resolved instance_node count exceeds "
                f"{_limits.MAX_RESOLVED_NODE_INSTANCES}"
            )
        return next_stack

    def resolve_geometry(self) -> None:
        self.geometry_instances += 1
        if self.geometry_instances > _limits.MAX_RESOLVED_GEOMETRY_INSTANCES:
            raise PVColladaResourceLimitError(
                "resolved geometry-instance count exceeds "
                f"{_limits.MAX_RESOLVED_GEOMETRY_INSTANCES}"
            )


@dataclass
class _SceneBuilder:
    root: etree._Element
    geometry_revision: str
    digest: str
    unit_to_m: float
    source_application: str | None
    geometry_models: dict[str, ParsedMesh]
    geometry_elements: dict[str, etree._Element]
    library_nodes: dict[str, etree._Element]
    terrains: list[TerrainSurface]
    receivers: list[PVReceiver]
    shading: list[ShadingObject]
    budget: _ExpansionBudget

    def provenance(self, source_object_id: str | None = None) -> SourceProvenance:
        return SourceProvenance(
            source_format="PVCollada",
            source_version="2.0",
            source_application=self.source_application,
            source_digest=self.digest,
            source_object_id=source_object_id,
            geometry_revision=self.geometry_revision,
        )

    def walk_node(
        self,
        node: etree._Element,
        parent_transform: npt.NDArray[np.float64],
        path: str,
        active_instance_stack: tuple[str, ...] = (),
    ) -> None:
        transform = parent_transform @ node_transform(node)
        node_id = node.get("id") or path
        node_name = node.get("name")
        for position, child in enumerate(node):
            if not isinstance(child.tag, str):
                continue
            if etree.QName(child).namespace != COLLADA_NAMESPACE:
                continue
            tag = etree.QName(child).localname
            child_path = f"{path}/{position}"
            if tag == "node":
                self.walk_node(child, transform, child_path, active_instance_stack)
            elif tag == "instance_geometry":
                self.add_geometry_instance(child, transform, node_id, node_name, child_path)
            elif tag == "instance_node":
                reference = _internal_reference(child.get("url"), "instance_node")
                next_stack = self.budget.follow_instance(reference, active_instance_stack)
                try:
                    referenced = self.library_nodes[reference]
                except KeyError as exc:
                    raise PVColladaValidationError(
                        f"dangling instance_node reference: {reference}"
                    ) from exc
                table = child.find(
                    f"c:extra/c:technique[@profile='{PVCOLLADA_PROFILE}']/pv:instance_table",
                    namespaces=_NS,
                )
                if table is not None:
                    self.add_table(referenced, transform, table, node_name, next_stack)
                else:
                    self.walk_node(referenced, transform, child_path, next_stack)

    def add_table(
        self,
        model: etree._Element,
        transform: npt.NDArray[np.float64],
        instance_table: etree._Element,
        source_name: str | None,
        active_instance_stack: tuple[str, ...],
    ) -> None:
        table_id = _required_id(instance_table, "instance_table")
        model_type = model.findtext(
            f"c:extra/c:technique[@profile='{PVCOLLADA_PROFILE}']/pv:table/pv:type",
            namespaces=_NS,
        )
        kind = {
            "fixed": ReceiverKind.FIXED_TABLE,
            "tracker": ReceiverKind.TRACKER_TABLE,
        }.get(model_type)
        if kind is None:
            raise PVColladaValidationError("table type must be fixed or tracker")
        rack_parts: list[tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]] = []

        def collect(
            node: etree._Element,
            parent: npt.NDArray[np.float64],
            path: str,
            stack: tuple[str, ...],
        ) -> None:
            current = parent @ node_transform(node)
            for position, child in enumerate(node):
                if not isinstance(child.tag, str):
                    continue
                if etree.QName(child).namespace != COLLADA_NAMESPACE:
                    continue
                tag = etree.QName(child).localname
                child_path = f"{path}/{position}"
                if tag == "node":
                    collect(child, current, child_path, stack)
                elif tag == "instance_geometry":
                    marker = _pvc_instance_marker(child)
                    if marker == "instance_rack":
                        self.budget.resolve_geometry()
                        geometry_id, parsed = self.resolve_geometry(child)
                        rack_type = self.geometry_elements[geometry_id].findtext(
                            f"c:extra/c:technique[@profile='{PVCOLLADA_PROFILE}']/pv:rack/pv:rack_type",
                            namespaces=_NS,
                        )
                        expected = "fixed_tilt" if kind is ReceiverKind.FIXED_TABLE else "tracker"
                        if rack_type != expected:
                            raise PVColladaValidationError(
                                "rack type is inconsistent with table type"
                            )
                        rack_parts.append(
                            (
                                transform_vertices(parsed.vertices, current, self.unit_to_m),
                                parsed.faces,
                            )
                        )
                    else:
                        self.add_geometry_instance(
                            child,
                            current,
                            table_id,
                            source_name,
                            f"{table_id}:{child_path}",
                        )
                elif tag == "instance_node":
                    reference = _internal_reference(child.get("url"), "instance_node")
                    next_stack = self.budget.follow_instance(reference, stack)
                    try:
                        nested = self.library_nodes[reference]
                    except KeyError as exc:
                        raise PVColladaValidationError(
                            f"dangling instance_node reference: {reference}"
                        ) from exc
                    collect(nested, current, child_path, next_stack)

        collect(model, transform, table_id, active_instance_stack)
        if not rack_parts:
            raise PVColladaValidationError(f"table {table_id} has no rack receiving geometry")
        mesh = _combine_meshes(rack_parts)
        normal = _mesh_normal(mesh)
        centre_values = np.mean(mesh.vertices_enu_m, axis=0)
        centre = (
            float(centre_values[0]),
            float(centre_values[1]),
            float(centre_values[2]),
        )
        self.receivers.append(
            PVReceiver(
                id=f"receiver:{table_id}",
                mesh=mesh,
                centre_enu_m=centre,
                normal_enu=normal,
                receiver_kind=kind,
                provenance=self.provenance(table_id),
                source_semantic_name=source_name,
            )
        )

    def resolve_geometry(self, instance: etree._Element) -> tuple[str, ParsedMesh]:
        geometry_id = _internal_reference(instance.get("url"), "instance_geometry")
        try:
            return geometry_id, self.geometry_models[geometry_id]
        except KeyError as exc:
            raise PVColladaValidationError(
                f"dangling instance_geometry reference: {geometry_id}"
            ) from exc

    def add_geometry_instance(
        self,
        instance: etree._Element,
        transform: npt.NDArray[np.float64],
        owner_id: str,
        source_name: str | None,
        path: str,
    ) -> None:
        self.budget.resolve_geometry()
        geometry_id, parsed = self.resolve_geometry(instance)
        vertices = transform_vertices(parsed.vertices, transform, self.unit_to_m)
        mesh = TriangleMesh(vertices, parsed.faces)
        marker = _pvc_instance_marker(instance)
        marker_element = _pvc_instance_element(instance)
        source_id = marker_element.get("id") if marker_element is not None else None
        semantic = _geometry_semantic(self.geometry_elements[geometry_id])
        if marker == "instance_terrain" and semantic == "terrain":
            object_id = source_id or f"{owner_id}:{geometry_id}:{path}"
            self.terrains.append(
                TerrainSurface(
                    id=f"terrain:{object_id}",
                    mesh=mesh,
                    provenance=self.provenance(object_id),
                    source_semantic_name=source_name,
                )
            )
        elif marker in _PVC_INSTANCE_TAGS and semantic == _PVC_INSTANCE_TAGS[marker]:
            object_id = f"{owner_id}:{source_id or geometry_id}:{path}"
            self.shading.append(
                ShadingObject(
                    id=f"object:{object_id}",
                    mesh=mesh,
                    shadow_role=ShadowRole.UNKNOWN,
                    provenance=self.provenance(source_id or geometry_id),
                    semantic_category=semantic,
                    source_semantic_name=source_name,
                )
            )


def import_pvcollada_2(data: bytes, *, geometry_revision: str) -> PVColladaImportResult:
    """Validate hostile `.pvc2` bytes and construct complete canonical geometry."""
    if not isinstance(geometry_revision, str) or not geometry_revision.strip():
        raise PVColladaValidationError("geometry_revision must be non-empty")
    root = parse_and_validate(data)
    digest = hashlib.sha256(data).hexdigest()
    unit = root.find("c:asset/c:unit", namespaces=_NS)
    if unit is None:
        raise PVColladaValidationError("COLLADA asset unit is required")
    try:
        unit_to_m = float(unit.get("meter", ""))
    except ValueError as exc:
        raise PVColladaValidationError("unit meter scale is malformed") from exc
    if not np.isfinite(unit_to_m) or unit_to_m <= 0.0:
        raise PVColladaValidationError("unit meter scale must be finite and positive")
    up_axis = root.findtext("c:asset/c:up_axis", namespaces=_NS)
    if up_axis != "Z_UP":
        raise PVColladaValidationError("PVCollada 2.0 requires Z_UP")

    application = _optional_text(
        root.findtext(
            f"c:asset/c:extra/c:technique[@profile='{PVCOLLADA_PROFILE}']/pv:software/pv:source",
            namespaces=_NS,
        )
    )
    geometries = root.xpath("./c:library_geometries/c:geometry", namespaces=_NS)
    geometry_elements = {_required_id(item, "geometry"): item for item in geometries}
    geometry_models = {
        identifier: parse_geometry(item) for identifier, item in geometry_elements.items()
    }
    library_nodes = {
        _required_id(item, "library node"): item
        for item in root.xpath("./c:library_nodes/c:node", namespaces=_NS)
    }
    builder = _SceneBuilder(
        root=root,
        geometry_revision=geometry_revision,
        digest=digest,
        unit_to_m=unit_to_m,
        source_application=application,
        geometry_models=geometry_models,
        geometry_elements=geometry_elements,
        library_nodes=library_nodes,
        terrains=[],
        receivers=[],
        shading=[],
        budget=_ExpansionBudget(),
    )
    scene_instance = root.find("c:scene/c:instance_visual_scene", namespaces=_NS)
    if scene_instance is None:
        raise PVColladaValidationError("active visual scene is required")
    scene_id = _internal_reference(scene_instance.get("url"), "instance_visual_scene")
    scenes = {
        _required_id(item, "visual_scene"): item
        for item in root.xpath("./c:library_visual_scenes/c:visual_scene", namespaces=_NS)
    }
    try:
        scene = scenes[scene_id]
    except KeyError as exc:
        raise PVColladaValidationError(f"dangling visual scene reference: {scene_id}") from exc
    for position, node in enumerate(scene.findall(f"{{{COLLADA_NAMESPACE}}}node")):
        builder.walk_node(node, np.eye(4), f"scene:{scene_id}/{position}")

    origin = _geographic_origin(root)
    source_crs = _optional_text(
        root.findtext(
            f"c:asset/c:extra/c:technique[@profile='{PVCOLLADA_PROFILE}']/pv:project/pv:local_projection",
            namespaces=_NS,
        )
    )
    source_transform = np.diag([unit_to_m, unit_to_m, unit_to_m, 1.0])
    coordinate_reference = CoordinateReference(
        source_unit=unit.get("name"),
        source_unit_to_m=unit_to_m,
        source_up_axis=up_axis,
        source_crs=source_crs,
        origin_latitude_deg=origin[0] if origin else None,
        origin_longitude_deg=origin[1] if origin else None,
        origin_altitude_m=origin[2] if origin else None,
        source_to_canonical_transform=source_transform,
    )
    provenance = builder.provenance()
    site = SiteGeometry(
        geometry_revision=geometry_revision,
        source_provenance=provenance,
        coordinate_reference=coordinate_reference,
        pv_receivers=tuple(builder.receivers),
        terrain_surfaces=tuple(builder.terrains),
        shading_objects=tuple(builder.shading),
    )
    unsupported = tuple(
        dict.fromkeys(
            profile
            for profile in root.xpath(".//c:technique/@profile", namespaces=_NS)
            if profile not in {PVCOLLADA_PROFILE, "COMMON"}
        )
    )
    electrical = bool(
        root.xpath(
            ".//pv:circuit | .//pv:instance_inverter | .//pv:instance_transformer",
            namespaces=_NS,
        )
    )
    diagnostics = PVColladaDiagnostic(
        source_digest=digest,
        source_application=application,
        document_version="2.0",
        receiver_count=len(builder.receivers),
        terrain_count=len(builder.terrains),
        shading_object_count=len(builder.shading),
        unsupported_extension_profiles=unsupported,
        ignored_electrical_content_present=electrical,
    )
    return PVColladaImportResult(site_geometry=site, diagnostics=diagnostics)


def _combine_meshes(
    parts: list[tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]],
) -> TriangleMesh:
    vertices: list[npt.NDArray[np.float64]] = []
    faces: list[npt.NDArray[np.int64]] = []
    offset = 0
    for part_vertices, part_faces in parts:
        vertices.append(part_vertices)
        faces.append(part_faces + offset)
        offset += part_vertices.shape[0]
    return TriangleMesh(np.vstack(vertices), np.vstack(faces))


def _mesh_normal(mesh: TriangleMesh) -> tuple[float, float, float]:
    triangles = mesh.vertices_enu_m[mesh.faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normal = np.sum(normals, axis=0)
    norm = float(np.linalg.norm(normal))
    if not np.isfinite(norm) or norm <= 1e-12:
        raise PVColladaValidationError("receiver geometry has no stable surface normal")
    unit = normal / norm
    return float(unit[0]), float(unit[1]), float(unit[2])


def _geographic_origin(root: etree._Element) -> tuple[float, float, float] | None:
    location = root.find("c:asset/c:coverage/c:geographic_location", namespaces=_NS)
    if location is None:
        return None
    altitude = location.find("c:altitude", namespaces=_NS)
    if altitude is None or altitude.get("mode") != "absolute":
        raise PVColladaValidationError("geographic altitude must use absolute mode")
    try:
        longitude = float(location.findtext("c:longitude", namespaces=_NS) or "")
        latitude = float(location.findtext("c:latitude", namespaces=_NS) or "")
        altitude_value = float(altitude.text or "")
    except ValueError as exc:
        raise PVColladaValidationError("geographic origin contains malformed values") from exc
    return latitude, longitude, altitude_value


def _geometry_semantic(geometry: etree._Element) -> str | None:
    technique = geometry.find(
        f"c:extra/c:technique[@profile='{PVCOLLADA_PROFILE}']", namespaces=_NS
    )
    if technique is None:
        return None
    children = [
        child
        for child in technique
        if isinstance(child.tag, str) and etree.QName(child).namespace == PVCOLLADA_NAMESPACE
    ]
    return etree.QName(children[0]).localname if len(children) == 1 else None


def _pvc_instance_element(instance: etree._Element) -> etree._Element | None:
    elements = instance.xpath(
        f"./c:extra/c:technique[@profile='{PVCOLLADA_PROFILE}']/pv:*", namespaces=_NS
    )
    return elements[0] if len(elements) == 1 else None


def _pvc_instance_marker(instance: etree._Element) -> str | None:
    element = _pvc_instance_element(instance)
    return etree.QName(element).localname if element is not None else None


def _required_id(element: etree._Element, label: str) -> str:
    identifier = element.get("id")
    if not identifier:
        raise PVColladaValidationError(f"{label} requires an id")
    return str(identifier)


def _internal_reference(value: str | None, label: str) -> str:
    if not value or not value.startswith("#") or len(value) == 1:
        raise PVColladaUnsupportedError(f"{label} must use an internal fragment reference")
    return value[1:]


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "PVColladaDiagnostic",
    "PVColladaImportError",
    "PVColladaImportResult",
    "PVColladaParseError",
    "PVColladaResourceLimitError",
    "PVColladaUnsupportedError",
    "PVColladaValidationError",
    "import_pvcollada_2",
]
