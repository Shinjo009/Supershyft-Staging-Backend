"""Blog validation errors raised while normalizing story content."""

from __future__ import annotations

from core.exceptions import AppError


class ApiError(AppError):
    def __init__(self, message: str, status: int = 400):
        code = "NOT_FOUND" if status == 404 else "INVALID_INPUT"
        super().__init__(status_code=status, error_code=code, message=message)
