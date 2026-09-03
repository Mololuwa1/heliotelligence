"""Tests for the one-shot jobs CLI."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from heliotelligence.collectors import scheduler as scheduler_module
from heliotelligence.jobs import __main__ as cli
from heliotelligence.jobs import executor
from heliotelligence.jobs.executor import SiteResolutionError, UnsupportedWorkloadError


def test_success_returns_zero_and_serializes_datetimes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = {
        "site_id": "site-001",
        "rows_upserted": 4,
        "chunks_run": 1,
        "start_time": datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        "end_time": datetime(2026, 1, 2, 4, 4, tzinfo=UTC),
        "workload": "physics",
        "execution_id": "execution-1",
    }
    run_once = AsyncMock(return_value=result)
    monkeypatch.setattr(cli, "run_workload_once", run_once)

    exit_code = cli.main(["run", "--workload", "physics", "--site-id", "site-001"])

    assert exit_code == 0
    run_once.assert_awaited_once_with("physics", "site-001")
    assert json.loads(capsys.readouterr().out) == {
        **result,
        "start_time": "2026-01-02T03:04:00+00:00",
        "end_time": "2026-01-02T04:04:00+00:00",
    }


@pytest.mark.parametrize(
    ("failure", "workload"),
    [
        (SiteResolutionError("missing site"), "physics"),
        (UnsupportedWorkloadError("unsupported"), "alerts"),
        (RuntimeError("execution failed"), "physics"),
    ],
)
def test_failure_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    workload: str,
) -> None:
    monkeypatch.setattr(cli, "run_workload_once", AsyncMock(side_effect=failure))

    assert cli.main(["run", "--workload", workload, "--site-id", "site-001"]) == 1


def test_cli_failure_log_does_not_expose_exception_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_url = "postgresql://user:super-secret-password@example/db"
    monkeypatch.setattr(
        cli,
        "run_workload_once",
        AsyncMock(side_effect=RuntimeError(sensitive_url)),
    )
    cli.log.addHandler(caplog.handler)
    caplog.set_level(logging.ERROR, logger=cli.log.name)

    try:
        exit_code = cli.main(
            ["run", "--workload", "physics", "--site-id", "site-001"]
        )
    finally:
        cli.log.removeHandler(caplog.handler)

    assert exit_code == 1
    assert "RuntimeError" in caplog.text
    assert "super-secret-password" not in caplog.text
    assert sensitive_url not in caplog.text


def test_cli_does_not_start_or_configure_apscheduler(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_scheduler = MagicMock()
    configure_scheduler = MagicMock()
    selected = MagicMock()
    selected.id = "site-001"
    session = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=context)
    monkeypatch.setattr(scheduler_module, "get_scheduler", get_scheduler)
    monkeypatch.setattr(scheduler_module, "configure_scheduler", configure_scheduler)
    monkeypatch.setattr(executor, "load_sites", MagicMock(return_value=[selected]))
    monkeypatch.setattr(executor, "get_session_factory", MagicMock(return_value=factory))
    run_pipeline = AsyncMock(
        return_value={
            "site_id": "site-001",
            "rows_upserted": 0,
            "chunks_run": 0,
            "start_time": None,
            "end_time": None,
        }
    )
    monkeypatch.setattr(executor, "run_pipeline", run_pipeline)

    assert cli.main(["run", "--workload", "physics", "--site-id", "site-001"]) == 0
    run_pipeline.assert_awaited_once_with(selected, session)
    get_scheduler.assert_not_called()
    configure_scheduler.assert_not_called()
    assert scheduler_module.scheduler.running is False
    capsys.readouterr()
