"""Deterministic COLLADA position-source and triangle extraction."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from lxml import etree  # type: ignore[import-untyped]

from heliotelligence.ingest.pvcollada.validation import (
    COLLADA_NAMESPACE,
    MAX_FACES,
    MAX_VERTICES,
    PVColladaResourceLimitError,
    PVColladaUnsupportedError,
    PVColladaValidationError,
)

_NS = {"c": COLLADA_NAMESPACE}


@dataclass(frozen=True)
class ParsedMesh:
    """Reusable source-space triangle mesh."""

    vertices: npt.NDArray[np.float64]
    faces: npt.NDArray[np.int64]


def parse_geometry(geometry: etree._Element) -> ParsedMesh:
    """Extract one COLLADA mesh using POSITION/VERTEX primitive inputs."""
    mesh = geometry.find(f"{{{COLLADA_NAMESPACE}}}mesh")
    if mesh is None:
        raise PVColladaUnsupportedError("geometry must contain a mesh")
    sources = {
        _required_id(source): _parse_source(source)
        for source in mesh.findall(f"{{{COLLADA_NAMESPACE}}}source")
    }
    vertices_map: dict[str, str] = {}
    for vertices in mesh.findall(f"{{{COLLADA_NAMESPACE}}}vertices"):
        identifier = _required_id(vertices)
        inputs = vertices.xpath("./c:input[@semantic='POSITION']", namespaces=_NS)
        if len(inputs) != 1:
            raise PVColladaValidationError("vertices must have exactly one POSITION input")
        vertices_map[identifier] = _internal_reference(inputs[0].get("source"), "POSITION")

    selected_source: str | None = None
    polygons: list[list[int]] = []
    for primitive in mesh:
        if not isinstance(primitive.tag, str):
            continue
        kind = etree.QName(primitive).localname
        if etree.QName(primitive).namespace != COLLADA_NAMESPACE:
            continue
        if kind not in {"triangles", "polylist", "polygons"}:
            if kind in {"lines", "linestrips", "trifans", "tristrips"}:
                raise PVColladaUnsupportedError(f"unsupported COLLADA primitive: {kind}")
            continue
        source_id, offset, stride = _position_input(primitive, vertices_map)
        if source_id not in sources:
            raise PVColladaValidationError(f"dangling position source: {source_id}")
        if selected_source is None:
            selected_source = source_id
        elif selected_source != source_id:
            raise PVColladaUnsupportedError(
                "one geometry using multiple position sources is unsupported"
            )
        if kind == "triangles":
            p = primitive.find(f"{{{COLLADA_NAMESPACE}}}p")
            indices = _primitive_indices(p, offset, stride)
            if len(indices) % 3:
                raise PVColladaValidationError("triangles index count must be divisible by 3")
            polygons.extend(indices[index : index + 3] for index in range(0, len(indices), 3))
        elif kind == "polylist":
            vcount = _integer_text(primitive.find(f"{{{COLLADA_NAMESPACE}}}vcount"), "vcount")
            indices = _primitive_indices(
                primitive.find(f"{{{COLLADA_NAMESPACE}}}p"), offset, stride
            )
            cursor = 0
            for count in vcount:
                if count < 3 or cursor + count > len(indices):
                    raise PVColladaValidationError("polylist has inconsistent vcount")
                polygons.append(indices[cursor : cursor + count])
                cursor += count
            if cursor != len(indices):
                raise PVColladaValidationError("polylist indices exceed vcount")
        else:
            if primitive.find(f"{{{COLLADA_NAMESPACE}}}ph") is not None:
                raise PVColladaUnsupportedError("polygons with holes are unsupported")
            polygons.extend(
                _primitive_indices(p, offset, stride)
                for p in primitive.findall(f"{{{COLLADA_NAMESPACE}}}p")
            )
    if selected_source is None or not polygons:
        raise PVColladaValidationError("geometry has no supported position primitives")
    vertices = sources[selected_source]
    faces: list[tuple[int, int, int]] = []
    for polygon in polygons:
        faces.extend(_triangulate_polygon(polygon, vertices))
        if len(faces) > MAX_FACES:
            raise PVColladaResourceLimitError(f"geometry exceeds {MAX_FACES} faces")
    result = np.asarray(faces, dtype=np.int64)
    if np.any(result < 0) or np.any(result >= vertices.shape[0]):
        raise PVColladaValidationError("primitive contains out-of-range vertex index")
    return ParsedMesh(vertices=vertices, faces=result)


def _parse_source(source: etree._Element) -> npt.NDArray[np.float64]:
    arrays = source.findall(f"{{{COLLADA_NAMESPACE}}}float_array")
    accessor = source.find(
        f"{{{COLLADA_NAMESPACE}}}technique_common/{{{COLLADA_NAMESPACE}}}accessor"
    )
    if len(arrays) != 1 or accessor is None:
        raise PVColladaValidationError("position source requires one float_array and accessor")
    array = arrays[0]
    values = _float_text(array, "float_array")
    declared = _positive_int(array.get("count"), "float_array count", allow_zero=True)
    if declared != len(values):
        raise PVColladaValidationError("float_array count does not match data")
    stride = _positive_int(accessor.get("stride", "1"), "accessor stride")
    offset = _positive_int(accessor.get("offset", "0"), "accessor offset", allow_zero=True)
    count = _positive_int(accessor.get("count"), "accessor count", allow_zero=True)
    params = accessor.findall(f"{{{COLLADA_NAMESPACE}}}param")
    names = [param.get("name") for param in params]
    try:
        positions = [names.index(axis) for axis in ("X", "Y", "Z")]
    except ValueError as exc:
        raise PVColladaValidationError("position accessor must expose X, Y, and Z") from exc
    if any(position >= stride for position in positions) or offset + count * stride > len(values):
        raise PVColladaValidationError("accessor exceeds float_array bounds")
    if count > MAX_VERTICES:
        raise PVColladaResourceLimitError(f"geometry exceeds {MAX_VERTICES} vertices")
    output = np.empty((count, 3), dtype=np.float64)
    for row in range(count):
        start = offset + row * stride
        output[row] = [values[start + position] for position in positions]
    return output


def _position_input(
    primitive: etree._Element, vertices_map: dict[str, str]
) -> tuple[str, int, int]:
    inputs = primitive.findall(f"{{{COLLADA_NAMESPACE}}}input")
    if not inputs:
        raise PVColladaValidationError("primitive requires inputs")
    offsets = [
        _positive_int(item.get("offset", "0"), "input offset", allow_zero=True)
        for item in inputs
    ]
    candidates = [item for item in inputs if item.get("semantic") in {"VERTEX", "POSITION"}]
    if len(candidates) != 1:
        raise PVColladaValidationError("primitive requires exactly one VERTEX or POSITION input")
    item = candidates[0]
    source = _internal_reference(item.get("source"), "primitive")
    if item.get("semantic") == "VERTEX":
        try:
            source = vertices_map[source]
        except KeyError as exc:
            raise PVColladaValidationError(f"dangling vertices reference: {source}") from exc
    return (
        source,
        _positive_int(item.get("offset", "0"), "input offset", allow_zero=True),
        max(offsets) + 1,
    )


def _primitive_indices(element: etree._Element | None, offset: int, stride: int) -> list[int]:
    values = _integer_text(element, "primitive indices")
    if len(values) % stride:
        raise PVColladaValidationError("primitive index stream is inconsistent with input offsets")
    return values[offset::stride]


def _triangulate_polygon(
    indices: list[int], vertices: npt.NDArray[np.float64]
) -> list[tuple[int, int, int]]:
    if len(indices) > 3 and indices[0] == indices[-1]:
        indices = indices[:-1]
    if len(indices) < 3 or len(set(indices)) != len(indices):
        raise PVColladaValidationError("polygon must contain at least three distinct vertices")
    if any(index < 0 or index >= vertices.shape[0] for index in indices):
        raise PVColladaValidationError("primitive contains out-of-range vertex index")
    points = vertices[indices]
    normal = np.zeros(3)
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        normal += np.cross(point, following)
    norm = float(np.linalg.norm(normal))
    if norm <= 1e-12:
        raise PVColladaUnsupportedError("degenerate polygon cannot be triangulated")
    unit_normal = normal / norm
    scale = max(1.0, float(np.ptp(points, axis=0).max()))
    if np.max(np.abs((points - points[0]) @ unit_normal)) > 1e-9 * scale:
        raise PVColladaUnsupportedError("non-planar polygon cannot be triangulated safely")
    axis = int(np.argmax(np.abs(unit_normal)))
    projected = np.delete(points, axis, axis=1)
    signs: list[float] = []
    for index in range(len(projected)):
        a, b, c = projected[index - 1], projected[index], projected[(index + 1) % len(projected)]
        first = b - a
        second = c - b
        cross = float(first[0] * second[1] - first[1] * second[0])
        if abs(cross) > 1e-12:
            signs.append(cross)
    if not signs or (min(signs) < 0.0 < max(signs)):
        raise PVColladaUnsupportedError("non-convex polygon cannot be triangulated safely")
    return [
        (indices[0], indices[index], indices[index + 1])
        for index in range(1, len(indices) - 1)
    ]


def _required_id(element: etree._Element) -> str:
    identifier = element.get("id")
    if not identifier:
        raise PVColladaValidationError("source element requires an id")
    return str(identifier)


def _internal_reference(value: str | None, label: str) -> str:
    if not value or not value.startswith("#") or len(value) == 1:
        raise PVColladaUnsupportedError(f"{label} reference must be an internal fragment")
    return value[1:]


def _float_text(element: etree._Element | None, label: str) -> list[float]:
    if element is None:
        raise PVColladaValidationError(f"missing {label}")
    try:
        values = [float(item) for item in (element.text or "").split()]
    except ValueError as exc:
        raise PVColladaValidationError(f"malformed {label}") from exc
    if not np.isfinite(values).all():
        raise PVColladaValidationError(f"non-finite {label}")
    return values


def _integer_text(element: etree._Element | None, label: str) -> list[int]:
    if element is None:
        raise PVColladaValidationError(f"missing {label}")
    try:
        return [int(item) for item in (element.text or "").split()]
    except ValueError as exc:
        raise PVColladaValidationError(f"malformed {label}") from exc


def _positive_int(value: str | None, label: str, *, allow_zero: bool = False) -> int:
    try:
        result = int(value) if value is not None else -1
    except ValueError as exc:
        raise PVColladaValidationError(f"malformed {label}") from exc
    if result < (0 if allow_zero else 1):
        raise PVColladaValidationError(f"invalid {label}")
    return result
