"""Dormant P1 output/persistence boundary; no physics execution or database I/O.

Tuple order is explicit caller provenance order, never silently normalised. Wire
arrays use lists, while admitted records contain only frozen objects and tuples.
The redundant timestamp identity detects inconsistent persisted timezone edits;
this format is not a cryptographic authenticity mechanism.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import timedelta, timezone
from numbers import Real
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.engine.expected_energy_source import (
    LEGACY_EXPECTED_ENERGY_SOURCE,
    validate_expected_energy_source,
)

PHYSICAL_SHADOW_OUTPUT_CONTRACT_ID = "canonical_physical_shadow_run_output_contract_v1"
PHYSICAL_SHADOW_OUTPUT_SCOPE = (
    "timestamped_site_model_boundary_physical_output_"
    "before_shadow_execution_or_production_selection"
)
PHYSICAL_SHADOW_TIMESTAMP_SEMANTICS = "instantaneous_physical_model_state"
FULL_FIDELITY = "full_declared_physical_path"
LOWER_FIDELITY = "explicit_lower_fidelity_physical_path"
UNRESOLVED_FIDELITY = "unresolved_physical_path"
RESOLVED = "resolved_physical_output"
PARTIAL = "partial_physical_output"
UNRESOLVED = "unresolved_physical_output"


def _text(value: object) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("identifier must be an exact non-empty unpadded str")


def _uuid(value: object) -> None:
    _text(value)
    if str(UUID(str(value))) != value:
        raise ValueError("UUID must use canonical lowercase hyphenated string form")


def _ids(value: object) -> None:
    if type(value) is not tuple:
        raise ValueError("identifiers must be an immutable tuple")
    for item in value:
        _text(item)
    if len(set(value)) != len(value):
        raise ValueError("duplicate identifiers")


def _timezone_spec(timestamp: pd.Timestamp) -> dict[str, Any]:
    tz = timestamp.tz
    if isinstance(tz, timezone):
        offset = tz.utcoffset(None)
        if offset is None:
            raise ValueError("unrepresentable fixed timezone")
        return {"kind": "fixed_offset", "name": str(tz), "offset_seconds": offset.total_seconds()}
    name = getattr(tz, "key", None) or getattr(tz, "zone", None)
    if type(name) is not str:
        raise ValueError("timezone must have an exact IANA identity or fixed offset")
    ZoneInfo(name)
    return {"kind": "named", "name": name}


def _timestamp_wire(timestamp: pd.Timestamp) -> dict[str, Any]:
    if type(timestamp) is not pd.Timestamp or pd.isna(timestamp) or timestamp.tz is None:
        raise ValueError("timestamp must be an exact aware non-NaT pandas.Timestamp")
    try:
        ns = timestamp.value
    except (OverflowError, ValueError) as exc:
        raise ValueError("timestamp must be exactly representable in UTC nanoseconds") from exc
    spec = _timezone_spec(timestamp)
    return {
        "timestamp_utc_ns": ns,
        "timestamp_timezone": spec,
        "timestamp_identity": timestamp.isoformat() + "|" + json.dumps(spec, sort_keys=True),
    }


@dataclass(frozen=True, slots=True)
class PhysicalShadowRunIdentity:
    run_id: str
    site_id: str
    model_source: str
    model_version: str
    code_revision: str

    def __post_init__(self) -> None:
        _uuid(self.run_id)
        _uuid(self.site_id)
        validate_expected_energy_source(self.model_source)
        if self.model_source == LEGACY_EXPECTED_ENERGY_SOURCE:
            raise ValueError("legacy compatibility source cannot identify a physical run")
        _text(self.model_version)
        _text(self.code_revision)


@dataclass(frozen=True, slots=True)
class PhysicalShadowOutputProvenance:
    upstream_contract_ids: tuple[str, ...]
    upstream_model_ids: tuple[str, ...]
    authority_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (
            self.upstream_contract_ids,
            self.upstream_model_ids,
            self.authority_evidence_ids,
        ):
            _ids(value)


@dataclass(frozen=True, slots=True)
class PhysicalShadowOutputRecord:
    run_identity: PhysicalShadowRunIdentity
    timestamp: pd.Timestamp
    reference_plane: str
    boundary_id: str
    active_power_resolved: bool
    active_power_w: float | None
    reactive_power_resolved: bool
    reactive_power_var: float | None
    active_power_sign_convention: str
    reactive_power_sign_convention: str
    power_basis: str
    fidelity_class: str
    fidelity_id: str | None
    fallback_applied: bool
    fallback_id: str | None
    active_power_unresolved_reason_codes: tuple[str, ...]
    reactive_power_unresolved_reason_codes: tuple[str, ...]
    provenance: PhysicalShadowOutputProvenance
    apparent_power_va: float | None = field(init=False)
    overall_state: str = field(init=False)
    timestamp_semantics: str = field(init=False, default=PHYSICAL_SHADOW_TIMESTAMP_SEMANTICS)
    active_power_unit: str = field(init=False, default="W")
    reactive_power_unit: str = field(init=False, default="var")
    apparent_power_unit: str = field(init=False, default="VA")
    contract: str = field(init=False, default=PHYSICAL_SHADOW_OUTPUT_CONTRACT_ID)
    scope: str = field(init=False, default=PHYSICAL_SHADOW_OUTPUT_SCOPE)

    def __post_init__(self) -> None:
        if type(self.run_identity) is not PhysicalShadowRunIdentity:
            raise ValueError("exact run identity required")
        self.run_identity.__post_init__()
        if type(self.provenance) is not PhysicalShadowOutputProvenance:
            raise ValueError("exact provenance required")
        self.provenance.__post_init__()
        _timestamp_wire(self.timestamp)
        for semantic in (
            self.reference_plane,
            self.boundary_id,
            self.active_power_sign_convention,
            self.reactive_power_sign_convention,
            self.power_basis,
            self.fidelity_class,
        ):
            _text(semantic)
        for name, resolved, value, reasons in (
            (
                "active_power_w",
                self.active_power_resolved,
                self.active_power_w,
                self.active_power_unresolved_reason_codes,
            ),
            (
                "reactive_power_var",
                self.reactive_power_resolved,
                self.reactive_power_var,
                self.reactive_power_unresolved_reason_codes,
            ),
        ):
            _ids(reasons)
            if type(resolved) is not bool:
                raise ValueError("channel resolution must be exact bool")
            if resolved:
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise ValueError("resolved channel requires finite real power")
                try:
                    numeric = float(value)
                except (OverflowError, ValueError) as exc:
                    raise ValueError(
                        "power must have a finite engineering-unit representation"
                    ) from exc
                if not math.isfinite(numeric):
                    raise ValueError("resolved channel requires finite real power")
                object.__setattr__(self, name, numeric)
                if reasons:
                    raise ValueError("resolved channel cannot have unresolved reasons")
            elif value is not None or not reasons:
                raise ValueError("unresolved channel requires None and explicit reasons")
        available = self.active_power_resolved + self.reactive_power_resolved
        if available and (
            not self.provenance.upstream_contract_ids or not self.provenance.upstream_model_ids
        ):
            raise ValueError("resolved power requires upstream contracts and models")
        if self.fidelity_class not in (FULL_FIDELITY, LOWER_FIDELITY, UNRESOLVED_FIDELITY):
            raise ValueError("unsupported fidelity class")
        if self.fidelity_class == UNRESOLVED_FIDELITY:
            if available or self.fidelity_id is not None:
                raise ValueError("unresolved path requires no resolved channels and no fidelity ID")
        else:
            _text(self.fidelity_id)
        if type(self.fallback_applied) is not bool:
            raise ValueError("fallback_applied must be exact bool")
        if self.fallback_applied:
            _text(self.fallback_id)
            if (
                self.fidelity_class != LOWER_FIDELITY
                or self.fallback_id == LEGACY_EXPECTED_ENERGY_SOURCE
            ):
                raise ValueError("fallback requires explicit lower-fidelity physics, never legacy")
        elif self.fallback_id is not None:
            raise ValueError("non-fallback forbids fallback ID")
        apparent = None
        if available == 2:
            assert self.active_power_w is not None and self.reactive_power_var is not None
            apparent = math.hypot(self.active_power_w, self.reactive_power_var)
            if not math.isfinite(apparent):
                raise ValueError("nonfinite apparent power")
        object.__setattr__(self, "apparent_power_va", apparent)
        object.__setattr__(self, "overall_state", (UNRESOLVED, PARTIAL, RESOLVED)[available])


def validate_physical_shadow_output(record: PhysicalShadowOutputRecord) -> None:
    """Independently audit a record, including forged frozen/derived fields.

    Deliberately does not call constructors, __post_init__, admission helpers or
    the serializer. Timestamp persistence identity is reconstructed here as well.
    """
    if type(record) is not PhysicalShadowOutputRecord:
        raise ValueError("exact physical record required")
    identity = record.run_identity
    if type(identity) is not PhysicalShadowRunIdentity:
        raise ValueError("invalid run identity")
    for value in (identity.run_id, identity.site_id):
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError("noncanonical UUID")
    for value in (
        identity.model_source,
        identity.model_version,
        identity.code_revision,
        record.reference_plane,
        record.boundary_id,
        record.active_power_sign_convention,
        record.reactive_power_sign_convention,
        record.power_basis,
        record.fidelity_class,
    ):
        if type(value) is not str or not value or value.strip() != value:
            raise ValueError("invalid identifier")
    if identity.model_source == "physics_sdm":
        raise ValueError("reserved compatibility source")
    timestamp = record.timestamp
    if type(timestamp) is not pd.Timestamp or pd.isna(timestamp) or timestamp.tz is None:
        raise ValueError("invalid timestamp")
    try:
        ns = timestamp.value
        tz = timestamp.tz
        if isinstance(tz, timezone):
            offset = tz.utcoffset(None)
            if offset is None:
                raise ValueError("invalid timezone offset")
            restored_tz = timezone(offset, str(tz))
        else:
            zone_name = getattr(tz, "key", None) or getattr(tz, "zone", None)
            if type(zone_name) is not str:
                raise ValueError("unrepresentable timezone identity")
            restored_tz = ZoneInfo(zone_name)  # type: ignore[assignment]
        restored = pd.Timestamp(ns, tz="UTC").tz_convert(restored_tz)
        if (
            restored != timestamp
            or str(restored.tz) != str(timestamp.tz)
            or restored.isoformat() != timestamp.isoformat()
        ):
            raise ValueError("timestamp persistence is not lossless")
    except (OverflowError, TypeError) as exc:
        raise ValueError("unrepresentable timestamp") from exc
    provenance = record.provenance
    if type(provenance) is not PhysicalShadowOutputProvenance:
        raise ValueError("invalid provenance")
    tuples = (
        provenance.upstream_contract_ids,
        provenance.upstream_model_ids,
        provenance.authority_evidence_ids,
        record.active_power_unresolved_reason_codes,
        record.reactive_power_unresolved_reason_codes,
    )
    for values in tuples:
        if type(values) is not tuple:
            raise ValueError("immutable identifier tuple required")
        for value in values:
            if type(value) is not str or not value or value != value.strip():
                raise ValueError("invalid identifier tuple member")
        if len(set(values)) != len(values):
            raise ValueError("duplicate identifier")
    count = 0
    for resolved, power, reasons in (
        (
            record.active_power_resolved,
            record.active_power_w,
            record.active_power_unresolved_reason_codes,
        ),
        (
            record.reactive_power_resolved,
            record.reactive_power_var,
            record.reactive_power_unresolved_reason_codes,
        ),
    ):
        if type(resolved) is not bool:
            raise ValueError("nonboolean resolution")
        if resolved:
            if type(power) is not float or not math.isfinite(power) or reasons:
                raise ValueError("invalid resolved channel")
            count += 1
        elif power is not None or not reasons:
            raise ValueError("invalid unresolved channel")
    if count and (not provenance.upstream_contract_ids or not provenance.upstream_model_ids):
        raise ValueError("missing physical provenance")
    if record.fidelity_class == UNRESOLVED_FIDELITY:
        if count or record.fidelity_id is not None:
            raise ValueError("unresolved fidelity contradiction")
    elif record.fidelity_class in (FULL_FIDELITY, LOWER_FIDELITY):
        if (
            type(record.fidelity_id) is not str
            or not record.fidelity_id
            or record.fidelity_id.strip() != record.fidelity_id
        ):
            raise ValueError("missing fidelity ID")
    else:
        raise ValueError("unknown fidelity")
    if type(record.fallback_applied) is not bool:
        raise ValueError("nonboolean fallback")
    if record.fallback_applied:
        if (
            record.fidelity_class != LOWER_FIDELITY
            or record.fallback_id == "physics_sdm"
            or type(record.fallback_id) is not str
            or not record.fallback_id
            or record.fallback_id.strip() != record.fallback_id
        ):
            raise ValueError("invalid fallback")
    elif record.fallback_id is not None:
        raise ValueError("unexpected fallback ID")
    expected_state = RESOLVED if count == 2 else PARTIAL if count == 1 else UNRESOLVED
    if type(record.overall_state) is not str or record.overall_state != expected_state:
        raise ValueError("overall state contradiction")
    expected_s = None
    if count == 2:
        assert record.active_power_w is not None and record.reactive_power_var is not None
        expected_s = math.hypot(record.active_power_w, record.reactive_power_var)
        if not math.isfinite(expected_s):
            raise ValueError("nonfinite apparent power")
    if expected_s is None:
        if record.apparent_power_va is not None:
            raise ValueError("apparent power without both channels")
    elif type(record.apparent_power_va) is not float or record.apparent_power_va != expected_s:
        raise ValueError("apparent power contradiction")
    for actual, expected in (
        (record.timestamp_semantics, PHYSICAL_SHADOW_TIMESTAMP_SEMANTICS),
        (record.active_power_unit, "W"),
        (record.reactive_power_unit, "var"),
        (record.apparent_power_unit, "VA"),
        (record.contract, PHYSICAL_SHADOW_OUTPUT_CONTRACT_ID),
        (record.scope, PHYSICAL_SHADOW_OUTPUT_SCOPE),
    ):
        if type(actual) is not str or actual != expected:
            raise ValueError("fixed semantics contradiction")


@dataclass(frozen=True, slots=True)
class PhysicalShadowOutputDiagnostics:
    total_record_count: int
    resolved_count: int
    partial_count: int
    unresolved_count: int
    full_fidelity_count: int
    lower_fidelity_count: int
    unresolved_fidelity_count: int
    fallback_count: int
    reference_plane_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class PhysicalShadowOutputBatch:
    """Ordered records, possibly from several runs; one identity per run UUID."""

    records: tuple[PhysicalShadowOutputRecord, ...]
    diagnostics: PhysicalShadowOutputDiagnostics = field(init=False)

    def __post_init__(self) -> None:
        if type(self.records) is not tuple:
            raise ValueError("records must be immutable tuple")
        keys: set[tuple[str, pd.Timestamp, str, str]] = set()
        identities: dict[str, PhysicalShadowRunIdentity] = {}
        for record in self.records:
            validate_physical_shadow_output(record)
            identity = record.run_identity
            if identity.run_id in identities and identities[identity.run_id] != identity:
                raise ValueError("one run UUID cannot describe conflicting model identities")
            identities[identity.run_id] = identity
            key = (identity.run_id, record.timestamp, record.reference_plane, record.boundary_id)
            if key in keys:
                raise ValueError("duplicate canonical output identity")
            keys.add(key)
        object.__setattr__(
            self,
            "diagnostics",
            PhysicalShadowOutputDiagnostics(
                len(self.records),
                sum(r.overall_state == RESOLVED for r in self.records),
                sum(r.overall_state == PARTIAL for r in self.records),
                sum(r.overall_state == UNRESOLVED for r in self.records),
                sum(r.fidelity_class == FULL_FIDELITY for r in self.records),
                sum(r.fidelity_class == LOWER_FIDELITY for r in self.records),
                sum(r.fidelity_class == UNRESOLVED_FIDELITY for r in self.records),
                sum(r.fallback_applied for r in self.records),
                tuple(sorted(Counter(r.reference_plane for r in self.records).items())),
            ),
        )


def validate_physical_shadow_output_batch(batch: PhysicalShadowOutputBatch) -> None:
    """Replay collection identity and counts without invoking its constructor."""
    if type(batch) is not PhysicalShadowOutputBatch or type(batch.records) is not tuple:
        raise ValueError("exact immutable batch required")
    seen: set[tuple[str, pd.Timestamp, str, str]] = set()
    runs: dict[str, PhysicalShadowRunIdentity] = {}
    counts = [0] * 8
    planes: dict[str, int] = {}
    for r in batch.records:
        validate_physical_shadow_output(r)
        key = (r.run_identity.run_id, r.timestamp, r.reference_plane, r.boundary_id)
        if key in seen or (
            r.run_identity.run_id in runs and runs[r.run_identity.run_id] != r.run_identity
        ):
            raise ValueError("duplicate output or conflicting run identity")
        seen.add(key)
        runs[r.run_identity.run_id] = r.run_identity
        counts[0] += 1
        counts[{RESOLVED: 1, PARTIAL: 2, UNRESOLVED: 3}[r.overall_state]] += 1
        counts[{FULL_FIDELITY: 4, LOWER_FIDELITY: 5, UNRESOLVED_FIDELITY: 6}[r.fidelity_class]] += 1
        counts[7] += int(r.fallback_applied)
        planes[r.reference_plane] = planes.get(r.reference_plane, 0) + 1
    d = batch.diagnostics
    if type(d) is not PhysicalShadowOutputDiagnostics:
        raise ValueError("invalid diagnostics")
    expected: tuple[object, ...] = (*counts, tuple(sorted(planes.items())))
    for descriptor, value in zip(fields(d), expected, strict=True):
        actual = getattr(d, descriptor.name)
        if type(actual) is not type(value) or actual != value:
            raise ValueError("diagnostics contradiction")
    if any(type(k) is not str or type(n) is not int for k, n in d.reference_plane_counts):
        raise ValueError("malformed plane counts")


def serialize_physical_shadow_output(record: PhysicalShadowOutputRecord) -> dict[str, Any]:
    """Return a deterministic JSON-safe record, including checked derived fields."""
    validate_physical_shadow_output(record)
    output: dict[str, Any] = {}
    for descriptor in fields(record):
        name = descriptor.name
        value = getattr(record, name)
        if name == "run_identity":
            output[name] = {f.name: getattr(value, f.name) for f in fields(value)}
        elif name == "provenance":
            output[name] = {f.name: list(getattr(value, f.name)) for f in fields(value)}
        elif name == "timestamp":
            output[name] = _timestamp_wire(value)
        elif isinstance(value, tuple):
            output[name] = list(value)
        elif name in ("active_power_w", "reactive_power_var") and value is not None:
            converted = float(value)
            if converted != value:
                raise ValueError("power not losslessly representable as persistence float")
            output[name] = converted
        else:
            output[name] = value
    return output


def deserialize_physical_shadow_output(payload: Mapping[str, Any]) -> PhysicalShadowOutputRecord:
    """Strict wire admission; stored states/units/S must agree with derivation."""
    if not isinstance(payload, Mapping) or set(payload) != {
        f.name for f in fields(PhysicalShadowOutputRecord)
    }:
        raise ValueError("invalid persisted record schema")
    values = dict(payload)
    raw_identity = values["run_identity"]
    raw_provenance = values["provenance"]
    if type(raw_identity) is not dict or set(raw_identity) != {
        f.name for f in fields(PhysicalShadowRunIdentity)
    }:
        raise ValueError("invalid persisted identity")
    if type(raw_provenance) is not dict or set(raw_provenance) != {
        f.name for f in fields(PhysicalShadowOutputProvenance)
    }:
        raise ValueError("invalid persisted provenance")
    for items in raw_provenance.values():
        if type(items) is not list:
            raise ValueError("persisted provenance must use arrays")
    for name in ("active_power_unresolved_reason_codes", "reactive_power_unresolved_reason_codes"):
        if type(values[name]) is not list:
            raise ValueError("persisted reasons must use arrays")
        values[name] = tuple(values[name])
    raw_time = values["timestamp"]
    if type(raw_time) is not dict or set(raw_time) != {
        "timestamp_utc_ns",
        "timestamp_timezone",
        "timestamp_identity",
    }:
        raise ValueError("invalid persisted timestamp schema")
    ns, spec = raw_time["timestamp_utc_ns"], raw_time["timestamp_timezone"]
    if type(ns) is not int or type(spec) is not dict:
        raise ValueError("invalid persisted timestamp identity")
    try:
        if spec.get("kind") == "named" and set(spec) == {"kind", "name"}:
            _text(spec["name"])
            tz: Any = ZoneInfo(spec["name"])
        elif spec.get("kind") == "fixed_offset" and set(spec) == {"kind", "name", "offset_seconds"}:
            _text(spec["name"])
            seconds = spec["offset_seconds"]
            if type(seconds) not in (int, float) or not math.isfinite(seconds):
                raise ValueError("invalid persisted timezone offset")
            tz = timezone(timedelta(seconds=seconds), spec["name"])
        else:
            raise ValueError("invalid persisted timezone schema")
        timestamp = pd.Timestamp(ns, tz="UTC").tz_convert(tz)
        if _timestamp_wire(timestamp) != raw_time:
            raise ValueError("inconsistent persisted timestamp/timezone")
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("invalid persisted timestamp") from exc
    values["timestamp"] = timestamp
    values["run_identity"] = PhysicalShadowRunIdentity(**raw_identity)
    values["provenance"] = PhysicalShadowOutputProvenance(
        **{k: tuple(v) for k, v in raw_provenance.items()}
    )
    record = PhysicalShadowOutputRecord(
        **{f.name: values[f.name] for f in fields(PhysicalShadowOutputRecord) if f.init}
    )
    for f in fields(record):
        if not f.init:
            actual, expected = values[f.name], getattr(record, f.name)
            if type(actual) is not type(expected) or actual != expected:
                raise ValueError("persisted derived state contradicts canonical record")
    validate_physical_shadow_output(record)
    return record
