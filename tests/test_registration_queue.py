"""The internal review queue exposes only live, verified applications."""

from datetime import timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import RegistrationRequest, User
from altero.services import registrations
from tests.test_registration_review import reject, reviewer, verified
from tests.test_registrations import NOW, submit


async def queue(session: AsyncSession, actor: int, **options: object) -> list[RegistrationRequest]:
    function = getattr(registrations, "review_queue", None)
    assert callable(function), "A bounded current-administrator review queue must be implemented"
    return await function(session, actor_id=actor, **{"now": NOW, **options})


async def test_review_queue_filters_and_pages_live_verified_requests(session: AsyncSession) -> None:
    actor = await reviewer(session)
    await submit(session, username="Unverified", email="unverified@example.org")
    expired = await verified(session, username="Expired", email="expired@example.org")
    rejected = await verified(session, username="Rejected", email="rejected@example.org")
    assert await reject(session, rejected.id, actor.id)
    first = await verified(
        session, username="First", email="first@example.org", expires=NOW + timedelta(days=2)
    )
    second = await verified(
        session, username="Second", email="second@example.org", expires=NOW + timedelta(days=2)
    )
    rows = await queue(session, actor.id, now=expired.expires, limit=1)
    assert [r.id for r in rows] == [first.id]
    assert [
        r.id for r in await queue(session, actor.id, now=expired.expires, after_id=first.id)
    ] == [second.id]
    assert await queue(session, actor.id, after_id=second.id) == []


@pytest.mark.parametrize("options", [{"limit": 0}, {"limit": 201}, {"after_id": -1}])
async def test_queue_bounds_are_enforced(session: AsyncSession, options: dict[str, int]) -> None:
    actor = await reviewer(session)
    with pytest.raises(InvalidInputError):
        await queue(session, actor.id, **options)


@pytest.mark.parametrize("changes", [{"administrator": False}, {"disabled_at": NOW}])
async def test_queue_rechecks_current_permission(
    app: FastAPI,
    session: AsyncSession,
    changes: dict[str, object],
) -> None:
    actor = await reviewer(session)
    await verified(session)
    async with app.state.database.session_factory() as other:
        await other.execute(update(User).where(User.id == actor.id).values(**changes))
        await other.commit()
    with pytest.raises(ForbiddenError):
        await queue(session, actor.id)


async def test_a_missing_reviewer_cannot_read_the_queue(session: AsyncSession) -> None:
    await verified(session)
    with pytest.raises(ForbiddenError):
        await queue(session, 999)
