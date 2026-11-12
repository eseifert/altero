"""Approval creates an account/library only inside the recorded decision transaction."""

import asyncio
import importlib
import importlib.util
from datetime import timedelta
from types import ModuleType

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import Library, RegistrationStatus, User
from altero.services import admin, registrationaccess, registrations
from tests.test_registration_policy import policy
from tests.test_registration_review import reviewer, verified
from tests.test_registrations import NOW, POLICY, submit


def admission() -> ModuleType:
    assert importlib.util.find_spec("altero.services.registrationadmission"), (
        "Atomic administrator approval must be implemented"
    )
    return importlib.import_module("altero.services.registrationadmission")


async def approve(
    session: AsyncSession, request_id: int, actor: int, **changes: object
) -> int | None:
    return await admission().approve(
        session, request_id, actor_id=actor, **{"policy": POLICY, "now": NOW, **changes}
    )


async def test_approval_records_actor_and_creates_only_one_non_admin_account(
    session: AsyncSession,
) -> None:
    actor = await reviewer(session)
    record = await verified(session)
    key = await approve(session, record.id, actor.id)
    assert key
    user = await session.get(User, key)
    assert user is not None
    assert not user.administrator
    assert user.email_verified == NOW
    assert user.password_hash is None
    assert (
        await session.scalar(
            select(func.count()).select_from(Library).where(Library.owner_id == key)
        )
        == 1
    )
    await session.refresh(record)
    assert record.status == RegistrationStatus.APPROVED
    assert record.user_id == key
    assert record.decided_by == actor.id
    assert not await approve(session, record.id, actor.id)


async def test_unverified_expired_and_ineligible_requests_create_no_user(
    session: AsyncSession,
) -> None:
    actor = await reviewer(session)
    unverified = await submit(session)
    assert not await approve(session, unverified.id, actor.id)
    record = await verified(session, username="Other", email="other@example.org")
    request_id, actor_id = record.id, actor.id
    with pytest.raises(ForbiddenError):
        await approve(session, request_id, actor_id, policy=policy("elsewhere.example"))
    assert not await approve(session, request_id, actor_id, now=NOW + timedelta(days=1))
    assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_operator_provisioned_identity_wins_over_an_older_reservation(
    session: AsyncSession,
) -> None:
    actor = await reviewer(session)
    record = await verified(session)
    await admin.create_user(session, username=record.username)
    with pytest.raises(InvalidInputError):
        await approve(session, record.id, actor.id)
    await session.refresh(record)
    assert record.status == RegistrationStatus.REVIEW_PENDING


async def test_competing_approvals_create_one_account(app: FastAPI, session: AsyncSession) -> None:
    actor = await reviewer(session)
    record = await verified(session)

    async def worker() -> int | None:
        async with app.state.database.session_factory() as other:
            return await approve(other, record.id, actor.id)

    assert sum(bool(v) for v in await asyncio.gather(worker(), worker())) == 1
    assert await session.scalar(select(func.count()).select_from(User)) == 2


async def test_failed_approval_rolls_back_account_library_and_decision(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = await reviewer(session)
    record = await verified(session)

    async def fail() -> None:
        raise RuntimeError("Injected commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            await approve(session, record.id, actor.id)
    await session.refresh(record)
    assert record.status == RegistrationStatus.REVIEW_PENDING
    assert record.user_id is None
    assert await session.scalar(select(func.count()).select_from(User)) == 1
    assert await session.scalar(select(func.count()).select_from(Library)) == 1


@pytest.mark.parametrize("changes", [{"administrator": False}, {"disabled_at": NOW}])
async def test_approval_rechecks_reviewer_permission(
    app: FastAPI,
    session: AsyncSession,
    changes: dict[str, object],
) -> None:
    actor = await reviewer(session)
    record = await verified(session)
    async with app.state.database.session_factory() as other:
        await other.execute(update(User).where(User.id == actor.id).values(**changes))
        await other.commit()
    with pytest.raises(ForbiddenError):
        await approve(session, record.id, actor.id)
    assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_approve_reject_and_cancel_have_only_one_winner(
    app: FastAPI, session: AsyncSession
) -> None:
    actor = await reviewer(session)
    record = await verified(session)
    token = await registrationaccess.issue(session, record.id, now=NOW)

    async def worker(action: str) -> bool:
        async with app.state.database.session_factory() as other:
            if action == "approve":
                return bool(await approve(other, record.id, actor.id))
            if action == "reject":
                return await registrations.reject(other, record.id, actor_id=actor.id, now=NOW)
            return await registrationaccess.cancel(other, token, now=NOW)

    assert sum(await asyncio.gather(*(worker(a) for a in ("approve", "reject", "cancel")))) == 1
    await session.refresh(record)
    expected = 2 if record.status == RegistrationStatus.APPROVED else 1
    assert await session.scalar(select(func.count()).select_from(User)) == expected
    assert await session.scalar(select(func.count()).select_from(Library)) == expected
