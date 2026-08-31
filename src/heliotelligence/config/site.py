"""Site configuration model and YAML loader."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ModuleConfig(BaseModel):
    """PV module parameters for the single-diode model.

    Fields are optional with sensible defaults so existing YAML files that
    omit the module block continue to validate without error.

    Lookup priority (resolved at runtime in physics/module_lookup.py):
      Tier 1 — CEC database (cec_name)
      Tier 2 — CEC auto-search (local_module_name as search key)
      Tier 3 — local module library YAML (local_module_name)
      Tier 4 — inline datasheet fields (v_mp/i_mp/v_oc/i_sc all set)
      Tier 5 — PVWatts simplified fallback (pnom_wp + gamma_pmp)
    """

    # --- CEC / local-library identification ---------------------------------
    cec_name: str | None = None
    local_module_name: str | None = None

    # --- Technology ---------------------------------------------------------
    technology: Literal["mono_si", "poly_si", "cdte", "cigs", "hjt"] = "mono_si"

    # --- STC datasheet parameters (needed for Tier 3/4 SDM fitting) ---------
    pnom_wp: float | None = None
    v_mp: float | None = None
    i_mp: float | None = None
    v_oc: float | None = None
    i_sc: float | None = None
    alpha_sc: float | None = None   # temperature coeff of Isc  [%/°C]
    beta_voc: float | None = None   # temperature coeff of Voc  [%/°C]
    gamma_pmp: float | None = None  # temperature coeff of Pmax [%/°C]
    cells_in_series: int | None = None

    # --- Bifacial -----------------------------------------------------------
    bifacial: bool = False
    bifaciality_factor: float = 0.80

    # --- Thermal model (Faiman) ---------------------------------------------
    u_c: float = 29.0   # heat transfer coefficient  [W/m²·K]
    u_v: float = 0.0    # wind-speed coefficient      [W/m²·K/(m/s)]
    noct_c: float = 45.0  # NOCT fallback              [°C]

    # --- Loss cascade -------------------------------------------------------
    soiling_loss_pct: float = 1.0        # % of DC power
    lid_loss_pct: float = 0.60           # light-induced degradation [%]
    mismatch_loss_pct: float = 1.15      # legacy aggregate mismatch [%]
    wiring_loss_dc_pct: float = 0.48     # legacy aggregate DC wiring [%]

    # --- Array geometry -----------------------------------------------------
    modules_per_string: int = 24
    num_strings: int = 1
    modules_per_table: int = 72
    num_tables: int | None = None
    row_pitch_m: float = 6.6


class InverterConfig(BaseModel):
    """Inverter parameters.

    pvlib_model selects which pvlib model family is used:
      'pvwatts' — simple efficiency scalar (default)
      'sandia'  — Sandia inverter model (requires Sandia database entry)
      'cec'     — CEC inverter model
    """

    model: str | None = None
    pvlib_model: Literal["pvwatts", "sandia", "cec"] = "pvwatts"
    pnom_kwac: float | None = None
    num_units: int = 1
    eta_nom: float = 0.9842
    wiring_loss_ac_pct: float = 1.70
    grid_limit_kwac: float | None = None


class StringConfig(BaseModel):
    """One physical PV string in the electrical topology.

    This topology is intentionally separate from the existing aggregate module
    configuration. It is optional so legacy sites continue to run unchanged
    while Stage 4 is migrated to string/MPPT resolution.
    """

    id: str
    modules_per_string: int = Field(gt=0)
    zone_id: str | None = None
    label: str | None = None


class MPPTConfig(BaseModel):
    """One independent MPPT input on a physical inverter."""

    id: str
    strings: list[StringConfig] = Field(default_factory=list)

    @property
    def string_count(self) -> int:
        return len(self.strings)


class InverterUnitConfig(BaseModel):
    """One physical inverter unit and its MPPT inputs."""

    id: str
    group_id: str | None = None
    model_ref: str | None = None
    mppts: list[MPPTConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_mppt_ids(self) -> "InverterUnitConfig":
        mppt_ids = [mppt.id for mppt in self.mppts]
        if len(mppt_ids) != len(set(mppt_ids)):
            raise ValueError(f"Duplicate MPPT id within inverter '{self.id}'")
        return self

    @property
    def mppt_count(self) -> int:
        return len(self.mppts)

    @property
    def string_count(self) -> int:
        return sum(mppt.string_count for mppt in self.mppts)


class ElectricalTopologyConfig(BaseModel):
    """Physical Site → Inverter → MPPT → String connectivity."""

    inverters: list[InverterUnitConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ElectricalTopologyConfig":
        inverter_ids = [inverter.id for inverter in self.inverters]
        if len(inverter_ids) != len(set(inverter_ids)):
            raise ValueError("Duplicate inverter id in electrical topology")

        seen_strings: set[str] = set()
        for inverter in self.inverters:
            for mppt in inverter.mppts:
                for string in mppt.strings:
                    if string.id in seen_strings:
                        raise ValueError(
                            f"Duplicate string id '{string.id}' in electrical topology"
                        )
                    seen_strings.add(string.id)
        return self

    @property
    def inverter_count(self) -> int:
        return len(self.inverters)

    @property
    def mppt_count(self) -> int:
        return sum(inverter.mppt_count for inverter in self.inverters)

    @property
    def string_count(self) -> int:
        return sum(inverter.string_count for inverter in self.inverters)


class InverterGroupConfig(BaseModel):
    id: str
    label: str
    centre_lat: float
    centre_lon: float
    inverter_count: int
    inverters: list[str] = []


class SiteLayoutConfig(BaseModel):
    inverter_groups: list[InverterGroupConfig] = []


class SiteConfig(BaseModel):
    """Top-level site configuration.

    azimuth_deg uses the PVsyst convention: 0 = South, negative = East,
    positive = West.  Use the pvlib_azimuth property for pvlib calls,
    which uses the meteorological convention: 0 = North, 90 = East,
    180 = South, 270 = West.
    """

    # --- Identity -----------------------------------------------------------
    id: str
    name: str

    # --- Location -----------------------------------------------------------
    latitude: float
    longitude: float
    altitude_m: float = 0.0
    timezone: str

    # --- Array description --------------------------------------------------
    capacity_kwp: float
    tilt_deg: float = Field(default=30.0, ge=0.0, le=90.0)
    azimuth_deg: float = Field(default=0.0, ge=-180.0, le=180.0)  # PVsyst: 0=South
    gcr: float = 0.40           # ground coverage ratio (collector_width / pitch)
    height_m: float = 1.0       # array bottom height above ground [m], for bifacial
    pitch_m: float | None = None  # row-to-row spacing [m]; if None → estimated as 2.3/gcr
    albedo: float = 0.25        # ground albedo for bifacial rear irradiance
    pvsyst_pr_target_pct: float | None = None  # PVsyst-modelled PR target [%]

    # --- External data ------------------------------------------------------
    solcast_resource_id: str
    scada_csv_dir: Path | None = None

    # --- Nested configs -----------------------------------------------------
    module: ModuleConfig = Field(default_factory=ModuleConfig)
    inverter: InverterConfig = Field(default_factory=InverterConfig)
    electrical_topology: ElectricalTopologyConfig | None = None
    layout: SiteLayoutConfig | None = None

    # --- Derived property ---------------------------------------------------
    @property
    def pvlib_azimuth(self) -> float:
        """Convert PVsyst azimuth (0=South) to pvlib azimuth (180=South).

        PVsyst:  0 = South, -90 = East,  +90 = West
        pvlib:   180 = South, 90 = East, 270 = West
        """
        return self.azimuth_deg + 180.0


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
