"""Tests for S9-0 topology-aware inverter equipment authority."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import (
    ElectricalTopologyConfig,
    InverterUnitConfig,
)
from heliotelligence.physics import (
    inverter,
    inverter_envelope,
    inverter_envelope_lookup,
    inverter_lookup,
)
from heliotelligence.physics.inverter_authority import (
    TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
    TOPOLOGY_INVERTER_AUTHORITY_SCOPE,
    TopologyInverterAuthorityResult,
    resolve_topology_inverter_authority,
)

MODEL_A = "Manufacturer_Model_A"
MODEL_B = "Manufacturer_Model_B"


def _database() -> pd.DataFrame:
    return pd.DataFrame(
        {
            MODEL_A: {
                "Paco": 6000.0,
                "Pdco": 6158.0,
                "Vdco": 360.0,
                "Pso": 36.0,
                "C0": 0.0,
                "C1": 0.0,
                "C2": 0.0,
                "C3": 0.0,
                "Pnt": 1.8,
                "Vdcmax": 600.0,
                "Idcmax": 32.0,
                "Mppt_low": 200.0,
                "Mppt_high": 500.0,
            },
            MODEL_B: {
                "Paco": 8000.0,
                "Pdco": 8200.0,
                "Vdco": 420.0,
                "Pso": 40.0,
                "C0": 0.0,
                "C1": 0.0,
                "C2": 0.0,
                "C3": 0.0,
                "Pnt": 2.0,
                "Vdcmax": 700.0,
                "Idcmax": 40.0,
                "Mppt_low": 250.0,
                "Mppt_high": 600.0,
            },
        }
    )


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", _database)
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        _database,
    )


def _topology(
    inverter_ids: list[str],
    *,
    model_refs: list[str | None] | None = None,
) -> ElectricalTopologyConfig:
    refs = model_refs or [None] * len(inverter_ids)
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(id=inverter_id, model_ref=model_ref)
            for inverter_id, model_ref in zip(inverter_ids, refs, strict=True)
        ]
    )


def test_one_explicit_reference_matches_both_direct_canonical_lookups() -> None:
    topology = _topology(["inverter-1"])

    result = resolve_topology_inverter_authority(
        topology, {"inverter-1": MODEL_A}
    )

    assert type(result) is TopologyInverterAuthorityResult
    assert result.sandia_models_by_inverter_id["inverter-1"] == (
        inverter_lookup.resolve_cec_sandia_inverter_model(MODEL_A)
    )
    assert result.dc_envelopes_by_inverter_id["inverter-1"] == (
        inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope(MODEL_A)
    )
    row = result.states.loc["inverter-1"]
    assert row["inverter_authority_resolved"] == True  # noqa: E712
    assert row["inverter_authority_state"] == (
        "resolved_cec_sam_sandia_inverter_authority"
    )


def test_two_inverters_resolve_two_different_exact_references() -> None:
    topology = _topology(["inverter-a", "inverter-b"])
    result = resolve_topology_inverter_authority(
        topology,
        {"inverter-a": MODEL_A, "inverter-b": MODEL_B},
    )

    assert list(result.sandia_models_by_inverter_id) == ["inverter-a", "inverter-b"]
    assert result.sandia_models_by_inverter_id["inverter-a"].parameters.paco_w == 6000.0
    assert result.sandia_models_by_inverter_id["inverter-b"].parameters.paco_w == 8000.0
    assert result.dc_envelopes_by_inverter_id[
        "inverter-a"
    ].envelope.dc_current_max_a == 32.0
    assert result.dc_envelopes_by_inverter_id[
        "inverter-b"
    ].envelope.dc_current_max_a == 40.0


def test_shared_model_is_resolved_once_per_lookup_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(["inverter-1", "inverter-2", "inverter-3"])
    real_sandia = inverter_lookup.resolve_cec_sandia_inverter_model
    real_envelope = inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope
    sandia_calls: list[str] = []
    envelope_calls: list[str] = []

    def resolve_sandia(name: str) -> Any:
        sandia_calls.append(name)
        return real_sandia(name)

    def resolve_envelope(name: str) -> Any:
        envelope_calls.append(name)
        return real_envelope(name)

    monkeypatch.setattr(
        inverter_lookup, "resolve_cec_sandia_inverter_model", resolve_sandia
    )
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "resolve_cec_inverter_dc_operating_envelope",
        resolve_envelope,
    )
    result = resolve_topology_inverter_authority(
        topology,
        {"inverter-1": MODEL_A, "inverter-2": MODEL_A, "inverter-3": MODEL_B},
    )

    assert sandia_calls == [MODEL_A, MODEL_B]
    assert envelope_calls == [MODEL_A, MODEL_B]
    assert result.sandia_models_by_inverter_id["inverter-1"] is (
        result.sandia_models_by_inverter_id["inverter-2"]
    )
    assert result.dc_envelopes_by_inverter_id["inverter-1"] is (
        result.dc_envelopes_by_inverter_id["inverter-2"]
    )
    assert result.diagnostics.unique_explicit_model_count == 2
    assert result.diagnostics.sandia_lookup_count == 2
    assert result.diagnostics.envelope_lookup_count == 2


def test_topology_order_is_authority_and_mapping_order_has_no_influence() -> None:
    topology = _topology(["inverter-z", "inverter-a"])
    first = resolve_topology_inverter_authority(
        topology, {"inverter-a": MODEL_B, "inverter-z": MODEL_A}
    )
    second = resolve_topology_inverter_authority(
        topology, {"inverter-z": MODEL_A, "inverter-a": MODEL_B}
    )

    assert first.states.index.tolist() == ["inverter-z", "inverter-a"]
    assert list(first.sandia_models_by_inverter_id) == ["inverter-z", "inverter-a"]
    pd.testing.assert_frame_equal(first.states, second.states, check_exact=True)
    assert first.diagnostics == second.diagnostics


def test_missing_and_mixed_authority_remain_explicitly_unresolved() -> None:
    topology = _topology(["resolved", "missing"])
    result = resolve_topology_inverter_authority(topology, {"resolved": MODEL_A})

    assert list(result.sandia_models_by_inverter_id) == ["resolved"]
    assert list(result.dc_envelopes_by_inverter_id) == ["resolved"]
    row = result.states.loc["missing"]
    assert row["inverter_model_reference"] == ""
    assert row["inverter_authority_resolved"] == False  # noqa: E712
    assert row["inverter_authority_state"] == (
        "unresolved_no_explicit_inverter_model_reference"
    )
    assert row["sandia_parameter_source"] == ""
    assert row["sandia_confidence"] == "unknown"
    assert row["envelope_parameter_source"] == ""
    assert row["envelope_confidence"] == "unknown"
    assert result.diagnostics.resolved_inverter_count == 1
    assert result.diagnostics.unresolved_inverter_count == 1


def test_unexpected_inverter_reference_is_rejected_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(["inverter-a"])
    calls = 0

    def forbidden(name: str) -> Any:
        nonlocal calls
        calls += 1
        raise AssertionError(name)

    monkeypatch.setattr(
        inverter_lookup, "resolve_cec_sandia_inverter_model", forbidden
    )
    with pytest.raises(ValueError, match="unexpected inverter model reference IDs"):
        resolve_topology_inverter_authority(
            topology, {"inverter-a": MODEL_A, "inverter-z": MODEL_B}
        )
    assert calls == 0


@pytest.mark.parametrize("name", ["", "   ", 123, True, None])
def test_explicit_model_reference_requires_non_whitespace_string(
    name: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(["inverter-1"])
    calls = 0

    def forbidden(value: str) -> Any:
        nonlocal calls
        calls += 1
        raise AssertionError(value)

    monkeypatch.setattr(
        inverter_lookup, "resolve_cec_sandia_inverter_model", forbidden
    )
    with pytest.raises(ValueError, match="non-empty, non-whitespace string"):
        resolve_topology_inverter_authority(
            topology,
            {"inverter-1": name},  # type: ignore[dict-item]
        )
    assert calls == 0


def test_unknown_explicit_reference_is_invalid_not_missing() -> None:
    topology = _topology(["inverter-1"])
    with pytest.raises(
        ValueError,
        match="CEC/SAM inverter model not found: 'Unknown_Model'",
    ):
        resolve_topology_inverter_authority(
            topology, {"inverter-1": "Unknown_Model"}
        )


def test_empty_topology_and_unexpected_empty_topology_mapping() -> None:
    topology = _topology([])
    result = resolve_topology_inverter_authority(topology, {})

    assert result.states.empty
    assert result.states.index.name == "inverter_id"
    assert list(result.states.columns) == [
        "inverter_model_reference",
        "inverter_authority_resolved",
        "inverter_authority_state",
        "sandia_parameter_source",
        "sandia_confidence",
        "envelope_parameter_source",
        "envelope_confidence",
        "topology_inverter_authority_contract",
        "topology_inverter_authority_model",
        "topology_inverter_authority_scope",
        "topology_inverter_authority_coverage_scope",
    ]
    assert result.diagnostics.inverter_count == 0
    with pytest.raises(ValueError, match="unexpected inverter model reference IDs"):
        resolve_topology_inverter_authority(topology, {"inverter-z": MODEL_A})


def test_inputs_are_not_mutated_and_result_mappings_are_read_only() -> None:
    topology = _topology(["inverter-1"])
    topology_before = topology.model_copy(deep=True)
    supplied = {"inverter-1": MODEL_A}
    supplied_before = supplied.copy()

    result = resolve_topology_inverter_authority(topology, supplied)

    assert topology == topology_before
    assert supplied == supplied_before
    sandia_mapping: Any = result.sandia_models_by_inverter_id
    envelope_mapping: Any = result.dc_envelopes_by_inverter_id
    with pytest.raises(TypeError):
        sandia_mapping["other"] = sandia_mapping["inverter-1"]
    with pytest.raises(TypeError):
        envelope_mapping["other"] = envelope_mapping["inverter-1"]


def test_model_ref_is_opaque_and_never_used_as_cec_authority() -> None:
    topology = _topology(
        ["inverter-1", "inverter-2"],
        model_refs=["Unknown_Legacy_Value", MODEL_B],
    )

    missing = resolve_topology_inverter_authority(topology, {})
    explicit = resolve_topology_inverter_authority(
        topology, {"inverter-1": MODEL_A}
    )

    assert missing.diagnostics.resolved_inverter_count == 0
    assert explicit.states.loc["inverter-1", "inverter_model_reference"] == MODEL_A
    assert explicit.states.loc[
        "inverter-2", "inverter_authority_state"
    ] == "unresolved_no_explicit_inverter_model_reference"


def test_api_has_no_site_or_operating_state_authority() -> None:
    parameters = inspect.signature(resolve_topology_inverter_authority).parameters
    assert list(parameters) == ["topology", "cec_sam_name_by_inverter_id"]


def test_state_provenance_and_diagnostics_close_exactly() -> None:
    topology = _topology(["inverter-a", "inverter-b"])
    result = resolve_topology_inverter_authority(
        topology, {"inverter-a": MODEL_A}
    )

    assert result.states[
        "topology_inverter_authority_contract"
    ].eq(TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID).all()
    assert result.states[
        "topology_inverter_authority_model"
    ].eq(TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID).all()
    assert result.states[
        "topology_inverter_authority_scope"
    ].eq(TOPOLOGY_INVERTER_AUTHORITY_SCOPE).all()
    assert result.states[
        "topology_inverter_authority_coverage_scope"
    ].eq(TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE).all()
    diagnostics = result.diagnostics
    assert diagnostics.inverter_count == 2
    assert diagnostics.resolved_inverter_count == 1
    assert diagnostics.unresolved_inverter_count == 1
    assert diagnostics.explicit_reference_count == 1
    assert diagnostics.missing_reference_count == 1
    assert diagnostics.authority_model == TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID


def test_no_dc_envelope_evaluation_or_inverter_conversion_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(["inverter-1"])

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("operating physics must not run")

    monkeypatch.setattr(inverter, "calculate_sandia_inverter_ac_power", forbidden)
    monkeypatch.setattr(
        inverter_envelope,
        "evaluate_inverter_dc_operating_envelope",
        forbidden,
    )
    pvlib_inverter: Any = importlib.import_module("pvlib.inverter")
    monkeypatch.setattr(pvlib_inverter, "sandia", forbidden)
    monkeypatch.setattr(pvlib_inverter, "sandia_multi", forbidden)

    result = resolve_topology_inverter_authority(
        topology, {"inverter-1": MODEL_A}
    )
    assert result.diagnostics.resolved_inverter_count == 1


def test_mapping_type_is_required() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        resolve_topology_inverter_authority(_topology(["inverter-1"]), [])  # type: ignore[arg-type]


def test_exact_topology_type_is_required() -> None:
    with pytest.raises(TypeError, match="exactly ElectricalTopologyConfig"):
        resolve_topology_inverter_authority(object(), {})  # type: ignore[arg-type]
