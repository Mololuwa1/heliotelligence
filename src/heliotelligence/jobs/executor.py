"""Execute one supported workload for one explicitly selected site."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from heliotelligence.config.settings import settings
from heliotelligence.config.site import SiteConfig, load_sites
from heliotelligence.db.session import get_session_factory
from heliotelligence.engine.pipeline import run_pipeline

log = logging.getLogger(__name__)


class SiteResolutionError(ValueError):
    """Raised when a site slug cannot be resolved unambiguously."""


class UnsupportedWorkloadError(ValueError):
    """Raised when the single-run executor receives an unsupported workload."""


def resolve_site(site_id: str) -> SiteConfig:
    """Resolve exactly one configured site by its stable ``SiteConfig.id`` slug."""
    matches = [
        site
        for site in load_sites(settings.site_config_path)
        if site.id == site_id
    ]
    if not matches:
        raise SiteResolutionError(f"Site '{site_id}' was not found")
    if len(matches) > 1:
        raise SiteResolutionError(
            f"Site '{site_id}' is configured more than once; execution is ambiguous"
        )
    return matches[0]


async def run_workload_once(
    workload: str,
    site_id: str,
    *,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Run one physics invocation for one pre-synchronized configured site.

    The executor owns the database transaction and deliberately calls the
    physics business function directly. It does not use APScheduler or its
    process-local status wrappers.
    """
    current_execution_id = execution_id or str(uuid.uuid4())
    started = time.monotonic()
    log.info(
        "workload execution started workload=%s site_id=%s execution_id=%s",
        workload,
        site_id,
        current_execution_id,
    )

    try:
        if workload != "physics":
            raise UnsupportedWorkloadError(
                f"Unsupported workload '{workload}'; only 'physics' is supported"
            )

        site = resolve_site(site_id)
        factory = get_session_factory()
        async with factory() as session:
            try:
                pipeline_result = await run_pipeline(site, session)
                await session.commit()
            except Exception:
                try:
                    await session.rollback()
                except Exception as rollback_exc:
                    log.error(
                        "workload rollback failed workload=%s site_id=%s "
                        "execution_id=%s rollback_error_type=%s",
                        workload,
                        site_id,
                        current_execution_id,
                        type(rollback_exc).__name__,
                    )
                raise
    except Exception as exc:
        log.error(
            "workload execution failed workload=%s site_id=%s execution_id=%s "
            "duration_seconds=%.3f error_type=%s",
            workload,
            site_id,
            current_execution_id,
            time.monotonic() - started,
            type(exc).__name__,
        )
        raise

    result = dict(pipeline_result)
    result["workload"] = workload
    result["execution_id"] = current_execution_id
    log.info(
        "workload execution succeeded workload=%s site_id=%s execution_id=%s "
        "rows_upserted=%s chunks_run=%s duration_seconds=%.3f",
        workload,
        site_id,
        current_execution_id,
        result.get("rows_upserted"),
        result.get("chunks_run"),
        time.monotonic() - started,
    )
    return result
