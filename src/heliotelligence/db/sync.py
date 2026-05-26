"""Startup synchronisation helpers.

sync_sites() ensures every site declared in config/sites.yaml exists in the
`sites` table before the ingest pipeline runs.  Without this, every upsert
into weather_readings / meter_readings / etc. fails on the site_id FK.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.config.site import SiteConfig

log = logging.getLogger(__name__)

_DEFAULT_STRINGS_PER_INV = 32

# The upsert keeps site_id as the stable key and refreshes all mutable fields.
# strings_per_inv defaults to 32; subsidy_type is left NULL unless already set.
_UPSERT_SQL = text(
    """
    INSERT INTO sites (
        site_id,
        site_name,
        site_code,
        latitude,
        longitude,
        timezone,
        capacity_kwp,
        strings_per_inv,
        subsidy_type
    ) VALUES (
        :site_id,
        :site_name,
        :site_code,
        :latitude,
        :longitude,
        :timezone,
        :capacity_kwp,
        :strings_per_inv,
        :subsidy_type
    )
    ON CONFLICT (site_code) DO UPDATE SET
        site_name      = EXCLUDED.site_name,
        latitude       = EXCLUDED.latitude,
        longitude      = EXCLUDED.longitude,
        timezone       = EXCLUDED.timezone,
        capacity_kwp   = EXCLUDED.capacity_kwp
    """
)


async def sync_sites(
    sites: list[SiteConfig],
    session: AsyncSession,
) -> int:
    """Upsert each SiteConfig into the sites table.

    Parameters
    ----------
    sites:   Site configurations loaded from YAML.
    session: An open AsyncSession.  The caller is responsible for committing.

    Returns
    -------
    int
        Number of rows upserted (equals len(sites); every entry is processed
        regardless of whether it was an insert or an update).
    """
    if not sites:
        log.debug("sync_sites: no sites to sync")
        return 0

    for site in sites:
        params = {
            "site_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)),  # deterministic UUID from text id
            "site_name": site.name,
            "site_code": site.id,          # plain text id; conflict target via sites_site_code_key
            "latitude": site.latitude,
            "longitude": site.longitude,
            "timezone": site.timezone,
            "capacity_kwp": site.capacity_kwp,
            "strings_per_inv": _DEFAULT_STRINGS_PER_INV,
            "subsidy_type": None,
        }
        await session.execute(_UPSERT_SQL, params)
        log.info(
            "sync_sites: upserted site %s (%s, %.4f°N %.4f°E, %.1f kWp)",
            site.id,
            site.name,
            site.latitude,
            site.longitude,
            site.capacity_kwp,
        )

    return len(sites)
