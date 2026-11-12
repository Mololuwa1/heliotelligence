"""Explicit diode evidence, never a universal forward voltage assumption."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from typing import Any

import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import string_member_topology_authority as t
from heliotelligence.physics import string_section_bypass_diode_authority as d
from heliotelligence.physics import string_section_reverse_breakdown_authority as r


def parent() -> t.TopologyStringMemberAuthorityResult:
    config = ElectricalTopologyConfig.model_validate(
        {
            "inverters": [
                {
                    "id": "inv",
                    "mppts": [
                        {
                            "id": "mppt",
                            "strings": [
                                {"id": "string-z", "modules_per_string": 2},
                                {"id": "string-a", "modules_per_string": 1},
                                {"id": "string-no-members", "modules_per_string": 1},
                            ],
                        }
                    ],
                }
            ]
        }
    )
    declared = {}
    for key, count in (("string-z", 2), ("string-a", 1)):
        declared[key] = t.StringMemberTopologyAuthority(
            key,
            tuple(
                t.PhysicalModuleMember(
                    f"{key}-module-{i}",
                    i,
                    f"drawing:{i}",
                    (
                        t.BypassProtectedSection("section-z", 24, 2),
                        t.BypassProtectedSection("section-a", 24, 2),
                    ),
                )
                for i in range(count)
            ),
            "synthetic",
            "unknown",
            "test",
            "test only",
        )
    return t.resolve_topology_string_member_authority(config, declared)


def reverse(p: t.TopologyStringMemberAuthorityResult) -> r.SectionReverseBreakdownAuthorityResult:
    declared = {}
    for a in p.authorities_by_string_id.values():
        for m in a.module_members:
            for s in m.bypass_protected_sections:
                identity = r.BypassSectionIdentity(m.module_id, s.section_id)
                declared[identity] = r.SectionReverseBreakdownAuthority(
                    identity, 0.002, -15.0, 3.0, "synthetic", "unknown", "test", "test only"
                )
    return r.resolve_section_reverse_breakdown_authority(p, declared)


def diode(identity: r.BypassSectionIdentity) -> d.SectionBypassDiodeAuthority:
    return d.SectionBypassDiodeAuthority(
        identity,
        0.5,
        "synthetic-test-only",
        "unknown",
        "explicit-test-method",
        "synthetic section only",
    )


def test_full_partial_empty_and_parent_order() -> None:
    p = parent()
    rev = reverse(p)
    keys = rev.resolved_section_ids
    supplied = {key: diode(key) for key in reversed(keys)}
    result = d.resolve_section_bypass_diode_authority(p, rev, supplied)
    assert tuple(result.authorities_by_section) == result.resolved_section_ids == keys
    assert not result.unavailable_section_ids
    assert result.diagnostics == d.SectionBypassDiodeDiagnostics(6, 6, 0)
    partial = d.resolve_section_bypass_diode_authority(p, rev, {keys[2]: diode(keys[2])})
    assert partial.resolved_section_ids == (keys[2],)
    assert partial.unavailable_section_ids == tuple(k for k in keys if k != keys[2])
    empty_reverse = r.resolve_section_reverse_breakdown_authority(p, {})
    # Diode binding does not require reverse electrical evidence to exist for a section.
    empty = d.resolve_section_bypass_diode_authority(p, empty_reverse, {})
    assert empty.diagnostics == d.SectionBypassDiodeDiagnostics(6, 0, 6)
    all_diodes = d.resolve_section_bypass_diode_authority(p, empty_reverse, supplied)
    assert all_diodes.resolved_section_ids == keys
    d.validate_section_bypass_diode_authority(p, rev, result)


def test_exact_ids_and_no_default() -> None:
    a = diode(reverse(parent()).resolved_section_ids[0])
    assert a.contract == d.BYPASS_DIODE_CONTRACT_ID == "explicit_bypass_section_diode_authority_v1"
    assert a.model == d.BYPASS_DIODE_MODEL_ID == "constant_forward_voltage_bypass_diode_v1"
    assert (
        a.scope
        == d.BYPASS_DIODE_SCOPE
        == "advanced_s8_section_bypass_diode_before_common_current_composition"
    )
    assert (
        a.coverage_scope
        == d.BYPASS_DIODE_COVERAGE_SCOPE
        == "explicit_stage4a1_bypass_sections_with_reviewed_diode_forward_voltage"
    )
    from dataclasses import MISSING

    assert next(f for f in fields(a) if f.name == "forward_voltage_v").default is MISSING


@pytest.mark.parametrize(
    "value", [0, -1, True, False, float("nan"), float("inf"), -float("inf"), "0.5", None]
)
def test_forward_voltage_invalid(value: Any) -> None:
    a = diode(reverse(parent()).resolved_section_ids[0])
    with pytest.raises(ValueError):
        replace(a, forward_voltage_v=value)


@pytest.mark.parametrize(
    "field", ["parameter_source", "confidence", "method_reference", "applicability_description"]
)
@pytest.mark.parametrize("value", ["", " padded", "padded ", None, 1])
def test_provenance_invalid(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(diode(reverse(parent()).resolved_section_ids[0]), **{field: value})


@pytest.mark.parametrize("confidence", ["high", "medium", "low", "unknown"])
def test_confidence(confidence: str) -> None:
    d.validate_section_bypass_diode_parameters(
        replace(diode(reverse(parent()).resolved_section_ids[0]), confidence=confidence)
    )


def test_unknown_section_identity_mismatch_and_no_input_mutation() -> None:
    p = parent()
    rev = reverse(p)
    key = rev.resolved_section_ids[0]
    a = diode(key)
    before = repr(p), repr(rev), repr(a)
    result = d.resolve_section_bypass_diode_authority(p, rev, {key: a})
    assert (repr(p), repr(rev), repr(a)) == before
    unknown = r.BypassSectionIdentity("unknown", "section-z")
    with pytest.raises(ValueError):
        d.resolve_section_bypass_diode_authority(p, rev, {unknown: diode(unknown)})
    with pytest.raises(ValueError):
        d.resolve_section_bypass_diode_authority(p, rev, {rev.resolved_section_ids[1]: a})
    copied = result.authorities_by_section[key]
    assert copied is not a and copied.identity is not a.identity
    object.__setattr__(a, "forward_voltage_v", 5.0)
    assert copied.forward_voltage_v == 0.5
    with pytest.raises(FrozenInstanceError):
        copied.forward_voltage_v = 1.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.authorities_by_section[key] = copied  # type: ignore[index]


@pytest.mark.parametrize(
    "field,value",
    [
        ("forward_voltage_v", True),
        ("forward_voltage_v", 0),
        ("parameter_source", ""),
        ("confidence", "certain"),
        ("method_reference", " padded"),
        ("applicability_description", ""),
        ("contract", "other"),
        ("model", "other"),
        ("scope", "other"),
        ("coverage_scope", "other"),
    ],
)
def test_forged_authority_rejected(field: str, value: Any) -> None:
    p = parent()
    rev = reverse(p)
    key = rev.resolved_section_ids[0]
    a = diode(key)
    result = d.resolve_section_bypass_diode_authority(p, rev, {key: a})
    object.__setattr__(a, field, value)
    with pytest.raises(ValueError):
        d.resolve_section_bypass_diode_authority(p, rev, {key: a})
    object.__setattr__(result.authorities_by_section[key], field, value)
    with pytest.raises(ValueError):
        d.validate_section_bypass_diode_authority(p, rev, result)


@pytest.mark.parametrize(
    "field",
    [
        "contract",
        "model",
        "scope",
        "coverage_scope",
        "resolved_section_ids",
        "unavailable_section_ids",
        "authorities_by_section",
    ],
)
def test_forged_result(field: str) -> None:
    p = parent()
    rev = reverse(p)
    key = rev.resolved_section_ids[0]
    result = d.resolve_section_bypass_diode_authority(p, rev, {key: diode(key)})
    object.__setattr__(result, field, None)
    with pytest.raises(ValueError):
        d.validate_section_bypass_diode_authority(p, rev, result)


@pytest.mark.parametrize("field", [f.name for f in fields(d.SectionBypassDiodeDiagnostics)])
def test_counts_independent(field: str) -> None:
    p = parent()
    rev = reverse(p)
    result = d.resolve_section_bypass_diode_authority(p, rev, {})
    object.__setattr__(result.diagnostics, field, True)
    with pytest.raises(ValueError):
        d.validate_section_bypass_diode_authority(p, rev, result)


def test_independent_validator_and_forged_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    p = parent()
    rev = reverse(p)
    key = rev.resolved_section_ids[0]
    result = d.resolve_section_bypass_diode_authority(p, rev, {key: diode(key)})

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("builder called")

    monkeypatch.setattr(d, "resolve_section_bypass_diode_authority", forbidden)
    for cls in (
        d.SectionBypassDiodeAuthority,
        d.SectionBypassDiodeDiagnostics,
        d.SectionBypassDiodeAuthorityResult,
    ):
        monkeypatch.setattr(cls, "__init__", forbidden)
        if hasattr(cls, "__post_init__"):
            monkeypatch.setattr(cls, "__post_init__", forbidden)
    d.validate_section_bypass_diode_authority(p, rev, result)
    object.__setattr__(
        p.authorities_by_string_id["string-z"].module_members[0], "series_index", True
    )
    with pytest.raises(ValueError):
        d.validate_section_bypass_diode_authority(p, rev, result)
