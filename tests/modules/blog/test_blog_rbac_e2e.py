"""E2E RBAC for the blog dashboard (current model: author partner + full admin only)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from modules.blog.models import Author
from modules.employee.models import EmployeeRole
from tests.helpers.auth import (
    employee_auth_header,
    partner_auth_header,
    seed_employee,
    seed_partner,
    user_auth_header,
)
from tests.modules.employee.test_inferior_admin_permissions import _seed_employee as seed_inferior_admin


def _paragraph_post(category_id: int, *, title: str = "RBAC story", status: str = "draft") -> dict:
    return {
        "title": title,
        "content": [{"tag": "p", "content": "body", "marks": []}],
        "category_id": category_id,
        "status": status,
    }


async def _create_category(async_client, headers: dict[str, str], name: str = "RBAC") -> int:
    response = await async_client.post(
        "/blog/categories",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["category"]["id"]


@pytest.mark.asyncio
async def test_assign_author_role_on_partner_create_links_author_row(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8200, role="admin")

    create = await async_client.post(
        "/partners",
        headers=employee_auth_header(8200),
        json={"name": "Blog Author", "phone": "8200000001", "role": "author"},
    )
    assert create.status_code in {200, 201}, create.text
    partner_id = create.json()["data"]["partner_id"]

    row = (
        await test_db_session.execute(select(Author).where(Author.partner_id == partner_id))
    ).scalar_one_or_none()
    assert row is not None
    assert row.partner_id == partner_id


@pytest.mark.asyncio
async def test_promote_phlebo_to_author_can_write_posts(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8201, role="admin")
    phlebo = await seed_partner(
        test_db_session,
        partner_id=8202,
        role="phlebo",
        phone="8202000001",
        name="Was Phlebo",
    )

    updated = await async_client.put(
        f"/partners/{phlebo.partner_id}",
        headers=employee_auth_header(8201),
        json={
            "name": "Now Author",
            "phone": phlebo.phone,
            "role": "author",
        },
    )
    assert updated.status_code == 200, updated.text

    author_row = (
        await test_db_session.execute(
            select(Author).where(Author.partner_id == phlebo.partner_id)
        )
    ).scalar_one_or_none()
    assert author_row is not None

    headers = partner_auth_header(phlebo.partner_id)
    category_id = await _create_category(async_client, headers, name="Promoted")
    post = await async_client.post(
        "/blog/posts",
        headers=headers,
        json=_paragraph_post(category_id, title="After promotion"),
    )
    assert post.status_code == 201, post.text


@pytest.mark.asyncio
async def test_inferior_admin_without_partners_grant_cannot_create_author(async_client, test_db_session):
    await seed_inferior_admin(
        test_db_session,
        employee_id=8210,
        role=EmployeeRole.inferior_admin,
        grants={"users": (True, True)},
    )

    create = await async_client.post(
        "/partners",
        headers=employee_auth_header(8210),
        json={"name": "Blocked Author", "phone": "8210000001", "role": "author"},
    )
    assert create.status_code == 403
    assert create.json()["error_code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_inferior_admin_with_partners_edit_can_create_author_but_not_use_blog(
    async_client, test_db_session,
):
    await seed_inferior_admin(
        test_db_session,
        employee_id=8211,
        role=EmployeeRole.inferior_admin,
        grants={"partners": (True, True)},
    )

    create = await async_client.post(
        "/partners",
        headers=employee_auth_header(8211),
        json={"name": "IA Created Author", "phone": "8211000001", "role": "author"},
    )
    assert create.status_code in {200, 201}, create.text

    blog_write = await async_client.post(
        "/blog/posts",
        headers=employee_auth_header(8211),
        json=_paragraph_post(1, title="Should fail"),
    )
    assert blog_write.status_code == 403
    assert blog_write.json()["error_code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_blog_rbac_access_matrix(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8220, role="admin")
    author = await seed_partner(
        test_db_session,
        partner_id=8221,
        role="author",
        phone="8221000001",
        name="Primary Author",
    )
    other_author = await seed_partner(
        test_db_session,
        partner_id=8222,
        role="author",
        phone="8222000001",
        name="Other Author",
    )
    phlebo = await seed_partner(test_db_session, partner_id=8223, role="phlebo", phone="8223000001")
    expert = await seed_partner(test_db_session, partner_id=8224, role="expert", phone="8224000001")
    org_mgr = await seed_partner(
        test_db_session,
        partner_id=8225,
        role="organization_manager",
        phone="8225000001",
    )
    inactive_author = await seed_partner(
        test_db_session,
        partner_id=8226,
        role="author",
        phone="8226000001",
        status="inactive",
    )
    await seed_inferior_admin(
        test_db_session,
        employee_id=8227,
        role=EmployeeRole.inferior_admin,
        grants={"users": (True, True), "partners": (True, True)},
    )

    # Ensure author rows for seeded author partners (create flow also does this).
    for pid in (author.partner_id, other_author.partner_id, inactive_author.partner_id):
        test_db_session.add(Author(partner_id=pid))
    await test_db_session.commit()

    author_headers = partner_auth_header(author.partner_id)
    category_id = await _create_category(async_client, author_headers, name="Matrix")

    draft = await async_client.post(
        "/blog/posts",
        headers=author_headers,
        json=_paragraph_post(category_id, title="Draft matrix", status="draft"),
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["data"]["id"]

    published = await async_client.post(
        "/blog/posts",
        headers=author_headers,
        json=_paragraph_post(category_id, title="Published matrix", status="published"),
    )
    assert published.status_code == 201, published.text
    published_id = published.json()["data"]["id"]

    assert (await async_client.get(f"/blog/posts/{draft_id}")).status_code == 404
    pub_detail = await async_client.get(f"/blog/posts/{published_id}")
    assert pub_detail.status_code == 200
    assert pub_detail.json()["data"]["post"]["title"] == "Published matrix"

    for headers in (None, user_auth_header(1)):
        post_kwargs = {"json": _paragraph_post(category_id)}
        if headers:
            post_kwargs["headers"] = headers
        unauth_post = await async_client.post("/blog/posts", **post_kwargs)
        assert unauth_post.status_code in {401, 403}

    for denied_headers in (
        partner_auth_header(phlebo.partner_id),
        partner_auth_header(expert.partner_id),
        partner_auth_header(org_mgr.partner_id),
        partner_auth_header(inactive_author.partner_id),
        employee_auth_header(8227),
        user_auth_header(1),
    ):
        assert (
            await async_client.post(
                "/blog/posts",
                headers=denied_headers,
                json=_paragraph_post(category_id),
            )
        ).status_code in {401, 403}
        assert (
            await async_client.get("/blog/categories", headers=denied_headers)
        ).status_code in {401, 403}

    admin_headers = employee_auth_header(8220)
    admin_list = await async_client.get("/blog/posts", headers=admin_headers)
    assert admin_list.status_code == 200
    titles = {row["title"] for row in admin_list.json()["data"]["posts"]}
    assert "Draft matrix" in titles
    assert "Published matrix" in titles

    author_list = await async_client.get("/blog/posts", headers=author_headers)
    assert author_list.status_code == 200
    assert "Draft matrix" in {row["title"] for row in author_list.json()["data"]["posts"]}

    own_update = await async_client.put(
        f"/blog/posts/{draft_id}",
        headers=author_headers,
        json=_paragraph_post(category_id, title="Author edited", status="draft"),
    )
    assert own_update.status_code == 200

    blocked = await async_client.put(
        f"/blog/posts/{draft_id}",
        headers=partner_auth_header(other_author.partner_id),
        json=_paragraph_post(category_id, title="Hijack", status="published"),
    )
    assert blocked.status_code == 403

    admin_update = await async_client.put(
        f"/blog/posts/{draft_id}",
        headers=admin_headers,
        json=_paragraph_post(category_id, title="Admin edited", status="draft"),
    )
    assert admin_update.status_code == 200

    deleted = await async_client.delete(f"/blog/posts/{draft_id}", headers=author_headers)
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_author_partner_cannot_access_admin_employee_surfaces(async_client, test_db_session):
    author = await seed_partner(
        test_db_session,
        partner_id=8230,
        role="author",
        phone="8230000001",
    )
    test_db_session.add(Author(partner_id=author.partner_id))
    await test_db_session.commit()

    headers = partner_auth_header(author.partner_id)
    for path in ("/partners", "/employees", "/engagements"):
        response = await async_client.get(path, headers=headers)
        assert response.status_code in {401, 403}, f"{path} returned {response.status_code}"
