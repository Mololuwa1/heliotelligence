"""Firebase identity and centralized, deny-by-default platform/site authorization.

Only the verified boolean platform_admin custom claim grants global authority.
Normal site access requires an exact uid/site row with a viewer or admin role.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Annotated, Any

import firebase_admin  # type: ignore[import-untyped]
from fastapi import Depends, Header, HTTPException
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.db.session import get_session_factory

log = logging.getLogger(__name__)
_SITE_ROLES = frozenset(("viewer", "admin"))


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


async def get_current_user(authorization: Annotated[str, Header()] = "") -> dict[str, Any]:
    """Verify a Firebase ID token and expose only uid, email and platform_admin."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    id_token = authorization.removeprefix("Bearer ").strip()
    if not id_token:
        raise HTTPException(status_code=401, detail="Empty bearer token")
    try:
        _get_firebase_app()
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception as exc:
        # Verification (including SDK/setup failure) never grants access. Avoid
        # logging token contents or arbitrary exception text from this boundary.
        log.warning("Firebase token verification failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if not isinstance(decoded, dict) or type(decoded.get("uid")) is not str or not decoded["uid"]:
        raise HTTPException(status_code=401, detail="Invalid token identity")
    email = decoded.get("email")
    return {
        "uid": decoded["uid"],
        "email": email if isinstance(email, str) else None,
        "platform_admin": decoded.get("platform_admin") is True,
    }


async def require_platform_admin(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Require explicit global authority from the verified Firebase token."""
    if user.get("platform_admin") is not True:
        raise HTTPException(status_code=403, detail="Platform administrator access required")
    return user


async def _site_role(session: AsyncSession, uid: str, site_id: str) -> object:
    result = await session.execute(
        text("SELECT role FROM user_site_access WHERE uid = :uid AND site_id = :site_id"),
        {"uid": uid, "site_id": site_id},
    )
    role: object = result.scalar_one_or_none()
    return role


async def authorize_site_access(
    site_id: str,
    user: dict[str, Any],
    *,
    require_admin: bool = False,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Authorize an exact site, optionally within a resource lookup's transaction.

    The session form lets indirect resources (alerts) authorize their canonical
    site before mutation. No role, UID or site ID is normalized or inferred.
    """
    if user.get("platform_admin") is True:
        return user
    if session is not None:
        role = await _site_role(session, user["uid"], site_id)
    else:
        async with get_session_factory()() as owned_session:
            role = await _site_role(owned_session, user["uid"], site_id)
    if type(role) is not str or role not in _SITE_ROLES or (require_admin and role != "admin"):
        raise HTTPException(
            status_code=403,
            detail="Site administrator access required"
            if require_admin
            else "Site access required",
        )
    return user


async def require_site_access(
    site_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Allow exact viewer/admin membership or explicit platform administration."""
    return await authorize_site_access(site_id, user)


async def require_site_admin(
    site_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Allow site admin membership or explicit platform administration."""
    return await authorize_site_access(site_id, user, require_admin=True)


async def get_user_sites(user: Annotated[dict[str, Any], Depends(get_current_user)]) -> list[str]:
    """List valid memberships; platform administrators intentionally see all sites."""
    async with get_session_factory()() as session:
        if user.get("platform_admin") is True:
            result = await session.execute(
                text("SELECT CAST(site_id AS TEXT) FROM sites ORDER BY site_id")
            )
            return [row[0] for row in result.fetchall()]
        result = await session.execute(
            text("SELECT site_id, role FROM user_site_access WHERE uid = :uid ORDER BY site_id"),
            {"uid": user["uid"]},
        )
        return [
            row[0] for row in result.fetchall() if type(row[1]) is str and row[1] in _SITE_ROLES
        ]
