"""Server health host-state persistence (latest metrics + CPU alert latch)."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, func

from db.base import Base


class ServerHealthHostState(Base):
    """One row per hostname reported by health_check.sh."""

    __tablename__ = "server_health_host_state"

    hostname = Column(String(255), primary_key=True)
    cpu_usage = Column(Float, nullable=False)
    memory_usage = Column(Float, nullable=False)
    storage_usage = Column(Float, nullable=False)
    load_1m = Column(Float, nullable=False)
    cores = Column(Integer, nullable=False)
    reported_at = Column(DateTime(timezone=True), nullable=False)
    is_alerting = Column(Boolean, nullable=False, default=False, server_default="false")
    last_alerted_at = Column(DateTime(timezone=True), nullable=True)
    last_recovered_at = Column(DateTime(timezone=True), nullable=True)
    last_alert_notification_id = Column(Integer, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
