"""Admin API endpoints for site management and SCADA data upload.

GET  /api/v1/admin/sites            — list all sites from config
POST /api/v1/admin/sites            — create a new site, append to sites.yaml
POST /api/v1/admin/sites/{site_id}/upload — upload a SCADA CSV file
"""

from __future__ import annotations

import logging
import re
import tempfile
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from heliotelligence.config.settings import settings
from heliotelligence.config.site import load_sites
from heliotelligence.db.session import get_session_factory
from heliotelligence.ingest.csv_parser import parse_csv
from heliotelligence.ingest.upsert import upsert_all

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class InverterGroupIn(BaseModel):
    id: str
    label: str
    centre_lat: float
    centre_lon: float
    inverter_count: int
    inverter_id_prefix: str


class NewSiteRequest(BaseModel):
    # Identity
    name: str
    latitude: float
    longitude: float
    altitude_m: float = 0.0
    timezone: str = "Europe/London"
    # Array
    capacity_kwp: float
    tilt_deg: float = 15.0
    azimuth_deg: float = 0.0
    gcr: float = 0.4
    height_m: float = 0.7
    pvsyst_pr_target_pct: float | None = None
    # Module
    technology: str = "mono_si"
    bifacial: bool = True
    modules_per_string: int = 24
    num_strings: int = 1
    row_pitch_m: float = 6.0
    num_tables: int | None = None
    modules_per_table: int = 72
    soiling_loss_pct: float = 1.0
    lid_loss_pct: float = 0.6
    mismatch_loss_pct: float = 1.15
    wiring_loss_dc_pct: float = 0.48
    # Inverter
    inverter_model: str = ""
    num_inverters: int = 1
    inverter_pnom_kwac: float = 350.0
    inverter_eta_nom: float = 0.984
    wiring_loss_ac_pct: float = 1.70
    grid_limit_kwac: float | None = None
    # Layout
    inverter_groups: list[InverterGroupIn] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _site_uuid(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, slug))


def _find_site_by_uuid(site_id: str):
    sites = load_sites(settings.site_config_path)
    for s in sites:
        if _site_uuid(s.id) == site_id:
            return s
    return None


# ---------------------------------------------------------------------------
# GET /api/v1/admin/sites
# ---------------------------------------------------------------------------

@router.get("/sites")
async def list_sites() -> list[dict]:
    sites = load_sites(settings.site_config_path)
    return [
        {
            "id": _site_uuid(s.id),
            "slug": s.id,
            "name": s.name,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "capacity_kwp": s.capacity_kwp,
            "tilt_deg": s.tilt_deg,
            "azimuth_deg": s.azimuth_deg,
            "timezone": s.timezone,
            "num_inverter_groups": len(s.layout.inverter_groups) if s.layout else 0,
            "total_inverters": sum(g.inverter_count for g in s.layout.inverter_groups) if s.layout else 0,
        }
        for s in sites
    ]


# ---------------------------------------------------------------------------
# POST /api/v1/admin/sites
# ---------------------------------------------------------------------------

@router.post("/sites", status_code=201)
async def create_site(req: NewSiteRequest) -> dict:
    # Generate slug from name
    slug = re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-")

    # Check for duplicate
    existing = load_sites(settings.site_config_path)
    if any(s.id == slug for s in existing):
        raise HTTPException(status_code=409, detail=f"Site with slug '{slug}' already exists")

    # Build inverter groups with auto-generated inverter IDs
    groups = []
    for g in req.inverter_groups:
        inverters = [f"{g.inverter_id_prefix}{101 + i}" for i in range(g.inverter_count)]
        groups.append({
            "id": g.id,
            "label": g.label,
            "centre_lat": g.centre_lat,
            "centre_lon": g.centre_lon,
            "inverter_count": g.inverter_count,
            "inverters": inverters,
        })

    # Build YAML structure
    site_dict: dict = {
        "id": slug,
        "name": req.name,
        "latitude": req.latitude,
        "longitude": req.longitude,
        "altitude_m": req.altitude_m,
        "timezone": req.timezone,
        "capacity_kwp": req.capacity_kwp,
        "tilt_deg": req.tilt_deg,
        "azimuth_deg": req.azimuth_deg,
        "gcr": req.gcr,
        "height_m": req.height_m,
        "solcast_resource_id": "",
        "module": {
            "technology": req.technology,
            "bifacial": req.bifacial,
            "modules_per_string": req.modules_per_string,
            "num_strings": req.num_strings,
            "row_pitch_m": req.row_pitch_m,
            "modules_per_table": req.modules_per_table,
            "soiling_loss_pct": req.soiling_loss_pct,
            "lid_loss_pct": req.lid_loss_pct,
            "mismatch_loss_pct": req.mismatch_loss_pct,
            "wiring_loss_dc_pct": req.wiring_loss_dc_pct,
        },
        "inverter": {
            "pvlib_model": "pvwatts",
            "num_units": req.num_inverters,
            "eta_nom": req.inverter_eta_nom,
            "wiring_loss_ac_pct": req.wiring_loss_ac_pct,
        },
    }

    if req.pvsyst_pr_target_pct is not None:
        site_dict["pvsyst_pr_target_pct"] = req.pvsyst_pr_target_pct
    if req.inverter_model:
        site_dict["inverter"]["model"] = req.inverter_model
    if req.inverter_pnom_kwac:
        site_dict["inverter"]["pnom_kwac"] = req.inverter_pnom_kwac
    if req.grid_limit_kwac is not None:
        site_dict["inverter"]["grid_limit_kwac"] = req.grid_limit_kwac
    if req.num_tables is not None:
        site_dict["module"]["num_tables"] = req.num_tables
    if groups:
        site_dict["layout"] = {"inverter_groups": groups}

    # Append to sites.yaml
    config_path = settings.site_config_path
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    else:
        data = {}

    sites_list: list = data.get("sites", [])
    sites_list.append(site_dict)
    data["sites"] = sites_list

    with config_path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)

    site_id = _site_uuid(slug)
    log.info("Created site '%s' (slug=%s, uuid=%s)", req.name, slug, site_id)

    return {"site_id": site_id, "slug": slug, "name": req.name}


# ---------------------------------------------------------------------------
# POST /api/v1/admin/sites/{site_id}/upload
# ---------------------------------------------------------------------------

@router.post("/sites/{site_id}/upload")
async def upload_scada(
    site_id: str,
    file: UploadFile = File(...),
) -> dict:
    site = _find_site_by_uuid(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")

    contents = await file.read()
    suffix = Path(file.filename or "upload.csv").suffix or ".csv"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        weather, meter, inverters, strings = parse_csv(
            path=tmp_path,
            site_id=site_id,
            site_name=site.name,
            source_tz=site.timezone,
        )

        factory = get_session_factory()
        async with factory() as session:
            await upsert_all(session, weather, meter, inverters, strings)

        log.info(
            "Uploaded SCADA for site %s: %d weather, %d meter, %d inverter, %d string rows",
            site_id, len(weather), len(meter), len(inverters), len(strings),
        )

        return {
            "site_id": site_id,
            "filename": file.filename,
            "weather_rows": len(weather),
            "meter_rows": len(meter),
            "inverter_rows": len(inverters),
            "string_rows": len(strings),
        }
    finally:
        tmp_path.unlink(missing_ok=True)
