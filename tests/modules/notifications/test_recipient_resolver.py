"""Unit tests for notification recipient resolution."""

from __future__ import annotations

import pytest

from modules.notifications.recipient_resolver import (
    recipient_uses_user_dispatch,
    resolve_recipients,
)
from modules.users.models import User


@pytest.mark.asyncio
async def test_participant_from_user_id(test_db_session):
    user = User(
        user_id=9001,
        first_name="Ada",
        last_name="Lovelace",
        phone="+911234567890",
        email="ada@example.com",
    )
    test_db_session.add(user)
    await test_db_session.commit()

    contacts = await resolve_recipients(
        test_db_session,
        recipient_type="participant",
        payload={"user_id": 9001},
        engagement_id=None,
    )
    assert len(contacts) == 1
    assert contacts[0]["email"] == "ada@example.com"
    assert recipient_uses_user_dispatch(contacts) == [9001]


@pytest.mark.asyncio
async def test_participant_members_override_db(test_db_session):
    contacts = await resolve_recipients(
        test_db_session,
        recipient_type="participant",
        payload={
            "members": [
                {"first_name": "Bob", "phone": "+910000000001", "email": "bob@test.com"}
            ]
        },
        engagement_id=None,
    )
    assert len(contacts) == 1
    assert contacts[0]["first_name"] == "Bob"
    assert recipient_uses_user_dispatch(contacts) is None
