"""Advanced S8 connectivity is explicit, immutable and independent of numerics."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import string_member_topology_authority as a


def topology() -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig.model_validate(
        {
            "inverters": [
                {
                    "id": "inverter",
                    "mppts": [
                        {
                            "id": "tracker",
                            "strings": [
                                {"id": "string-z", "modules_per_string": 2},
                                {"id": "string-a", "modules_per_string": 1},
                                {"id": "string-c", "modules_per_string": 2},
                            ],
                        }
                    ],
                }
            ]
        }
    )


def authority(key: str = "string-z", count: int = 2) -> a.StringMemberTopologyAuthority:
    return a.StringMemberTopologyAuthority(
        key,
        tuple(
            a.PhysicalModuleMember(
                f"{key}-module-{i}",
                i,
                f"drawing:{key}:member:{i}",
                (
                    a.BypassProtectedSection("section-a", 24, 2),
                    a.BypassProtectedSection("section-b", 48, 1),
                ),
            )
            for i in range(count)
        ),
        "explicit-test-drawing",
        "unknown",
        "review:test",
        "synthetic physical strings only",
    )


def resolved() -> a.TopologyStringMemberAuthorityResult:
    return a.resolve_topology_string_member_authority(topology(), {"string-z": authority()})


def test_contract_and_counts() -> None:
    r = resolved()
    assert r.contract == "explicit_string_member_bypass_section_topology_authority_v1"
    assert r.model == "ordered_physical_module_members_and_bypass_protected_sections_v1"
    assert r.scope == "advanced_s8_string_member_electrical_topology_before_section_iv_resolution"
    assert r.coverage_scope == (
        "explicit_existing_physical_strings_with_complete_ordered_member_and_bypass_section_topology"
    )
    assert r.contract == a.STRING_MEMBER_TOPOLOGY_AUTHORITY_CONTRACT_ID
    assert r.model == a.STRING_MEMBER_TOPOLOGY_AUTHORITY_MODEL_ID
    assert r.scope == a.STRING_MEMBER_TOPOLOGY_AUTHORITY_SCOPE
    assert r.coverage_scope == a.STRING_MEMBER_TOPOLOGY_AUTHORITY_COVERAGE_SCOPE
    assert r.advanced_resolved_string_ids == ("string-z",)
    assert r.advanced_unavailable_string_ids == ("string-a", "string-c")
    assert r.diagnostics == a.StringMemberTopologyDiagnostics(3, 1, 2, 2, 4)
    a.validate_topology_string_member_authority(topology(), r)


def test_multiple_partial_order_and_no_aliases() -> None:
    t = topology()
    before = t.model_dump()
    declared = {"string-c": authority("string-c"), "string-z": authority()}
    original = dict(declared)
    r = a.resolve_topology_string_member_authority(t, declared)
    reverse = a.resolve_topology_string_member_authority(t, dict(reversed(declared.items())))
    assert r == reverse
    assert tuple(r.authorities_by_string_id) == ("string-z", "string-c")
    assert r.advanced_unavailable_string_ids == ("string-a",)
    assert r.diagnostics == a.StringMemberTopologyDiagnostics(3, 2, 1, 4, 8)
    assert declared == original
    assert t.model_dump() == before
    copied = r.authorities_by_string_id["string-z"]
    assert copied is not declared["string-z"]
    assert copied.module_members[0] is not declared["string-z"].module_members[0]
    assert (
        copied.module_members[0].bypass_protected_sections[0]
        is not (declared["string-z"].module_members[0].bypass_protected_sections[0])
    )
    object.__setattr__(declared["string-z"].module_members[0], "module_id", "tampered-caller")
    declared.clear()
    assert copied.module_members[0].module_id == "string-z-module-0"
    a.validate_topology_string_member_authority(t, r)


def test_all_strings_and_local_section_ids() -> None:
    r = a.resolve_topology_string_member_authority(
        topology(),
        {
            "string-c": authority("string-c"),
            "string-a": authority("string-a", 1),
            "string-z": authority(),
        },
    )
    assert r.advanced_unavailable_string_ids == ()
    assert r.diagnostics == a.StringMemberTopologyDiagnostics(3, 3, 0, 5, 10)
    # Identical section labels in different physical modules are intentional.
    assert (
        len(
            {
                s.section_id
                for v in r.authorities_by_string_id.values()
                for m in v.module_members
                for s in m.bypass_protected_sections
            }
        )
        == 2
    )


@pytest.mark.parametrize("empty", [False, True])
def test_empty_advanced_mapping_preserves_homogeneous_topology(empty: bool) -> None:
    t = ElectricalTopologyConfig() if empty else topology()
    before = t.model_dump()
    r = a.resolve_topology_string_member_authority(t, {})
    assert not r.authorities_by_string_id
    assert not r.advanced_resolved_string_ids
    assert r.advanced_unavailable_string_ids == (
        () if empty else ("string-z", "string-a", "string-c")
    )
    assert r.diagnostics == a.StringMemberTopologyDiagnostics(
        t.string_count, 0, t.string_count, 0, 0
    )
    assert t.model_dump() == before
    assert ElectricalTopologyConfig.model_validate(before) == t


@pytest.mark.parametrize("key,count", [("string-z", 1), ("string-a", 2), ("unknown", 2)])
def test_binding_rejects_unknown_or_member_count(key: str, count: int) -> None:
    with pytest.raises(ValueError):
        a.resolve_topology_string_member_authority(topology(), {key: authority(key, count)})


def test_mapping_identity_must_agree() -> None:
    with pytest.raises(ValueError):
        a.resolve_topology_string_member_authority(topology(), {"string-c": authority()})


@pytest.mark.parametrize("field", ["series_cells_per_branch", "parallel_cell_branches"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 24.0, "24", None])
def test_section_counts_strict(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(a.BypassProtectedSection("section", 24, 2), **{field: value})


@pytest.mark.parametrize("indexes", [(0, 0), (0, 2), (1, 2), (-1, 0), (1, 0)])
def test_electrical_order_is_exact(indexes: tuple[int, int]) -> None:
    original = authority()
    with pytest.raises(ValueError):
        replace(
            original,
            module_members=tuple(
                replace(m, series_index=index)
                for m, index in zip(original.module_members, indexes, strict=True)
            ),
        )


@pytest.mark.parametrize("index", [True, 0.0, "0", -1])
def test_member_index_exact_int(index: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority().module_members[0], series_index=index)


def test_duplicate_modules_and_sections_and_empty_collections() -> None:
    original = authority()
    first, second = original.module_members
    with pytest.raises(ValueError):
        replace(original, module_members=(first, replace(second, module_id=first.module_id)))
    with pytest.raises(ValueError):
        replace(first, bypass_protected_sections=first.bypass_protected_sections * 2)
    with pytest.raises(ValueError):
        replace(first, bypass_protected_sections=())
    with pytest.raises(ValueError):
        replace(original, module_members=())
    other = authority("string-a", 1)
    other = replace(
        other, module_members=(replace(other.module_members[0], module_id=first.module_id),)
    )
    with pytest.raises(ValueError, match="physical module"):
        a.resolve_topology_string_member_authority(
            topology(),
            {
                "string-z": original,
                "string-a": other,
            },
        )


@pytest.mark.parametrize(
    "field",
    [
        "string_id",
        "parameter_source",
        "confidence",
        "method_reference",
        "applicability_description",
    ],
)
@pytest.mark.parametrize("value", ["", " padded", "padded ", "\t", 1, None])
def test_provenance_is_exact(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority(), **{field: value})


@pytest.mark.parametrize("value", ["high", "medium", "low", "unknown"])
def test_confidence_provenance(value: str) -> None:
    declared = replace(authority(), confidence=value)
    r = a.resolve_topology_string_member_authority(topology(), {"string-z": declared})
    assert r.diagnostics == resolved().diagnostics
    assert r.authorities_by_string_id["string-z"].confidence == value


@pytest.mark.parametrize("value", ["certain", "HIGH", " high"])
def test_unknown_confidence(value: str) -> None:
    with pytest.raises(ValueError):
        replace(authority(), confidence=value)


@pytest.mark.parametrize(
    "record,field",
    [
        (a.BypassProtectedSection("section", 1, 1), "section_id"),
        (authority().module_members[0], "module_id"),
        (authority(), "string_id"),
        (resolved(), "model"),
        (resolved().diagnostics, "module_member_count"),
    ],
)
def test_frozen_records(record: Any, field: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(record, field, None)


def test_mapping_and_tuples_immutable() -> None:
    r = resolved()
    with pytest.raises(TypeError):
        r.authorities_by_string_id["new"] = authority()  # type: ignore[index]
    assert type(r.advanced_resolved_string_ids) is tuple
    assert type(r.authorities_by_string_id["string-z"].module_members) is tuple
    assert type(r.authorities_by_string_id) is MappingProxyType


@pytest.mark.parametrize(
    "level,field,value",
    [
        ("authority", "string_id", "other"),
        ("authority", "parameter_source", " padded"),
        ("authority", "confidence", "certain"),
        ("authority", "method_reference", ""),
        ("authority", "applicability_description", ""),
        ("authority", "module_members", ()),
        ("member", "module_id", ""),
        ("member", "series_index", True),
        ("member", "series_index", 2),
        ("member", "physical_position_reference", " padded"),
        ("member", "bypass_protected_sections", ()),
        ("section", "section_id", ""),
        ("section", "series_cells_per_branch", True),
        ("section", "parallel_cell_branches", 0),
    ],
)
def test_nested_tamper_rejected_by_resolution_and_validator(
    level: str,
    field: str,
    value: Any,
) -> None:
    declared = authority()
    r = a.resolve_topology_string_member_authority(topology(), {"string-z": declared})
    for target in (declared, r.authorities_by_string_id["string-z"]):
        record: Any = target
        if level in {"member", "section"}:
            record = record.module_members[0]
        if level == "section":
            record = record.bypass_protected_sections[0]
        object.__setattr__(record, field, value)
    with pytest.raises(ValueError):
        a.resolve_topology_string_member_authority(topology(), {"string-z": declared})
    with pytest.raises(ValueError):
        a.validate_topology_string_member_authority(topology(), r)


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract", "wrong"),
        ("model", "wrong"),
        ("scope", "wrong"),
        ("coverage_scope", "wrong"),
        ("advanced_resolved_string_ids", ()),
        ("advanced_unavailable_string_ids", ()),
        ("authorities_by_string_id", {}),
        ("diagnostics", a.StringMemberTopologyDiagnostics(3, 1, 2, True, 4)),
    ],
)
def test_result_tampering(field: str, value: Any) -> None:
    r = resolved()
    object.__setattr__(r, field, value)
    with pytest.raises(ValueError):
        a.validate_topology_string_member_authority(topology(), r)


@pytest.mark.parametrize("field", [f.name for f in fields(a.StringMemberTopologyDiagnostics)])
def test_every_diagnostic_reconstructed(field: str) -> None:
    r = resolved()
    object.__setattr__(r.diagnostics, field, -1)
    with pytest.raises(ValueError):
        a.validate_topology_string_member_authority(topology(), r)


def test_independent_validator_without_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    t, r = topology(), resolved()

    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("construction/admission helper called")

    for name in ("_text", "_integer", "resolve_topology_string_member_authority"):
        monkeypatch.setattr(a, name, disabled)
    for cls in (
        a.BypassProtectedSection,
        a.PhysicalModuleMember,
        a.StringMemberTopologyAuthority,
        a.StringMemberTopologyDiagnostics,
        a.TopologyStringMemberAuthorityResult,
    ):
        monkeypatch.setattr(cls, "__init__", disabled)
        if hasattr(cls, "__post_init__"):
            monkeypatch.setattr(cls, "__post_init__", disabled)
    a.validate_topology_string_member_authority(t, r)
    object.__setattr__(
        r.authorities_by_string_id["string-z"].module_members[0], "series_index", True
    )
    with pytest.raises(ValueError):
        a.validate_topology_string_member_authority(t, r)


def test_only_stdlib_and_existing_config_imports_no_numerics() -> None:
    tree = ast.parse(Path(a.__file__).read_text())
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {
        "__future__",
        "collections.abc",
        "dataclasses",
        "types",
        "heliotelligence.config.site",
    }
    assert not any(isinstance(n, ast.Import) for n in ast.walk(tree))
    excluded = {"breakdown_voltage", "bypass_forward_voltage", "bishop_parameters", "diode_state"}
    for cls in (a.BypassProtectedSection, a.PhysicalModuleMember, a.StringMemberTopologyAuthority):
        assert excluded.isdisjoint(f.name for f in fields(cls))


@pytest.mark.parametrize("field", ["module_id", "physical_position_reference"])
@pytest.mark.parametrize("value", ["", " padded", "padded ", 1, None])
def test_member_text(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority().module_members[0], **{field: value})


@pytest.mark.parametrize("value", ["", " padded", "padded ", 1, None])
def test_section_label(value: Any) -> None:
    with pytest.raises(ValueError):
        a.BypassProtectedSection(value, 24, 2)


@pytest.mark.parametrize("level", ["authority", "member", "section"])
def test_wrong_nested_container_or_record_rejected(level: str) -> None:
    declared = authority()
    if level == "authority":
        object.__setattr__(declared, "module_members", None)
    elif level == "member":
        object.__setattr__(declared, "module_members", (object(), object()))
    else:
        object.__setattr__(declared.module_members[0], "bypass_protected_sections", None)
    with pytest.raises(ValueError):
        a.resolve_topology_string_member_authority(topology(), {"string-z": declared})


def test_forged_nested_duplicate_section_and_module_ids_rejected() -> None:
    r = resolved()
    members = r.authorities_by_string_id["string-z"].module_members
    object.__setattr__(members[1], "module_id", members[0].module_id)
    with pytest.raises(ValueError, match="physical module"):
        a.validate_topology_string_member_authority(topology(), r)
    r = resolved()
    sections = r.authorities_by_string_id["string-z"].module_members[0].bypass_protected_sections
    object.__setattr__(sections[1], "section_id", sections[0].section_id)
    with pytest.raises(ValueError, match="module-local"):
        a.validate_topology_string_member_authority(topology(), r)


def test_forged_physical_string_count_rejected() -> None:
    t = topology()
    t.inverters[0].mppts[0].strings[0].modules_per_string = True
    with pytest.raises(ValueError):
        a.resolve_topology_string_member_authority(t, {})
    with pytest.raises(ValueError):
        a.validate_topology_string_member_authority(t, resolved())
