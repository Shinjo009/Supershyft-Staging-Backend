"""Staff auth request schemas."""

from __future__ import annotations

from pydantic import BaseModel

from common.validation import PhoneStr


class EligibleRolesRequest(BaseModel):
    phone: PhoneStr
