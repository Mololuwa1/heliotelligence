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

    Uses as-built parameters from SiteConfig.module (row_pitch_m, modules_per_string).
    All geometry is derived from config — no DB access.
    """
    # Module dimensions (TOPCon landscape orientation)
    MOD_W_M = 2.278   # panel width along row (E-W, landscape)
    MOD_H_M = 1.134   # panel height across row (N-S, tilt direction)

    # From as-built or config
    modules_per_string = site.module.modules_per_string  # 24
    num_strings = site.module.num_strings                 # 2076
    row_pitch_m = site.module.row_pitch_m                 # 6.6m actual inter-row spacing

    # Table geometry: panels arranged in a 3-portrait × 24-landscape grid
    table_width_m = modules_per_string * MOD_W_M   # E-W: 54.67m
    table_depth_m = 3 * MOD_H_M                    # N-S panel area: 3.4m  # noqa: F841

    # Azimuth: PVsyst convention 0=South, -0.6 ≈ South (rows run E-W).
    # For near-zero azimuth: along_row ≈ E-W (lon), across_row ≈ N-S (lat).
    az_rad = math.radians(site.azimuth_deg)
    along_row_lon = math.cos(az_rad)    # E-W component (dominant)
    along_row_lat = math.sin(az_rad)    # N-S component (tiny for az≈0)
    across_row_lon = -math.sin(az_rad)  # perpendicular E-W (tiny)
    across_row_lat = math.cos(az_rad)   # perpendicular N-S (dominant)

    groups_cfg = site.layout.inverter_groups if site.layout else []
    total_inverters = sum(g.inverter_count for g in groups_cfg)

    result_groups: list[dict] = []

    for group in groups_cfg:
        centre_lat: float = group.centre_lat
        centre_lon: float = group.centre_lon

        # Metre-to-degree conversion at this latitude
        lat_per_m: float = 1.0 / 111320.0
        lon_per_m: float = 1.0 / (111320.0 * math.cos(math.radians(centre_lat)))

        # Strings for this group (proportional to inverter count)
        group_strings: int = round(num_strings * group.inverter_count / total_inverters)

        # Tables per E-W row: groups span full E-W width (~820m from as-built)
        tables_per_ew_row: int = round(820 / table_width_m)  # ~15 tables
        # Each mounting table has 3 string rows (3P portrait structure)
        # Convert strings to tables before computing N-S row count
        group_tables: int = math.ceil(group_strings / 3)
        num_ns_rows: int = math.ceil(group_tables / tables_per_ew_row)

        # Generate one point per table (represents a 54m × 3.4m mounting table)
        panels: list[list[float]] = []
        for row_i in range(num_ns_rows):
            row_offset_m = (row_i - num_ns_rows / 2.0 + 0.5) * row_pitch_m
            for table_i in range(tables_per_ew_row):
                table_offset_m = (table_i - tables_per_ew_row / 2.0 + 0.5) * table_width_m
                dx = table_offset_m * along_row_lon + row_offset_m * across_row_lon
                dy = table_offset_m * along_row_lat + row_offset_m * across_row_lat
                panel_lon = centre_lon + dx * lon_per_m
                panel_lat = centre_lat + dy * lat_per_m
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
            "zone_ew_m": round(tables_per_ew_row * table_width_m, 1),
            "zone_ns_m": round(num_ns_rows * row_pitch_m, 1),
            "panels": panels,
        })

    return {
        "site_id": str(site.id),
        "module_width_m": MOD_W_M,
        "module_height_m": MOD_H_M,
        "tilt_deg": site.tilt_deg,
        "azimuth_deg": site.azimuth_deg,
        "row_pitch_m": row_pitch_m,
        "table_width_m": round(table_width_m, 3),
        "num_strings": num_strings,
        "total_panels": num_strings * modules_per_string if num_strings else 0,
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
