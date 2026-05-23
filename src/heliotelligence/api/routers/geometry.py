"""Site panel geometry endpoint.

GET /api/v1/sites/{site_id}/geometry
    Computes 3D panel positions for a site from SiteConfig parameters only.
    No database access — pure geometry derived from YAML config.

Query parameters
────────────────
  max_panels_per_group : int (default 500)
      Downsample panels for frontend rendering. When len(panels) > max,
      every Nth panel is returned so approximately max panels are returned
      per group.

Response shape
──────────────
{
  "site_id": "...",
  "module_width_m": 2.278,
  "module_height_m": 1.134,
  "tilt_deg": 15.0,
  "azimuth_deg": -0.6,
  "row_pitch_m": 1.734,
  "row_length_m": 54.672,
  "total_panels": 50042,
  "groups": [
    {
      "id": "MQA11",
      "centre_lat": 52.560587,
      "centre_lon": 1.211691,
      "panel_count": 500,          ← after downsampling
      "panels": [[lon, lat], ...]
    },
    ...
  ]
}
"""

from __future__ import annotations

import math
import logging
import uuid

from fastapi import APIRouter, HTTPException, Query

from heliotelligence.config.settings import settings
from heliotelligence.config.site import SiteConfig, load_sites

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sites", tags=["geometry"])

# Standard module dimensions for utility-scale TOPCon panels.
# TODO: read from SiteConfig.module when dimension fields are added.
_MOD_W_M = 2.278   # panel width along row (landscape orientation)
_MOD_H_M = 1.134   # panel height across row (tilt direction)
_MODULE_KWP = 0.570  # JKM570N nameplate — used to estimate panel count


def _find_site(site_id: str) -> SiteConfig | None:
    sites = load_sites(settings.site_config_path)
    for site in sites:
        if str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)) == site_id:
            return site
    return None


def compute_site_geometry(
    site: SiteConfig,
    max_panels_per_group: int | None = 500,
) -> dict:
    """Compute panel centre positions for every inverter group in *site*.

    All geometry is derived from SiteConfig fields — no DB access.
    """
    modules_per_string: int = site.module.modules_per_string
    num_strings: int = site.module.num_strings
    num_modules: int = round(site.capacity_kwp / _MODULE_KWP)

    # Row geometry
    row_pitch_m: float = _MOD_H_M / site.gcr          # horizontal row-to-row spacing
    row_length_m: float = modules_per_string * _MOD_W_M  # length of one string row

    # Azimuth conversion:
    #   PVsyst: 0=South, -90=East, +90=West
    #   pvlib:  pvlib_az = azimuth_deg + 180  (0=North, 90=East, 180=South)
    #   math:   az_rad = 90° - pvlib_az  (0=East, CCW positive)
    pvlib_az: float = site.azimuth_deg + 180.0
    az_rad: float = math.radians(90.0 - pvlib_az)

    # Unit vectors in the horizontal plane
    along_row   = (math.cos(az_rad),  math.sin(az_rad))   # parallel to panel strings
    across_row  = (-math.sin(az_rad), math.cos(az_rad))   # row-to-row direction

    groups_cfg = site.layout.inverter_groups if site.layout else []
    total_inverters = sum(g.inverter_count for g in groups_cfg)

    result_groups: list[dict] = []

    for group in groups_cfg:
        # Strings allocated to this group proportional to inverter count
        group_strings: int = round(num_strings * group.inverter_count / total_inverters)

        centre_lat: float = group.centre_lat
        centre_lon: float = group.centre_lon

        # Metre-to-degree conversion at this latitude
        lat_per_m: float = 1.0 / 111320.0
        lon_per_m: float = 1.0 / (111320.0 * math.cos(math.radians(centre_lat)))

        # Generate panel centre positions
        panels: list[list[float]] = []
        half_rows = group_strings / 2.0

        for row_i in range(group_strings):
            row_offset = (row_i - half_rows + 0.5) * row_pitch_m
            row_dx = row_offset * across_row[0]
            row_dy = row_offset * across_row[1]

            for col_i in range(modules_per_string):
                col_offset = (col_i - modules_per_string / 2.0 + 0.5) * _MOD_W_M
                panel_dx = row_dx + col_offset * along_row[0]
                panel_dy = row_dy + col_offset * along_row[1]

                panel_lon = centre_lon + panel_dx * lon_per_m
                panel_lat = centre_lat + panel_dy * lat_per_m

                panels.append([round(panel_lon, 7), round(panel_lat, 7)])

        # Downsample for frontend performance
        if max_panels_per_group and len(panels) > max_panels_per_group:
            step = max(1, len(panels) // max_panels_per_group)
            panels = panels[::step]

        result_groups.append({
            "id": group.id,
            "centre_lat": centre_lat,
            "centre_lon": centre_lon,
            "panel_count": len(panels),
            "panels": panels,
        })

    return {
        "site_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)),
        "module_width_m": _MOD_W_M,
        "module_height_m": _MOD_H_M,
        "tilt_deg": site.tilt_deg,
        "azimuth_deg": site.azimuth_deg,
        "row_pitch_m": round(row_pitch_m, 3),
        "row_length_m": round(row_length_m, 3),
        "total_panels": num_modules,
        "groups": result_groups,
    }


@router.get("/{site_id}/geometry")
async def get_site_geometry(
    site_id: str,
    max_panels_per_group: int = Query(
        default=500,
        ge=1,
        description="Max panels returned per group (downsampled). Use 0 for full resolution.",
    ),
) -> dict:
    site = _find_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    if not site.layout:
        raise HTTPException(status_code=404, detail=f"Site {site_id} has no layout configured")

    limit = max_panels_per_group if max_panels_per_group > 0 else None
    return compute_site_geometry(site, max_panels_per_group=limit)
