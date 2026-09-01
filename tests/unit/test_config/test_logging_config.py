"""Tests for application-specific logging configuration."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from io import StringIO
from typing import NamedTuple

import pytest
import uvicorn

from heliotelligence.config.logging_config import configure_application_logging


_LOGGER_NAMES = (
    "",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "heliotelligence",
    "heliotelligence.api.app",
    "heliotelligence.collectors.scheduler",
)


class _LoggerState(NamedTuple):
    level: int
    handlers: list[logging.Handler]
    propagate: bool
    disabled: bool


def _snapshot(logger: logging.Logger) -> _LoggerState:
    return _LoggerState(
        level=logger.level,
        handlers=list(logger.handlers),
        propagate=logger.propagate,
        disabled=logger.disabled,
    )


@pytest.fixture(autouse=True)
def isolate_logging_state() -> Iterator[None]:
    states = {name: _snapshot(logging.getLogger(name)) for name in _LOGGER_NAMES}
    application_logger = logging.getLogger("heliotelligence")
    application_logger.handlers = []
    application_logger.setLevel(logging.NOTSET)
    application_logger.propagate = True

    yield

    for name, state in states.items():
        logger = logging.getLogger(name)
        logger.handlers = state.handlers
        logger.setLevel(state.level)
        logger.propagate = state.propagate
        logger.disabled = state.disabled


def test_coexists_with_uvicorn_without_changing_its_logging() -> None:
    uvicorn.Config("diagnostic:app", log_level="info").configure_logging()
    protected_loggers = {
        name: _snapshot(logging.getLogger(name))
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    }

    configure_application_logging("INFO")

    assert logging.getLogger("heliotelligence.api.app").isEnabledFor(logging.INFO)
    assert logging.getLogger().getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("uvicorn").isEnabledFor(logging.INFO)
    for name, state in protected_loggers.items():
        assert _snapshot(logging.getLogger(name)) == state


def test_info_message_is_emitted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_application_logging("INFO")

    logging.getLogger("heliotelligence.api.app").info("test message")

    assert "INFO heliotelligence.api.app: test message" in capsys.readouterr().err


def test_repeated_configuration_emits_exactly_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_application_logging("INFO")
    configure_application_logging("INFO")

    logging.getLogger("heliotelligence.api.app").info("exactly once")

    assert capsys.readouterr().err.count("exactly once") == 1


def test_existing_application_handler_is_preserved_without_duplication() -> None:
    application_logger = logging.getLogger("heliotelligence")
    stream = StringIO()
    external_handler = logging.StreamHandler(stream)
    external_formatter = logging.Formatter("external %(message)s")
    external_handler.setFormatter(external_formatter)
    application_logger.addHandler(external_handler)
    initial_handler_count = len(application_logger.handlers)
    protected_loggers = {
        name: _snapshot(logging.getLogger(name))
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    }

    configure_application_logging("INFO")

    assert application_logger.handlers == [external_handler]
    assert len(application_logger.handlers) == initial_handler_count
    assert external_handler.formatter is external_formatter
    assert external_handler.stream is stream
    assert logging.getLogger("heliotelligence.api.app").isEnabledFor(logging.INFO)
    logging.getLogger("heliotelligence.api.app").info("external message")
    assert stream.getvalue().count("external message") == 1
    for name, state in protected_loggers.items():
        assert _snapshot(logging.getLogger(name)) == state


def test_log_level_can_be_reconfigured(capsys: pytest.CaptureFixture[str]) -> None:
    logger = logging.getLogger("heliotelligence.api.app")
    configure_application_logging("WARNING")

    logger.info("hidden info")
    logger.warning("visible warning")

    first_output = capsys.readouterr().err
    assert "hidden info" not in first_output
    assert "WARNING heliotelligence.api.app: visible warning" in first_output

    configure_application_logging("INFO")
    logger.info("visible info")

    assert "INFO heliotelligence.api.app: visible info" in capsys.readouterr().err


def test_child_namespace_inherits_application_logging(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_application_logging("INFO")

    logging.getLogger("heliotelligence.collectors.scheduler").info("child message")

    assert (
        "INFO heliotelligence.collectors.scheduler: child message"
        in capsys.readouterr().err
    )


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_standard_logging_level_names_are_supported(level: str) -> None:
    configure_application_logging(level)

    assert logging.getLogger("heliotelligence").level == logging.getLevelNamesMapping()[level]


def test_invalid_logging_level_uses_standard_validation() -> None:
    with pytest.raises(ValueError, match="Unknown level"):
        configure_application_logging("VERBOSE")
