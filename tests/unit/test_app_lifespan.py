"""Unit tests for the in-process scheduler lifespan gate."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from heliotelligence.api import app as app_module


def _session_factory() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=context)
    return factory, session


@pytest.mark.parametrize("run_scheduler", [True, False])
async def test_lifespan_gates_scheduler_and_preserves_site_sync(
    monkeypatch: pytest.MonkeyPatch,
    run_scheduler: bool,
) -> None:
    sites = [MagicMock()]
    factory, session = _session_factory()
    scheduler = MagicMock()
    scheduler.get_jobs.return_value = []
    configure_scheduler = MagicMock()
    get_scheduler = MagicMock(return_value=scheduler)
    load_sites = MagicMock(return_value=sites)
    sync_sites = AsyncMock(return_value=1)

    monkeypatch.setattr(app_module.settings, "run_scheduler", run_scheduler)
    monkeypatch.setattr(app_module, "load_sites", load_sites)
    monkeypatch.setattr(app_module, "get_session_factory", MagicMock(return_value=factory))
    monkeypatch.setattr(app_module, "sync_sites", sync_sites)
    monkeypatch.setattr(app_module, "get_scheduler", get_scheduler)
    monkeypatch.setattr(app_module, "configure_scheduler", configure_scheduler)

    async with app_module.lifespan(FastAPI()):
        pass

    load_sites.assert_called_once_with(app_module.settings.site_config_path)
    sync_sites.assert_awaited_once_with(sites, session)
    session.commit.assert_awaited_once_with()

    if run_scheduler:
        get_scheduler.assert_called_once_with()
        configure_scheduler.assert_called_once_with(sites)
        scheduler.start.assert_called_once_with()
        scheduler.shutdown.assert_called_once_with(wait=False)
    else:
        get_scheduler.assert_not_called()
        configure_scheduler.assert_not_called()
        scheduler.start.assert_not_called()
        scheduler.shutdown.assert_not_called()
