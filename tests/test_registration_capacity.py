"""A distributed submission flood cannot exceed the instance pending cap."""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import RegistrationLimitError
from altero.models import RegistrationRequest, RegistrationStatus
from altero.services import registrationaccess
from tests.test_registrations import NOW, POLICY


async def apply(
    session: AsyncSession, name: str, *, now: datetime = NOW, expires: datetime | None = None
) -> tuple[RegistrationRequest, str]:
    return await registrationaccess.submit(
        session,
        username=name,
        email=name.lower() + "@example.org",
        expires=expires or NOW + timedelta(days=1),
        enabled=True,
        policy=POLICY,
        now=now,
        max_pending=1,
    )


async def test_capacity_frees_at_request_expiry(session: AsyncSession) -> None:
    await apply(session, "First")
    with pytest.raises(RegistrationLimitError):
        await apply(session, "Second")
    assert (
        await apply(session, "Second", now=NOW + timedelta(days=1), expires=NOW + timedelta(days=2))
    )[0].username == "Second"


async def test_concurrent_workers_cannot_exceed_capacity(app: FastAPI) -> None:
    async def worker(name: str) -> bool:
        async with app.state.database.session_factory() as session:
            try:
                await apply(session, name)
            except RegistrationLimitError:
                return False
            return True

    assert sum(await asyncio.gather(worker("First"), worker("Second"))) == 1


async def test_submission_prunes_old_unreviewed_history_but_keeps_decisions(
    session: AsyncSession,
) -> None:
    old_time = NOW - timedelta(days=40)
    old, _ = await apply(session, "Old", now=old_time, expires=old_time + timedelta(days=1))
    old_id = old.id
    await apply(session, "Current")
    assert (
        await session.scalar(select(RegistrationRequest.id).where(RegistrationRequest.id == old_id))
        is None
    )
    current = await session.scalar(select(RegistrationRequest))
    assert current
    current.status = RegistrationStatus.REJECTED
    current.email_verified = current.decided_at = NOW
    current.decided_by = 99
    current.reserved_username = current.reserved_email = None
    current.created = old_time
    current_id = current.id
    await session.commit()
    await apply(session, "Next")
    assert (
        await session.scalar(
            select(RegistrationRequest.id).where(RegistrationRequest.id == current_id)
        )
        == current_id
    )
