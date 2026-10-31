"""Alerts API endpoints.

GET  /api/v1/alerts/{site_id}
    Query params:
      unacknowledged_only  bool (default False)
      limit                int (default 100, max 500)

POST /api/v1/alerts/{alert_id}/acknowledge
    Marks the alert as acknowledged.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.api.auth import authorize_site_access, get_current_user, require_site_access
from heliotelligence.db.session import get_db, get_session_factory
from heliotelligence.models.alerts import Alert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("/{site_id}", dependencies=[Depends(require_site_access)])
async def list_alerts(
    site_id: str,
    unacknowledged_only: bool = Query(False, description="Return only unacknowledged alerts"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of alerts to return"),
) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(Alert)
            .where(Alert.site_id == site_id)
            .order_by(Alert.fired_at.desc())
            .limit(limit)
        )
        if unacknowledged_only:
            stmt = stmt.where(Alert.acknowledged.is_(False))

        result = await session.execute(stmt)
        alerts = result.scalars().all()

    return [
        {
            "id": a.id,
            "site_id": a.site_id,
            "fired_at": a.fired_at.isoformat() if a.fired_at else None,
            "rule_name": a.rule_name,
            "severity": a.severity,
            "metric_value": a.metric_value,
            "threshold": a.threshold,
            "message": a.message,
            "acknowledged": a.acknowledged,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        }
        for a in alerts
    ]


async def require_alert_site_admin(
    alert_id: int,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Alert:
    """Resolve the alert's canonical site before checking mutation authority."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert: Alert | None = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    await authorize_site_access(alert.site_id, user, require_admin=True, session=db)
    return alert


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert: Annotated[Alert, Depends(require_alert_site_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    # FastAPI shares the dependency's session; authorization precedes mutation.
    alert.acknowledged = True
    await db.commit()
    await db.refresh(alert)
    return {
        "id": alert.id,
        "acknowledged": alert.acknowledged,
        "rule_name": alert.rule_name,
        "message": alert.message,
    }
