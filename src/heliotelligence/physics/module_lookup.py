"""Five-tier module parameter resolution for the single-diode model.

Lookup order (highest accuracy first):

  Tier 1 — CEC database (cec_name set and found in pvlib CECMod)
  Tier 2 — CEC auto-search (local_module_name matched against CEC index)
  Tier 3 — local module library YAML (local_module_name found in library)
  Tier 4 — inline datasheet params from ModuleConfig (v_mp/i_mp/v_oc/i_sc all set)
  Tier 5 — PVWatts simplified fallback (pnom_wp + gamma_pmp set)

Returns a dict:
  {
    'params':      dict of raw module parameters,
    'source':      str  ('cec' | 'cec_auto' | 'local_library' |
                         'datasheet' | 'pvwatts_fallback'),
    'fit_quality': str  ('high' | 'low' | 'pvwatts'),
    'tier':        int  (1-5),
  }

Raises ValueError if no tier resolves.
Logs at INFO level which tier was used on every call.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from heliotelligence.config.site import ModuleConfig

logger = logging.getLogger(__name__)

# Path to the local module library relative to the project root.
# Resolved at import time so callers don't need to pass it.
_LIBRARY_PATH = Path(__file__).parents[3] / "config" / "module_library.yaml"


def _load_cec_database() -> "pandas.DataFrame":  # noqa: F821 — avoid top-level pandas import
    """Return the pvlib CEC module database as a DataFrame."""
    import pvlib.pvsystem

    return pvlib.pvsystem.retrieve_sam("CECMod")


def _load_local_library() -> dict:
    """Return the local module library as a dict keyed by module name."""
    if not _LIBRARY_PATH.exists():
        return {}
    with _LIBRARY_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return (data or {}).get("modules", {})


def _normalize(name: str) -> str:
    """Lower-case and replace common separators for fuzzy matching."""
    return name.lower().replace("-", "_").replace(" ", "_")


def resolve_module_params(module_cfg: ModuleConfig) -> dict:
    """Resolve SDM module parameters through the five-tier lookup hierarchy.

    Parameters
    ----------
    module_cfg : ModuleConfig
        Module configuration from SiteConfig.

    Returns
    -------
    dict with keys:
        'params'      — dict of raw module parameters suitable for passing
                        to pvlib calcparams_* functions.
        'source'      — string identifying which source was used.
        'fit_quality' — 'high' (CEC measured), 'low' (datasheet fit),
                        or 'pvwatts' (simplified fallback).
        'tier'        — integer 1–5.

    Raises
    ------
    ValueError
        If no tier resolves (all paths exhausted without finding parameters).
    """
    # ------------------------------------------------------------------
    # Tier 1 — CEC database by explicit cec_name
    # ------------------------------------------------------------------
    if module_cfg.cec_name:
        cec_db = _load_cec_database()
        if module_cfg.cec_name in cec_db.columns:
            params = cec_db[module_cfg.cec_name].to_dict()
            logger.info(
                "Module lookup Tier 1 (CEC database): %s",
                module_cfg.cec_name,
            )
            return {"params": params, "source": "cec", "fit_quality": "high", "tier": 1}
        else:
            logger.warning(
                "cec_name '%s' not found in CEC database; falling through to Tier 2.",
                module_cfg.cec_name,
            )

    # ------------------------------------------------------------------
    # Tier 2 — CEC auto-search via local_module_name fuzzy match
    # ------------------------------------------------------------------
    if module_cfg.local_module_name:
        cec_db = _load_cec_database()
        needle = _normalize(module_cfg.local_module_name)
        matches = [col for col in cec_db.columns if needle in _normalize(col)]
        if matches:
            best = matches[0]
            params = cec_db[best].to_dict()
            logger.warning(
                "Module lookup Tier 2 (CEC auto-search): matched '%s' to CEC entry "
                "'%s'.  For reproducibility, set cec_name: \"%s\" in sites.yaml.",
                module_cfg.local_module_name,
                best,
                best,
            )
            return {
                "params": params,
                "source": "cec_auto",
                "fit_quality": "high",
                "tier": 2,
            }

    # ------------------------------------------------------------------
    # Tier 3 — local module library YAML
    # ------------------------------------------------------------------
    if module_cfg.local_module_name:
        library = _load_local_library()
        if module_cfg.local_module_name in library:
            entry = library[module_cfg.local_module_name]
            fit_quality = entry.get("fit_quality", "low")
            logger.info(
                "Module lookup Tier 3 (local library): %s (fit_quality=%s)",
                module_cfg.local_module_name,
                fit_quality,
            )
            return {
                "params": entry,
                "source": "local_library",
                "fit_quality": fit_quality,
                "tier": 3,
            }

    # ------------------------------------------------------------------
    # Tier 4 — inline datasheet params from ModuleConfig
    # ------------------------------------------------------------------
    _datasheet_required = (
        module_cfg.v_mp,
        module_cfg.i_mp,
        module_cfg.v_oc,
        module_cfg.i_sc,
    )
    if all(v is not None for v in _datasheet_required):
        params = {
            "pnom_wp": module_cfg.pnom_wp,
            "v_mp": module_cfg.v_mp,
            "i_mp": module_cfg.i_mp,
            "v_oc": module_cfg.v_oc,
            "i_sc": module_cfg.i_sc,
            "alpha_sc": module_cfg.alpha_sc,
            "beta_voc": module_cfg.beta_voc,
            "gamma_pmp": module_cfg.gamma_pmp,
            "cells_in_series": module_cfg.cells_in_series,
            "technology": module_cfg.technology,
        }
        logger.info(
            "Module lookup Tier 4 (inline datasheet): technology=%s, "
            "pnom_wp=%s Wp",
            module_cfg.technology,
            module_cfg.pnom_wp,
        )
        return {
            "params": params,
            "source": "datasheet",
            "fit_quality": "low",
            "tier": 4,
        }

    # ------------------------------------------------------------------
    # Tier 5 — PVWatts simplified fallback
    # ------------------------------------------------------------------
    if module_cfg.pnom_wp is not None and module_cfg.gamma_pmp is not None:
        params = {
            "pnom_wp": module_cfg.pnom_wp,
            "gamma_pmp": module_cfg.gamma_pmp,
            "technology": module_cfg.technology,
        }
        logger.info(
            "Module lookup Tier 5 (PVWatts fallback): pnom_wp=%s Wp, "
            "gamma_pmp=%s %%/°C",
            module_cfg.pnom_wp,
            module_cfg.gamma_pmp,
        )
        return {
            "params": params,
            "source": "pvwatts_fallback",
            "fit_quality": "pvwatts",
            "tier": 5,
        }

    # ------------------------------------------------------------------
    # No tier resolved
    # ------------------------------------------------------------------
    raise ValueError(
        "No module parameters could be resolved for ModuleConfig "
        f"(cec_name={module_cfg.cec_name!r}, "
        f"local_module_name={module_cfg.local_module_name!r}).  "
        "Set at least pnom_wp + gamma_pmp for PVWatts fallback, or "
        "v_mp/i_mp/v_oc/i_sc for the full SDM, or point to a CEC/library entry."
    )
