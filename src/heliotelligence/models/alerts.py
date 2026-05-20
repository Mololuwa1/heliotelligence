"""Alert ORM model for persistent alerting engine."""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Double, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from heliotelligence.db.base import Base


class Alert(Base):
    """Persisted alert record — one row per fired rule per evaluation cycle."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), nullable=False, index=True)
    fired_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)  # 'critical' | 'warning' | 'info'
    metric_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Double, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
