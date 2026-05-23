"""Site layout API endpoint.

GET /api/v1/sites/{site_id}/layout
    Returns the site's physical layout with current inverter group status.
    Inverter availability is derived from the most recent inv_p_ac_kw reading
    per inverter (no time filter — uses last known reading).

Response shape
──────────────
{
  "site_id": "...",
  "site_name": "Bracon Ash",
  "centre_lat": 52.5625,
  "centre_lon": 1.2135,
  "tilt_deg": 15.0,
  "azimuth_deg": -0.6,
  "capacity_kwp": 28524.0,
  "inverter_groups": [
    {
      "id": "MQA11",
      "label": "Block MQA11 (TB101–TB116)",
      "centre_lat": 52.560587,
      "centre_lon": 1.211691,
      "inverter_count": 16,
      "active_inverters": 16,
      "fault_inverters": 0,
      "availability_pct": 100.0,
      "status": "normal"
    },
    ...
  ]
}

Status thresholds
─────────────────
  normal   — mean availability >= 95 %
  degraded — mean availability >= 50 %
  offline  — mean availability < 50 %
  unknown  — no data found for this inverter
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from heliotelligence.config.settings import settings
from heliotelligence.config.site import SiteConfig, load_sites
from heliotelligence.db.session import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sites", tags=["layout"])


def _find_site(site_id: str) -> SiteConfig | None:
    sites = load_sites(settings.site_config_path)
    for site in sites:
        if str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)) == site_id:
            return site
    return None


def _group_status(mean_avail: float | None) -> str:
    if mean_avail is None:
        return "unknown"
    if mean_avail >= 95.0:
        return "normal"
    if mean_avail >= 50.0:
        return "degraded"
    return "offline"


@router.get("/{site_id}/layout")
async def get_site_layout(site_id: str) -> dict:
    site = _find_site(site_id)
    if site is None:
        raise HTTPException(
            status_code=404,
            detail=f"Site {site_id} not found in configuration",
        )

    # Fetch latest inv_p_ac_kw per inverter (last known reading, no time filter).
    # inv_avail_pct is NULL for all rows; availability is derived from AC power.
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT DISTINCT ON (inverter_id)
                    inverter_id,
                    inv_p_ac_kw
                FROM inverter_readings
                WHERE site_id = :site_id
                ORDER BY inverter_id, time DESC
            """),
            {"site_id": site_id},
        )
        rows = result.fetchall()

    # Build lookup: inverter_id → latest inv_p_ac_kw (None if column is NULL)
    power_map: dict[str, float | None] = {
        row.inverter_id: row.inv_p_ac_kw for row in rows
    }

    # Compute site centre as mean of group centres
    groups_cfg = (site.layout.inverter_groups if site.layout else [])
    if groups_cfg:
        centre_lat = sum(g.centre_lat for g in groups_cfg) / len(groups_cfg)
        centre_lon = sum(g.centre_lon for g in groups_cfg) / len(groups_cfg)
    else:
        centre_lat = site.latitude
        centre_lon = site.longitude

    # Assemble per-group status derived from inv_p_ac_kw.
    # active   = inverters with inv_p_ac_kw > 0
    # fault    = inverters with inv_p_ac_kw = 0 or NULL
    # availability_pct = active / inverter_count × 100
    inverter_groups = []
    for group in groups_cfg:
        known = [inv_id for inv_id in group.inverters if inv_id in power_map]

        if known:
            active = sum(1 for inv_id in known if (power_map[inv_id] or 0) > 0)
            fault = len(known) - active
            availability_pct = round(active / group.inverter_count * 100, 2)
            mean_avail = availability_pct
        else:
            active = 0
            fault = 0
            availability_pct = None
            mean_avail = None

        inverter_groups.append({
            "id": group.id,
            "label": group.label,
            "centre_lat": group.centre_lat,
            "centre_lon": group.centre_lon,
            "inverter_count": group.inverter_count,
            "active_inverters": active,
            "fault_inverters": fault,
            "availability_pct": availability_pct,
            "status": _group_status(mean_avail),
        })

    return {
        "site_id": site_id,
        "site_name": site.name,
        "centre_lat": round(centre_lat, 6),
        "centre_lon": round(centre_lon, 6),
        "tilt_deg": site.tilt_deg,
        "azimuth_deg": site.azimuth_deg,
        "capacity_kwp": site.capacity_kwp,
        "inverter_groups": inverter_groups,
    }
