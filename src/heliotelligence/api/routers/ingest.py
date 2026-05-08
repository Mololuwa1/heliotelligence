"""Ingest management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from heliotelligence.collectors.scheduler import get_job_status

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


@router.get("/status")
async def ingest_status() -> dict[str, dict[str, Any]]:
    """Return last run time and success status for each scheduled ingest job.

    Response shape (one entry per registered job):

    .. code-block:: json

        {
          "solcast:site-a": {
            "last_run": "2024-01-01T12:00:00+00:00",
            "last_success": "2024-01-01T12:00:00+00:00",
            "last_error": null,
            "rows_upserted": 24
          },
          "scada_csv:site-a": {
            "last_run": "2024-01-01T12:05:00+00:00",
            "last_success": "2024-01-01T12:05:00+00:00",
            "last_error": null,
            "files_processed": 2
          }
        }
    """
    return get_job_status()
