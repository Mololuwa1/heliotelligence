"""Firebase Authentication dependencies for FastAPI.

Provides:
  - get_current_user   — verifies Firebase ID token, returns uid + email
  - get_admin_user     — same, but also validates X-Admin-Key header
  - get_user_sites     — returns list of site_ids the user can access
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import Depends, Header, HTTPException
from sqlalchemy import text

from heliotelligence.db.session import get_session_factory

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Firebase app initialisation (lazy, singleton)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_firebase_app() -> firebase_admin.App:
    """Initialise (or return cached) Firebase Admin SDK app.

    Looks for FIREBASE_SERVICE_ACCOUNT env var containing JSON credentials.
    Falls back to Application Default Credentials for local dev.
    """
    sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
    sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if sa_json:
        import json
        cred = credentials.Certificate(json.loads(sa_json))
    elif sa_path:
        cred = credentials.Certificate(sa_path)
    else:
        # Local dev: uses gcloud application-default credentials
        cred = credentials.ApplicationDefault()
    return firebase_admin.initialize_app(cred)


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

async def get_current_user(
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Verify Firebase ID token from Authorization: Bearer <token> header.

    Returns a dict with at least: uid, email (may be None for anonymous users).
    Raises 401 if token is missing or invalid.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    id_token = authorization.removeprefix("Bearer ").strip()
    if not id_token:
        raise HTTPException(status_code=401, detail="Empty bearer token")

    try:
        _get_firebase_app()  # ensure app is initialised
        decoded = firebase_auth.verify_id_token(id_token)
    except firebase_admin.exceptions.FirebaseError as exc:
        log.warning("Firebase token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    return {"uid": decoded["uid"], "email": decoded.get("email")}


async def get_admin_user(
    user: dict[str, Any] = Depends(get_current_user),
    x_admin_key: str = Header(default=""),
) -> dict[str, Any]:
    """Require both a valid Firebase token AND the admin API key."""
    expected = os.environ.get("ADMIN_API_KEY", "")
    if not expected or x_admin_key != expected:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ---------------------------------------------------------------------------
# Site access query
# ---------------------------------------------------------------------------

async def get_user_sites(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[str]:
    """Return list of site_ids the current user has access to."""
    uid = user["uid"]
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("SELECT site_id FROM user_site_access WHERE uid = :uid"),
            {"uid": uid},
        )
        return [row[0] for row in result.fetchall()]
