"""Export log models.

Export logs are append-only.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from db.base import Base
from db.column_types import export_type_enum


class ExportLog(Base):
    """SQLAlchemy model for `export_logs` table."""

    __tablename__ = "export_logs"
    __table_args__ = (
        Index("ix_export_logs_created_at", "created_at"),
        Index("ix_export_logs_employee_id", "employee_id"),
    )

    export_log_id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(
        Integer,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason = Column(Text, nullable=False)
    export_type = Column(export_type_enum, nullable=False)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
