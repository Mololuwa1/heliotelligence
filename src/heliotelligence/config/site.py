"""Site configuration model and YAML loader."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SiteConfig(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    timezone: str
    capacity_kwp: float
    solcast_resource_id: str
    tilt_deg: float = Field(default=30.0, ge=0.0, le=90.0)
    azimuth_deg: float = Field(default=0.0, ge=-180.0, le=180.0)  # PVsyst: 0=South
    scada_csv_dir: Path | None = None


def load_sites(path: Path) -> list[SiteConfig]:
    """Load all site configurations from a YAML file.

    Returns an empty list (not an error) when the file does not exist,
    so the application can start in environments without a sites config.
    """
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    sites_raw: list[dict] = (data or {}).get("sites", [])
    return [SiteConfig.model_validate(s) for s in sites_raw]
