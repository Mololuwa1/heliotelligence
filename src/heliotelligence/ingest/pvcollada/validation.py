"""Hostile-input controls and offline PVCollada 2.0 validation."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from io import BytesIO
from pathlib import Path

from lxml import etree, isoschematron  # type: ignore[import-untyped]

COLLADA_NAMESPACE = "http://www.collada.org/2008/03/COLLADASchema"
PVCOLLADA_NAMESPACE = "https://pvcollada.org/2026/XMLSchema"
PVCOLLADA_PROFILE = "PVCollada-2.0"
MAX_INPUT_BYTES = 50 * 1024 * 1024
MAX_XML_ELEMENTS = 200_000
MAX_GEOMETRIES = 20_000
MAX_NODES = 100_000
MAX_VERTICES = 5_000_000
MAX_FACES = 10_000_000
MAX_NUMERIC_VALUES = 30_000_000
MAX_RESOLVED_NODE_INSTANCES = 100_000
MAX_RESOLVED_GEOMETRY_INSTANCES = 500_000
MAX_INSTANCE_DEPTH = 128
_FORBIDDEN_DECLARATION = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


class PVColladaImportError(ValueError):
    """Base class for fatal PVCollada import failures."""


class PVColladaParseError(PVColladaImportError):
    """The input could not be parsed securely as XML."""


class PVColladaValidationError(PVColladaImportError):
    """The parsed document violates PVCollada or extraction invariants."""


class PVColladaResourceLimitError(PVColladaImportError):
    """The input exceeds a bounded ingestion resource limit."""


class PVColladaUnsupportedError(PVColladaImportError):
    """The input uses a generation or geometry feature outside S3."""


def parse_and_validate(data: bytes) -> etree._Element:
    """Securely parse bytes and run pinned offline XSD and Schematron rules."""
    if not isinstance(data, bytes):
        raise PVColladaParseError("PVCollada input must be bytes")
    if not data:
        raise PVColladaParseError("PVCollada input is empty")
    if len(data) > MAX_INPUT_BYTES:
        raise PVColladaResourceLimitError(
            f"PVCollada input exceeds {MAX_INPUT_BYTES} bytes"
        )
    if _FORBIDDEN_DECLARATION.search(data):
        raise PVColladaParseError("DOCTYPE and entity declarations are prohibited")
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        huge_tree=False,
        recover=False,
        remove_comments=False,
    )
    try:
        root = etree.parse(BytesIO(data), parser).getroot()
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise PVColladaParseError(_concise("malformed XML", str(exc))) from exc
    if root.getroottree().docinfo.doctype:
        raise PVColladaParseError("DOCTYPE declarations are prohibited")

    elements = sum(1 for _ in root.iter())
    if elements > MAX_XML_ELEMENTS:
        raise PVColladaResourceLimitError(
            f"document exceeds {MAX_XML_ELEMENTS} XML elements"
        )
    if etree.QName(root).namespace != COLLADA_NAMESPACE or etree.QName(root).localname != "COLLADA":
        raise PVColladaUnsupportedError("root must be COLLADA 1.5")
    if root.get("version") != "1.5.0":
        raise PVColladaUnsupportedError("only COLLADA version 1.5.0 is supported")
    namespace = {"c": COLLADA_NAMESPACE, "pv": PVCOLLADA_NAMESPACE}
    profiles = root.xpath(
        ".//c:technique[@profile=$profile]",
        namespaces=namespace,
        profile=PVCOLLADA_PROFILE,
    )
    if not profiles or not root.xpath(".//pv:*", namespaces=namespace):
        raise PVColladaUnsupportedError("PVCollada 2.0 profile and namespace are required")

    ids: set[str] = set()
    for element in root.xpath(".//*[@id]"):
        identifier = element.get("id")
        if identifier in ids:
            raise PVColladaValidationError(f"duplicate source id: {identifier}")
        ids.add(identifier)

    _validate_resource_counts(root, namespace)
    xsd, schematrons = _compiled_validators()
    tree = root.getroottree()
    if not xsd.validate(tree):
        raise PVColladaValidationError(_validation_message("XSD", xsd.error_log))
    for label, schematron in schematrons:
        if not schematron.validate(tree):
            raise PVColladaValidationError(_schematron_message(label, schematron))
    return root


def _validate_resource_counts(root: etree._Element, ns: dict[str, str]) -> None:
    limits = (
        ("geometry", int(root.xpath("count(.//c:geometry)", namespaces=ns)), MAX_GEOMETRIES),
        ("node", int(root.xpath("count(.//c:node)", namespaces=ns)), MAX_NODES),
    )
    for label, actual, maximum in limits:
        if actual > maximum:
            raise PVColladaResourceLimitError(f"document exceeds {maximum} {label} elements")
    numeric_total = 0
    for array in root.xpath(".//c:float_array | .//c:p | .//c:vcount", namespaces=ns):
        numeric_total += len((array.text or "").split())
        if numeric_total > MAX_NUMERIC_VALUES:
            raise PVColladaResourceLimitError(
                f"document exceeds {MAX_NUMERIC_VALUES} numeric values"
            )


@lru_cache(maxsize=1)
def _compiled_validators() -> tuple[
    etree.XMLSchema, tuple[tuple[str, isoschematron.Schematron], ...]
]:
    package = resources.files("heliotelligence.ingest.pvcollada.schemas")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    with resources.as_file(package) as directory:
        parser.resolvers.add(_OfflineSchemaResolver(directory))
        path = directory / "pvcollada_schema_2.0.xsd"
        xsd = etree.XMLSchema(etree.parse(str(path), parser))
    compiled: list[tuple[str, isoschematron.Schematron]] = []
    for label, filename in (
        ("structure Schematron", "pvcollada_structure_2.0.sch"),
        ("reference Schematron", "pvcollada_references_2.0.sch"),
        ("business Schematron", "pvcollada_business_2.0.sch"),
    ):
        with resources.as_file(package / filename) as path:
            compiled.append(
                (label, isoschematron.Schematron(etree.parse(str(path), parser), store_report=True))
            )
    return xsd, tuple(compiled)


class _OfflineSchemaResolver(etree.Resolver):  # type: ignore[misc]
    def __init__(self, directory: Path) -> None:
        super().__init__()
        self._directory = directory

    def resolve(self, url: str, public_id: str | None, context: object) -> object:
        del public_id
        if url == "http://www.w3.org/Math/XMLSchema/mathml2/mathml2.xsd":
            return self.resolve_filename(
                str(self._directory / "mathml2_geometry_stub.xsd"), context
            )
        if url in {
            "http://www.w3.org/2001/xml.xsd",
            "http://www.w3.org/2009/01/xml.xsd",
        }:
            return self.resolve_filename(str(self._directory / "xml.xsd"), context)
        if "://" in url:
            raise PVColladaValidationError(f"external schema resolution prohibited: {url}")
        return None


def _validation_message(label: str, error_log: etree._ListErrorLog) -> str:
    message = (
        error_log.last_error.message
        if error_log.last_error is not None
        else "validation failed"
    )
    return _concise(label, message)


def _schematron_message(label: str, validator: isoschematron.Schematron) -> str:
    report = validator.validation_report
    messages: list[str] = []
    if report is not None:
        messages = [
            " ".join(text.split())
            for text in report.xpath(
                "//svrl:failed-assert/svrl:text/text()",
                namespaces={"svrl": "http://purl.oclc.org/dsdl/svrl"},
            )[:3]
        ]
    return _concise(label, "; ".join(messages) or "validation failed")


def _concise(label: str, message: str) -> str:
    return f"{label}: {' '.join(message.split())[:500]}"
