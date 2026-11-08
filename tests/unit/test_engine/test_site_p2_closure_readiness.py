"""P2H review closure is not physical admission or P3 activation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import fields, replace
from itertools import combinations
from pathlib import Path

import pytest

from heliotelligence.engine import site_evidence_manifest as m

ROOT = Path(__file__).resolve().parents[3]
DOCUMENT = ROOT / "docs/architecture/site-p2-closure.md"
ADMITTED = (
    "irradiance.bifacial_applicability",
    "module.electrical_parameters",
    "s8.inverter_inventory_binding",
    "s8.string_module_count",
    "site.identity.physical",
    "site.module.model_label",
)
COUNTS = (
    ("upstream_environment", 6, 8),
    ("module_electrical_input", 9, 10),
    ("s8_dc", 6, 9),
    ("s9_s10_inverter_control", 10, 10),
    ("s11_lv_collection", 5, 5),
    ("s12_transformer", 5, 7),
    ("s13_mv_hv_meter", 9, 9),
    ("s14_benchmarking", 2, 2),
    ("uncertainty", 2, 2),
)
P2H = frozenset(
    {
        "s14.interval_support_policy",
        "s14.benchmark_interval_semantics",
        "uncertainty.measurement_chain",
        "uncertainty.expected_model",
    }
)


@pytest.fixture
def manifest() -> m.SiteEvidenceManifest:
    return m.load_site_evidence_manifest(ROOT / "evidence/sites/bracon-ash.yaml")


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def baseline_ready(coverage: tuple[m.SitePhysicalPathCoverage, ...]) -> bool:
    return all(not section.blocking_requirement_ids for section in coverage)


def full_ready(coverage: tuple[m.SitePhysicalPathCoverage, ...]) -> bool:
    return all(not section.full_fidelity_blocking_requirement_ids for section in coverage)


def ownership() -> dict[str, tuple[str, ...]]:
    document = DOCUMENT.read_text()
    output = {}
    for owner in ("P2E", "P2F", "P2G", "P2H"):
        block = document.split(f"<!-- BEGIN {owner} BASELINE OWNERSHIP -->\n", 1)[1].split(
            f"\n<!-- END {owner} BASELINE OWNERSHIP -->", 1
        )[0]
        identifiers = tuple(re.findall(r"^- `([^`]+)`$", block, re.MULTILINE))
        assert block == "\n".join(f"- `{key}`" for key in identifiers)
        assert identifiers == tuple(sorted(set(identifiers)))
        output[owner] = identifiers
    return output


def test_manifest_and_admissions_unchanged(manifest: m.SiteEvidenceManifest) -> None:
    # Complete canonical state is unchanged from PR #138 / PR #139 checkpoints;
    # reviewed base ba0044d39985796dbbf82884b18b53b475e2e620.
    wire = m.serialize_site_evidence_manifest(manifest)
    assert len(wire["items"]) == 66
    assert (
        fingerprint(wire["items"])
        == "e87ea62987b75b3b4d30af07c90cf938facded06b470151a1a54e2a686e70592"
    )
    assert fingerprint(wire) == "ed9972021f8e54d6a544272d65ce2515aa09f3a4030b514bec102fe0e90d6e77"
    assert manifest.identity.manifest_version == "bracon-ash-dc-inverter-control-admission-v6"
    assert (
        tuple(i.requirement_id for i in manifest.items if i.admission_state == "admitted")
        == ADMITTED
    )
    assert all(
        i.supported_fidelity
        == (m.FULL_SUPPORT if i.requirement_id == "site.identity.physical" else m.LOWER_SUPPORT)
        for i in manifest.items
        if i.admission_state == "admitted"
    )
    d = manifest.diagnostics
    assert (d.present_count, d.missing_count, d.conflicting_count, d.not_applicable_count) == (
        17,
        48,
        1,
        0,
    )
    assert (
        d.admitted_count,
        d.not_admitted_count,
        d.blocked_count,
        d.admission_not_applicable_count,
    ) == (6, 11, 49, 0)
    assert (
        d.full_fidelity_support_count,
        d.lower_fidelity_support_count,
        d.non_resolving_count,
        d.fidelity_not_applicable_count,
    ) == (1, 5, 60, 0)


@pytest.mark.parametrize("key", sorted(P2H))
def test_direct_p2h_requirements_stay_blocked(manifest: m.SiteEvidenceManifest, key: str) -> None:
    item = next(i for i in manifest.items if i.requirement_id == key)
    assert (item.evidence_state, item.admission_state, item.supported_fidelity) == (
        "missing",
        "blocked",
        m.NON_RESOLVING,
    )
    assert item.source_references == ()
    assert item.admitted_authority_contract_ids == ()
    assert item.authority_binding_reference is None
    assert item.physical_scope == m.PhysicalEvidenceScope("unknown", ())
    assert item.temporal_scope == m.EvidenceTemporalScope("unknown")


def test_path_universe_and_states(manifest: m.SiteEvidenceManifest) -> None:
    assert len(manifest.path_coverage) == 9
    assert tuple(p.section for p in manifest.path_coverage) == m.PATH_SECTIONS
    assert all(
        p.blocking_requirement_ids and p.full_fidelity_blocking_requirement_ids
        for p in manifest.path_coverage
    )
    assert all(
        p.state == p.full_fidelity_state == "partially_admitted" for p in manifest.path_coverage
    )


@pytest.mark.parametrize("section,baseline,full", COUNTS)
def test_exact_blocker_matrix(
    manifest: m.SiteEvidenceManifest, section: str, baseline: int, full: int
) -> None:
    path = next(p for p in manifest.path_coverage if p.section == section)
    assert (
        len(path.blocking_requirement_ids),
        len(path.full_fidelity_blocking_requirement_ids),
    ) == (baseline, full)


def test_global_blocker_totals_and_duplicate_population(manifest: m.SiteEvidenceManifest) -> None:
    baseline = Counter(k for p in manifest.path_coverage for k in p.blocking_requirement_ids)
    full = Counter(
        k for p in manifest.path_coverage for k in p.full_fidelity_blocking_requirement_ids
    )
    assert (sum(baseline.values()), len(baseline)) == (54, 53)
    assert (sum(full.values()), len(full)) == (62, 61)
    assert {k: n for k, n in baseline.items() if n > 1} == {"site.population.module_count": 2}
    assert {
        p.section
        for p in manifest.path_coverage
        if "site.population.module_count" in p.blocking_requirement_ids
    } == {"module_electrical_input", "s8_dc"}


def test_unique_future_update_ownership(manifest: m.SiteEvidenceManifest) -> None:
    baseline = {k for p in manifest.path_coverage for k in p.blocking_requirement_ids}
    owners = ownership()
    assert {o: len(ids) for o, ids in owners.items()} == {"P2E": 14, "P2F": 16, "P2G": 19, "P2H": 4}
    assert set(owners["P2E"]) == {
        k for k in baseline if k.startswith(("weather.", "irradiance.", "thermal."))
    }
    assert set(owners["P2F"]) == {
        k
        for k in baseline
        if k.startswith(("s8.", "s9.", "s10."))
        or k in {"site.population.module_count", "site.geometry.electrical_mapping"}
    }
    assert set(owners["P2G"]) == {k for k in baseline if k.startswith(("s11.", "s12.", "s13."))}
    assert frozenset(owners["P2H"]) == P2H
    assert "site.population.module_count" not in owners["P2E"]
    for left, right in combinations(owners.values(), 2):
        assert set(left).isdisjoint(right)
    assert set().union(*map(set, owners.values())) == baseline
    assert sum(map(len, owners.values())) == 53


def test_current_p3_evidence_decision(manifest: m.SiteEvidenceManifest) -> None:
    assert baseline_ready(manifest.path_coverage) is False
    assert full_ready(manifest.path_coverage) is False
    status = (
        "ELIGIBLE_TO_BEGIN_P3_ENGINEERING" if baseline_ready(manifest.path_coverage) else "BLOCKED"
    )
    assert status == "BLOCKED"
    document = DOCUMENT.read_text()
    assert f"P3_ENTRY_EVIDENCE_STATUS = {status}" in document
    assert "reason: 53 unique mandatory baseline requirements remain unresolved" in document


def test_gate_uses_independent_public_blocker_fields(manifest: m.SiteEvidenceManifest) -> None:
    before = m.serialize_site_evidence_manifest(manifest)
    # Hypothetical standalone public coverage records, not a forged admitted manifest.
    baseline_clear = tuple(
        replace(p, blocking_requirement_ids=(), state="admitted") for p in manifest.path_coverage
    )
    assert baseline_ready(baseline_clear) is True
    assert full_ready(baseline_clear) is False
    full_clear = tuple(
        replace(p, full_fidelity_blocking_requirement_ids=(), full_fidelity_state="admitted")
        for p in baseline_clear
    )
    assert baseline_ready(full_clear) is True
    assert full_ready(full_clear) is True
    assert m.serialize_site_evidence_manifest(manifest) == before


def test_reviewed_lower_fidelity_can_satisfy_baseline_gate(
    manifest: m.SiteEvidenceManifest,
) -> None:
    before = m.serialize_site_evidence_manifest(manifest)
    any_path = {
        r.requirement_id for r in m.REQUIREMENT_CATALOGUE if r.requirement_level == m.ANY_PATH
    }
    # Synthetic declaration tests existing manifest semantics only, never genuine
    # Bracon authority, evidence truth, physics resolution or activation.
    synthetic = replace(
        manifest,
        identity=replace(manifest.identity, manifest_version="test-only-baseline-admission"),
        items=tuple(
            replace(
                i,
                evidence_state="present",
                admission_state="admitted",
                source_references=("test-only-reviewed-source",),
                source_kind="engineering_study",
                supported_fidelity=m.LOWER_SUPPORT,
                admitted_authority_contract_ids=("test_only_reviewed_lower_fidelity_authority",),
                authority_binding_reference="test-only-reviewed-binding",
                gap_reason_codes=(),
                facts=(),
                notes="Synthetic test-only reviewed declaration; not Bracon evidence.",
            )
            if i.requirement_id in any_path
            and i.admission_state not in ("admitted", "not_applicable")
            else i
            for i in manifest.items
        ),
    )
    m.validate_site_evidence_manifest(synthetic)
    assert baseline_ready(synthetic.path_coverage) is True
    assert full_ready(synthetic.path_coverage) is False
    assert all(p.state == "admitted" for p in synthetic.path_coverage)
    assert m.serialize_site_evidence_manifest(manifest) == before


def test_gate_is_boolean_not_maturity_score(manifest: m.SiteEvidenceManifest) -> None:
    assert type(baseline_ready(manifest.path_coverage)) is bool
    assert type(full_ready(manifest.path_coverage)) is bool
    assert not any("percent" in f.name or "score" in f.name for f in fields(manifest.diagnostics))


def test_document_status_and_matrix_projection(manifest: m.SiteEvidenceManifest) -> None:
    document = DOCUMENT.read_text()
    for status in (
        "P2 REVIEW STATUS = COMPLETE",
        "P2 BASELINE PHYSICAL ADMISSION STATUS = INCOMPLETE",
        "P3_ENTRY_EVIDENCE_STATUS = BLOCKED",
        "P3 EXECUTION STATUS = INACTIVE",
    ):
        assert status in document
    assert "No P2I, P2J or P2K is planned" in document
    assert "eligible to begin P3" in document
    expected = "\n".join(
        (
            "| Section | Baseline blockers | Full-fidelity blockers |",
            "| --- | ---: | ---: |",
            *(
                f"| `{p.section}` | {len(p.blocking_requirement_ids)} | "
                f"{len(p.full_fidelity_blocking_requirement_ids)} |"
                for p in manifest.path_coverage
            ),
        )
    )
    block = document.split("<!-- BEGIN P2H BLOCKER MATRIX -->\n", 1)[1].split(
        "\n<!-- END P2H BLOCKER MATRIX -->", 1
    )[0]
    assert block == expected


def test_three_site_evidence_bundles() -> None:
    document = (ROOT / "docs/sites/bracon-ash.md").read_text()
    assert "### P2H benchmark / uncertainty evidence still required" in document
    block = document.split("<!-- BEGIN P2H EVIDENCE BUNDLES -->\n", 1)[1].split(
        "\n<!-- END P2H EVIDENCE BUNDLES -->", 1
    )[0]
    assert re.findall(r"^([1-9])\. \*\*([^*]+)\*\*", block, re.MULTILINE) == [
        ("1", "Benchmark interval + support policy"),
        ("2", "Revenue-meter measurement uncertainty"),
        ("3", "Expected-model uncertainty"),
    ]


def test_no_new_authority_or_readiness_engine() -> None:
    directory = ROOT / "evidence/authorities/bracon-ash"
    assert {
        p.relative_to(directory).as_posix()
        for p in directory.rglob("*")
        if p.suffix in {".yaml", ".yml"}
    } == {
        "site-identity.yaml",
        "module-electrical-basis.yaml",
        "string-series-count.yaml",
        "bifacial-applicability.yaml",
        "inverter-inventory.yaml",
    }
    engine = ROOT / "src/heliotelligence/engine"
    assert {p.name for p in engine.glob("site_*authority.py")} == {
        "site_physical_identity_authority.py",
        "site_module_electrical_authority.py",
        "site_string_series_count_authority.py",
        "site_bifacial_applicability_authority.py",
        "site_inverter_inventory_authority.py",
    }
    assert not (engine / "site_p2_closure_readiness.py").exists()
