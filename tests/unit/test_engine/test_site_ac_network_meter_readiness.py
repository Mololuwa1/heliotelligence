"""P2G zero-admission review; migration association is not meter engineering."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from heliotelligence.config.site import load_sites
from heliotelligence.engine import site_evidence_manifest as m

ROOT = Path(__file__).resolve().parents[3]
CSV_REFERENCE = "data_migration/ts_meter_readings.csv"
SITE_UUID = "5ab83b40-553c-5ddd-976f-71f6cb5d490f"
ARCHITECTURE = ROOT / "docs/architecture/site-ac-network-meter-admission.md"
S11 = (
    "s11.collection_exits",
    "s11.exit_voltage",
    "s11.inverter_terminal_nodes",
    "s11.lv_topology",
    "s11.segment_impedance",
)
S12 = (
    "s12.factory_loss_evidence",
    "s12.lower_fidelity_baseline",
    "s12.ratio_tapping_impedance",
    "s12.transformer_equipment",
    "s12.transformer_terminal_binding",
)
S12_FULL = ("s12.construction_component_evidence", "s12.thermal_evidence")
S13_NETWORK = (
    "s13.grid_boundary",
    "s13.grid_boundary_voltage",
    "s13.mv_hv_topology",
    "s13.segment_parameters",
    "s13.transformer_network_binding",
)
S13_METER = (
    "s13.revenue_meter_binding",
    "s13.revenue_meter_measurement_semantics",
    "s13.revenue_meter_scaling",
    "s13.revenue_meter_sign_conventions",
)
DOWNSTREAM = (*S11, *S12, *S12_FULL, "s12.harmonic_evidence", *S13_NETWORK, *S13_METER)
ADMITTED = (
    "irradiance.bifacial_applicability",
    "module.electrical_parameters",
    "s8.inverter_inventory_binding",
    "s8.string_module_count",
    "site.identity.physical",
    "site.module.model_label",
)


@pytest.fixture
def manifest() -> m.SiteEvidenceManifest:
    return m.load_site_evidence_manifest(ROOT / "evidence/sites/bracon-ash.yaml")


def fingerprint(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def test_exact_p2f_checkpoint_retained(manifest: m.SiteEvidenceManifest) -> None:
    # Captured from PR #138 merge 076c310ce6087048e266bc42cc3bff95b76084d3. No runtime
    # Git, second manifest or migration interpretation is needed to replay it.
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


def test_partitions_unchanged(manifest: m.SiteEvidenceManifest) -> None:
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


@pytest.mark.parametrize("requirement_id", DOWNSTREAM)
def test_all_downstream_evidence_stays_missing_blocked(
    manifest: m.SiteEvidenceManifest, requirement_id: str
) -> None:
    item = next(i for i in manifest.items if i.requirement_id == requirement_id)
    assert (item.evidence_state, item.admission_state) == ("missing", "blocked")
    assert item.admitted_authority_contract_ids == ()
    assert item.authority_binding_reference is None
    assert item.source_references == ()
    assert CSV_REFERENCE not in item.source_references
    assert item.physical_scope == m.PhysicalEvidenceScope("unknown", ())
    assert SITE_UUID not in item.physical_scope.identifiers
    assert item.temporal_scope == m.EvidenceTemporalScope("unknown")


@pytest.mark.parametrize(
    "section,baseline,full",
    [
        ("s11_lv_collection", S11, S11),
        ("s12_transformer", S12, tuple(sorted((*S12, *S12_FULL)))),
        (
            "s13_mv_hv_meter",
            tuple(sorted((*S13_NETWORK, *S13_METER))),
            tuple(sorted((*S13_NETWORK, *S13_METER))),
        ),
    ],
)
def test_downstream_blocker_sets_unchanged(
    manifest: m.SiteEvidenceManifest, section: str, baseline: tuple[str, ...], full: tuple[str, ...]
) -> None:
    path = next(p for p in manifest.path_coverage if p.section == section)
    assert path.blocking_requirement_ids == baseline
    assert path.full_fidelity_blocking_requirement_ids == full
    assert path.state == path.full_fidelity_state == "partially_admitted"
    assert (len(baseline), len(full)) == {
        "s11_lv_collection": (5, 5),
        "s12_transformer": (5, 7),
        "s13_mv_hv_meter": (9, 9),
    }[section]


def test_requirement_levels_not_weakened() -> None:
    requirements = {r.requirement_id: r for r in m.REQUIREMENT_CATALOGUE}
    assert all(
        requirements[k].requirement_level == m.ANY_PATH
        for k in (*S11, *S12, *S13_NETWORK, *S13_METER)
    )
    assert all(requirements[k].requirement_level == m.FULL_PATH for k in S12_FULL)
    assert requirements["s12.harmonic_evidence"].requirement_level == m.OPTIONAL
    assert "s12.harmonic_evidence" not in S12


def test_migration_header_and_site_association_are_not_admission(
    manifest: m.SiteEvidenceManifest,
) -> None:
    before = m.serialize_site_evidence_manifest(manifest)
    path = ROOT / CSV_REFERENCE
    assert path.is_file()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        assert header is not None
        assert {
            "time",
            "site_id",
            "p_ac_kw",
            "e_exported_kwh",
            "e_imported_kwh",
            "e_net_kwh",
            "v_ph1_n_v",
            "i_ph1_a",
            "freq_hz",
            "power_factor",
            "q_kvar",
            "quality",
        } <= set(header)
        # Intentionally access ONLY site_id values. No timestamps, registers,
        # power, quality, scaling or other numerical patterns are interpreted.
        associations = {row["site_id"] for row in reader}
    assert associations == {SITE_UUID}
    m.validate_site_evidence_manifest(manifest)
    assert m.serialize_site_evidence_manifest(manifest) == before
    assert all(
        CSV_REFERENCE not in i.source_references
        for i in manifest.items
        if i.requirement_id.startswith("s13.")
    )
    assert all(
        not i.physical_scope.identifiers
        for i in manifest.items
        if i.requirement_id.startswith("s13.")
    )


@pytest.mark.parametrize(
    "marker,expected",
    [
        ("S11 BLOCKERS", S11),
        ("S12 BASELINE BLOCKERS", S12),
        ("S12 FULL ADDITIONS", S12_FULL),
        ("S13 NETWORK BLOCKERS", S13_NETWORK),
        ("S13 METER BLOCKERS", S13_METER),
    ],
)
def test_architecture_blocker_projection(marker: str, expected: tuple[str, ...]) -> None:
    document = ARCHITECTURE.read_text()
    block = document.split(f"<!-- BEGIN P2G {marker} -->\n", 1)[1].split(
        f"\n<!-- END P2G {marker} -->", 1
    )[0]
    assert block == "\n".join(f"- `{key}`" for key in expected)


def test_site_request_has_exactly_four_bundles() -> None:
    document = (ROOT / "docs/sites/bracon-ash.md").read_text()
    assert "### P2G AC network / transformer / meter evidence still required" in document
    block = document.split("<!-- BEGIN P2G EVIDENCE BUNDLES -->\n", 1)[1].split(
        "\n<!-- END P2G EVIDENCE BUNDLES -->", 1
    )[0]
    assert re.findall(r"^([1-9])\. \*\*([^*]+)\*\*", block, re.MULTILINE) == [
        ("1", "LV collection"),
        ("2", "Transformers"),
        ("3", "MV/HV and grid boundary"),
        ("4", "Revenue meter"),
    ]


def test_zero_authority_additions() -> None:
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
    assert {p.name for p in (ROOT / "src/heliotelligence/engine").glob("site_*authority.py")} == {
        "site_physical_identity_authority.py",
        "site_module_electrical_authority.py",
        "site_string_series_count_authority.py",
        "site_bifacial_applicability_authority.py",
        "site_inverter_inventory_authority.py",
    }


def test_population_and_topology_stay_unresolved(manifest: m.SiteEvidenceManifest) -> None:
    site = load_sites(ROOT / "config/sites.yaml")[0]
    assert site.electrical_topology is None
    population = next(
        i for i in manifest.items if i.requirement_id == "site.population.module_count"
    )
    assert (population.evidence_state, population.admission_state) == ("conflicting", "blocked")
    facts = {f.fact_id: f.value for f in population.facts}
    assert tuple(
        facts[k]
        for k in (
            "configured_string_module_count",
            "configured_table_module_count",
            "geometry_extracted_module_count",
        )
    ) == ("49824", "47448", "50736")
