"""Explicit support-gap eligibility authority, with no cadence inference."""

from dataclasses import FrozenInstanceError
from typing import Any

import numpy as np
import pytest

from heliotelligence.physics import revenue_meter_interval_support_policy as module


def policy(
    maximum_gap: float = 900.0, **changes: Any
) -> module.RevenueMeterIntervalSupportPolicyAuthority:
    # Numerical values here are test evidence, never project recommendations.
    values = dict(
        maximum_expected_sample_gap_seconds=maximum_gap,
        policy_scope=module.POLICY_SCOPE,
        evidence_kind="validated_sampling_sensitivity_study",
        parameter_source="explicit synthetic sensitivity study",
        confidence="high",
        method_reference="analytic quadratic test profile",
        applicability_description="test meter and declared test interval only",
    )
    values.update(changes)
    return module.RevenueMeterIntervalSupportPolicyAuthority(**values)


def test_valid_policy_and_exact_identities() -> None:
    assert policy().maximum_expected_sample_gap_seconds == 900
    assert (
        module.REVENUE_METER_INTERVAL_SUPPORT_POLICY_CONTRACT_ID
        == "explicit_revenue_meter_interval_expected_support_maximum_gap_policy_v1"
    )
    assert (
        module.REVENUE_METER_INTERVAL_SUPPORT_POLICY_SCOPE
        == "revenue_meter_interval_expected_support_density_eligibility"
    )
    assert module.POLICY_SCOPE == "s14b_expected_interval_support_density_eligibility_only"
    with pytest.raises(FrozenInstanceError):
        policy().confidence = "low"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value", [0, -1, np.nan, np.inf, -np.inf, True, np.bool_(False), "900", None]
)
def test_invalid_gap(value: Any) -> None:
    with pytest.raises(ValueError):
        policy(value)


@pytest.mark.parametrize(
    "field",
    [
        "policy_scope",
        "evidence_kind",
        "parameter_source",
        "confidence",
        "method_reference",
        "applicability_description",
    ],
)
@pytest.mark.parametrize("value", ["", " padded", "padded ", None, 1])
def test_exact_text(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        policy(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_scope", "electrical_model"),
        ("confidence", "HIGH"),
        ("evidence_kind", "legacy_assumption"),
        ("evidence_kind", "implicit_default"),
        ("evidence_kind", "nominal_cadence_without_validation"),
    ],
)
def test_unsupported_vocabulary(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        policy(**{field: value})


@pytest.mark.parametrize("kind", sorted(module.EVIDENCE_KINDS))
def test_admitted_evidence(kind: str) -> None:
    assert policy(evidence_kind=kind).evidence_kind == kind
