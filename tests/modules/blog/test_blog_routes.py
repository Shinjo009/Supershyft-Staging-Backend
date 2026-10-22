"""Author blog dashboard access and shared post list."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from modules.blog.models import Author
from modules.employee.models import Employee, EmployeeRole
from tests.helpers.auth import employee_auth_header, partner_auth_header, seed_employee, seed_partner


@pytest.mark.asyncio
async def test_create_author_partner_links_author_row(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8101, role="admin")

    create = await async_client.post(
        "/partners",
        headers=employee_auth_header(8101),
        json={"name": "Ada Author", "phone": "8101000001", "role": "author"},
    )
    assert create.status_code in {200, 201}, create.text
    partner_id = create.json()["data"]["partner_id"]

    row = (
        await test_db_session.execute(select(Author).where(Author.partner_id == partner_id))
    ).scalar_one_or_none()
    assert row is not None
    assert row.partner_id == partner_id


@pytest.mark.asyncio
async def test_blog_dashboard_auth_and_own_post_writes(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8102, role="admin")
    phlebo = await seed_partner(
        test_db_session,
        partner_id=8103,
        role="phlebo",
        phone="8103000001",
        name="Phlebo",
    )
    first = await async_client.post(
        "/partners",
        headers=employee_auth_header(8102),
        json={"name": "Author One", "phone": "8102000001", "role": "author"},
    )
    second = await async_client.post(
        "/partners",
        headers=employee_auth_header(8102),
        json={"name": "Author Two", "phone": "8102000002", "role": "author"},
    )
    assert first.status_code in {200, 201}, first.text
    assert second.status_code in {200, 201}, second.text
    first_id = first.json()["data"]["partner_id"]
    second_id = second.json()["data"]["partner_id"]

    public_list = await async_client.get("/blog/posts")
    assert public_list.status_code == 200, public_list.text

    denied_categories = await async_client.get(
        "/blog/categories", headers=partner_auth_header(phlebo.partner_id)
    )
    assert denied_categories.status_code == 403

    category = await async_client.post(
        "/blog/categories",
        headers=partner_auth_header(first_id),
        json={"name": "Nutrition"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["data"]["category"]["id"]

    created = await async_client.post(
        "/blog/posts",
        headers=partner_auth_header(first_id),
        json={
            "title": "Shared story",
            "content": [{"tag": "p", "content": "Hello from the dashboard", "marks": []}],
            "category_id": category_id,
            "status": "draft",
            "focus_keyword": ["AI", "personal growth"],
        },
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["data"]["id"]

    public_draft = await async_client.get(f"/blog/posts/{post_id}")
    assert public_draft.status_code == 404

    listed = await async_client.get("/blog/posts", headers=partner_auth_header(second_id))
    assert listed.status_code == 200, listed.text
    titles = [row["title"] for row in listed.json()["data"]["posts"]]
    assert "Shared story" in titles

    blocked = await async_client.put(
        f"/blog/posts/{post_id}",
        headers=partner_auth_header(second_id),
        json={
            "title": "Edited by the other author",
            "content": [{"tag": "p", "content": "Still the same byline", "marks": []}],
            "category_id": category_id,
            "status": "published",
        },
    )
    assert blocked.status_code == 403, blocked.text

    updated = await async_client.put(
        f"/blog/posts/{post_id}",
        headers=partner_auth_header(first_id),
        json={
            "title": "Owned story",
            "content": [{"tag": "p", "content": "Published by owner", "marks": []}],
            "category_id": category_id,
            "status": "published",
            "focus_keyword": "AI, small habits",
        },
    )
    assert updated.status_code == 200, updated.text

    public_detail = await async_client.get(f"/blog/posts/{post_id}")
    assert public_detail.status_code == 200, public_detail.text
    post = public_detail.json()["data"]["post"]
    assert post["title"] == "Owned story"
    colliding_admin = (
        await test_db_session.execute(select(Employee).where(Employee.employee_id == first_id))
    ).scalar_one_or_none()
    admin_role = colliding_admin.role if colliding_admin is not None else None
    admin_role_text = admin_role.value if isinstance(admin_role, EmployeeRole) else str(admin_role or "")
    if colliding_admin is not None and admin_role_text == EmployeeRole.admin.value:
        assert post["author_name"] == (colliding_admin.name or "").strip()
    else:
        assert post["author_name"] == "Author One"
    assert post["status"] == "published"
    assert post["focus_keyword"] == "AI, small habits"

    admin_update = await async_client.put(
        f"/blog/posts/{post_id}",
        headers=employee_auth_header(8102),
        json={
            "title": "Admin touched",
            "content": [{"tag": "p", "content": "Admin can edit any", "marks": []}],
            "category_id": category_id,
            "status": "published",
        },
    )
    assert admin_update.status_code == 200, admin_update.text


@pytest.mark.asyncio
async def test_admin_writes_json_content_and_string_content_is_rejected(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8104, role="admin", name="Admin Writer")
    headers = employee_auth_header(8104)

    listed = await async_client.get("/blog/posts", headers=headers)
    assert listed.status_code == 200, listed.text

    category = await async_client.post(
        "/blog/categories",
        headers=headers,
        json={"name": "Admin notes"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["data"]["category"]["id"]

    rejected = await async_client.post(
        "/blog/posts",
        headers=headers,
        json={
            "title": "String content",
            "content": "not json",
            "category_id": category_id,
            "status": "draft",
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "valid list" in rejected.json()["message"]

    legacy = await async_client.post(
        "/blog/posts",
        headers=headers,
        json={
            "title": "Legacy type block",
            "content": [{"type": "paragraph", "content": "x"}],
            "category_id": category_id,
            "status": "draft",
        },
    )
    assert legacy.status_code == 400, legacy.text
    assert "Unknown content block" in legacy.json()["message"]

    created = await async_client.post(
        "/blog/posts",
        headers=headers,
        json={
            "title": "Admin story",
            "content": [
                {"tag": "p", "content": "From the admin", "marks": []},
                {
                    "tag": "ul",
                    "items": [
                        {"text": "First item", "marks": []},
                        {"text": "Bold item", "marks": [{"type": "bold", "start": 0, "end": 4}]},
                    ],
                },
            ],
            "category_id": category_id,
            "status": "draft",
        },
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["data"]["id"]

    author_row = (
        await test_db_session.execute(select(Author).where(Author.partner_id == 8104))
    ).scalar_one_or_none()
    assert author_row is not None
    assert author_row.partner_id == 8104

    detail = await async_client.get(f"/blog/posts/{post_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    post = detail.json()["data"]["post"]
    assert post["author_name"] == "Admin Writer"
    assert post["author_role"] == "admin"
    assert isinstance(post["content"], list)
    assert post["content"][0]["tag"] == "p"
    assert post["content"][0]["text"] == "From the admin"
    assert "content" not in post["content"][0]
    assert post["content"][0]["marks"] == []
    list_block = post["content"][1]
    assert list_block["tag"] == "ul"
    assert isinstance(list_block["items"][0], dict)
    assert list_block["items"][0] == {"text": "First item", "marks": []}
    assert list_block["items"][1]["text"] == "Bold item"
    assert isinstance(list_block["items"][1]["marks"], list)
    assert list_block["items"][1]["marks"][0]["type"] == "bold"


@pytest.mark.asyncio
async def test_post_background_color_and_video_block(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8105, role="admin", name="Bg Writer")
    headers = employee_auth_header(8105)

    category = await async_client.post(
        "/blog/categories",
        headers=headers,
        json={"name": "Media"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["data"]["category"]["id"]

    rejected = await async_client.post(
        "/blog/posts",
        headers=headers,
        json={
            "title": "Bad color",
            "content": [{"tag": "p", "content": "Hello", "marks": []}],
            "category_id": category_id,
            "background_color": "not-a-color",
            "status": "draft",
        },
    )
    assert rejected.status_code == 400, rejected.text

    created = await async_client.post(
        "/blog/posts",
        headers=headers,
        json={
            "title": "With video and background",
            "content": [
                {"tag": "p", "content": "Watch this", "marks": []},
                {
                    "tag": "video",
                    "attributes": {"src": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                },
            ],
            "category_id": category_id,
            "background_color": "#f4faf8",
            "status": "draft",
        },
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["data"]["id"]

    detail = await async_client.get(f"/blog/posts/{post_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    post = detail.json()["data"]["post"]
    assert post["background_color"] == "#f4faf8"
    video = next(block for block in post["content"] if block.get("tag") == "video")
    assert video["attributes"]["src"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    custom = await async_client.put(
        f"/blog/posts/{post_id}",
        headers=headers,
        json={
            "title": "With video and background",
            "content": [{"tag": "p", "content": "Custom color", "marks": []}],
            "category_id": category_id,
            "background_color": "#123456",
            "status": "draft",
        },
    )
    assert custom.status_code == 200, custom.text
    custom_detail = await async_client.get(f"/blog/posts/{post_id}", headers=headers)
    assert custom_detail.json()["data"]["post"]["background_color"] == "#123456"

    cleared = await async_client.put(
        f"/blog/posts/{post_id}",
        headers=headers,
        json={
            "title": "With video and background",
            "content": [{"tag": "p", "content": "No video now", "marks": []}],
            "category_id": category_id,
            "background_color": "",
            "status": "draft",
        },
    )
    assert cleared.status_code == 200, cleared.text
    again = await async_client.get(f"/blog/posts/{post_id}", headers=headers)
    assert again.json()["data"]["post"]["background_color"] is None


@pytest.mark.asyncio
async def test_posts_accept_section_blocks_with_background(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8110, role="admin")
    author = await async_client.post(
        "/partners",
        headers=employee_auth_header(8110),
        json={"name": "Section Author", "phone": "8110000001", "role": "author"},
    )
    assert author.status_code in {200, 201}, author.text
    partner_id = author.json()["data"]["partner_id"]
    headers = partner_auth_header(partner_id)

    category = await async_client.post(
        "/blog/categories",
        headers=headers,
        json={"name": "Sections"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["data"]["category"]["id"]

    nested = await async_client.post(
        "/blog/posts",
        headers=headers,
        json={
            "title": "Nested section rejected",
            "content": [
                {
                    "tag": "section",
                    "attributes": {"style": {"backgroundColor": "#EFF6FF"}},
                    "content": [
                        {
                            "tag": "section",
                            "attributes": {"style": {"backgroundColor": "#FEF3C7"}},
                            "content": [{"tag": "p", "content": "Nope", "marks": []}],
                        }
                    ],
                }
            ],
            "category_id": category_id,
            "status": "draft",
        },
    )
    assert nested.status_code == 400, nested.text

    created = await async_client.post(
        "/blog/posts",
        headers=headers,
        json={
            "title": "Section story",
            "content": [
                {
                    "tag": "section",
                    "attributes": {"style": {"backgroundColor": "#EFF6FF"}},
                    "content": [
                        {
                            "tag": "h2",
                            "content": "Introduction",
                            "marks": [
                                {"type": "fontSize", "start": 0, "end": 12, "value": "28px"},
                                {"type": "fontFamily", "start": 0, "end": 12, "value": "Georgia"},
                            ],
                        },
                        {
                            "tag": "p",
                            "attributes": {"style": {"textAlign": "justify"}},
                            "content": "Start small.",
                            "marks": [
                                {"type": "fontSize", "start": 0, "end": 11, "value": "16px"},
                                {"type": "fontFamily", "start": 0, "end": 11, "value": "Arial"},
                            ],
                        },
                    ],
                }
            ],
            "category_id": category_id,
            "status": "draft",
        },
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["data"]["id"]

    detail = await async_client.get(f"/blog/posts/{post_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    content = detail.json()["data"]["post"]["content"]
    assert content[0]["tag"] == "section"
    assert content[0]["attributes"]["style"]["backgroundColor"] == "#eff6ff"
    assert content[0]["content"][0]["tag"] == "h2"
    assert content[0]["content"][0]["text"] == "Introduction"
    assert "content" not in content[0]["content"][0]
    assert any(mark.get("type") == "fontFamily" for mark in content[0]["content"][0].get("marks") or [])
    assert content[0]["content"][1]["attributes"]["style"]["textAlign"] == "justify"


@pytest.mark.asyncio
async def test_full_article_stores_text_video_and_hr(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8120, role="admin", name="Story Admin")
    headers = employee_auth_header(8120)
    category = await async_client.post(
        "/blog/categories",
        headers=headers,
        json={"name": "Machine Learning"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["data"]["category"]["id"]

    story = [
        {"tag": "h2", "marks": [], "content": "Introduction"},
        {
            "tag": "p",
            "marks": [{"end": 10, "type": "bold", "start": 0}],
            "content": "Imagine AI and ML.",
        },
        {
            "tag": "ol",
            "items": [
                {"text": "Learn Python fundamentals.", "marks": []},
                {"text": "Study basic mathematics.", "marks": []},
            ],
        },
        {
            "tag": "p",
            "marks": [{"end": 43, "type": "bold", "start": 0}],
            "text": "Do I need Python to learn machine learning?",
        },
        {
            "tag": "p",
            "marks": [],
            "text": "Python is not strictly required, but it is widely used.",
        },
        {
            "tag": "video",
            "attributes": {"src": "https://www.youtube.com/watch?v=5GN2FswYJoI"},
        },
        {"tag": "hr"},
        {
            "tag": "p",
            "marks": [
                {"end": 21, "type": "bold", "start": 0},
                {"end": 21, "type": "fontSize", "start": 0, "value": "24px"},
            ],
            "text": "welcome to Supershyft",
            "attributes": {"style": {"textAlign": "center"}},
        },
    ]

    created = await async_client.post(
        "/blog/posts",
        headers=headers,
        json={
            "title": "AI and Machine Learning",
            "content": story,
            "category_id": category_id,
            "status": "published",
        },
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["data"]["id"]

    author_row = (
        await test_db_session.execute(select(Author).where(Author.partner_id == 8120))
    ).scalar_one_or_none()
    assert author_row is not None
    assert author_row.partner_id == 8120

    detail = await async_client.get(f"/blog/posts/{post_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    post = detail.json()["data"]["post"]
    assert post["author_name"] == "Story Admin"
    assert post["author_role"] == "admin"
    blocks = post["content"]
    assert [block["tag"] for block in blocks] == ["h2", "p", "ol", "p", "p", "video", "hr", "p"]
    assert blocks[0]["text"] == "Introduction"
    assert "content" not in blocks[0]
    assert blocks[1]["text"] == "Imagine AI and ML."
    assert blocks[2]["items"][0] == {"text": "Learn Python fundamentals.", "marks": []}
    assert blocks[3]["text"] == "Do I need Python to learn machine learning?"
    assert blocks[5]["attributes"]["src"] == "https://www.youtube.com/watch?v=5GN2FswYJoI"
    assert blocks[6] == {"tag": "hr"}
    assert blocks[7]["text"] == "welcome to Supershyft"
    assert blocks[7]["attributes"]["style"]["textAlign"] == "center"
