"""POA irradiance calculation for a fixed-tilt PV array.

Public API
----------
calculate_poa(site, weather_df, solar_position=None) -> pd.DataFrame

Output columns
--------------
  poa_total      — total effective POA irradiance [W/m²]
  poa_direct     — beam component on the front surface [W/m²]
  poa_diffuse    — total diffuse component on the front surface [W/m²]
  poa_rear       — rear irradiance × bifaciality_factor (0 if not bifacial) [W/m²]
  aoi            — angle of incidence on the front surface [degrees]
  solar_zenith   — apparent solar zenith [degrees]
  solar_azimuth  — solar azimuth, pvlib convention (0=N, 90=E) [degrees]

pvlib functions used
--------------------
  pvlib.location.Location
  pvlib.solarposition.get_solarposition
  pvlib.irradiance.get_total_irradiance  (model='perez')
  pvlib.irradiance.aoi                   (angle of incidence)
  pvlib.bifacial.infinite_sheds.get_irradiance  (bifacial sites)
  pvlib.iam.physical                     (IAM correction)
"""

from __future__ import annotations

import logging

import pandas as pd

from heliotelligence.config.site import SiteConfig

logger = logging.getLogger(__name__)

# Ground albedo default used when not set on SiteConfig.
_DEFAULT_ALBEDO = 0.25

# Default collector slant-height [m] used to estimate pitch when pitch_m is
# not explicitly configured.  Appropriate for large-format bifacial modules
# (≈2.3 m slant height at 15° tilt for a ~2.3 m wide module).
_DEFAULT_COLLECTOR_WIDTH_M = 2.3


def _build_location(site: SiteConfig) -> "pvlib.location.Location":  # noqa: F821
    """Build a pvlib.Location from a SiteConfig.

    Parameters
    ----------
    site : SiteConfig

    Returns
    -------
    pvlib.location.Location
    """
    import pvlib

    return pvlib.location.Location(
        latitude=site.latitude,
        longitude=site.longitude,
        tz=site.timezone,
        altitude=site.altitude_m,
        name=site.name,
    )


def calculate_poa(
    site: SiteConfig,
    weather_df: pd.DataFrame,
    solar_position: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Calculate plane-of-array irradiance for a fixed-tilt site.

    Parameters
    ----------
    site : SiteConfig
        Site configuration including tilt, azimuth, bifacial settings.
    weather_df : pd.DataFrame
        Timeseries with a DatetimeIndex (timezone-aware, UTC or local).
        Expected columns (all in W/m²):
          - ghi_wm2    — global horizontal irradiance
          - dhi_wm2    — diffuse horizontal irradiance
          - dni_wm2    — direct normal irradiance
          Optional:
          - poa_wm2    — measured plane-of-array irradiance (used directly
                         if present and <20 % NaN)
    solar_position : pd.DataFrame, optional
        Pre-computed solar position DataFrame (output of
        pvlib.solarposition.get_solarposition).  Computed internally if
        not supplied.

    Returns
    -------
    pd.DataFrame
        Columns: poa_total, poa_direct, poa_diffuse, poa_rear, aoi,
                 solar_zenith, solar_azimuth.
    """
    import pvlib
    import pvlib.bifacial.infinite_sheds
    import pvlib.iam
    import pvlib.irradiance

    location = _build_location(site)

    # --- Solar position ---------------------------------------------------
    if solar_position is None:
        solar_position = location.get_solarposition(weather_df.index)

    solar_zenith = solar_position["apparent_zenith"]
    solar_azimuth = solar_position["azimuth"]  # pvlib convention: 0=N

    # --- Angle of incidence -----------------------------------------------
    aoi = pvlib.irradiance.aoi(
        surface_tilt=site.tilt_deg,
        surface_azimuth=site.pvlib_azimuth,
        solar_zenith=solar_zenith,
        solar_azimuth=solar_azimuth,
    )

    # --- Measured POA shortcut -------------------------------------------
    # If measured POA is available and has <20 % NaN, use it as poa_total
    # but still compute aoi and solar position for downstream use.
    measured_poa_available = (
        "poa_wm2" in weather_df.columns
        and weather_df["poa_wm2"].isna().mean() < 0.20
    )

    if measured_poa_available:
        logger.info(
            "Using measured poa_wm2 as poa_total for site %s (%.1f%% NaN).",
            site.id,
            weather_df["poa_wm2"].isna().mean() * 100,
        )
        poa_total = weather_df["poa_wm2"].copy()
        # For measured POA we cannot decompose into direct/diffuse cleanly;
        # report NaN for the sub-components.
        poa_direct = pd.Series(float("nan"), index=weather_df.index)
        poa_diffuse = pd.Series(float("nan"), index=weather_df.index)
        poa_rear = pd.Series(0.0, index=weather_df.index)
    else:
        # --- Perez transposition -----------------------------------------
        ghi = weather_df.get("ghi_wm2", pd.Series(0.0, index=weather_df.index))
        dhi = weather_df.get("dhi_wm2", pd.Series(0.0, index=weather_df.index))
        dni = weather_df.get("dni_wm2", pd.Series(0.0, index=weather_df.index))
        dni_extra = pvlib.irradiance.get_extra_radiation(weather_df.index)

        poa_components = pvlib.irradiance.get_total_irradiance(
            surface_tilt=site.tilt_deg,
            surface_azimuth=site.pvlib_azimuth,
            solar_zenith=solar_zenith,
            solar_azimuth=solar_azimuth,
            dni=dni,
            ghi=ghi,
            dhi=dhi,
            dni_extra=dni_extra,
            model="perez",
        )
        poa_direct = poa_components["poa_direct"].fillna(0.0)
        poa_diffuse = (
            poa_components["poa_sky_diffuse"].fillna(0.0)
            + poa_components["poa_ground_diffuse"].fillna(0.0)
        )
        poa_front = poa_direct + poa_diffuse

        # Apply IAM correction to beam component
        iam = pvlib.iam.physical(aoi)
        poa_direct_iam = poa_direct * iam

        # --- Bifacial rear irradiance ------------------------------------
        poa_rear = pd.Series(0.0, index=weather_df.index)
        if site.module.bifacial:
            albedo = getattr(site, "albedo", _DEFAULT_ALBEDO)
            # Estimate pitch if not configured
            pitch = (
                site.pitch_m
                if site.pitch_m is not None
                else _DEFAULT_COLLECTOR_WIDTH_M / site.gcr
            )
            logger.info(
                "Bifacial rear irradiance: gcr=%.3f, height=%.2f m, pitch=%.2f m.",
                site.gcr,
                site.height_m,
                pitch,
            )
            try:
                bifacial_out = pvlib.bifacial.infinite_sheds.get_irradiance(
                    surface_tilt=site.tilt_deg,
                    surface_azimuth=site.pvlib_azimuth,
                    solar_zenith=solar_zenith,
                    solar_azimuth=solar_azimuth,
                    gcr=site.gcr,
                    height=site.height_m,
                    pitch=pitch,
                    ghi=ghi,
                    dhi=dhi,
                    dni=dni,
                    albedo=albedo,
                    bifaciality=site.module.bifaciality_factor,
                )
                # poa_back in the output is raw back irradiance;
                # poa_global already applies bifaciality internally.
                poa_rear = bifacial_out["poa_back"].fillna(0.0) * site.module.bifaciality_factor
                # Use bifacial poa_global as total (replaces Perez front-only total)
                poa_front = bifacial_out["poa_front"].fillna(0.0)
            except Exception as exc:
                logger.warning(
                    "Bifacial calculation failed (%s); using front-only POA.", exc
                )

        # Apply IAM to final direct component
        poa_direct = poa_direct_iam
        poa_total = poa_front + poa_rear

    return pd.DataFrame(
        {
            "poa_total": poa_total,
            "poa_direct": poa_direct,
            "poa_diffuse": poa_diffuse,
            "poa_rear": poa_rear,
            "aoi": aoi,
            "solar_zenith": solar_zenith,
            "solar_azimuth": solar_azimuth,
        },
        index=weather_df.index,
    )
