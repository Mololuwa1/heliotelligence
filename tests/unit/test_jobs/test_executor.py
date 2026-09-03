"""Tests for the single-run physics executor."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from heliotelligence.config.site import SiteConfig
from heliotelligence.jobs import executor


def _site(site_id: str) -> SiteConfig:
    return SiteConfig(
        id=site_id,
        name=f"Site {site_id}",
        latitude=52.0,
        longitude=1.0,
        timezone="Europe/London",
        capacity_kwp=100.0,
        solcast_resource_id="test-resource",
    )


def _session_factory() -> tuple[MagicMock, AsyncMock, MagicMock]:
    session = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=context), session, context


def test_resolve_site_selects_exact_match_and_ignores_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _site("site-001")
    other = _site("site-002")
    load_sites = MagicMock(return_value=[other, selected])
    path = Path("test-sites.yaml")
    monkeypatch.setattr(executor.settings, "site_config_path", path)
    monkeypatch.setattr(executor, "load_sites", load_sites)

    assert executor.resolve_site("site-001") is selected
    load_sites.assert_called_once_with(path)


def test_resolve_site_rejects_unknown_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executor, "load_sites", MagicMock(return_value=[_site("other")]))

    with pytest.raises(executor.SiteResolutionError, match="Site 'missing' was not found"):
        executor.resolve_site("missing")


def test_resolve_site_rejects_duplicate_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        executor,
        "load_sites",
        MagicMock(return_value=[_site("duplicate"), _site("duplicate")]),
    )

    with pytest.raises(executor.SiteResolutionError, match="execution is ambiguous"):
        executor.resolve_site("duplicate")


async def test_physics_execution_uses_one_site_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _site("site-001")
    other = _site("site-002")
    factory, session, context = _session_factory()
    pipeline_result = {
        "site_id": "site-001",
        "rows_upserted": 12,
        "chunks_run": 2,
        "start_time": None,
        "end_time": None,
    }
    run_pipeline = AsyncMock(return_value=pipeline_result)
    monkeypatch.setattr(executor, "load_sites", MagicMock(return_value=[other, selected]))
    get_session_factory = MagicMock(return_value=factory)
    monkeypatch.setattr(executor, "get_session_factory", get_session_factory)
    monkeypatch.setattr(executor, "run_pipeline", run_pipeline)

    result = await executor.run_workload_once(
        "physics", "site-001", execution_id="execution-1"
    )

    run_pipeline.assert_awaited_once_with(selected, session)
    get_session_factory.assert_called_once_with()
    factory.assert_called_once_with()
    context.__aenter__.assert_awaited_once_with()
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    assert result == {
        **pipeline_result,
        "workload": "physics",
        "execution_id": "execution-1",
    }


async def test_physics_execution_rolls_back_and_propagates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _site("site-001")
    factory, session, _ = _session_factory()
    failure = RuntimeError("physics failed")
    monkeypatch.setattr(executor, "load_sites", MagicMock(return_value=[selected]))
    monkeypatch.setattr(executor, "get_session_factory", MagicMock(return_value=factory))
    monkeypatch.setattr(executor, "run_pipeline", AsyncMock(side_effect=failure))

    with pytest.raises(RuntimeError) as caught:
        await executor.run_workload_once("physics", "site-001")

    assert caught.value is failure
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()


async def test_rollback_failure_does_not_replace_original_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _site("site-001")
    factory, session, _ = _session_factory()
    original_failure = RuntimeError("physics failed")
    rollback_failure = OSError("rollback failed")
    session.rollback.side_effect = rollback_failure
    monkeypatch.setattr(executor, "load_sites", MagicMock(return_value=[selected]))
    monkeypatch.setattr(executor, "get_session_factory", MagicMock(return_value=factory))
    monkeypatch.setattr(executor, "run_pipeline", AsyncMock(side_effect=original_failure))

    with pytest.raises(RuntimeError) as caught:
        await executor.run_workload_once("physics", "site-001")

    assert caught.value is original_failure
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()


async def test_executor_failure_log_does_not_expose_exception_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    selected = _site("site-001")
    factory, _, _ = _session_factory()
    sensitive_url = "postgresql://user:super-secret-password@example/db"
    monkeypatch.setattr(executor, "load_sites", MagicMock(return_value=[selected]))
    monkeypatch.setattr(executor, "get_session_factory", MagicMock(return_value=factory))
    monkeypatch.setattr(
        executor,
        "run_pipeline",
        AsyncMock(side_effect=RuntimeError(sensitive_url)),
    )
    executor.log.addHandler(caplog.handler)
    caplog.set_level(logging.ERROR, logger=executor.log.name)

    try:
        with pytest.raises(RuntimeError):
            await executor.run_workload_once("physics", "site-001")
    finally:
        executor.log.removeHandler(caplog.handler)

    assert "RuntimeError" in caplog.text
    assert "super-secret-password" not in caplog.text
    assert sensitive_url not in caplog.text


async def test_unsupported_workload_fails_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_session_factory = MagicMock()
    monkeypatch.setattr(executor, "get_session_factory", get_session_factory)

    with pytest.raises(executor.UnsupportedWorkloadError, match="only 'physics'"):
        await executor.run_workload_once("alerts", "site-001")

    get_session_factory.assert_not_called()
