"""APScheduler wiring for all periodic ingest jobs.

Job registry
────────────
solcast:<site_id>      Hourly Solcast API fetch (skipped when SOLCAST_API_KEY is unset).
scada_csv:<site_id>    Periodic SCADA CSV drop-folder poll.

Status tracking
───────────────
Each job wrapper updates ``_job_status`` so that the /api/v1/ingest/status
endpoint can return a lightweight health snapshot without touching the
database.  Keys per job entry:

  last_run        datetime (UTC) of most recent execution attempt, or None
  last_success    datetime (UTC) of last successful run, or None
  last_error      error string from last failure, or None
  rows_upserted   (Solcast only) row count from last success
  files_processed (SCADA only)  file count from last success
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from heliotelligence.config.settings import settings
from heliotelligence.config.site import SiteConfig
from heliotelligence.collectors.solcast import run_solcast_collector
from heliotelligence.collectors.scada_csv import ScadaCsvCollector
from heliotelligence.db.session import get_session_factory
from heliotelligence.engine.pipeline import run_pipeline

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level scheduler (one instance per process)
# ---------------------------------------------------------------------------

scheduler = AsyncIOScheduler(timezone="UTC")

# { "solcast:<site_id>" | "scada_csv:<site_id>": { ... } }
_job_status: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_scheduler() -> AsyncIOScheduler:
    """Return the shared APScheduler instance."""
    return scheduler


def get_job_status() -> dict[str, dict[str, Any]]:
    """Return a snapshot of every registered job's last-run metadata."""
    return dict(_job_status)


def configure_scheduler(sites: list[SiteConfig]) -> None:
    """Register Solcast, SCADA CSV, physics pipeline, and alerts jobs for each site.

    Safe to call multiple times; ``replace_existing=True`` ensures existing
    jobs are updated rather than duplicated.
    """
    import uuid as _uuid
    for site in sites:
        _register_solcast_job(site)
        _register_scada_job(site)
        _register_physics_job(site)
        _register_alerts_job(site, str(_uuid.uuid5(_uuid.NAMESPACE_DNS, site.id)))


# ---------------------------------------------------------------------------
# Job registration helpers
# ---------------------------------------------------------------------------

def _register_solcast_job(site: SiteConfig) -> None:
    if not settings.solcast_api_key:
        log.warning(
            "SOLCAST_API_KEY not set — Solcast job skipped for site %s", site.id
        )
        return

    key = f"solcast:{site.id}"
    scheduler.add_job(
        _run_solcast_job,
        trigger="interval",
        minutes=settings.solcast_poll_interval_minutes,
        args=[site],
        id=f"solcast_{site.id}",
        name=f"Solcast — {site.name}",
        replace_existing=True,
    )
    _job_status.setdefault(key, {"last_run": None, "last_success": None, "last_error": None})
    log.info(
        "Scheduled Solcast job for %s every %d min",
        site.name, settings.solcast_poll_interval_minutes,
    )


def _register_scada_job(site: SiteConfig) -> None:
    if site.scada_csv_dir is None:
        return

    key = f"scada_csv:{site.id}"
    scheduler.add_job(
        _run_scada_job,
        trigger="interval",
        minutes=settings.scada_csv_poll_interval_minutes,
        args=[site],
        id=f"scada_csv_{site.id}",
        name=f"SCADA CSV — {site.name}",
        replace_existing=True,
    )
    _job_status.setdefault(key, {"last_run": None, "last_success": None, "last_error": None})
    log.info(
        "Scheduled SCADA CSV job for %s every %d min",
        site.name, settings.scada_csv_poll_interval_minutes,
    )


def _register_alerts_job(site: SiteConfig, site_uuid: str) -> None:
    key = f"alerts:{site.id}"
    scheduler.add_job(
        _run_alerts_job,
        trigger="interval",
        minutes=15,
        args=[site_uuid],
        id=f"alerts_{site.id}",
        name=f"Alerts — {site.name}",
        replace_existing=True,
    )
    _job_status.setdefault(key, {
        "last_run": None,
        "last_success": None,
        "last_error": None,
        "alerts_fired": None,
    })
    log.info("Scheduled alerts job for %s every 15 min", site.name)


def _register_physics_job(site: SiteConfig) -> None:
    key = f"physics:{site.id}"
    scheduler.add_job(
        _run_physics_job,
        trigger="interval",
        minutes=settings.physics_pipeline_interval_minutes,
        args=[site],
        id=f"physics_{site.id}",
        name=f"Physics pipeline — {site.name}",
        replace_existing=True,
    )
    _job_status.setdefault(key, {
        "last_run": None,
        "last_success": None,
        "last_error": None,
        "rows_upserted": None,
        "chunks_run": None,
    })
    log.info(
        "Scheduled physics pipeline for %s every %d min",
        site.name, settings.physics_pipeline_interval_minutes,
    )


# ---------------------------------------------------------------------------
# Job wrapper functions (write to _job_status on every run)
# ---------------------------------------------------------------------------

async def _run_solcast_job(site: SiteConfig) -> None:
    key = f"solcast:{site.id}"
    try:
        rows = await run_solcast_collector(site)
        now = datetime.now(timezone.utc)
        _job_status[key].update(
            last_run=now,
            last_success=now,
            last_error=None,
            rows_upserted=rows,
        )
    except Exception as exc:
        now = datetime.now(timezone.utc)
        _job_status.setdefault(key, {}).update(last_run=now, last_error=str(exc))
        log.error("Solcast job failed for site %s: %s", site.id, exc)


async def _run_physics_job(site: SiteConfig) -> None:
    key = f"physics:{site.id}"
    try:
        factory = get_session_factory()
        async with factory() as session:
            result = await run_pipeline(site, session)
            await session.commit()
        now = datetime.now(timezone.utc)
        _job_status[key].update(
            last_run=now,
            last_success=now,
            last_error=None,
            rows_upserted=result["rows_upserted"],
            chunks_run=result["chunks_run"],
        )
    except Exception as exc:
        now = datetime.now(timezone.utc)
        _job_status.setdefault(key, {}).update(last_run=now, last_error=str(exc))
        log.error("Physics pipeline failed for site %s: %s", site.id, exc)


async def _run_alerts_job(site_uuid: str) -> None:
    key = f"alerts:{site_uuid}"
    try:
        from heliotelligence.alerts.evaluator import evaluate_and_persist_alerts
        factory = get_session_factory()
        async with factory() as session:
            fired = await evaluate_and_persist_alerts(site_uuid, session)
            await session.commit()
        now = datetime.now(timezone.utc)
        _job_status.setdefault(key, {}).update(
            last_run=now,
            last_success=now,
            last_error=None,
            alerts_fired=len(fired),
        )
        if fired:
            log.info("Alerts job fired %d alert(s) for site %s", len(fired), site_uuid)
    except Exception as exc:
        now = datetime.now(timezone.utc)
        _job_status.setdefault(key, {}).update(last_run=now, last_error=str(exc))
        log.error("Alerts job failed for site %s: %s", site_uuid, exc)


async def _run_scada_job(site: SiteConfig) -> None:
    key = f"scada_csv:{site.id}"
    try:
        collector = ScadaCsvCollector(site)
        files = await collector.poll()
        now = datetime.now(timezone.utc)
        _job_status[key].update(
            last_run=now,
            last_success=now,
            last_error=None,
            files_processed=files,
        )
    except Exception as exc:
        now = datetime.now(timezone.utc)
        _job_status.setdefault(key, {}).update(last_run=now, last_error=str(exc))
        log.error("SCADA CSV job failed for site %s: %s", site.id, exc)
