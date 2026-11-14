"""Exact numerical classes preserve distinct physical assets and evidence."""

from dataclasses import fields, replace
from types import MappingProxyType
from typing import Any

import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import string_operating_classes as c
from heliotelligence.physics.string_member_topology_authority import (
    BypassProtectedSection,
    PhysicalModuleMember,
    StringMemberTopologyAuthority,
    resolve_topology_string_member_authority,
)
from heliotelligence.physics.string_section_bypass_diode_authority import (
    SectionBypassDiodeAuthority,
    resolve_section_bypass_diode_authority,
)
from heliotelligence.physics.string_section_direct_beam_state import (
    resolve_section_direct_beam_state,
)
from heliotelligence.physics.string_section_electrical_state_authority import (
    SectionElectricalOperatingStateBinding,
    resolve_section_electrical_state_authority,
)
from heliotelligence.physics.string_section_optical_binding_authority import (
    SectionOpticalBinding,
    resolve_section_optical_binding_authority,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    SectionReverseBreakdownAuthority,
    resolve_section_reverse_breakdown_authority,
)
from tests.unit.test_physics.test_string_section_bypass_clamp import state
from tests.unit.test_physics.test_string_section_direct_beam_state import snapshot
from tests.unit.test_physics.test_string_section_electrical_state_authority import STAMP
from tests.unit.test_physics.test_string_section_optical_binding_authority import geometry


def inputs(module_counts: tuple[int, ...] = (1, 1, 1)) -> Any:
    names = ("string-z", "string-a", "string-b")
    topology = ElectricalTopologyConfig.model_validate(
        {
            "inverters": [
                {
                    "id": "inv",
                    "mppts": [
                        {
                            "id": "mppt",
                            "strings": [
                                {"id": name, "modules_per_string": count}
                                for name, count in zip(names, module_counts, strict=True)
                            ],
                        }
                    ],
                }
            ]
        }
    )
    declared = {
        name: StringMemberTopologyAuthority(
            name,
            tuple(
                PhysicalModuleMember(
                    f"{name}-module-{m}",
                    m,
                    f"position:{name}:{m}",
                    tuple(
                        BypassProtectedSection(f"{name}-local-{s}", 24 + 24 * s, 2 - s)
                        for s in range(2)
                    ),
                )
                for m in range(count)
            ),
            f"source:{name}",
            "unknown",
            f"method:{name}",
            "synthetic",
        )
        for name, count in zip(names, module_counts, strict=True)
    }
    p = resolve_topology_string_member_authority(topology, declared)
    g = geometry()
    sections = [
        (BypassSectionIdentity(m.module_id, s.section_id), m, j)
        for a in p.authorities_by_string_id.values()
        for m in a.module_members
        for j, s in enumerate(m.bypass_protected_sections)
    ]
    reverse = resolve_section_reverse_breakdown_authority(
        p,
        {
            k: SectionReverseBreakdownAuthority(
                k, 0.002, -15.0, 3.0, f"source:{k.module_id}", "unknown", "test", "synthetic"
            )
            for k, _, _ in sections
        },
    )
    diode = resolve_section_bypass_diode_authority(
        p,
        reverse,
        {
            k: SectionBypassDiodeAuthority(k, 0.45, "test", "unknown", "test", "synthetic")
            for k, _, _ in sections
        },
    )
    static = resolve_section_optical_binding_authority(
        p,
        g,
        {
            k: SectionOpticalBinding(
                k,
                m.physical_position_reference,
                "revision-1",
                "receiver-independent",
                2,
                4,
                (i,),
                "test",
                "unknown",
                "test",
                "synthetic",
            )
            for i, (k, m, _) in enumerate(sections)
        },
    )
    snaps = (snapshot(),)
    optical = resolve_section_direct_beam_state(p, g, static, snaps)
    bindings = {
        k: SectionElectricalOperatingStateBinding(
            k,
            "revision-1",
            "snapshot:test",
            STAMP,
            replace(state(2.0 if j == 0 else 10.0), state_reference=f"state:{k.module_id}:{j}"),
            "test",
            "low" if "string-a" in k.module_id else "unknown",
            "test",
            "explicit synthetic electrical equivalent",
            "explicit synthetic cell temperature",
            "synthetic",
        )
        for k, _, j in sections
    }
    electrical = resolve_section_electrical_state_authority(
        p, g, static, snaps, optical, STAMP, bindings
    )
    return [p, g, static, snaps, optical, electrical, reverse, diode]


def classify(x: Any) -> c.StringOperatingClassesResult:
    return c.resolve_string_operating_classes(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7])


def validate(x: Any, r: Any) -> None:
    c.validate_string_operating_classes(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], r)


def update_electrical(x: Any, supplied: Any) -> None:
    x[5] = resolve_section_electrical_state_authority(x[0], x[1], x[2], x[3], x[4], STAMP, supplied)


def test_identity_provenance_excluded_exact_class_order_and_closure() -> None:
    x = inputs()
    r = classify(x)
    assert r.contract == "exact_advanced_string_operating_equivalence_classes_v1"
    assert r.model == "ordered_section_topology_and_complete_numerical_state_equivalence_v1"
    assert r.scope == "advanced_s8_exact_string_classification_before_method_b_candidate_evaluation"
    assert r.coverage_scope == "complete_stage4a_section_state_reverse_and_bypass_diode_evidence"
    assert len(r.classes) == 1
    assert r.classes[0].class_id == "operating-class-0000"
    assert r.classes[0].representative_string_id == "string-z"
    assert r.classes[0].member_string_ids == ("string-z", "string-a", "string-b")
    assert r.diagnostics == c.StringOperatingClassDiagnostics(3, 3, 3, 0, 1, 2)
    b = dict(reversed(list(x[5].bindings_by_section.items())))
    update_electrical(x, b)
    assert classify(x) == r
    assert type(r.class_id_by_string_id) is MappingProxyType
    assert r.electrical_state_authority is not x[5]
    key = next(iter(x[5].bindings_by_section))
    object.__setattr__(x[5].bindings_by_section[key].operating_state, "photocurrent_a", -1.0)
    assert (
        r.electrical_state_authority.bindings_by_section[key].operating_state.photocurrent_a == 2.0
    )


@pytest.mark.parametrize(
    "field",
    [
        "effective_irradiance_wm2",
        "cell_temperature_c",
        "photocurrent_a",
        "saturation_current_a",
        "resistance_series_ohm",
        "resistance_shunt_ohm",
        "n_ns_vth_v",
    ],
)
def test_each_operating_numeric_and_near_equal_value_splits(field: str) -> None:
    x = inputs()
    b = dict(x[5].bindings_by_section)
    key = list(b)[2]
    v = b[key]
    b[key] = replace(
        v,
        operating_state=replace(
            v.operating_state, **{field: getattr(v.operating_state, field) + 1e-10}
        ),
    )
    update_electrical(x, b)
    r = classify(x)
    assert [a.member_string_ids for a in r.classes] == [("string-z", "string-b"), ("string-a",)]
    assert [a.class_id for a in r.classes] == ["operating-class-0000", "operating-class-0001"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("breakdown_factor", 0.003),
        ("breakdown_voltage_v", -16.0),
        ("breakdown_exponent", 3.1),
        ("forward_voltage_v", 0.46),
    ],
)
def test_each_reverse_and_diode_numeric_splits(field: str, value: float) -> None:
    x = inputs()
    key = list(x[6].authorities_by_section)[2]
    if field == "forward_voltage_v":
        b = dict(x[7].authorities_by_section)
        b[key] = replace(b[key], **{field: value})
        x[7] = resolve_section_bypass_diode_authority(x[0], x[6], b)
    else:
        b = dict(x[6].authorities_by_section)
        b[key] = replace(b[key], **{field: value})
        x[6] = resolve_section_reverse_breakdown_authority(x[0], b)
    assert len(classify(x).classes) == 2


@pytest.mark.parametrize("field", ["series_cells_per_branch", "parallel_cell_branches"])
def test_topology_count_splits(field: str) -> None:
    x = inputs()
    section = (
        x[0].authorities_by_string_id["string-a"].module_members[0].bypass_protected_sections[0]
    )
    object.__setattr__(section, field, getattr(section, field) + 1)
    assert len(classify(x).classes) == 2


def test_module_boundaries_and_section_order_matter() -> None:
    assert len(classify(inputs((1, 2, 1))).classes) == 2
    x = inputs()
    b = dict(x[5].bindings_by_section)
    keys = list(b)[2:4]
    first, second = b[keys[0]], b[keys[1]]
    b[keys[0]] = replace(first, operating_state=second.operating_state)
    b[keys[1]] = replace(second, operating_state=first.operating_state)
    update_electrical(x, b)
    assert len(classify(x).classes) == 2


@pytest.mark.parametrize("kind", ["electrical", "reverse", "diode"])
def test_incomplete_string_is_unavailable(kind: str) -> None:
    x = inputs()
    key = next(iter(x[5].bindings_by_section))
    if kind == "electrical":
        update_electrical(x, {k: v for k, v in x[5].bindings_by_section.items() if k != key})
    elif kind == "reverse":
        x[6] = resolve_section_reverse_breakdown_authority(
            x[0], {k: v for k, v in x[6].authorities_by_section.items() if k != key}
        )
    else:
        x[7] = resolve_section_bypass_diode_authority(
            x[0], x[6], {k: v for k, v in x[7].authorities_by_section.items() if k != key}
        )
    assert classify(x).unavailable_string_ids == ("string-z",)


@pytest.mark.parametrize("field", [f.name for f in fields(c.StringOperatingClassesResult)])
def test_independent_validator_catches_result_tampering(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    x = inputs()
    r = classify(x)
    object.__setattr__(r, field, None)
    monkeypatch.setattr(
        c, "resolve_string_operating_classes", lambda *args: pytest.fail("resolver called")
    )
    with pytest.raises(ValueError):
        validate(x, r)


def test_forged_signature_representative_and_members_rejected() -> None:
    for field, value in [
        ("signature", ()),
        ("representative_string_id", "string-a"),
        ("member_string_ids", ("string-z", "string-z")),
    ]:
        x = inputs()
        r = classify(x)
        object.__setattr__(r.classes[0], field, value)
        with pytest.raises(ValueError):
            validate(x, r)


def test_provenance_only_changes_do_not_split() -> None:
    x = inputs()
    bindings = {
        k: replace(
            v,
            parameter_source=f"source:{k.module_id}",
            confidence="high",
            method_reference=f"method:{k.module_id}",
            applicability_description=f"applicability:{k.module_id}",
            irradiance_basis_description=f"irradiance:{k.module_id}",
            temperature_basis_description=f"temperature:{k.module_id}",
            operating_state=replace(v.operating_state, state_reference=f"new:{k.module_id}"),
        )
        for k, v in x[5].bindings_by_section.items()
    }
    update_electrical(x, bindings)
    assert len(classify(x).classes) == 1


def test_equal_flat_sections_different_module_boundaries_split() -> None:
    x = inputs((1, 2, 1))
    declared = dict(x[0].authorities_by_string_id)
    modules = declared["string-a"].module_members
    declared["string-a"] = replace(
        declared["string-a"],
        module_members=(
            replace(
                modules[0], bypass_protected_sections=(modules[0].bypass_protected_sections[0],)
            ),
            replace(
                modules[1], bypass_protected_sections=(modules[1].bypass_protected_sections[1],)
            ),
        ),
    )
    topology = ElectricalTopologyConfig.model_validate(
        {
            "inverters": [
                {
                    "id": "inv",
                    "mppts": [
                        {
                            "id": "mppt",
                            "strings": [
                                {"id": sid, "modules_per_string": len(a.module_members)}
                                for sid, a in declared.items()
                            ],
                        }
                    ],
                }
            ]
        }
    )
    x[0] = resolve_topology_string_member_authority(topology, declared)
    keys = {
        BypassSectionIdentity(m.module_id, s.section_id)
        for a in declared.values()
        for m in a.module_members
        for s in m.bypass_protected_sections
    }
    x[2] = resolve_section_optical_binding_authority(
        x[0], x[1], {k: v for k, v in x[2].bindings_by_section.items() if k in keys}
    )
    x[4] = resolve_section_direct_beam_state(x[0], x[1], x[2], x[3])
    update_electrical(x, {k: v for k, v in x[5].bindings_by_section.items() if k in keys})
    x[6] = resolve_section_reverse_breakdown_authority(
        x[0], {k: v for k, v in x[6].authorities_by_section.items() if k in keys}
    )
    x[7] = resolve_section_bypass_diode_authority(
        x[0], x[6], {k: v for k, v in x[7].authorities_by_section.items() if k in keys}
    )
    r = classify(x)
    assert [c.member_string_ids for c in r.classes] == [("string-z", "string-b"), ("string-a",)]
    assert tuple(s for module in r.classes[0].signature for s in module) == tuple(
        s for module in r.classes[1].signature for s in module
    )


def test_no_tolerant_classification_or_policy_defaults() -> None:
    import ast
    from pathlib import Path

    assert c.__file__ is not None
    tree = ast.parse(Path(c.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert name not in {"round", "isclose", "allclose", "digitize", "histogram", "hash"}
