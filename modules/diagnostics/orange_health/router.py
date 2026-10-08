"""Orange Health admin HTTP routes (static catalog, no live API)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from common.responses import success_response
from modules.diagnostics.healthians.schemas import (
    HealthiansConstituent,
    HealthiansConstituentsResponse,
)
from modules.diagnostics.orange_health.catalog import load_d2c_tests
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext

router = APIRouter(tags=["diagnostics-orange-health"])


@router.get("/diagnostics/orange-health/constituents")
async def get_orange_health_constituents(
    employee: EmployeeContext = Depends(get_current_employee),
):
    constituents = [
        HealthiansConstituent(id=item["id"], name=item["name"])
        for item in load_d2c_tests()
    ]
    resp = HealthiansConstituentsResponse(constituents=constituents, package_name=None)
    return success_response(resp.model_dump())
