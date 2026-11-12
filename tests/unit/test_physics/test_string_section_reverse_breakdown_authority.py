"""Stage4a-2 reverse parameters never manufacture missing section authority."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from types import MappingProxyType
from typing import Any

import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import string_member_topology_authority as p
from heliotelligence.physics import string_section_reverse_breakdown_authority as a


def parent() -> p.TopologyStringMemberAuthorityResult:
    topology = ElectricalTopologyConfig.model_validate(
        {
            "inverters": [
                {
                    "id": "inverter",
                    "mppts": [
                        {
                            "id": "tracker",
                            "strings": [
                                {"id": "string-z", "modules_per_string": 1},
                                {"id": "string-a", "modules_per_string": 1},
                                {"id": "string-unavailable", "modules_per_string": 1},
                            ],
                        }
                    ],
                }
            ]
        }
    )
    declared = {}
    for string_id, module_id in (("string-a", "module-a"), ("string-z", "module-z")):
        member = p.PhysicalModuleMember(
            module_id,
            0,
            "drawing:test",
            (
                p.BypassProtectedSection("local-2", 24, 2),
                p.BypassProtectedSection("local-1", 24, 2),
            ),
        )
        declared[string_id] = p.StringMemberTopologyAuthority(
            string_id,
            (member,),
            "test",
            "unknown",
            "review:test",
            "synthetic only",
        )
    return p.resolve_topology_string_member_authority(topology, declared)


def authority(
    module: str = "module-z", section: str = "local-2"
) -> a.SectionReverseBreakdownAuthority:
    # pvlib partial-module-shading example pattern; test values, never defaults.
    return a.SectionReverseBreakdownAuthority(
        a.BypassSectionIdentity(module, section),
        0.002,
        -15.0,
        3.0,
        "synthetic-test-evidence",
        "unknown",
        "test-only-method",
        "test-only equivalent section",
    )


def test_full_partial_empty_order_and_closure() -> None:
    topology = parent()
    expected = tuple(
        a.BypassSectionIdentity(module, section)
        for module in ("module-z", "module-a")
        for section in ("local-2", "local-1")
    )
    declared = {key: authority(key.module_id, key.section_id) for key in reversed(expected)}
    full = a.resolve_section_reverse_breakdown_authority(topology, declared)
    assert full.resolved_section_ids == expected
    assert not full.unavailable_section_ids
    assert tuple(full.authorities_by_section) == expected
    assert full.diagnostics == a.SectionReverseBreakdownDiagnostics(4, 4, 0, 4)
    assert len(declared) == 4
    partial = a.resolve_section_reverse_breakdown_authority(
        topology, {key: declared[key] for key in (expected[2], expected[0])}
    )
    assert partial.resolved_section_ids == (expected[0], expected[2])
    assert partial.unavailable_section_ids == (expected[1], expected[3])
    assert partial.diagnostics == a.SectionReverseBreakdownDiagnostics(4, 2, 2, 2)
    empty = a.resolve_section_reverse_breakdown_authority(topology, {})
    assert empty.unavailable_section_ids == expected
    assert empty.diagnostics == a.SectionReverseBreakdownDiagnostics(4, 0, 4, 0)
    a.validate_section_reverse_breakdown_authority(topology, full)


def test_zero_factor_explicit_not_missing() -> None:
    declared = replace(authority(), breakdown_factor=0)
    r = a.resolve_section_reverse_breakdown_authority(parent(), {declared.identity: declared})
    assert r.diagnostics == a.SectionReverseBreakdownDiagnostics(4, 1, 3, 0)
    assert r.authorities_by_section[declared.identity].breakdown_factor == 0


@pytest.mark.parametrize(
    "module,section",
    [
        ("unknown", "local-2"),
        ("module-z", "unknown"),
        ("string-unavailable", "local-2"),
    ],
)
def test_unknown_or_unavailable_sections(module: str, section: str) -> None:
    declared = authority(module, section)
    with pytest.raises(ValueError, match="unknown"):
        a.resolve_section_reverse_breakdown_authority(parent(), {declared.identity: declared})


def test_identity_disagreement() -> None:
    with pytest.raises(ValueError, match="identity"):
        a.resolve_section_reverse_breakdown_authority(
            parent(),
            {
                a.BypassSectionIdentity("module-a", "local-2"): authority(),
            },
        )


@pytest.mark.parametrize("field", ["breakdown_factor", "breakdown_voltage_v", "breakdown_exponent"])
@pytest.mark.parametrize(
    "value", [True, False, float("nan"), float("inf"), -float("inf"), "1", None]
)
def test_invalid_numeric_type_or_nonfinite(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority(), **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("breakdown_factor", -0.01),
        ("breakdown_factor", 1.01),
        ("breakdown_voltage_v", 0),
        ("breakdown_voltage_v", 1),
        ("breakdown_exponent", 0),
        ("breakdown_exponent", -1),
    ],
)
def test_numeric_domains(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority(), **{field: value})


@pytest.mark.parametrize("factor", [0, 1, 0.002])
def test_factor_domain_endpoints(factor: float) -> None:
    a.validate_section_reverse_breakdown_parameters(replace(authority(), breakdown_factor=factor))


@pytest.mark.parametrize(
    "field", ["parameter_source", "method_reference", "applicability_description"]
)
@pytest.mark.parametrize("value", ["", " padded", "padded ", None, 5])
def test_strict_provenance(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority(), **{field: value})


@pytest.mark.parametrize("field", ["module_id", "section_id"])
@pytest.mark.parametrize("value", ["", " padded", "padded ", None, 5])
def test_strict_identity(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority().identity, **{field: value})


@pytest.mark.parametrize("confidence", ["high", "medium", "low", "unknown"])
def test_confidence(confidence: str) -> None:
    a.validate_section_reverse_breakdown_parameters(replace(authority(), confidence=confidence))


@pytest.mark.parametrize("confidence", ["HIGH", "certain", " unknown", "", 1])
def test_confidence_invalid(confidence: Any) -> None:
    with pytest.raises(ValueError):
        replace(authority(), confidence=confidence)


def test_fixed_ids() -> None:
    declared = authority()
    assert declared.contract == "explicit_bypass_section_reverse_breakdown_authority_v1"
    assert declared.model == "bishop88_explicit_section_reverse_breakdown_parameters_v1"
    assert (
        declared.scope
        == "advanced_s8_section_reverse_breakdown_before_diode_clamp_and_series_composition"
    )
    assert (
        declared.coverage_scope
        == "explicit_stage4a1_bypass_sections_with_reviewed_reverse_breakdown_parameters"
    )
    r = a.resolve_section_reverse_breakdown_authority(parent(), {declared.identity: declared})
    assert (r.contract, r.model, r.scope, r.coverage_scope) == (
        declared.contract,
        declared.model,
        declared.scope,
        declared.coverage_scope,
    )


@pytest.mark.parametrize("field", ["contract", "model", "scope", "coverage_scope"])
def test_fixed_semantics_cannot_change(field: str) -> None:
    updates: dict[str, Any] = {field: "other"}
    with pytest.raises(ValueError):
        replace(authority(), **updates)
    r = a.resolve_section_reverse_breakdown_authority(parent(), {})
    object.__setattr__(r, field, "other")
    with pytest.raises(ValueError):
        a.validate_section_reverse_breakdown_authority(parent(), r)


def test_detached_frozen_inputs_and_output() -> None:
    topology = parent()
    declared = authority()
    original = {declared.identity: declared}
    r = a.resolve_section_reverse_breakdown_authority(topology, original)
    assert original == {declared.identity: declared}
    output = r.authorities_by_section[declared.identity]
    assert output == declared and output is not declared
    assert output.identity is not declared.identity
    with pytest.raises(FrozenInstanceError):
        declared.breakdown_factor = 0.5  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        output.identity.module_id = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        r.diagnostics.topology_section_count = 0  # type: ignore[misc]
    with pytest.raises(TypeError):
        r.authorities_by_section[declared.identity] = declared  # type: ignore[index]
    object.__setattr__(declared, "breakdown_factor", 0.7)
    original.clear()
    object.__setattr__(
        topology.authorities_by_string_id["string-z"].module_members[0],
        "physical_position_reference",
        "changed-after-resolution",
    )
    assert output.breakdown_factor == 0.002
    assert len(r.authorities_by_section) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("breakdown_factor", True),
        ("breakdown_voltage_v", 0),
        ("breakdown_exponent", -1),
        ("confidence", "certain"),
        ("parameter_source", ""),
        ("method_reference", " padded"),
        ("applicability_description", ""),
        ("contract", "wrong"),
        ("model", "wrong"),
        ("scope", "wrong"),
        ("coverage_scope", "wrong"),
    ],
)
def test_forged_authority_rejected(field: str, value: Any) -> None:
    declared = authority()
    r = a.resolve_section_reverse_breakdown_authority(parent(), {declared.identity: declared})
    object.__setattr__(declared, field, value)
    with pytest.raises(ValueError):
        a.resolve_section_reverse_breakdown_authority(parent(), {declared.identity: declared})
    output = next(iter(r.authorities_by_section.values()))
    object.__setattr__(output, field, value)
    with pytest.raises(ValueError):
        a.validate_section_reverse_breakdown_authority(parent(), r)


@pytest.mark.parametrize("field", [f.name for f in fields(a.SectionReverseBreakdownDiagnostics)])
def test_diagnostic_tampering(field: str) -> None:
    r = a.resolve_section_reverse_breakdown_authority(parent(), {})
    object.__setattr__(r.diagnostics, field, True)
    with pytest.raises(ValueError):
        a.validate_section_reverse_breakdown_authority(parent(), r)


@pytest.mark.parametrize(
    "field,value",
    [
        ("resolved_section_ids", ()),
        ("unavailable_section_ids", ()),
        ("authorities_by_section", {}),
    ],
)
def test_partition_tampering(field: str, value: Any) -> None:
    declared = authority()
    r = a.resolve_section_reverse_breakdown_authority(parent(), {declared.identity: declared})
    object.__setattr__(r, field, value)
    with pytest.raises(ValueError):
        a.validate_section_reverse_breakdown_authority(parent(), r)


@pytest.mark.parametrize(
    "level,field,value",
    [
        ("parent", "contract", "wrong"),
        ("parent", "advanced_resolved_string_ids", ()),
        ("parent", "authorities_by_string_id", {}),
        ("diagnostics", "module_member_count", True),
        ("string", "confidence", "certain"),
        ("string", "module_members", ()),
        ("member", "series_index", True),
        ("member", "module_id", ""),
        ("member", "bypass_protected_sections", ()),
        ("section", "series_cells_per_branch", True),
        ("section", "parallel_cell_branches", 0),
        ("section", "section_id", " padded"),
    ],
)
def test_forged_parent_rejected(level: str, field: str, value: Any) -> None:
    topology = parent()
    declared = authority()
    r = a.resolve_section_reverse_breakdown_authority(topology, {declared.identity: declared})
    targets = {
        "parent": topology,
        "diagnostics": topology.diagnostics,
        "string": topology.authorities_by_string_id["string-z"],
        "member": topology.authorities_by_string_id["string-z"].module_members[0],
        "section": topology.authorities_by_string_id["string-z"]
        .module_members[0]
        .bypass_protected_sections[0],
    }
    object.__setattr__(targets[level], field, value)
    with pytest.raises(ValueError):
        a.resolve_section_reverse_breakdown_authority(topology, {})
    with pytest.raises(ValueError):
        a.validate_section_reverse_breakdown_authority(topology, r)


def test_validator_without_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    topology = parent()
    declared = authority()
    r = a.resolve_section_reverse_breakdown_authority(topology, {declared.identity: declared})

    def disabled(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("admission/construction helper called")

    monkeypatch.setattr(a, "resolve_section_reverse_breakdown_authority", disabled)
    monkeypatch.setattr(a, "_text", disabled)
    for cls in (
        a.BypassSectionIdentity,
        a.SectionReverseBreakdownAuthority,
        a.SectionReverseBreakdownAuthorityResult,
        a.SectionReverseBreakdownDiagnostics,
    ):
        monkeypatch.setattr(cls, "__init__", disabled)
        if hasattr(cls, "__post_init__"):
            monkeypatch.setattr(cls, "__post_init__", disabled)
    a.validate_section_reverse_breakdown_authority(topology, r)
    object.__setattr__(next(iter(r.authorities_by_section.values())), "breakdown_factor", True)
    with pytest.raises(ValueError):
        a.validate_section_reverse_breakdown_authority(topology, r)


def test_order_tamper_and_empty_parent() -> None:
    topology = parent()
    declared = {
        a.BypassSectionIdentity(m, "local-2"): authority(m) for m in ("module-z", "module-a")
    }
    r = a.resolve_section_reverse_breakdown_authority(topology, declared)
    object.__setattr__(
        r,
        "authorities_by_section",
        MappingProxyType(dict(reversed(tuple(r.authorities_by_section.items())))),
    )
    with pytest.raises(ValueError, match="order"):
        a.validate_section_reverse_breakdown_authority(topology, r)
    empty_parent = p.resolve_topology_string_member_authority(ElectricalTopologyConfig(), {})
    empty = a.resolve_section_reverse_breakdown_authority(empty_parent, {})
    assert empty.diagnostics == a.SectionReverseBreakdownDiagnostics(0, 0, 0, 0)
