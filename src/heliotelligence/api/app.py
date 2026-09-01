"""FastAPI application with APScheduler lifespan.

Startup sequence
────────────────
  1. Load site configs from YAML.
  2. Sync sites to the database (INSERT … ON CONFLICT DO UPDATE).
  3. When RUN_SCHEDULER is enabled, configure jobs via collectors.scheduler.
  4. When enabled, the scheduler starts; the app begins serving requests.

Shutdown
────────
  5. A scheduler started by this process is stopped gracefully.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from heliotelligence.api.auth import get_current_user
from heliotelligence.api.routers import admin as admin_router
from heliotelligence.api.routers import alerts as alerts_router
from heliotelligence.api.routers import analysis as analysis_router
from heliotelligence.api.routers import backfill as backfill_router
from heliotelligence.api.routers import benchmarking as benchmarking_router
from heliotelligence.api.routers import expected_energy as expected_energy_router
from heliotelligence.api.routers import geometry as geometry_router
from heliotelligence.api.routers import health as health_router
from heliotelligence.api.routers import ingest as ingest_router
from heliotelligence.api.routers import layout as layout_router
from heliotelligence.api.routers import reports as reports_router
from heliotelligence.collectors.scheduler import configure_scheduler, get_scheduler
from heliotelligence.config.settings import settings
from heliotelligence.config.site import load_sites
from heliotelligence.db.session import get_session_factory
from heliotelligence.db.sync import sync_sites

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("Starting Heliotelligence API (environment=%s)", settings.app_env)

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

    sched = None
    if settings.run_scheduler:
        sched = get_scheduler()
        configure_scheduler(sites)
        sched.start()
        log.info("APScheduler started with %d job(s)", len(sched.get_jobs()))
    else:
        log.info("In-process APScheduler disabled by RUN_SCHEDULER")

    try:
        yield
    finally:
        if sched is not None:
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router.router)  # public
app.include_router(admin_router.router)  # has own auth
app.include_router(ingest_router.router, dependencies=[Depends(get_current_user)])
app.include_router(expected_energy_router.router, dependencies=[Depends(get_current_user)])
app.include_router(benchmarking_router.router, dependencies=[Depends(get_current_user)])
app.include_router(analysis_router.router, dependencies=[Depends(get_current_user)])
app.include_router(reports_router.router, dependencies=[Depends(get_current_user)])
app.include_router(alerts_router.router, dependencies=[Depends(get_current_user)])
app.include_router(backfill_router.router, dependencies=[Depends(get_current_user)])
app.include_router(layout_router.router, dependencies=[Depends(get_current_user)])
app.include_router(geometry_router.router, dependencies=[Depends(get_current_user)])
