"""Explicit meter-specific interval support eligibility; no default cadence.

This policy classifies evidence sufficiency, not electrical reconstruction or
quantitative uncertainty. Callers explicitly bind authority to named meters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real

REVENUE_METER_INTERVAL_SUPPORT_POLICY_CONTRACT_ID = (
    "explicit_revenue_meter_interval_expected_support_maximum_gap_policy_v1"
)
REVENUE_METER_INTERVAL_SUPPORT_POLICY_SCOPE = (
    "revenue_meter_interval_expected_support_density_eligibility"
)
POLICY_SCOPE = "s14b_expected_interval_support_density_eligibility_only"
EVIDENCE_KINDS = frozenset(
    {
        "validated_sampling_sensitivity_study",
        "explicit_model_cadence_requirement",
        "commissioning_validation_study",
        "other_explicit",
    }
)


@dataclass(frozen=True)
class RevenueMeterIntervalSupportPolicyAuthority:
    maximum_expected_sample_gap_seconds: float
    policy_scope: str
    evidence_kind: str
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str

    def __post_init__(self) -> None:
        value = self.maximum_expected_sample_gap_seconds
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("maximum support gap must be a finite non-Boolean real number")
        if not math.isfinite(float(value)) or value <= 0:
            raise ValueError("maximum support gap must be finite and strictly positive seconds")
        for field in (
            "policy_scope",
            "evidence_kind",
            "parameter_source",
            "confidence",
            "method_reference",
            "applicability_description",
        ):
            text = getattr(self, field)
            if type(text) is not str or not text or text != text.strip():
                raise ValueError(f"{field} must be an exact non-empty unpadded string")
        if self.policy_scope != POLICY_SCOPE:
            raise ValueError("unsupported interval support policy scope")
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("unsupported interval support policy evidence kind")
        if self.confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError("unsupported interval support policy confidence")
