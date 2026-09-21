"""Export log models.

Export logs are append-only.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from db.base import Base


class ExportLog(Base):
    """SQLAlchemy model for `export_logs` table."""

    __tablename__ = "export_logs"
    __table_args__ = (
        CheckConstraint(
            "employee_id IS NOT NULL OR partner_id IS NOT NULL",
            name="ck_export_logs_actor",
        ),
        Index("ix_export_logs_created_at", "created_at"),
        Index("ix_export_logs_employee_id", "employee_id"),
    )

    export_log_id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(
        Integer,
        ForeignKey("employee.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    partner_id = Column(
        Integer,
        ForeignKey("partners.partner_id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_name = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    export_type = Column(String(64), nullable=False)
    export_format = Column(String(16), nullable=False)
    source_kind = Column(String(32), nullable=False)
    source_id = Column(String(64), nullable=True)
    row_count = Column(Integer, nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
