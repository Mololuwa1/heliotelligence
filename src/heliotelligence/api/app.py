"""FastAPI application with APScheduler lifespan.

Startup sequence
────────────────
  1. Load site configs from YAML.
  2. Sync sites to the database (INSERT … ON CONFLICT DO UPDATE).
  3. Configure Solcast and SCADA CSV jobs via collectors.scheduler.
  4. Scheduler starts; app begins serving requests.

Shutdown
────────
  5. Scheduler is stopped gracefully.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from heliotelligence.config.settings import settings
from heliotelligence.config.site import load_sites
from heliotelligence.collectors.scheduler import configure_scheduler, get_scheduler
from heliotelligence.db.session import get_session_factory
from heliotelligence.db.sync import sync_sites
from heliotelligence.api.routers import health as health_router
from heliotelligence.api.routers import ingest as ingest_router
from heliotelligence.api.routers import expected_energy as expected_energy_router

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    sites = load_sites(settings.site_config_path)
    if not sites:
        log.warning(
            "No site configs found at %s — ingest jobs will not run.",
            settings.site_config_path,
        )

    # Ensure every site in YAML exists in the DB before the ingest pipeline
    # runs.  Without this, FK constraints on site_id silently discard rows.
    factory = get_session_factory()
    async with factory() as session:
        synced = await sync_sites(sites, session)
        await session.commit()
    log.info("Synced %d site(s) to database", synced)

    sched = get_scheduler()
    configure_scheduler(sites)
    sched.start()
    log.info("APScheduler started with %d job(s)", len(sched.get_jobs()))

    yield

    sched.shutdown(wait=False)
    log.info("APScheduler stopped")


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Heliotelligence",
    description="Solar farm digital twin and performance benchmarking platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router.router)
app.include_router(ingest_router.router)
app.include_router(expected_energy_router.router)
