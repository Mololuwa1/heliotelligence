"""Command-line entrypoint for one-shot Heliotelligence workloads."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from heliotelligence.config.logging_config import configure_application_logging
from heliotelligence.config.settings import settings
from heliotelligence.jobs.executor import run_workload_once

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m heliotelligence.jobs")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    run_parser = subparsers.add_parser("run", help="run one workload once")
    run_parser.add_argument("--workload", required=True)
    run_parser.add_argument("--site-id", required=True)
    return parser


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested workload and return its process exit code."""
    configure_application_logging(settings.log_level)
    args = _build_parser().parse_args(argv)

    try:
        result = asyncio.run(run_workload_once(args.workload, args.site_id))
    except Exception as exc:
        log.error(
            "single-run process failed workload=%s site_id=%s error_type=%s",
            args.workload,
            args.site_id,
            type(exc).__name__,
        )
        return 1

    print(json.dumps(result, default=_json_default, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
