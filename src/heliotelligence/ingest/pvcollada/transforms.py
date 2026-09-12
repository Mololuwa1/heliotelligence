"""COLLADA transform composition using column vectors and ordered matrices."""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
from lxml import etree  # type: ignore[import-untyped]

from heliotelligence.ingest.pvcollada.validation import (
    COLLADA_NAMESPACE,
    PVColladaValidationError,
)

_TRANSFORM_TAGS = {"matrix", "translate", "rotate", "scale"}


def node_transform(node: etree._Element) -> npt.NDArray[np.float64]:
    """Return the ordered local transform for one COLLADA node."""
    result = np.eye(4, dtype=np.float64)
    for child in node:
        if not isinstance(child.tag, str):
            continue
        tag = etree.QName(child).localname
        if etree.QName(child).namespace != COLLADA_NAMESPACE or tag not in _TRANSFORM_TAGS:
            continue
        values = _finite_values(child)
        operation = np.eye(4, dtype=np.float64)
        if tag == "matrix":
            if len(values) != 16:
                raise PVColladaValidationError("matrix transform must contain 16 values")
            operation = np.asarray(values, dtype=np.float64).reshape((4, 4), order="F")
            if not np.allclose(operation[3], (0.0, 0.0, 0.0, 1.0)):
                raise PVColladaValidationError("matrix transform must be homogeneous affine")
        elif tag == "translate":
            if len(values) != 3:
                raise PVColladaValidationError("translate transform must contain 3 values")
            operation[:3, 3] = values
        elif tag == "scale":
            if len(values) != 3:
                raise PVColladaValidationError("scale transform must contain 3 values")
            operation[0, 0], operation[1, 1], operation[2, 2] = values
        else:
            if len(values) != 4:
                raise PVColladaValidationError("rotate transform must contain 4 values")
            axis = np.asarray(values[:3], dtype=np.float64)
            norm = float(np.linalg.norm(axis))
            if norm == 0.0:
                raise PVColladaValidationError("rotate transform axis must be non-zero")
            x, y, z = axis / norm
            angle = math.radians(values[3])
            c, s, one_minus_c = math.cos(angle), math.sin(angle), 1.0 - math.cos(angle)
            operation[:3, :3] = (
                (c + x * x * one_minus_c, x * y * one_minus_c - z * s, x * z * one_minus_c + y * s),
                (y * x * one_minus_c + z * s, c + y * y * one_minus_c, y * z * one_minus_c - x * s),
                (z * x * one_minus_c - y * s, z * y * one_minus_c + x * s, c + z * z * one_minus_c),
            )
        result = result @ operation
    if not np.isfinite(result).all():
        raise PVColladaValidationError("node transform contains non-finite values")
    return result


def transform_vertices(
    vertices: npt.NDArray[np.float64],
    transform: npt.NDArray[np.float64],
    unit_to_m: float,
) -> npt.NDArray[np.float64]:
    """Apply a source-space affine transform, then normalize coordinates to metres."""
    homogeneous = np.column_stack((vertices, np.ones(vertices.shape[0])))
    transformed = (transform @ homogeneous.T).T[:, :3] * unit_to_m
    if not np.isfinite(transformed).all():
        raise PVColladaValidationError("transformed geometry contains non-finite values")
    return np.asarray(transformed, dtype=np.float64)


def _finite_values(element: etree._Element) -> list[float]:
    try:
        values = [float(value) for value in (element.text or "").split()]
    except ValueError as exc:
        raise PVColladaValidationError("transform contains malformed numeric data") from exc
    if not all(math.isfinite(value) for value in values):
        raise PVColladaValidationError("transform contains non-finite values")
    return values
