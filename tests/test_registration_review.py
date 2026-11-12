"""Only a current instance administrator can decide a verified application."""

import asyncio
from datetime import timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import RegistrationRequest, RegistrationStatus, User
from altero.services import registrations
from tests.factories import make_user
from tests.test_registrations import NOW, POLICY, submit


async def reviewer(session: AsyncSession, key: int = 1) -> User:
    user = await make_user(session, user_id=key, username=f"reviewer{key}")
    user.administrator = True
    await session.commit()
    return user


async def verified(session: AsyncSession, **changes: object) -> RegistrationRequest:
    record = await submit(session, **changes)
    assert await registrations.record_email_verification(
        session, record.id, record.email, now=NOW, policy=POLICY
    )
    return record


async def reject(session: AsyncSession, key: int, actor: int, **changes: object) -> bool:
    function = getattr(registrations, "reject", None)
    assert callable(function), "Administrator rejection must be implemented"
    return await function(session, key, actor_id=actor, **{"now": NOW, **changes})


async def test_rejection_records_the_decision_and_releases_both_reservations(
    session: AsyncSession,
) -> None:
    actor = await reviewer(session)
    record = await verified(session)
    moment = NOW + timedelta(hours=1)
    assert await reject(session, record.id, actor.id, now=moment)
    await session.refresh(record)
    assert record.status == RegistrationStatus.REJECTED
    assert record.decided_by == actor.id
    assert record.decided_at == moment
    assert record.email_verified == NOW
    assert record.reserved_username is record.reserved_email is record.user_id is None
    assert not await reject(session, record.id, actor.id, now=moment + timedelta(hours=1))
    await session.refresh(record)
    assert record.decided_at == moment
    assert (await submit(session)).id != record.id
    assert await session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize("state", ["unverified", "cancelled", "expired", "missing"])
async def test_only_a_live_verified_request_can_be_rejected(
    session: AsyncSession,
    state: str,
) -> None:
    actor = await reviewer(session)
    record = await submit(session) if state == "unverified" else await verified(session)
    if state == "cancelled":
        assert await registrations.cancel(session, record.id, now=NOW)
    key = record.id + 100 if state == "missing" else record.id
    assert not await reject(
        session, key, actor.id, now=record.expires if state == "expired" else NOW
    )
    await session.refresh(record)
    assert record.decided_by is record.decided_at is None


@pytest.mark.parametrize("changes", [{"administrator": False}, {"disabled_at": NOW}])
async def test_stale_reviewer_objects_cannot_authorize_a_decision(
    app: FastAPI,
    session: AsyncSession,
    changes: dict[str, object],
) -> None:
    actor = await reviewer(session)
    record = await verified(session)
    async with app.state.database.session_factory() as other:
        await other.execute(update(User).where(User.id == actor.id).values(**changes))
        await other.commit()
    assert actor.administrator
    assert actor.disabled_at is None
    with pytest.raises(ForbiddenError):
        await reject(session, record.id, actor.id)
    await session.refresh(record)
    assert record.status == RegistrationStatus.REVIEW_PENDING


async def test_competing_reviewers_cannot_replace_the_winning_decision(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    first, second = await reviewer(session), await reviewer(session, 2)
    record = await verified(session)

    async def worker(actor: int) -> bool:
        async with app.state.database.session_factory() as other:
            return await reject(other, record.id, actor)

    assert sum(await asyncio.gather(worker(first.id), worker(second.id))) == 1
    await session.refresh(record)
    assert record.decided_by in {first.id, second.id}


async def test_failed_rejection_preserves_request_and_due_reservations(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = await reviewer(session)
    record = await verified(session)
    old = await submit(
        session, username="Old", email="old@example.org", now=NOW - timedelta(days=1), expires=NOW
    )

    async def fail() -> None:
        raise RuntimeError("Injected commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            await reject(session, record.id, actor.id)
    await session.rollback()
    await session.refresh(old)
    await session.refresh(record)
    assert old.status == RegistrationStatus.EMAIL_PENDING
    assert old.reserved_email
    assert record.status == RegistrationStatus.REVIEW_PENDING
    assert record.decided_at is None
    assert record.reserved_email
