"""Synthetic reviewed sample ownership, never a Bracon mapping."""

from dataclasses import FrozenInstanceError, fields, replace
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest

from heliotelligence.geometry.models import (
    CoordinateReference,
    PVReceiver,
    ReceiverKind,
    SiteGeometry,
    SourceProvenance,
    TriangleMesh,
)
from heliotelligence.physics import string_section_optical_binding_authority as a
from heliotelligence.physics.string_section_reverse_breakdown_authority import BypassSectionIdentity
from tests.unit.test_physics.test_string_member_topology_authority import resolved


def geometry() -> SiteGeometry:
    mesh = TriangleMesh(
        np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]), np.array([[0, 1, 2]])
    )
    receiver = PVReceiver(
        "receiver-independent", mesh, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ReceiverKind.UNKNOWN
    )
    return SiteGeometry("revision-1", SourceProvenance(), CoordinateReference(), (receiver,))


def bindings() -> dict[BypassSectionIdentity, a.SectionOpticalBinding]:
    parent = resolved()
    return {
        BypassSectionIdentity(m.module_id, s.section_id): a.SectionOpticalBinding(
            BypassSectionIdentity(m.module_id, s.section_id),
            m.physical_position_reference,
            "revision-1",
            "receiver-independent",
            2,
            4,
            (2 * n, 2 * n + 1),
            "reviewed synthetic drawing",
            "unknown",
            "method:test",
            "synthetic only",
        )
        for n, (m, s) in enumerate(
            (m, s)
            for x in parent.authorities_by_string_id.values()
            for m in x.module_members
            for s in m.bypass_protected_sections
        )
    }


def resolve(supplied: Any = None) -> a.SectionOpticalBindingAuthorityResult:
    return a.resolve_section_optical_binding_authority(
        resolved(), geometry(), bindings() if supplied is None else supplied
    )


def test_full_partial_empty_metadata_and_closure() -> None:
    for n in (4, 1, 0):
        r = resolve(dict(list(bindings().items())[:n]))
        assert r.contract == "explicit_string_section_optical_sample_binding_authority_v1"
        assert r.model == "explicit_receiver_visibility_sample_to_bypass_section_binding_v1"
        assert (
            r.scope
            == "advanced_s8_optical_geometry_to_section_binding_before_section_electrical_state"
        )
        assert (
            r.coverage_scope
            == "explicit_stage4a1_sections_with_geometry_revision_receiver_and_sample_cell_mapping"
        )
        assert r.diagnostics == a.SectionOpticalBindingDiagnostics(4, n, 4 - n, 2 * n, int(n > 0))
        assert len(r.resolved_section_ids) == n and len(r.unavailable_section_ids) == 4 - n
        a.validate_section_optical_binding_authority(resolved(), geometry(), r)


@pytest.mark.parametrize(
    "field,value",
    [
        ("geometry_revision", "old"),
        ("receiver_id", "unknown"),
        ("physical_position_reference", "wrong"),
        ("samples_u", True),
        ("samples_v", False),
        ("samples_u", 0),
        ("samples_v", -1),
        ("samples_u", 2.0),
        ("samples_v", "4"),
        ("samples_v", None),
        ("sample_indices", ()),
        ("sample_indices", []),
        ("sample_indices", (True,)),
        ("sample_indices", (-1,)),
        ("sample_indices", (8,)),
        ("sample_indices", (1, 1)),
        ("sample_indices", (2, 1)),
        ("sample_indices", (1.0,)),
        ("sample_indices", ("1",)),
        ("parameter_source", " padded"),
        ("confidence", "excellent"),
        ("method_reference", ""),
        ("applicability_description", " "),
        ("section_identity", BypassSectionIdentity("unknown", "section-a")),
        ("section_identity", BypassSectionIdentity("string-z-module-0", "unknown")),
    ],
)
def test_invalid_binding(field: str, value: Any) -> None:
    supplied = bindings()
    key = next(iter(supplied))
    # Controlled frozen tamper exercises resolver checks, not constructor admission.
    object.__setattr__(supplied[key], field, value)
    with pytest.raises(ValueError):
        resolve(supplied)


def test_overlap_and_mapping_key_mismatch_rejected() -> None:
    b = bindings()
    k = list(b)
    b[k[1]] = replace(b[k[1]], sample_indices=(1, 2))
    with pytest.raises(ValueError, match="overlap"):
        resolve(b)
    b = bindings()
    b[BypassSectionIdentity("wrong", "section-a")] = b.pop(k[0])
    with pytest.raises(ValueError):
        resolve(b)


def test_irregular_interleaved_unequal_partial_and_local_ids() -> None:
    b = bindings()
    k = list(b)
    b[k[0]] = replace(b[k[0]], sample_indices=(0, 3, 6))
    b[k[1]] = replace(b[k[1]], sample_indices=(1, 4))
    b[k[2]] = replace(b[k[2]], sample_indices=(2,))
    del b[k[3]]
    r = resolve(b)
    assert r.diagnostics.bound_sample_cell_count == 6  # 5 and 7 stay unassigned.
    assert len({key.module_id for key in r.resolved_section_ids}) == 2
    assert len({key.section_id for key in r.resolved_section_ids}) == 2
    assert tuple(r.bindings_by_section) == tuple(b)
    assert r == resolve(dict(reversed(list(b.items()))))


def test_detached_immutable_and_repeat_snapshots() -> None:
    b = bindings()
    r = resolve(b)
    again = resolve(b)
    key = next(iter(b))
    assert type(r.bindings_by_section) is MappingProxyType
    assert r.bindings_by_section[key] is not b[key]
    assert r.bindings_by_section[key] is not again.bindings_by_section[key]
    assert r.bindings_by_section[key].section_identity is not key
    object.__setattr__(b[key], "parameter_source", "changed")
    b.clear()
    assert r.bindings_by_section[key].parameter_source == "reviewed synthetic drawing"
    with pytest.raises(FrozenInstanceError):
        r.contract = "bad"  # type: ignore[misc]
    with pytest.raises(TypeError):
        r.bindings_by_section[key] = again.bindings_by_section[key]  # type: ignore[index]


@pytest.mark.parametrize("field", [f.name for f in fields(a.SectionOpticalBindingAuthorityResult)])
def test_independent_validator_rejects_forged_result(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = resolve()
    monkeypatch.setattr(
        a, "resolve_section_optical_binding_authority", lambda *args: pytest.fail("resolver called")
    )
    object.__setattr__(r, field, None)
    with pytest.raises(ValueError):
        a.validate_section_optical_binding_authority(resolved(), geometry(), r)


@pytest.mark.parametrize("field", [f.name for f in fields(a.SectionOpticalBinding)])
def test_independent_validator_rejects_nested_tamper(field: str) -> None:
    r = resolve()
    object.__setattr__(next(iter(r.bindings_by_section.values())), field, None)
    with pytest.raises(ValueError):
        a.validate_section_optical_binding_authority(resolved(), geometry(), r)


def test_forged_parent_geometry_and_diagnostic() -> None:
    r = resolve()
    p = resolved()
    object.__setattr__(p.diagnostics, "module_member_count", True)
    with pytest.raises(ValueError):
        a.validate_section_optical_binding_authority(p, geometry(), r)
    g = geometry()
    object.__setattr__(g, "geometry_revision", "stale")
    with pytest.raises(ValueError):
        a.validate_section_optical_binding_authority(resolved(), g, r)
    r = resolve()
    object.__setattr__(r.diagnostics, "bound_sample_cell_count", True)
    with pytest.raises(ValueError):
        a.validate_section_optical_binding_authority(resolved(), geometry(), r)


def test_independent_validation_does_not_call_binding_constructors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p, g, r = resolved(), geometry(), resolve()

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("binding constructor called")

    monkeypatch.setattr(a.SectionOpticalBinding, "__post_init__", forbidden)
    a.validate_section_optical_binding_authority(p, g, r)


def test_cell_branch_counts_and_opaque_names_never_infer_mapping() -> None:
    p = resolved()
    g = geometry()
    section = p.authorities_by_string_id["string-z"].module_members[0].bypass_protected_sections[0]
    object.__setattr__(section, "series_cells_per_branch", 999)
    object.__setattr__(section, "parallel_cell_branches", 7)
    r = a.resolve_section_optical_binding_authority(p, g, bindings())
    assert r == resolve()
    empty = a.resolve_section_optical_binding_authority(p, g, {})
    assert empty.resolved_section_ids == () and len(empty.unavailable_section_ids) == 4
