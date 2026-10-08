"""Dependencies for export log routes."""

from __future__ import annotations

from modules.export_logs.repository import ExportLogsRepository
from modules.export_logs.service import ExportLogsService


def get_export_logs_service() -> ExportLogsService:
    return ExportLogsService(ExportLogsRepository())
