"""Internal admission reservations do not provision an account."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import RegistrationRequest, RegistrationStatus, User
from altero.services import admin, registrations

NOW = datetime(2026, 11, 9, 12)


async def submit(session: AsyncSession, **changes: object) -> RegistrationRequest:
    function = getattr(registrations, "submit", None)
    assert callable(function), "Pending request submission must be implemented"
    return await function(
        session,
        **{
            "enabled": True,
            "username": "Ada",
            "email": "ada@example.org",
            "expires": NOW + timedelta(days=1),
            "now": NOW,
            **changes,
        },
    )


async def test_disabled_policy_creates_nothing(session: AsyncSession) -> None:
    with pytest.raises(ForbiddenError, match="not enabled"):
        await submit(session, enabled=False)
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 0


async def test_default_policy_is_disabled(session: AsyncSession) -> None:
    assert callable(getattr(registrations, "submit", None))
    with pytest.raises(ForbiddenError):
        await registrations.submit(
            session,
            username="Ada",
            email="ada@example.org",
            expires=NOW + timedelta(days=1),
            now=NOW,
        )


async def test_submission_normalizes_and_reserves_without_creating_a_user(
    session: AsyncSession,
) -> None:
    record = await submit(session, username="  Ada  ", email="  ADA@EXAMPLE.ORG  ")
    assert record.username == record.display_name == "Ada"
    assert record.email == record.reserved_email == "ada@example.org"
    assert record.reserved_username == "ada"
    assert record.status == RegistrationStatus.EMAIL_PENDING
    assert record.email_verified is None
    assert await session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"username": " "},
        {"username": "ada@example.org"},
        {"username": "x" * 256},
        {"email": "invalid"},
        {"display_name": "x" * 256},
        {"expires": NOW},
        {"expires": NOW - timedelta(seconds=1)},
        {"username": "Ada\x00"},
        {"email": "ada\x00@example.org"},
        {"display_name": "Ada\x00"},
    ],
)
async def test_invalid_submission_leaves_no_reservation(
    session: AsyncSession, changes: dict[str, object]
) -> None:
    with pytest.raises(InvalidInputError):
        await submit(session, **changes)
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 0


@pytest.mark.parametrize("changes", [{"username": "ADA"}, {"email": "ADA@EXAMPLE.ORG"}])
async def test_pending_names_and_addresses_cannot_be_reserved_twice(
    session: AsyncSession, changes: dict[str, object]
) -> None:
    await submit(session)
    with pytest.raises(InvalidInputError, match="unavailable"):
        await submit(session, **{"username": "Grace", "email": "grace@example.org", **changes})
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 1


@pytest.mark.parametrize("changes", [{"username": "ÉRIC"}, {"email": "ERIC@EXAMPLE.ORG"}])
async def test_existing_accounts_keep_their_names_and_addresses(
    session: AsyncSession, changes: dict[str, object]
) -> None:
    user = await admin.create_user(session, username="Éric")
    user.email = "eric@example.org"
    await session.commit()
    with pytest.raises(InvalidInputError, match="unavailable"):
        await submit(session, **changes)
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 0


async def test_expiry_boundary_releases_a_reservation_and_retains_history(
    session: AsyncSession,
) -> None:
    old = await submit(session, now=NOW - timedelta(days=1), expires=NOW)
    assert await registrations.expire(session, now=NOW) == 1
    assert await registrations.expire(session, now=NOW) == 0
    fresh = await submit(session)
    await session.refresh(old)
    assert old.status == RegistrationStatus.EXPIRED
    assert old.reserved_username is old.reserved_email is None
    assert old.username == "Ada"
    assert old.email == "ada@example.org"
    assert fresh.id != old.id
    assert fresh.status == RegistrationStatus.EMAIL_PENDING


async def test_aware_deadlines_are_stored_as_naive_utc(session: AsyncSession) -> None:
    record = await submit(
        session,
        now=NOW.replace(tzinfo=UTC),
        expires=(NOW + timedelta(hours=3)).replace(tzinfo=timezone(timedelta(hours=2))),
    )
    assert record.created == NOW
    assert record.expires == NOW + timedelta(hours=1)


async def test_independent_workers_have_one_reservation_winner(app: FastAPI) -> None:
    async def worker() -> object:
        async with app.state.database.session_factory() as session:
            try:
                return await submit(session)
            except InvalidInputError as error:
                return error

    outcomes = await asyncio.gather(worker(), worker())
    assert sum(isinstance(value, RegistrationRequest) for value in outcomes) == 1
    assert sum(isinstance(value, InvalidInputError) for value in outcomes) == 1
