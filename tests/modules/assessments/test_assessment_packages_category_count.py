"""Assessment package list category_count."""

from __future__ import annotations

import pytest

from modules.assessments.models import AssessmentPackage, AssessmentPackageCategory
from modules.employee.models import Employee
from modules.questionnaire.models import QuestionnaireCategory
from modules.users.models import User
from tests.helpers.auth import employee_auth_header


async def _seed_admin(test_db_session, employee_id: int):
    test_db_session.add(User(user_id=9000 + employee_id, age=30, phone=f"{employee_id}0000000000", status="active"))
    await test_db_session.flush()
    test_db_session.add(
        Employee(
            employee_id=employee_id,
            name=f"Employee {employee_id}",
            phone=str(employee_id).zfill(10)[:15],
            email=f"employee{employee_id}@test.example",
            role="admin",
            status="active",
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_list_assessment_packages_includes_category_count(async_client, test_db_session):
    await _seed_admin(test_db_session, 77)
    pkg = AssessmentPackage(
        package_id=77001,
        package_code="CATCNT",
        display_name="Cat count pkg",
        status="active",
    )
    cat = QuestionnaireCategory(
        category_id=77001,
        category_key="catcnt",
        display_name="Cat",
        status="active",
    )
    test_db_session.add_all([pkg, cat])
    await test_db_session.flush()
    test_db_session.add(
        AssessmentPackageCategory(package_id=pkg.package_id, category_id=cat.category_id, display_order=1)
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/assessment-packages",
        headers=employee_auth_header(77),
    )
    assert response.status_code == 200
    row = next(item for item in response.json()["data"] if item["package_id"] == pkg.package_id)
    assert row["category_count"] == 1
