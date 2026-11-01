"""P1 represents physical output without selecting or executing a physical model."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta, timezone
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.engine import physical_shadow_output_contract as p1


def identity(**changes: Any) -> p1.PhysicalShadowRunIdentity:
    values = dict(
        run_id="6fa459ea-ee8a-3ca4-894e-db77e160355e",
        site_id="7c9e6679-7425-40de-944b-e07fc1f90ae7",
        model_source="test-only-explicit-series",
        model_version="declared-model-v1",
        code_revision="reviewed-revision-reference",
    )
    values.update(changes)
    return p1.PhysicalShadowRunIdentity(**values)


def record(**changes: Any) -> p1.PhysicalShadowOutputRecord:
    values = dict(
        run_identity=identity(),
        timestamp=pd.Timestamp("2027-06-01 12:00:00.000000123", tz="Europe/London"),
        reference_plane="revenue_meter_boundary",
        boundary_id="explicit-meter-id",
        active_power_resolved=True,
        active_power_w=3000.0,
        reactive_power_resolved=True,
        reactive_power_var=4000.0,
        active_power_sign_convention="positive_plant_to_grid",
        reactive_power_sign_convention="positive_plant_to_grid",
        power_basis="three_phase_total",
        fidelity_class=p1.FULL_FIDELITY,
        fidelity_id="declared-admitted-path",
        fallback_applied=False,
        fallback_id=None,
        active_power_unresolved_reason_codes=(),
        reactive_power_unresolved_reason_codes=(),
        provenance=p1.PhysicalShadowOutputProvenance(
            ("upstream-contract-v1",), ("upstream-model-v1",)
        ),
    )
    values.update(changes)
    return p1.PhysicalShadowOutputRecord(**values)


@pytest.mark.parametrize("field", ["run_id", "site_id"])
@pytest.mark.parametrize(
    "value",
    [
        "site-slug",
        "",
        " 7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "7C9E6679-7425-40DE-944B-E07FC1F90AE7",
        "7c9e6679742540de944be07fc1f90ae7",
        123,
        None,
    ],
)
def test_uuid_admission(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        identity(**{field: value})


@pytest.mark.parametrize("field", ["model_source", "model_version", "code_revision"])
@pytest.mark.parametrize("value", ["", " padded", "padded ", 123, None, True])
def test_exact_model_identity(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        identity(**{field: value})


def test_no_source_default_or_legacy_fallback() -> None:
    assert identity().code_revision == "reviewed-revision-reference"
    with pytest.raises(ValueError):
        identity(model_source="physics_sdm")
    for field in ("model_version", "code_revision"):
        values = {f.name: getattr(identity(), f.name) for f in fields(identity())}
        del values[field]
        with pytest.raises(TypeError):
            p1.PhysicalShadowRunIdentity(**values)


@pytest.mark.parametrize(
    "timestamp", [pd.Timestamp("2027-01-01"), pd.NaT, "2027-01-01T00:00:00Z", None]
)
def test_invalid_timestamp(timestamp: object) -> None:
    with pytest.raises(ValueError):
        record(timestamp=timestamp)


@pytest.mark.parametrize(
    "timestamp",
    [
        pd.Timestamp("2027-01-01 00:00:00.000000001", tz="UTC"),
        pd.Timestamp("2027-06-01 00:00:00.000000123", tz="Europe/London"),
        pd.Timestamp("2026-10-25 00:30:00.000000456", tz="UTC").tz_convert("Europe/London"),
        pd.Timestamp("2026-10-25 01:30:00.000000456", tz="UTC").tz_convert("Europe/London"),
        pd.Timestamp("2027-01-01", tz=timezone(timedelta(hours=5, minutes=30), "explicit-offset")),
    ],
)
def test_exact_timestamp_and_wire_roundtrip(timestamp: pd.Timestamp) -> None:
    original = record(timestamp=timestamp)
    wire = p1.serialize_physical_shadow_output(original)
    restored = p1.deserialize_physical_shadow_output(json.loads(json.dumps(wire, allow_nan=False)))
    assert restored == original
    assert restored.timestamp.value == timestamp.value
    assert str(restored.timestamp.tz) == str(timestamp.tz)
    assert restored.timestamp.isoformat() == timestamp.isoformat()
    assert p1.serialize_physical_shadow_output(restored) == wire
    assert original.timestamp_semantics == p1.PHYSICAL_SHADOW_TIMESTAMP_SEMANTICS


def test_out_of_nanosecond_range_rejected() -> None:
    with pytest.raises((ValueError, OverflowError)):
        record(timestamp=pd.Timestamp("9999-01-01", tz="UTC"))


@pytest.mark.parametrize("p,q", [(3000.0, 4000.0), (-3000.0, -4000.0), (0.0, 0.0), (0.0, -4000.0)])
def test_resolved_pq(p: float, q: float) -> None:
    r = record(active_power_w=p, reactive_power_var=q)
    assert r.overall_state == p1.RESOLVED
    assert r.apparent_power_va == math.hypot(p, q)
    assert (r.active_power_unit, r.reactive_power_unit, r.apparent_power_unit) == ("W", "var", "VA")
    p1.validate_physical_shadow_output(r)


@pytest.mark.parametrize("p_ok,q_ok", [(True, False), (False, True), (False, False)])
def test_partial_and_unresolved_channels(p_ok: bool, q_ok: bool) -> None:
    r = record(
        active_power_resolved=p_ok,
        active_power_w=0.0 if p_ok else None,
        reactive_power_resolved=q_ok,
        reactive_power_var=0.0 if q_ok else None,
        active_power_unresolved_reason_codes=() if p_ok else ("unresolved_active_parent",),
        reactive_power_unresolved_reason_codes=() if q_ok else ("unresolved_reactive_parent",),
        fidelity_class=p1.FULL_FIDELITY if p_ok or q_ok else p1.UNRESOLVED_FIDELITY,
        fidelity_id="declared-path" if p_ok or q_ok else None,
    )
    assert r.overall_state == (p1.PARTIAL if p_ok or q_ok else p1.UNRESOLVED)
    assert r.apparent_power_va is None
    assert p1.deserialize_physical_shadow_output(p1.serialize_physical_shadow_output(r)) == r


@pytest.mark.parametrize(
    "channel,value_field,reason_field",
    [
        ("active_power_resolved", "active_power_w", "active_power_unresolved_reason_codes"),
        ("reactive_power_resolved", "reactive_power_var", "reactive_power_unresolved_reason_codes"),
    ],
)
@pytest.mark.parametrize("value", [0.0, float("nan"), 1.0, False])
def test_unresolved_value_must_be_absent(
    channel: str, value_field: str, reason_field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        record(**{channel: False, value_field: value, reason_field: ("missing",)})


@pytest.mark.parametrize("field", ["active_power_w", "reactive_power_var"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "123", None])
def test_resolved_requires_finite_real(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        record(**{field: value})


@pytest.mark.parametrize(
    "field", ["active_power_resolved", "reactive_power_resolved", "fallback_applied"]
)
@pytest.mark.parametrize("value", [1, "true", None])
def test_flags_are_exact_boolean(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        record(**{field: value})


@pytest.mark.parametrize(
    "reasons", [(), ("duplicate", "duplicate"), ("",), (" padded",), ["missing"], (12,)]
)
def test_unresolved_reasons_admission(reasons: object) -> None:
    with pytest.raises(ValueError):
        record(
            active_power_resolved=False,
            active_power_w=None,
            active_power_unresolved_reason_codes=reasons,
        )


def test_reason_order_preserved_and_resolved_forbids_reasons() -> None:
    r = record(
        active_power_resolved=False,
        active_power_w=None,
        active_power_unresolved_reason_codes=("z_reason", "a_reason"),
    )
    assert r.active_power_unresolved_reason_codes == ("z_reason", "a_reason")
    with pytest.raises(ValueError):
        record(active_power_unresolved_reason_codes=("contradiction",))


@pytest.mark.parametrize(
    "field",
    [
        "reference_plane",
        "boundary_id",
        "active_power_sign_convention",
        "reactive_power_sign_convention",
        "power_basis",
    ],
)
@pytest.mark.parametrize("value", ["", " padded", 1, None])
def test_boundary_and_power_semantics_explicit(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        record(**{field: value})


@pytest.mark.parametrize(
    "plane",
    [
        "inverter_ac_output",
        "lv_ac_collection_exit",
        "transformer_network_side_terminal",
        "mv_hv_transformer_terminal_node",
        "grid_interconnection_boundary",
        "revenue_meter_boundary",
        "future_explicit_plane",
    ],
)
def test_plane_never_inferred_from_source(plane: str) -> None:
    r = record(reference_plane=plane)
    assert r.reference_plane == plane
    assert r.run_identity.model_source == identity().model_source


@pytest.mark.parametrize(
    "changes",
    [
        {"fidelity_class": "unknown"},
        {"fidelity_id": None},
        {"fidelity_id": ""},
        {"fidelity_class": p1.LOWER_FIDELITY, "fidelity_id": None},
        {"fidelity_class": p1.UNRESOLVED_FIDELITY, "fidelity_id": None},
        {"fallback_applied": True, "fallback_id": "explicit-fallback"},
        {"fallback_applied": True, "fidelity_class": p1.LOWER_FIDELITY},
        {"fallback_id": "unexpected"},
    ],
)
def test_fidelity_fallback_invariants(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        record(**changes)


def test_s12m_fidelity_is_carried_without_redefinition() -> None:
    # Published S12M IDs are payload, not a new P1 physics/fidelity vocabulary.
    advanced = record(fidelity_id="coupled_advanced_load_loss")
    fallback = record(
        fidelity_class=p1.LOWER_FIDELITY,
        fidelity_id="coupled_s12g_load_loss_fallback",
        fallback_applied=True,
        fallback_id="coupled_s12g_load_loss_fallback",
    )
    assert advanced.fidelity_id == "coupled_advanced_load_loss"
    assert fallback.fidelity_id == fallback.fallback_id == "coupled_s12g_load_loss_fallback"
    assert fallback.reference_plane == advanced.reference_plane


def test_hypot_overflow_rejected() -> None:
    with pytest.raises(ValueError):
        record(active_power_w=1.7e308, reactive_power_var=1.7e308)


@pytest.mark.parametrize("values", [["contract"], ("",), (" padded",), ("same", "same"), (12,)])
def test_provenance_tuple_validation(values: Any) -> None:
    with pytest.raises(ValueError):
        p1.PhysicalShadowOutputProvenance(values, ("model",))


def test_provenance_and_records_are_frozen() -> None:
    r = record()
    for obj, key, value in [
        (r, "active_power_w", 1.0),
        (r.run_identity, "site_id", "slug"),
        (r.provenance, "upstream_model_ids", ("other",)),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, key, value)
    with pytest.raises(ValueError):
        record(provenance=p1.PhysicalShadowOutputProvenance((), ()))
    unresolved = record(
        active_power_resolved=False,
        active_power_w=None,
        reactive_power_resolved=False,
        reactive_power_var=None,
        active_power_unresolved_reason_codes=("missing",),
        reactive_power_unresolved_reason_codes=("missing",),
        fidelity_class=p1.UNRESOLVED_FIDELITY,
        fidelity_id=None,
        provenance=p1.PhysicalShadowOutputProvenance((), ()),
    )
    p1.validate_physical_shadow_output(unresolved)


def test_batch_identity_and_diagnostics() -> None:
    first = record()
    second = replace(
        first,
        timestamp=first.timestamp + pd.Timedelta(seconds=1),
        active_power_resolved=False,
        active_power_w=None,
        active_power_unresolved_reason_codes=("missing",),
    )
    third = replace(
        first,
        reference_plane="transformer_network_side_terminal",
        fidelity_class=p1.LOWER_FIDELITY,
        fidelity_id="explicit-physical-fallback",
        fallback_applied=True,
        fallback_id="upstream-fallback",
    )
    fourth = replace(
        second,
        timestamp=first.timestamp + pd.Timedelta(seconds=2),
        reactive_power_resolved=False,
        reactive_power_var=None,
        reactive_power_unresolved_reason_codes=("missing_q",),
        fidelity_class=p1.UNRESOLVED_FIDELITY,
        fidelity_id=None,
    )
    batch = p1.PhysicalShadowOutputBatch((first, second, third, fourth))
    d = batch.diagnostics
    assert (d.total_record_count, d.resolved_count, d.partial_count, d.unresolved_count) == (
        4,
        2,
        1,
        1,
    )
    assert (
        d.full_fidelity_count,
        d.lower_fidelity_count,
        d.unresolved_fidelity_count,
        d.fallback_count,
    ) == (2, 1, 1, 1)
    assert d.reference_plane_counts == (
        ("revenue_meter_boundary", 3),
        ("transformer_network_side_terminal", 1),
    )
    restored = p1.PhysicalShadowOutputBatch(
        tuple(
            p1.deserialize_physical_shadow_output(p1.serialize_physical_shadow_output(r))
            for r in batch.records
        )
    )
    assert restored == batch
    p1.validate_physical_shadow_output_batch(batch)
    assert p1.PhysicalShadowOutputBatch(()).diagnostics.total_record_count == 0
    with pytest.raises(ValueError):
        p1.PhysicalShadowOutputBatch((first, first))
    with pytest.raises(ValueError):
        p1.PhysicalShadowOutputBatch(
            (first, replace(first, timestamp=first.timestamp.tz_convert("UTC")))
        )
    with pytest.raises(ValueError):
        p1.PhysicalShadowOutputBatch(
            (
                first,
                replace(
                    second, run_identity=replace(first.run_identity, model_version="conflicting")
                ),
            )
        )
    with pytest.raises(ValueError):
        p1.PhysicalShadowOutputBatch([first])  # type: ignore[arg-type]


@pytest.mark.parametrize("field", [f.name for f in fields(p1.PhysicalShadowOutputRecord)])
def test_every_record_field_tamper_rejected(field: str) -> None:
    r = record()
    object.__setattr__(r, field, None if getattr(r, field) is not None else "forged")
    with pytest.raises((ValueError, TypeError, AttributeError)):
        p1.validate_physical_shadow_output(r)
    with pytest.raises((ValueError, TypeError, AttributeError)):
        p1.serialize_physical_shadow_output(r)


@pytest.mark.parametrize("field", [f.name for f in fields(p1.PhysicalShadowRunIdentity)])
def test_nested_identity_tamper_rejected(field: str) -> None:
    r = record()
    object.__setattr__(
        r.run_identity, field, "physics_sdm" if field == "model_source" else " padded"
    )
    with pytest.raises(ValueError):
        p1.validate_physical_shadow_output(r)
    with pytest.raises(ValueError):
        replace(r)


@pytest.mark.parametrize("field", [f.name for f in fields(p1.PhysicalShadowOutputProvenance)])
def test_nested_provenance_tamper_rejected(field: str) -> None:
    r = record()
    object.__setattr__(r.provenance, field, ["mutable"])
    with pytest.raises(ValueError):
        p1.validate_physical_shadow_output(r)
    with pytest.raises(ValueError):
        replace(r)


@pytest.mark.parametrize("field", [f.name for f in fields(p1.PhysicalShadowOutputDiagnostics)])
def test_every_diagnostic_tamper_rejected(field: str) -> None:
    batch = p1.PhysicalShadowOutputBatch((record(),))
    object.__setattr__(batch.diagnostics, field, () if field == "reference_plane_counts" else 999)
    with pytest.raises(ValueError):
        p1.validate_physical_shadow_output_batch(batch)


@pytest.mark.parametrize(
    "field,value",
    [
        ("overall_state", p1.UNRESOLVED),
        ("apparent_power_va", 0.0),
        ("active_power_resolved", False),
        ("active_power_w", None),
        ("active_power_unit", "kW"),
        ("contract", "forged"),
        ("scope", "forged"),
        ("extra_field", True),
        ("active_power_unresolved_reason_codes", ()),
    ],
)
def test_persisted_contradictions_rejected(field: str, value: Any) -> None:
    wire = p1.serialize_physical_shadow_output(record())
    wire[field] = value
    with pytest.raises(ValueError):
        p1.deserialize_physical_shadow_output(wire)


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy",
        "timezone",
        "nanoseconds",
        "identity",
        "provenance_tuple",
        "provenance_duplicate",
        "missing_key",
    ],
)
def test_nested_wire_tampering(mutation: str) -> None:
    wire = copy.deepcopy(p1.serialize_physical_shadow_output(record()))
    if mutation == "legacy":
        wire["run_identity"]["model_source"] = "physics_sdm"
    elif mutation == "timezone":
        wire["timestamp"]["timestamp_timezone"]["name"] = "UTC"
    elif mutation == "nanoseconds":
        wire["timestamp"]["timestamp_utc_ns"] += 1
    elif mutation == "identity":
        wire["timestamp"]["timestamp_identity"] = "forged"
    elif mutation == "provenance_tuple":
        wire["provenance"]["upstream_model_ids"] = ("model",)
    elif mutation == "provenance_duplicate":
        wire["provenance"]["upstream_model_ids"] = ["same", "same"]
    else:
        del wire["timestamp"]["timestamp_utc_ns"]
    with pytest.raises(ValueError):
        p1.deserialize_physical_shadow_output(wire)


def test_independent_validator_without_production_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    r = record()
    batch = p1.PhysicalShadowOutputBatch((r,))

    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper called")

    for name in (
        "_text",
        "_uuid",
        "_ids",
        "_timestamp_wire",
        "_timezone_spec",
        "serialize_physical_shadow_output",
        "deserialize_physical_shadow_output",
    ):
        monkeypatch.setattr(p1, name, disabled)
    for cls in (
        p1.PhysicalShadowRunIdentity,
        p1.PhysicalShadowOutputProvenance,
        p1.PhysicalShadowOutputRecord,
        p1.PhysicalShadowOutputBatch,
    ):
        monkeypatch.setattr(cls, "__post_init__", disabled)
    p1.validate_physical_shadow_output(r)
    p1.validate_physical_shadow_output_batch(batch)


def test_exact_type_and_nested_admission() -> None:
    class Text(str):
        pass

    with pytest.raises(ValueError):
        identity(model_source=Text("physical-series"))
    with pytest.raises(ValueError):
        record(fidelity_class=Text(p1.FULL_FIDELITY))
    with pytest.raises(ValueError):
        record(run_identity={"run_id": identity().run_id})
    with pytest.raises(ValueError):
        record(provenance={"upstream_contract_ids": ["contract"]})
    with pytest.raises(ValueError):
        record(fallback_applied=True, fallback_id="physics_sdm", fidelity_class=p1.LOWER_FIDELITY)
    numeric = record(active_power_w=3, reactive_power_var=4)
    assert type(numeric.active_power_w) is float
    assert numeric.apparent_power_va == 5.0
    assert (
        p1.deserialize_physical_shadow_output(p1.serialize_physical_shadow_output(numeric))
        == numeric
    )


def test_same_offset_timezone_tamper_still_rejected() -> None:
    wire = p1.serialize_physical_shadow_output(
        record(timestamp=pd.Timestamp("2027-01-01", tz="Europe/London"))
    )
    wire["timestamp"]["timestamp_timezone"]["name"] = "Etc/GMT"
    with pytest.raises(ValueError, match="timestamp/timezone"):
        p1.deserialize_physical_shadow_output(wire)


@pytest.mark.parametrize("field", ["active_power_w", "reactive_power_var"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1"])
def test_wire_invalid_numeric_values(field: str, value: Any) -> None:
    wire = p1.serialize_physical_shadow_output(record())
    wire[field] = value
    with pytest.raises(ValueError):
        p1.deserialize_physical_shadow_output(wire)


def test_batch_frozen_and_record_tamper_revalidated() -> None:
    r = record()
    batch = p1.PhysicalShadowOutputBatch((r,))
    with pytest.raises(FrozenInstanceError):
        batch.records = ()  # type: ignore[misc]
    object.__setattr__(r, "active_power_w", 7.0)
    with pytest.raises(ValueError, match="apparent"):
        p1.PhysicalShadowOutputBatch((r,))
    with pytest.raises(ValueError):
        p1.validate_physical_shadow_output_batch(batch)
