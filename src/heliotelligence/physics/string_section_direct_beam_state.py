"""Assigned finite direct-beam sample visibility, never an electrical derate.

No reviewed canonical mesh-to-rectangle adapter exists. The caller therefore
supplies a visibility-map snapshot and explicitly attests its revision/grid and
opaque snapshot reference. Schema/integrity checks are not evidence authentication
or geometric replay. No irradiance, solar position or timestamp is inferred.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from numbers import Integral, Real
from types import MappingProxyType

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry.models import SiteGeometry
from heliotelligence.physics.string_member_topology_authority import (
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_section_optical_binding_authority import (
    SectionOpticalBinding,
    SectionOpticalBindingAuthorityResult,
    validate_section_optical_binding_authority,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import BypassSectionIdentity

SECTION_DIRECT_BEAM_STATE_CONTRACT_ID = "section_direct_beam_visibility_state_v1"
SECTION_DIRECT_BEAM_STATE_MODEL_ID = "bound_receiver_sample_visibility_aggregation_v1"
SECTION_DIRECT_BEAM_STATE_SCOPE = (
    "advanced_s8_section_optical_state_before_section_electrical_parameter_resolution"
)
SECTION_DIRECT_BEAM_STATE_COVERAGE_SCOPE = (
    "explicit_bound_visibility_samples_on_reviewed_geometry_revision"
)
_COLUMNS = (
    "receiver_id",
    "sample_index",
    "sample_u_index",
    "sample_v_index",
    "sample_east_m",
    "sample_north_m",
    "sample_up_m",
    "beam_visible",
    "beam_shaded",
)


@dataclass(frozen=True)
class DirectBeamVisibilitySnapshot:
    geometry_revision: str
    snapshot_reference: str
    samples_u: int
    samples_v: int
    visibility_map: pd.DataFrame
    solar_zenith_deg: float | None = None
    solar_azimuth_deg: float | None = None


@dataclass(frozen=True)
class SectionDirectBeamOpticalState(SectionOpticalBinding):
    snapshot_reference: str
    bound_sample_count: int
    visible_sample_count: int
    shaded_sample_count: int
    beam_visible_fraction: float
    beam_shaded_fraction: float
    all_samples_visible: bool
    all_samples_shaded: bool
    shaded_sample_indices: tuple[int, ...]
    solar_zenith_deg: float | None
    solar_azimuth_deg: float | None
    resolved: bool = True
    state: str = "resolved_assigned_direct_beam_samples"

    @property
    def module_id(self) -> str:
        return self.section_identity.module_id

    @property
    def section_id(self) -> str:
        return self.section_identity.section_id

    @property
    def bound_sample_indices(self) -> tuple[int, ...]:
        return self.sample_indices


@dataclass(frozen=True)
class SectionDirectBeamStateResult:
    states_by_section: Mapping[BypassSectionIdentity, SectionDirectBeamOpticalState]
    unavailable_section_ids: tuple[BypassSectionIdentity, ...]
    contract: str = SECTION_DIRECT_BEAM_STATE_CONTRACT_ID
    model: str = SECTION_DIRECT_BEAM_STATE_MODEL_ID
    scope: str = SECTION_DIRECT_BEAM_STATE_SCOPE
    coverage_scope: str = SECTION_DIRECT_BEAM_STATE_COVERAGE_SCOPE


def _snapshot_rows(
    snapshot: DirectBeamVisibilitySnapshot, revision: str, receivers: set[str]
) -> dict[tuple[str, int], bool]:
    if type(snapshot) is not DirectBeamVisibilitySnapshot:
        raise ValueError("expected exact visibility snapshot")
    for text in (snapshot.geometry_revision, snapshot.snapshot_reference):
        if type(text) is not str or not text or text != text.strip():
            raise ValueError("snapshot metadata must be exact non-empty unpadded text")
    if snapshot.geometry_revision != revision:
        raise ValueError("stale visibility geometry revision")
    for count in (snapshot.samples_u, snapshot.samples_v):
        if type(count) is not int or count <= 0:
            raise ValueError("snapshot grid must use exact positive integers")
    for value, upper, closed in (
        (snapshot.solar_zenith_deg, 180.0, True),
        (snapshot.solar_azimuth_deg, 360.0, False),
    ):
        if value is not None and (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, Real)
            or not math.isfinite(value)
            or value < 0
            or (value > upper if closed else value >= upper)
        ):
            raise ValueError("supplied solar angle is invalid")
    frame = snapshot.visibility_map
    if type(frame) is not pd.DataFrame or frame.columns.tolist() != list(_COLUMNS):
        raise ValueError("visibility map requires exact canonical columns")
    seen: set[tuple[str, int]] = set()
    result: dict[tuple[str, int], bool] = {}
    for row in frame.itertuples(index=False, name=None):
        receiver, index, u, v, east, north, up, visible, shaded = row
        if type(receiver) is not str or not receiver or receiver != receiver.strip():
            raise ValueError("invalid snapshot receiver identity")
        if isinstance(index, (bool, np.bool_)) or not isinstance(index, Integral) or index < 0:
            raise ValueError("invalid sample index")
        key = (receiver, int(index))
        if key in seen:
            raise ValueError("duplicate visibility-map sample")
        seen.add(key)
        # Unrelated receiver rows confer no binding; their values are not used.
        if receiver not in receivers:
            continue
        for value, limit in ((u, snapshot.samples_u), (v, snapshot.samples_v)):
            if (
                isinstance(value, (bool, np.bool_))
                or not isinstance(value, Integral)
                or not 0 <= int(value) < limit
            ):
                raise ValueError("invalid sample u/v index")
        if index != u * snapshot.samples_v + v:
            raise ValueError("inconsistent sample_index/u/v triple")
        for value in (east, north, up):
            if (
                isinstance(value, (bool, np.bool_))
                or not isinstance(value, Real)
                or not math.isfinite(value)
            ):
                raise ValueError("sample coordinates must be finite non-Boolean reals")
        if (
            type(visible) not in (bool, np.bool_)
            or type(shaded) not in (bool, np.bool_)
            or bool(visible) == bool(shaded)
        ):
            raise ValueError("visibility/shading must be complementary booleans")
        result[key] = bool(shaded)
    return result


def resolve_section_direct_beam_state(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    authority: SectionOpticalBindingAuthorityResult,
    snapshots: tuple[DirectBeamVisibilitySnapshot, ...],
) -> SectionDirectBeamStateResult:
    """Aggregate only assigned sample sets, never continuous area or irradiance.

    One explicit snapshot per used grid is required; several grids are supported.
    Extra unrelated receivers remain unassigned. Bound samples must all exist.
    Snapshot references are caller evidence labels, not new temporal authority.
    """
    validate_section_optical_binding_authority(parent, geometry, authority)
    if type(snapshots) is not tuple:
        raise ValueError("snapshots must be an exact tuple")
    grids: dict[
        tuple[int, int], tuple[DirectBeamVisibilitySnapshot, dict[tuple[str, int], bool]]
    ] = {}
    for snapshot in snapshots:
        if type(snapshot) is not DirectBeamVisibilitySnapshot:
            raise ValueError("expected exact visibility snapshot")
        receivers = {
            b.receiver_id
            for b in authority.bindings_by_section.values()
            if (b.samples_u, b.samples_v) == (snapshot.samples_u, snapshot.samples_v)
        }
        rows = _snapshot_rows(snapshot, geometry.geometry_revision, receivers)
        grid = (snapshot.samples_u, snapshot.samples_v)
        if grid in grids:
            raise ValueError("duplicate grid snapshot")
        grids[grid] = (snapshot, rows)
    states: dict[BypassSectionIdentity, SectionDirectBeamOpticalState] = {}
    for identity, binding in authority.bindings_by_section.items():
        grid = (binding.samples_u, binding.samples_v)
        if grid not in grids:
            raise ValueError("missing visibility snapshot for binding grid")
        snapshot, rows = grids[grid]
        if any((binding.receiver_id, i) not in rows for i in binding.sample_indices):
            raise ValueError("missing bound visibility sample or wrong receiver")
        shaded = tuple(i for i in binding.sample_indices if rows[(binding.receiver_id, i)])
        count = len(binding.sample_indices)
        dark = len(shaded)
        lit = count - dark
        key = BypassSectionIdentity(identity.module_id, identity.section_id)
        # All retained values are immutable primitives/tuples; no frame aliases.
        values = {f.name: getattr(binding, f.name) for f in fields(SectionOpticalBinding)}
        values["section_identity"] = key
        states[key] = SectionDirectBeamOpticalState(
            **values,
            snapshot_reference=snapshot.snapshot_reference,
            bound_sample_count=count,
            visible_sample_count=lit,
            shaded_sample_count=dark,
            beam_visible_fraction=lit / count,
            beam_shaded_fraction=dark / count,
            all_samples_visible=dark == 0,
            all_samples_shaded=lit == 0,
            shaded_sample_indices=shaded,
            solar_zenith_deg=snapshot.solar_zenith_deg,
            solar_azimuth_deg=snapshot.solar_azimuth_deg,
        )
    unavailable = tuple(
        BypassSectionIdentity(k.module_id, k.section_id) for k in authority.unavailable_section_ids
    )
    return SectionDirectBeamStateResult(MappingProxyType(states), unavailable)
