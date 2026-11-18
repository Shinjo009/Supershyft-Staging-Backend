"""Read-only access to nginx API traffic rollup JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import settings
from core.exceptions import AppError


class ApiTrafficRepository:
    def __init__(self, json_path: str | None = None) -> None:
        self._json_path = json_path or settings.API_TRAFFIC_JSON_PATH

    def _ensure_available(self) -> Path:
        path = Path(self._json_path)
        if not path.is_file():
            raise AppError(
                status_code=503,
                error_code="SERVICE_UNAVAILABLE",
                message=(
                    "API traffic summary is not available. "
                    f"Expected file at {self._json_path}."
                ),
            )
        return path

    def load_sync(self) -> dict[str, Any]:
        path = self._ensure_available()
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                status_code=503,
                error_code="SERVICE_UNAVAILABLE",
                message=f"API traffic summary could not be read: {exc}",
            ) from exc
        if not isinstance(data, dict):
            raise AppError(
                status_code=503,
                error_code="SERVICE_UNAVAILABLE",
                message="API traffic summary file has an invalid format.",
            )
        return data