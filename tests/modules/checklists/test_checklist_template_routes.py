"""Checklist template list includes items_count (admin optimization)."""

from __future__ import annotations

import pytest

from modules.checklists.repository import ChecklistsRepository
from tests.helpers.auth import seed_employee, employee_auth_header


@pytest.mark.asyncio
async def test_list_checklist_templates_includes_items_count(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8801, role="admin")
    repo = ChecklistsRepository()
    template = await repo.create_template(
        test_db_session,
        name="E2E Template",
        description=None,
        audience="internal",
        created_employee_id=8801,
    )
    await repo.create_template_item(
        test_db_session,
        template_id=template.template_id,
        title="Step one",
        description=None,
        display_order=1,
    )
    await repo.create_template_item(
        test_db_session,
        template_id=template.template_id,
        title="Step two",
        description=None,
        display_order=2,
    )
    await test_db_session.commit()

    list_res = await async_client.get(
        "/checklist-templates",
        headers=employee_auth_header(8801),
    )
    assert list_res.status_code == 200
    rows = list_res.json()["data"]
    row = next(r for r in rows if r["template_id"] == template.template_id)
    assert row["items_count"] == 2

    detail_res = await async_client.get(
        f"/checklist-templates/{template.template_id}",
        headers=employee_auth_header(8801),
    )
    assert detail_res.status_code == 200
    assert len(detail_res.json()["data"]["items"]) == row["items_count"]
