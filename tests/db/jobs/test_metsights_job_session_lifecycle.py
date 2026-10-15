"""Regression: Metsights cron jobs must not wrap work in session.begin().

import_category_from_metsights / push_questionnaire_for_instance call
release_request_transaction() (commit) between HTTP hops. An outer
``async with session.begin():`` then raises:

  Can't operate on closed transaction inside context manager
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from db.transaction import release_request_transaction


@pytest.mark.asyncio
async def test_begin_context_breaks_after_release_request_transaction(test_db_session):
    """Reproduce the production import/push cron failure mode."""
    with pytest.raises(Exception, match="closed transaction|transaction is closed"):
        async with test_db_session.begin():
            await test_db_session.execute(text("SELECT 1"))
            await release_request_transaction(test_db_session)
            # Next statement inside begin() fails after the inner commit.
            await test_db_session.execute(text("SELECT 1"))


@pytest.mark.asyncio
async def test_job_session_pattern_survives_mid_work_release(test_db_session):
    """Match fixed cron commands: no begin(); commit only if still open."""
    await test_db_session.execute(text("SELECT 1"))
    await release_request_transaction(test_db_session)
    assert not test_db_session.in_transaction()

    await test_db_session.execute(text("SELECT 1"))
    assert test_db_session.in_transaction()
    if test_db_session.in_transaction():
        await test_db_session.commit()
    assert not test_db_session.in_transaction()
