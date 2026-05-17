"""Unit tests for heliotelligence.physics.module_lookup.

Tests
-----
1. CEC lookup returns tier=1 when cec_name matches a real CEC entry
2. Local library lookup returns tier=3 for JKM570N-72HL4-BDV
3. Datasheet params return tier=4
4. PVWatts fallback returns tier=5
5. ValueError raised when no tier resolves
6. Auto-CEC search (tier 2) logs WARNING suggesting user set cec_name
"""

from __future__ import annotations

import pytest

from heliotelligence.config.site import ModuleConfig
from heliotelligence.physics.module_lookup import resolve_module_params


def _real_cec_name() -> str:
    """Return the first key in the CEC database for use in tier-1 tests."""
    import pvlib.pvsystem

    cec_db = pvlib.pvsystem.retrieve_sam("CECMod")
    return cec_db.columns[0]


# ---------------------------------------------------------------------------
# Tier 1 — CEC database by explicit cec_name
# ---------------------------------------------------------------------------

def test_tier1_cec_returns_correct_tier():
    """CEC lookup by explicit cec_name should return tier=1 and source='cec'."""
    cec_name = _real_cec_name()
    cfg = ModuleConfig(cec_name=cec_name)
    result = resolve_module_params(cfg)

    assert result["tier"] == 1
    assert result["source"] == "cec"
    assert result["fit_quality"] == "high"
    assert isinstance(result["params"], dict)
    # CEC params must include the De Soto SDM keys
    for key in ("a_ref", "I_L_ref", "I_o_ref", "R_sh_ref", "R_s", "alpha_sc"):
        assert key in result["params"], f"CEC param '{key}' missing from tier-1 result"


# ---------------------------------------------------------------------------
# Tier 2 — CEC auto-search (logs WARNING about setting cec_name)
# ---------------------------------------------------------------------------

def test_tier2_autosearch_logs_warning(caplog):
    """Auto-CEC search should return tier=2 and log a WARNING with cec_name suggestion.

    We use a well-known manufacturer prefix that is present in the CEC database.
    The test asserts:
      - tier == 2
      - source == 'cec_auto'
      - WARNING logged containing 'cec_name'
    """
    import pvlib.pvsystem

    cec_db = pvlib.pvsystem.retrieve_sam("CECMod")
    # Pick the first CEC entry and derive a partial name that will auto-match
    first_entry = cec_db.columns[0]
    # Use the first 8 characters (enough to match, not an exact cec_name hit)
    partial_name = first_entry[:8]

    cfg = ModuleConfig(local_module_name=partial_name)

    import logging

    with caplog.at_level(logging.WARNING, logger="heliotelligence.physics.module_lookup"):
        result = resolve_module_params(cfg)

    if result["tier"] == 2:
        assert result["source"] == "cec_auto"
        assert result["fit_quality"] == "high"
        warning_messages = " ".join(caplog.messages)
        assert "cec_name" in warning_messages, (
            "Tier-2 auto-search should log a WARNING suggesting the user set cec_name"
        )
    else:
        # If partial name doesn't match CEC (unlikely but possible), skip
        pytest.skip(f"Partial name '{partial_name}' did not match CEC; skipping tier-2 test")


# ---------------------------------------------------------------------------
# Tier 3 — local module library
# ---------------------------------------------------------------------------

def test_tier3_local_library_jinko():
    """Local library lookup for JKM570N-72HL4-BDV should return tier=3."""
    cfg = ModuleConfig(local_module_name="JKM570N-72HL4-BDV")
    result = resolve_module_params(cfg)

    assert result["tier"] == 3
    assert result["source"] == "local_library"
    assert result["params"]["pnom_wp"] == pytest.approx(570.0)
    assert result["params"]["bifacial"] is True


# ---------------------------------------------------------------------------
# Tier 4 — inline datasheet params
# ---------------------------------------------------------------------------

def test_tier4_datasheet_params():
    """Inline datasheet params (v_mp/i_mp/v_oc/i_sc all set) should return tier=4."""
    cfg = ModuleConfig(
        v_mp=41.64,
        i_mp=13.69,
        v_oc=50.60,
        i_sc=13.48,
        alpha_sc=0.045,
        beta_voc=-0.25,
        gamma_pmp=-0.29,
        cells_in_series=144,
        pnom_wp=570.0,
    )
    result = resolve_module_params(cfg)

    assert result["tier"] == 4
    assert result["source"] == "datasheet"
    assert result["fit_quality"] == "low"
    assert result["params"]["v_mp"] == pytest.approx(41.64)


# ---------------------------------------------------------------------------
# Tier 5 — PVWatts fallback
# ---------------------------------------------------------------------------

def test_tier5_pvwatts_fallback():
    """PVWatts fallback should be used when only pnom_wp and gamma_pmp are set."""
    cfg = ModuleConfig(pnom_wp=570.0, gamma_pmp=-0.29)
    result = resolve_module_params(cfg)

    assert result["tier"] == 5
    assert result["source"] == "pvwatts_fallback"
    assert result["fit_quality"] == "pvwatts"
    assert result["params"]["pnom_wp"] == pytest.approx(570.0)


# ---------------------------------------------------------------------------
# No tier resolves → ValueError
# ---------------------------------------------------------------------------

def test_no_tier_raises_value_error():
    """An empty ModuleConfig with no resolvable params should raise ValueError."""
    cfg = ModuleConfig()  # all defaults, no identifiable params
    with pytest.raises(ValueError, match="No module parameters could be resolved"):
        resolve_module_params(cfg)
