"""Tests for recipient_resolver."""

from __future__ import annotations

import pytest

from modules.notifications.binding_resolver import ResolvedBinding
from modules.notifications.recipient_resolver import resolve_recipients


@pytest.mark.asyncio
async def test_resolve_custom_contacts(test_db_session):
    binding = ResolvedBinding(
        recipient_type="custom",
        notification_services=[],
        custom_contacts={"phones": ["918762830757"], "emails": []},
        filters=None,
        source="global",
    )
    recipients = await resolve_recipients(
        test_db_session,
        recipient_type="custom",
        payload={},
        binding=binding,
        engagement_id=None,
    )
    assert len(recipients.contacts) == 1
    assert recipients.contacts[0]["phone"] == "918762830757"


@pytest.mark.asyncio
async def test_resolve_participant_from_participant_user_id(test_db_session):
    binding = ResolvedBinding(
        recipient_type="participant",
        notification_services=[],
        custom_contacts=None,
        filters=None,
        source="global",
    )
    recipients = await resolve_recipients(
        test_db_session,
        recipient_type="participant",
        payload={"participant_user_id": 14446},
        binding=binding,
        engagement_id=1,
    )
    assert recipients.user_ids == [14446]


@pytest.mark.asyncio
async def test_resolve_family_members_individual(test_db_session):
    binding = ResolvedBinding(
        recipient_type="family_member",
        notification_services=[],
        custom_contacts=None,
        filters=None,
        source="global",
    )
    recipients = await resolve_recipients(
        test_db_session,
        recipient_type="family_member",
        payload={
            "members": [
                {"user_id": 101},
                {"user_id": 102},
            ]
        },
        binding=binding,
        engagement_id=1,
    )
    assert len(recipients.members_for_individual_dispatch) == 2
