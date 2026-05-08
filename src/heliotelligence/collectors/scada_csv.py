"""SCADA CSV drop-folder collector.

Watches a configurable directory for new CSV exports, ingests each file,
then routes it to:

  archive/   — successful ingestion
  failed/    — parse / upsert error (file kept for manual inspection)

DB-driven column map
────────────────────
If the ``instrument_column_map`` view exists the collector queries it for
the current site and logs the available field→column entries.  The view is
informational at this stage; physical column routing is handled by
ingest.normaliser which is the authoritative mapping layer.  If the view
is absent or empty the fallback is silent and does not block ingestion.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.config.site import SiteConfig
from heliotelligence.db.session import get_session_factory
from heliotelligence.ingest.csv_parser import parse_csv
from heliotelligence.ingest.upsert import upsert_all
from heliotelligence.quality.flags import apply_all_flags

log = logging.getLogger(__name__)


class ScadaCsvCollector:
    """Polls a drop folder and ingests any pending CSV files for *site*."""

    def __init__(self, site: SiteConfig) -> None:
        self.site = site

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def poll(self) -> int:
        """Scan the drop folder and ingest every pending CSV.

        Returns the number of files successfully processed.
        """
        if self.site.scada_csv_dir is None:
            return 0

        drop_dir = Path(self.site.scada_csv_dir)
        if not drop_dir.exists():
            log.debug("SCADA drop folder does not exist yet: %s", drop_dir)
            return 0

        archive_dir = drop_dir / "archive"
        failed_dir = drop_dir / "failed"
        archive_dir.mkdir(parents=True, exist_ok=True)
        failed_dir.mkdir(parents=True, exist_ok=True)

        csv_files = sorted(drop_dir.glob("*.csv"))
        if not csv_files:
            log.debug("No CSV files in %s", drop_dir)
            return 0

        factory = get_session_factory()

        # Load and log DB-driven column mappings (best-effort)
        try:
            async with factory() as session:
                col_map = await _load_column_map(session, str(uuid.uuid5(uuid.NAMESPACE_DNS, self.site.id)))
        except Exception:
            log.warning(
                "Could not load instrument_column_map for site %s — proceeding without it",
                self.site.id,
                exc_info=True,
            )
            col_map = {}
        if col_map:
            log.debug(
                "instrument_column_map: %d field mapping(s) for site %s",
                len(col_map), self.site.id,
            )

        processed = 0
        for csv_path in csv_files:
            success = await self._ingest_file(csv_path, factory)
            dest_dir = archive_dir if success else failed_dir
            _move_file(csv_path, dest_dir)
            if success:
                processed += 1

        return processed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ingest_file(self, csv_path: Path, factory) -> bool:
        """Parse, flag, and upsert one CSV file.

        Returns True on success, False on any error (after logging).
        """
        log.info("Ingesting %s for site %s", csv_path.name, self.site.id)
        site_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, self.site.id))
        try:
            weather, meter, inverters, strings = parse_csv(
                csv_path, site_id=site_uuid, site_name=self.site.name
            )
            weather, meter, inverters, strings = apply_all_flags(
                weather, meter, inverters, strings
            )
            async with factory() as session:
                await upsert_all(session, weather, meter, inverters, strings)
        except Exception:
            log.exception("Failed to ingest %s", csv_path.name)
            return False
        return True


# ---------------------------------------------------------------------------
# DB-driven column map (best-effort; non-blocking on missing view)
# ---------------------------------------------------------------------------

async def _load_column_map(session: AsyncSession, site_id: str) -> dict[str, str]:
    """Query ``instrument_column_map`` view for *site_id*.

    Returns an empty dict when the view does not exist or has no rows for
    the site — expected in environments where the view has not been created.
    The session is rolled back on error so the caller's transaction is clean.
    """
    try:
        result = await session.execute(
            text(
                "SELECT scada_field, db_column "
                "FROM instrument_column_map "
                "WHERE site_id = :site_id"
            ),
            {"site_id": site_id},
        )
        return {row.scada_field: row.db_column for row in result}
    except Exception as exc:
        log.warning(
            "instrument_column_map not available for site %s — %s",
            site_id, exc,
            exc_info=True,
        )
        await session.rollback()
        return {}


# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------

def _move_file(src: Path, dest_dir: Path) -> None:
    dest = dest_dir / src.name
    try:
        shutil.move(str(src), str(dest))
        log.info("Moved %s → %s/", src.name, dest_dir.name)
    except OSError:
        log.exception("Could not move %s to %s", src, dest_dir)
