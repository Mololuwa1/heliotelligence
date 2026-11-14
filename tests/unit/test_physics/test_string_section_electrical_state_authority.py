"""Explicit complete section state, never derived from optical fractions."""

import ast
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import string_section_direct_beam_state as optical
from heliotelligence.physics import string_section_electrical_state_authority as a
from heliotelligence.physics.string_section_optical_binding_authority import (
    SectionOpticalBinding,
    resolve_section_optical_binding_authority,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import BypassSectionIdentity
from tests.unit.test_physics.test_string_common_current_composition import inputs
from tests.unit.test_physics.test_string_section_direct_beam_state import snapshot
from tests.unit.test_physics.test_string_section_optical_binding_authority import geometry

STAMP = pd.Timestamp("2024-06-21T12:00:00Z")


def context() -> tuple[Any, ...]:
    p, rev, diodes, states = inputs()
    g = geometry()
    positions = {
        m.module_id: m.physical_position_reference
        for x in p.authorities_by_string_id.values()
        for m in x.module_members
    }
    declarations = {
        k: SectionOpticalBinding(
            k,
            positions[k.module_id],
            g.geometry_revision,
            "receiver-independent",
            2,
            4,
            (i,),
            "synthetic drawing",
            "unknown",
            "mapping:test",
            "synthetic only",
        )
        for i, k in enumerate(states)
    }
    static = resolve_section_optical_binding_authority(p, g, declarations)
    snaps = (snapshot(),)
    opt = optical.resolve_section_direct_beam_state(p, g, static, snaps)
    supplied = {
        k: a.SectionElectricalOperatingStateBinding(
            k,
            g.geometry_revision,
            "snapshot:test",
            STAMP,
            v,
            "reviewed synthetic state",
            "unknown",
            "method:test",
            "explicit synthetic complete section electrical-equivalent irradiance",
            "explicit synthetic cell temperature",
            "synthetic only",
        )
        for k, v in states.items()
    }
    return p, g, static, snaps, opt, rev, diodes, supplied


def resolve(supplied: Any = None, ctx: Any = None) -> a.SectionElectricalStateAuthorityResult:
    c = context() if ctx is None else ctx
    return a.resolve_section_electrical_state_authority(
        c[0], c[1], c[2], c[3], c[4], STAMP, c[7] if supplied is None else supplied
    )


def test_complete_partial_empty_fixed_metadata_counts() -> None:
    c = context()
    for n in (6, 1, 0):
        r = resolve(dict(list(c[7].items())[:n]), c)
        assert r.contract == "explicit_section_sdm_operating_state_binding_authority_v1"
        assert (
            r.model == "explicit_complete_section_single_diode_state_bound_to_optical_snapshot_v1"
        )
        assert (
            r.scope
            == "advanced_s8_section_electrical_state_before_bishop_clamp_and_series_composition"
        )
        assert (
            r.coverage_scope
            == "explicit_stage4a5a_sections_with_complete_reviewed_section_sdm_operating_state"
        )
        assert r.diagnostics == a.SectionElectricalStateDiagnostics(6, 6, n, 6 - n)
        assert len(r.resolved_section_ids) == n and len(r.unavailable_section_ids) == 6 - n
        assert r.observation_timestamp == STAMP
        a.validate_section_electrical_state_authority(c[0], c[1], c[2], c[3], c[4], r)


@pytest.mark.parametrize(
    "field,value",
    [
        ("section_identity", BypassSectionIdentity("unknown", "section-a")),
        ("section_identity", BypassSectionIdentity("string-z-module-0", "unknown")),
        ("geometry_revision", "old"),
        ("optical_snapshot_reference", "other"),
        ("observation_timestamp", pd.Timestamp("2024-06-21")),
        ("observation_timestamp", pd.NaT),
        ("observation_timestamp", "2024-06-21"),
        ("observation_timestamp", STAMP + pd.Timedelta(seconds=1)),
        ("parameter_source", " padded"),
        ("confidence", "certain"),
        ("method_reference", ""),
        ("irradiance_basis_description", " "),
        ("temperature_basis_description", ""),
        ("applicability_description", " "),
        ("operating_state", None),
    ],
)
def test_binding_drift_or_invalid_fields_rejected(field: str, value: Any) -> None:
    c = context()
    key = next(iter(c[7]))
    object.__setattr__(c[7][key], field, value)
    with pytest.raises(ValueError):
        resolve(ctx=c)


def test_same_instant_different_timezone_and_key_disagreement_rejected() -> None:
    c = context()
    key = next(iter(c[7]))
    c[7][key] = replace(c[7][key], observation_timestamp=STAMP.tz_convert("Europe/London"))
    with pytest.raises(ValueError):
        resolve(ctx=c)
    c = context()
    key = next(iter(c[7]))
    c[7][BypassSectionIdentity("wrong", "section-a")] = c[7].pop(key)
    with pytest.raises(ValueError):
        resolve(ctx=c)


@pytest.mark.parametrize("field", [f.name for f in fields(a.SectionElectricalStateAuthorityResult)])
def test_independent_validator_rejects_result_tamper(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = context()
    r = resolve(ctx=c)
    object.__setattr__(r, field, None)
    monkeypatch.setattr(
        a,
        "resolve_section_electrical_state_authority",
        lambda *args: pytest.fail("resolver called"),
    )
    with pytest.raises(ValueError):
        a.validate_section_electrical_state_authority(c[0], c[1], c[2], c[3], c[4], r)


@pytest.mark.parametrize(
    "field", [f.name for f in fields(a.SectionElectricalOperatingStateBinding)]
)
def test_independent_validator_rejects_nested_tamper(field: str) -> None:
    c = context()
    r = resolve(ctx=c)
    object.__setattr__(next(iter(r.bindings_by_section.values())), field, None)
    with pytest.raises(ValueError):
        a.validate_section_electrical_state_authority(c[0], c[1], c[2], c[3], c[4], r)


def test_canonical_state_validator_and_no_optical_inference() -> None:
    c = context()
    key = next(iter(c[7]))
    state = c[7][key].operating_state
    c[7][key] = replace(
        c[7][key],
        operating_state=replace(state, effective_irradiance_wm2=123.0, photocurrent_a=7.0),
    )
    r = resolve(ctx=c)
    assert c[4].states_by_section[key].beam_visible_fraction == 1.0
    assert r.bindings_by_section[key].operating_state.photocurrent_a == 7.0
    assert r.bindings_by_section[key].operating_state.effective_irradiance_wm2 == 123.0
    object.__setattr__(r.bindings_by_section[key].operating_state, "photocurrent_a", True)
    with pytest.raises(ValueError):
        a.validate_section_electrical_state_authority(c[0], c[1], c[2], c[3], c[4], r)


def test_requires_resolved_optical_state() -> None:
    c = list(context())
    missing = next(iter(c[7]))
    d = dict(c[2].bindings_by_section)
    del d[missing]
    c[2] = resolve_section_optical_binding_authority(c[0], c[1], d)
    c[4] = optical.resolve_section_direct_beam_state(*c[:4])
    with pytest.raises(ValueError):
        resolve(ctx=c)
    del c[7][missing]
    assert missing in resolve(ctx=c).unavailable_section_ids


def test_order_detachment_and_immutability() -> None:
    c = context()
    r = resolve(ctx=c)
    other = resolve(dict(reversed(list(c[7].items()))), c)
    assert r == other
    key = next(iter(c[7]))
    assert r.bindings_by_section[key] is not c[7][key]
    assert r.bindings_by_section[key].operating_state is not c[7][key].operating_state
    object.__setattr__(c[7][key].operating_state, "photocurrent_a", -1.0)
    assert r.bindings_by_section[key].operating_state.photocurrent_a >= 0
    assert type(r.bindings_by_section) is MappingProxyType
    with pytest.raises(FrozenInstanceError):
        r.scope = "bad"  # type: ignore[misc]


@pytest.mark.parametrize("field", [f.name for f in fields(optical.SectionDirectBeamStateResult)])
def test_optical_parent_forgery_rejected(field: str) -> None:
    c = context()
    object.__setattr__(c[4], field, 30.0 if getattr(c[4], field) is None else None)
    with pytest.raises(ValueError):
        resolve(ctx=c)


def test_optical_nested_equal_value_type_forgery_rejected() -> None:
    c = context()
    v = next(iter(c[4].states_by_section.values()))
    object.__setattr__(v, "visible_sample_count", True)
    with pytest.raises(ValueError):
        resolve(ctx=c)


def test_authority_has_no_inference_or_execution_owners() -> None:
    assert a.__file__ is not None
    tree = ast.parse(Path(a.__file__).read_text())
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            assert not any(
                x in (n.module or "")
                for x in (
                    "electrical",
                    "module_lookup",
                    "dc_collection",
                    "inverter",
                    "engine",
                    "api",
                    "pvlib",
                )
            )
        if isinstance(n, ast.Call):
            assert not (isinstance(n.func, ast.Attribute) and n.func.attr == "calcparams_desoto")


@pytest.mark.parametrize(
    "field,value",
    [
        ("effective_irradiance_wm2", -1.0),
        ("cell_temperature_c", float("nan")),
        ("photocurrent_a", float("inf")),
        ("saturation_current_a", 0.0),
        ("resistance_series_ohm", -1.0),
        ("resistance_shunt_ohm", 0.0),
        ("n_ns_vth_v", True),
    ],
)
def test_invalid_supplied_numeric_state_fails_canonical_validation(field: str, value: Any) -> None:
    c = context()
    binding = next(iter(c[7].values()))
    object.__setattr__(binding.operating_state, field, value)
    with pytest.raises(ValueError):
        resolve(ctx=c)


def test_changed_snapshot_and_noncanonical_mapping_key_fail_replay() -> None:
    c = context()
    c[3][0].visibility_map.loc[0, "beam_visible"] = False
    c[3][0].visibility_map.loc[0, "beam_shaded"] = True
    with pytest.raises(ValueError, match="optical parent"):
        resolve(ctx=c)
    c = context()
    key = next(iter(c[4].states_by_section))

    class NoncanonicalText(str):
        pass

    object.__setattr__(key, "module_id", NoncanonicalText(key.module_id))
    with pytest.raises(ValueError):
        resolve(ctx=c)
