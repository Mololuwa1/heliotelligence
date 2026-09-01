"""Application-specific logging configuration."""

from __future__ import annotations

import logging


_APPLICATION_LOGGER_NAME = "heliotelligence"
_HANDLER_MARKER = "_heliotelligence_application_handler"
_FORMAT = "%(levelname)s %(name)s: %(message)s"


def configure_application_logging(log_level: str) -> None:
    """Configure the Heliotelligence logger namespace without changing Uvicorn."""
    application_logger = logging.getLogger(_APPLICATION_LOGGER_NAME)
    application_logger.setLevel(log_level.upper())
    application_logger.propagate = False

    for handler in application_logger.handlers:
        if getattr(handler, _HANDLER_MARKER, False):
            return

    if application_logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    setattr(handler, _HANDLER_MARKER, True)
    application_logger.addHandler(handler)
