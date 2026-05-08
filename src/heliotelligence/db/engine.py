"""Backward-compatibility shim — canonical implementation is in db/session.py."""

from heliotelligence.db.session import get_db, get_engine, get_session_factory

# app.py imports _get_session_factory by this name
_get_session_factory = get_session_factory

__all__ = ["get_db", "get_engine", "get_session_factory", "_get_session_factory"]
