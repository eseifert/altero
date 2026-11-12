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
from tests.test_registration_policy import policy

NOW = datetime(2026, 11, 9, 12)
POLICY = policy()


async def submit(session: AsyncSession, **changes: object) -> RegistrationRequest:
    function = getattr(registrations, "submit", None)
    assert callable(function), "Pending request submission must be implemented"
    return await function(
        session,
        **{
            "enabled": True,
            "policy": POLICY,
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


async def test_email_verification_is_bound_to_the_address_and_cannot_be_replayed(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    verify = getattr(registrations, "record_email_verification", None)
    assert callable(verify), "Verified-mailbox recording must be implemented"
    moment = NOW + timedelta(hours=1)
    assert await verify(session, record.id, " ADA@EXAMPLE.ORG ", now=moment, policy=POLICY)
    await session.refresh(record)
    assert record.status == RegistrationStatus.REVIEW_PENDING
    assert record.email_verified == moment
    assert record.expires == NOW + timedelta(days=1)
    assert not await verify(
        session, record.id, record.email, now=moment + timedelta(hours=1), policy=POLICY
    )
    await session.refresh(record)
    assert record.email_verified == moment


async def test_a_different_address_cannot_advance_a_request(session: AsyncSession) -> None:
    record = await submit(session)
    assert not await registrations.record_email_verification(
        session, record.id, "different@example.org", now=NOW, policy=POLICY
    )
    await session.refresh(record)
    assert record.status == RegistrationStatus.EMAIL_PENDING
    assert record.email_verified is None


@pytest.mark.parametrize("late", [timedelta(0), timedelta(seconds=1)])
async def test_verification_at_or_after_expiry_cannot_advance_a_request(
    session: AsyncSession, late: timedelta
) -> None:
    record = await submit(session)
    assert not await registrations.record_email_verification(
        session, record.id, record.email, now=record.expires + late, policy=POLICY
    )
    await session.refresh(record)
    assert record.status == RegistrationStatus.EXPIRED
    assert record.email_verified is None


@pytest.mark.parametrize("verified", [False, True])
async def test_cancellation_releases_both_reservations_without_erasing_proof(
    session: AsyncSession, verified: bool
) -> None:
    record = await submit(session)
    if verified:
        assert await registrations.record_email_verification(
            session, record.id, record.email, now=NOW, policy=POLICY
        )
    assert await registrations.cancel(session, record.id, now=NOW)
    assert not await registrations.cancel(session, record.id, now=NOW)
    await session.refresh(record)
    assert record.status == RegistrationStatus.CANCELLED
    assert record.reserved_username is record.reserved_email is None
    assert record.email_verified == (NOW if verified else None)
    assert (await submit(session)).id != record.id


async def test_cancellation_does_not_relabel_an_expired_request(session: AsyncSession) -> None:
    record = await submit(session)
    assert not await registrations.cancel(session, record.id, now=record.expires)
    await session.refresh(record)
    assert record.status == RegistrationStatus.EXPIRED


async def test_missing_request_ids_authorize_no_transition(session: AsyncSession) -> None:
    assert not await registrations.cancel(session, 999, now=NOW)
    assert not await registrations.record_email_verification(
        session, 999, "ada@example.org", now=NOW, policy=POLICY
    )


@pytest.mark.parametrize(
    "state",
    [
        RegistrationStatus.APPROVED,
        RegistrationStatus.REJECTED,
        RegistrationStatus.CANCELLED,
        RegistrationStatus.EXPIRED,
    ],
)
async def test_terminal_history_cannot_be_reopened_or_relabelled(
    session: AsyncSession, state: RegistrationStatus
) -> None:
    record = await submit(session)
    record.status = state
    record.reserved_username = record.reserved_email = None
    if state in (RegistrationStatus.APPROVED, RegistrationStatus.REJECTED):
        record.email_verified = record.decided_at = NOW
        record.decided_by = 7
    if state == RegistrationStatus.APPROVED:
        record.user_id = 8
    await session.commit()
    assert not await registrations.record_email_verification(
        session, record.id, record.email, now=NOW, policy=POLICY
    )
    assert not await registrations.cancel(session, record.id, now=NOW)
    assert await registrations.expire(session, now=NOW + timedelta(days=2)) == 0
    await session.refresh(record)
    assert record.status == state
    assert record.decided_by == (7 if record.decided_at is not None else None)
    assert record.user_id == (8 if state == RegistrationStatus.APPROVED else None)


async def test_two_verification_workers_record_one_proof(
    app: FastAPI, session: AsyncSession
) -> None:
    record = await submit(session)

    async def worker() -> bool:
        async with app.state.database.session_factory() as other:
            return await registrations.record_email_verification(
                other, record.id, record.email, now=NOW, policy=POLICY
            )

    assert sum(await asyncio.gather(worker(), worker())) == 1
    await session.refresh(record)
    assert record.status == RegistrationStatus.REVIEW_PENDING


async def test_cancellation_wins_a_race_with_verification(
    app: FastAPI, session: AsyncSession
) -> None:
    record = await submit(session)

    async def verify() -> bool:
        async with app.state.database.session_factory() as other:
            return await registrations.record_email_verification(
                other, record.id, record.email, now=NOW, policy=POLICY
            )

    async def cancel() -> bool:
        async with app.state.database.session_factory() as other:
            return await registrations.cancel(other, record.id, now=NOW)

    _, cancelled = await asyncio.gather(verify(), cancel())
    assert cancelled
    await session.refresh(record)
    assert record.status == RegistrationStatus.CANCELLED
    assert record.reserved_username is record.reserved_email is None
    assert await session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize("operation", ["record_email_verification", "cancel"])
async def test_expiry_cleanup_and_transition_share_one_commit(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    current = await submit(session)
    old = await submit(
        session, username="Old", email="old@example.org", now=NOW - timedelta(days=1), expires=NOW
    )

    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Injected transition failure")

    function = getattr(registrations, operation)
    arguments = (
        [current.id, current.email] if operation == "record_email_verification" else [current.id]
    )
    options = {"policy": POLICY} if operation == "record_email_verification" else {}
    with monkeypatch.context() as patch:
        patch.setattr(session, "scalar", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            await function(session, *arguments, now=NOW, **options)
    await session.rollback()
    await session.refresh(old)
    await session.refresh(current)
    assert old.status == RegistrationStatus.EMAIL_PENDING
    assert old.reserved_username == "old"
    assert current.status == RegistrationStatus.EMAIL_PENDING
    assert current.email_verified is None
