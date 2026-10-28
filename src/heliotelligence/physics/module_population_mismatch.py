"""Dormant intra-string population residual after canonical shared-voltage MPPT.

This explicit lower-fidelity authority is not a member-resolved I-V model.
It consumes no SiteConfig, legacy percentage, random population or cable model.
Future series-member physics must compose V_string(I) = sum(V_member(I)), with
explicit reverse/bypass authority where current domains require it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import electrical

MODULE_POPULATION_MISMATCH_AUTHORITY_CONTRACT_ID = (
    "explicit_intra_string_population_mismatch_residual_authority_v1"
)
MODULE_POPULATION_MISMATCH_CONTRACT_ID = (
    "admitted_s8_common_voltage_mppt_and_population_residual_authority_"
    "to_population_complete_dc_state_v1"
)
MODULE_POPULATION_MISMATCH_MODEL_ID = (
    "shared_mppt_physical_mismatch_plus_explicit_post_mppt_equivalent_current_derate_v1"
)
MODULE_POPULATION_MISMATCH_SCOPE = "mppt_resolved_dc_after_population_mismatch_before_dc_collection"
MODULE_POPULATION_MISMATCH_COVERAGE_SCOPE = (
    "shared_mppt_physics_plus_explicit_lower_fidelity_intra_string_population_residual"
)
MECHANISM_SCOPE = (
    "intra_string_module_population_only_excluding_shared_mppt_common_voltage_mismatch"
)
_EVIDENCE = frozenset(
    {
        "factory_flash_population",
        "commissioning_iv_population",
        "validated_engineering_study",
        "measured_operating_population",
        "other_explicit",
    }
)
_MODES = frozenset({"explicit_negligible_by_evidence", "equivalent_post_mppt_current_derate"})
_ACTIVE = "resolved_common_voltage_mppt"
_ZERO = "resolved_zero_common_voltage_mppt"
_MEMBER = "unresolved_member_string_iv"
_MIXED = "unresolved_mixed_active_zero_requires_blocking_model"
_COUNTS = (
    "configured_string_count",
    "active_string_count",
    "zero_string_count",
    "unresolved_string_count",
)
_BASE = {
    "v_common_mppt_v": "v_common_mppt_v",
    "i_common_mppt_a": "i_common_mppt_a",
    "p_common_mppt_w": "p_common_mppt_w",
    "p_homogeneous_independent_mp_w": "p_independent_mp_w",
    "shared_mppt_mismatch_w": "p_mismatch_w",
    "shared_mppt_mismatch_pct": "mismatch_pct",
}
_ADJUSTED = (
    "population_mismatch_w",
    "v_after_population_mismatch_v",
    "i_after_population_mismatch_a",
    "p_after_population_mismatch_w",
    "total_mismatch_from_homogeneous_independent_w",
    "total_mismatch_pct",
)
_PROVENANCE = (
    "mechanism_scope",
    "evidence_kind",
    "parameter_source",
    "confidence",
    "method_reference",
    "applicability_description",
)
_PARENT_IDS = {
    "topology_string_iv_contract": electrical.TOPOLOGY_STRING_IV_CONTRACT_ID,
    "topology_string_iv_model": electrical.TOPOLOGY_STRING_IV_MODEL_ID,
    "topology_string_iv_scope": electrical.TOPOLOGY_STRING_IV_SCOPE,
    "topology_string_iv_coverage_scope": electrical.TOPOLOGY_STRING_IV_COVERAGE_SCOPE,
    "topology_mppt_mismatch_contract": electrical.TOPOLOGY_MPPT_MISMATCH_CONTRACT_ID,
    "topology_mppt_mismatch_model": electrical.TOPOLOGY_MPPT_MISMATCH_MODEL_ID,
    "topology_mppt_mismatch_scope": electrical.TOPOLOGY_MPPT_MISMATCH_SCOPE,
    "topology_mppt_mismatch_coverage_scope": electrical.TOPOLOGY_MPPT_MISMATCH_COVERAGE_SCOPE,
}
_FIXED = {
    "module_population_mismatch_authority_contract": (
        MODULE_POPULATION_MISMATCH_AUTHORITY_CONTRACT_ID
    ),
    "module_population_mismatch_contract": MODULE_POPULATION_MISMATCH_CONTRACT_ID,
    "module_population_mismatch_model": MODULE_POPULATION_MISMATCH_MODEL_ID,
    "module_population_mismatch_scope": MODULE_POPULATION_MISMATCH_SCOPE,
    "module_population_mismatch_coverage_scope": MODULE_POPULATION_MISMATCH_COVERAGE_SCOPE,
    **_PARENT_IDS,
}
_BOOL = (
    "population_mismatch_authority_present",
    "population_mismatch_is_lower_fidelity",
    "population_mismatch_resolved",
    "legacy_mismatch_percentage_consumed",
    "upstream_mppt_resolved",
)
_TEXT = (
    "population_mismatch_resolution_mode",
    "population_mismatch_state",
    "upstream_mppt_state",
    "unresolved_string_ids",
    "unresolved_string_states",
    *_PROVENANCE,
    *_FIXED,
)
_FLOAT = (*_BASE, "population_mismatch_fraction", *_ADJUSTED)
_COLUMNS = (*_COUNTS, *_FLOAT, *_BOOL, *_TEXT)


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be an exact non-empty unpadded string")


def _real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite non-Boolean real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _flag(value: object) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError("resolution flags must be Boolean")
    return bool(value)


def _count(value: object) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 0:
        raise ValueError("diagnostic/string counts must be non-negative integers")
    return int(value)


def _close(value: float, expected: float) -> bool:
    # Same closure tolerance as the canonical S8 electrical handoff.
    return math.isclose(value, expected, rel_tol=1e-10, abs_tol=1e-10)


@dataclass(frozen=True)
class ModulePopulationMismatchAuthority:
    resolution_mode: str
    equivalent_current_derate_fraction: float
    mechanism_scope: str
    evidence_kind: str
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str

    def __post_init__(self) -> None:
        for name in ("resolution_mode", *_PROVENANCE):
            _text(getattr(self, name), name)
        if self.resolution_mode not in _MODES or self.mechanism_scope != MECHANISM_SCOPE:
            raise ValueError("unsupported population resolution mode or mechanism scope")
        if self.evidence_kind not in _EVIDENCE:
            raise ValueError("unsupported population evidence kind")
        if self.confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError("unsupported confidence")
        fraction = _real(self.equivalent_current_derate_fraction, "population fraction")
        if (self.resolution_mode == "explicit_negligible_by_evidence" and fraction != 0.0) or (
            self.resolution_mode == "equivalent_post_mppt_current_derate" and not 0 < fraction < 1
        ):
            raise ValueError(
                "fraction must be zero for negligible mode or strictly between 0 and 1 for derate"
            )


@dataclass(frozen=True)
class ModulePopulationMismatchDiagnostics:
    timestamp_count: int
    populated_mppt_count: int
    authority_mppt_count: int
    row_count: int
    resolved_row_count: int
    unresolved_row_count: int
    missing_authority_row_count: int
    upstream_unresolved_row_count: int
    negligible_row_count: int
    derated_row_count: int
    zero_row_count: int
    state_counts: Mapping[str, int]
    contract: str = MODULE_POPULATION_MISMATCH_CONTRACT_ID
    model: str = MODULE_POPULATION_MISMATCH_MODEL_ID


@dataclass(frozen=True)
class ModulePopulationMismatchResult:
    states: pd.DataFrame
    diagnostics: ModulePopulationMismatchDiagnostics


def _admit(
    topology: ElectricalTopologyConfig,
    upstream: electrical.TopologyMPPTMismatchResult,
    authorities: Mapping[tuple[str, str], ModulePopulationMismatchAuthority],
) -> tuple[pd.DataFrame, Mapping[tuple[str, str], ModulePopulationMismatchAuthority]]:
    """Independently admit the public S8 contract, never its private validator."""
    if type(topology) is not ElectricalTopologyConfig:
        raise ValueError("exact ElectricalTopologyConfig required")
    topology = ElectricalTopologyConfig.model_validate(topology.model_dump())
    if type(upstream) is not electrical.TopologyMPPTMismatchResult:
        raise ValueError("exact TopologyMPPTMismatchResult required")
    if type(upstream.diagnostics) is not electrical.TopologyMPPTMismatchDiagnostics:
        raise ValueError("exact upstream diagnostics required")
    populated = {
        (inv.id, mppt.id): tuple(string.id for string in mppt.strings)
        for inv in topology.inverters
        for mppt in inv.mppts
        if mppt.strings
    }
    for inv in topology.inverters:
        _text(inv.id, "inverter ID")
        for mppt in inv.mppts:
            _text(mppt.id, "MPPT ID")
            for string in mppt.strings:
                _text(string.id, "string ID")
    if not isinstance(authorities, Mapping):
        raise ValueError("authority_by_mppt must be a mapping")
    admitted = {}
    for key, authority in authorities.items():
        if type(key) is not tuple or len(key) != 2 or any(type(v) is not str for v in key):
            raise ValueError("authority keys must be exact (inverter_id, mppt_id) tuples")
        if key not in populated:
            raise ValueError("authority key is unknown or refers to an empty MPPT")
        if type(authority) is not ModulePopulationMismatchAuthority:
            raise ValueError("exact ModulePopulationMismatchAuthority required")
        admitted[key] = replace(authority)  # Revalidate even supplied frozen instances.
    frame = upstream.operating_points
    if type(frame) is not pd.DataFrame or not frame.columns.is_unique:
        raise ValueError("upstream must contain a unique-column DataFrame")
    required = {
        *_COUNTS,
        *_BASE.values(),
        *_PARENT_IDS,
        "mppt_resolved",
        "mppt_state",
        "unresolved_string_ids",
        "unresolved_string_states",
    }
    if not required <= set(frame.columns):
        raise ValueError("incomplete upstream schema")
    if (
        not isinstance(frame.index, pd.MultiIndex)
        or frame.index.names != ["timestamp", "inverter_id", "mppt_id"]
        or not frame.index.is_unique
    ):
        raise ValueError("invalid upstream timestamp/inverter/MPPT MultiIndex")
    times = frame.index.get_level_values("timestamp").unique()
    if len(frame) and (
        not isinstance(times, pd.DatetimeIndex) or times.tz is None or times.hasnans
    ):
        raise ValueError("upstream timestamps must be timezone-aware and NaT-free")
    expected_index = pd.MultiIndex.from_tuples(
        [(t, inv, mppt) for t in times for inv, mppt in populated], names=frame.index.names
    )
    if not frame.index.equals(expected_index):
        raise ValueError("upstream populated MPPT row universe/order disagrees with topology")
    active_keys = set()
    states: Counter[str] = Counter()
    for key, row in frame.iterrows():
        for column, identity in _PARENT_IDS.items():
            if type(row[column]) is not str or row[column] != identity:
                raise ValueError("invalid upstream contract/model/scope provenance")
        string_ids = populated[(key[1], key[2])]
        configured, active, zero, unresolved = (_count(row[c]) for c in _COUNTS)
        if configured != len(string_ids) or configured != active + zero + unresolved:
            raise ValueError("upstream string classification counts disagree")
        ids = row["unresolved_string_ids"]
        causes = row["unresolved_string_states"]
        if type(ids) is not str or type(causes) is not str:
            raise ValueError("invalid unresolved string summary")
        listed = ids.split(",") if ids else []
        if (
            len(listed) != unresolved
            or len(set(listed)) != len(listed)
            or not set(listed) <= set(string_ids)
            or bool(causes) != bool(unresolved)
        ):
            raise ValueError("upstream unresolved string summary disagrees")
        expected_state = (
            _MEMBER
            if unresolved
            else _MIXED
            if active and zero
            else _ZERO
            if zero == configured
            else _ACTIVE
        )
        if row["mppt_state"] != expected_state or _flag(row["mppt_resolved"]) != (
            expected_state in {_ACTIVE, _ZERO}
        ):
            raise ValueError("upstream state/resolved consistency failed")
        states[expected_state] += 1
        if expected_state not in {_ACTIVE, _ZERO}:
            if any(
                not isinstance(row[c], Real)
                or isinstance(row[c], (bool, np.bool_))
                or not math.isnan(float(row[c]))
                for c in _BASE.values()
            ):
                raise ValueError("unresolved upstream numerics must be NaN")
            continue
        v, i, common, independent, mismatch, pct = (_real(row[c], c) for c in _BASE.values())
        if min(v, i, common, independent, mismatch, pct) < -1e-7:
            raise ValueError("negative upstream electrical quantity")
        if expected_state == _ZERO:
            if any(row[c] != 0 for c in _BASE.values()):
                raise ValueError("resolved-zero upstream must be exactly zero")
        else:
            active_keys.add((key[1], key[2]))
            if min(v, i, common, independent) <= 0:
                raise ValueError("active upstream V/I/P must be positive")
        if (
            not _close(common, v * i)
            or not _close(mismatch, independent - common)
            or common > independent + 1e-7
        ):
            raise ValueError("upstream electrical/mismatch power closure failed")
        expected_pct = 100 * mismatch / independent if independent > 0 else 0.0
        if not _close(pct, expected_pct) or pct > 100 + 1e-7:
            raise ValueError("upstream mismatch percentage closure failed")
    expected_diagnostics = {
        "inverter_count": topology.inverter_count,
        "mppt_count": topology.mppt_count,
        "populated_mppt_count": len(populated),
        "empty_mppt_count": topology.mppt_count - len(populated),
        "string_count": topology.string_count,
        "timestamp_count": len(times),
        "state_row_count": len(frame),
        "resolved_mppt_state_count": states[_ACTIVE] + states[_ZERO],
        "unresolved_mppt_state_count": states[_MEMBER] + states[_MIXED],
        "active_mppt_state_count": states[_ACTIVE],
        "zero_mppt_state_count": states[_ZERO],
        "upstream_unresolved_mppt_state_count": states[_MEMBER],
        "mixed_active_zero_unavailable_count": states[_MIXED],
        "physics_row_count": states[_ACTIVE],
        "physics_call_count": len(active_keys),
    }
    for column, value in expected_diagnostics.items():
        if _count(getattr(upstream.diagnostics, column)) != value:
            raise ValueError(f"upstream diagnostics disagree: {column}")
    if upstream.diagnostics.mppt_mismatch_model != electrical.TOPOLOGY_MPPT_MISMATCH_MODEL_ID:
        raise ValueError("upstream diagnostics model disagrees")
    return frame, MappingProxyType(admitted)


def _record(row: pd.Series, authority: ModulePopulationMismatchAuthority | None) -> dict[str, Any]:
    result: dict[str, Any] = {c: int(row[c]) for c in _COUNTS}
    result.update({out: row[parent] for out, parent in _BASE.items()})
    result.update(dict.fromkeys(_ADJUSTED, math.nan))
    result.update(dict.fromkeys(_BOOL, False))
    result.update(dict.fromkeys(_TEXT, ""))
    result.update(_FIXED)
    result.update(
        population_mismatch_fraction=math.nan,
        population_mismatch_authority_present=authority is not None,
        upstream_mppt_state=row["mppt_state"],
        upstream_mppt_resolved=bool(row["mppt_resolved"]),
        unresolved_string_ids=row["unresolved_string_ids"],
        unresolved_string_states=row["unresolved_string_states"],
        population_mismatch_state="unresolved_upstream_mppt"
        if not row["mppt_resolved"]
        else "unresolved_population_mismatch_authority",
    )
    if authority is not None:
        result.update({c: getattr(authority, c) for c in _PROVENANCE})
        result.update(
            population_mismatch_resolution_mode=authority.resolution_mode,
            population_mismatch_fraction=float(authority.equivalent_current_derate_fraction),
            population_mismatch_is_lower_fidelity=True,
        )
    if authority is None or not row["mppt_resolved"]:
        return result
    f = float(authority.equivalent_current_derate_fraction)
    voltage = float(row["v_common_mppt_v"])
    current = float(row["i_common_mppt_a"]) * (1 - f)
    power = voltage * current if f else float(row["p_common_mppt_w"])
    population = float(row["p_common_mppt_w"]) - power
    total = float(row["p_mismatch_w"]) + population
    independent = float(row["p_independent_mp_w"])
    result.update(
        v_after_population_mismatch_v=voltage,
        i_after_population_mismatch_a=current,
        p_after_population_mismatch_w=power,
        population_mismatch_w=population,
        total_mismatch_from_homogeneous_independent_w=total,
        total_mismatch_pct=100 * total / independent if independent else 0.0,
        population_mismatch_resolved=True,
        population_mismatch_state="resolved_zero_population_mismatch"
        if row["mppt_state"] == _ZERO
        else "resolved_" + authority.resolution_mode,
    )
    return result


def _frame(records: list[dict[str, Any]], index: pd.MultiIndex) -> pd.DataFrame:
    result = pd.DataFrame(records, index=index.copy(), columns=_COLUMNS)
    for column in _COUNTS + _FLOAT + _BOOL + _TEXT:
        result[column] = result[column].astype(
            int
            if column in _COUNTS
            else float
            if column in _FLOAT
            else bool
            if column in _BOOL
            else object
        )
    return result


def _diagnostics(
    frame: pd.DataFrame, topology: ElectricalTopologyConfig, authority_count: int
) -> ModulePopulationMismatchDiagnostics:
    counts = Counter(frame.population_mismatch_state)
    resolved = int(frame.population_mismatch_resolved.sum())
    return ModulePopulationMismatchDiagnostics(
        len(frame.index.get_level_values("timestamp").unique()),
        sum(bool(mppt.strings) for inv in topology.inverters for mppt in inv.mppts),
        authority_count,
        len(frame),
        resolved,
        len(frame) - resolved,
        counts["unresolved_population_mismatch_authority"],
        counts["unresolved_upstream_mppt"],
        counts["resolved_explicit_negligible_by_evidence"],
        counts["resolved_equivalent_post_mppt_current_derate"],
        counts["resolved_zero_population_mismatch"],
        MappingProxyType(dict(sorted(counts.items()))),
    )


def apply_module_population_mismatch(
    topology: ElectricalTopologyConfig,
    mppt_mismatch: electrical.TopologyMPPTMismatchResult,
    *,
    authority_by_mppt: Mapping[tuple[str, str], ModulePopulationMismatchAuthority],
) -> ModulePopulationMismatchResult:
    """Preserve shared mismatch; apply only explicitly admitted population residual."""
    baseline, authorities = _admit(topology, mppt_mismatch, authority_by_mppt)
    frame = _frame(
        [_record(row, authorities.get((key[1], key[2]))) for key, row in baseline.iterrows()],
        baseline.index,
    )
    result = ModulePopulationMismatchResult(frame, _diagnostics(frame, topology, len(authorities)))
    validate_module_population_mismatch(
        result, topology, mppt_mismatch, authority_by_mppt=authorities
    )
    return result


def validate_module_population_mismatch(
    result: ModulePopulationMismatchResult,
    topology: ElectricalTopologyConfig,
    mppt_mismatch: electrical.TopologyMPPTMismatchResult,
    *,
    authority_by_mppt: Mapping[tuple[str, str], ModulePopulationMismatchAuthority],
) -> None:
    """Independently replay publication, equations and diagnostics; no builder calls."""
    baseline, authorities = _admit(topology, mppt_mismatch, authority_by_mppt)
    if (
        type(result) is not ModulePopulationMismatchResult
        or type(result.diagnostics) is not ModulePopulationMismatchDiagnostics
    ):
        raise ValueError("exact population result and diagnostics required")
    output = result.states
    if (
        type(output) is not pd.DataFrame
        or not output.index.identical(baseline.index)
        or tuple(output.columns) != _COLUMNS
    ):
        raise ValueError("population result row universe/schema disagrees")
    states: Counter[str] = Counter()
    resolved_count = 0
    for key, parent in baseline.iterrows():
        row = output.loc[key]
        authority = authorities.get((key[1], key[2]))
        resolved = bool(parent.mppt_resolved) and authority is not None
        state = (
            "unresolved_upstream_mppt"
            if not parent.mppt_resolved
            else "unresolved_population_mismatch_authority"
            if authority is None
            else "resolved_zero_population_mismatch"
            if parent.mppt_state == _ZERO
            else "resolved_" + authority.resolution_mode
        )
        states[state] += 1
        resolved_count += int(resolved)
        expected: dict[str, Any] = {
            **_FIXED,
            **{c: int(parent[c]) for c in _COUNTS},
            **{out: parent[source] for out, source in _BASE.items()},
        }
        expected.update(
            population_mismatch_authority_present=authority is not None,
            population_mismatch_is_lower_fidelity=authority is not None,
            population_mismatch_resolution_mode=authority.resolution_mode if authority else "",
            population_mismatch_fraction=float(authority.equivalent_current_derate_fraction)
            if authority
            else math.nan,
            population_mismatch_state=state,
            population_mismatch_resolved=resolved,
            legacy_mismatch_percentage_consumed=False,
            upstream_mppt_state=parent.mppt_state,
            upstream_mppt_resolved=bool(parent.mppt_resolved),
            unresolved_string_ids=parent.unresolved_string_ids,
            unresolved_string_states=parent.unresolved_string_states,
        )
        expected.update({c: getattr(authority, c) if authority else "" for c in _PROVENANCE})
        expected.update(dict.fromkeys(_ADJUSTED, math.nan))
        if resolved:
            assert authority is not None
            fraction = float(authority.equivalent_current_derate_fraction)
            after = (
                (1 - fraction) * float(parent.i_common_mppt_a) * float(parent.v_common_mppt_v)
                if fraction
                else float(parent.p_common_mppt_w)
            )
            loss = float(parent.p_common_mppt_w) - after
            total = float(parent.p_independent_mp_w) - after
            expected.update(
                population_mismatch_w=loss,
                v_after_population_mismatch_v=float(parent.v_common_mppt_v),
                i_after_population_mismatch_a=float(parent.i_common_mppt_a) * (1 - fraction),
                p_after_population_mismatch_w=after,
                total_mismatch_from_homogeneous_independent_w=total,
                total_mismatch_pct=100 * total / float(parent.p_independent_mp_w)
                if parent.p_independent_mp_w
                else 0.0,
            )
            actual = {c: _real(row[c], c) for c in _ADJUSTED}
            if not _close(
                actual["p_after_population_mismatch_w"],
                actual["v_after_population_mismatch_v"] * actual["i_after_population_mismatch_a"],
            ):
                raise ValueError("population P=VI closure failed")
            if not _close(
                actual["total_mismatch_from_homogeneous_independent_w"],
                float(parent.p_mismatch_w) + actual["population_mismatch_w"],
            ):
                raise ValueError("shared plus population mismatch closure failed")
        for column, value in expected.items():
            actual_value = row[column]
            if column in _BOOL:
                valid = _flag(actual_value) == value
            elif column in _COUNTS:
                valid = _count(actual_value) == value
            elif column in _FLOAT:
                valid = (
                    isinstance(actual_value, Real)
                    and not isinstance(actual_value, (bool, np.bool_))
                    and (
                        math.isnan(float(actual_value))
                        if math.isnan(value)
                        else _close(float(actual_value), float(value))
                    )
                )
            else:
                valid = type(actual_value) is str and actual_value == value
            if not valid:
                raise ValueError(f"population result replay failed: {column}")
    expected_diagnostics = ModulePopulationMismatchDiagnostics(
        len(baseline.index.get_level_values("timestamp").unique()),
        sum(1 for inv in topology.inverters for mppt in inv.mppts if mppt.strings),
        len(authorities),
        len(baseline),
        resolved_count,
        len(baseline) - resolved_count,
        states["unresolved_population_mismatch_authority"],
        states["unresolved_upstream_mppt"],
        states["resolved_explicit_negligible_by_evidence"],
        states["resolved_equivalent_post_mppt_current_derate"],
        states["resolved_zero_population_mismatch"],
        MappingProxyType(dict(sorted(states.items()))),
    )
    for field in fields(ModulePopulationMismatchDiagnostics):
        actual_diagnostic = getattr(result.diagnostics, field.name)
        if field.name.endswith("_count"):
            _count(actual_diagnostic)
    for state_name, count in result.diagnostics.state_counts.items():
        _text(state_name, "diagnostic state")
        _count(count)
    if result.diagnostics != expected_diagnostics:
        raise ValueError("population diagnostics replay failed")
