"""A mailbox link proves its pending request's address, not an account login."""

import asyncio
import hashlib
from datetime import UTC, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import RegistrationRequest, RegistrationStatus, User
from altero.services import registrations
from tests.test_registrations import NOW, submit


async def issue(
    session: AsyncSession, request_id: int, **changes: object
) -> tuple[str, str] | None:
    function = getattr(registrations, "issue_email_verification", None)
    assert callable(function), "Pending registration mailbox proof issuance must be implemented"
    return await function(session, request_id, **{"now": NOW, **changes})


async def consume(session: AsyncSession, token: str, **changes: object) -> bool:
    function = getattr(registrations, "consume_email_verification", None)
    assert callable(function), "Pending registration mailbox proof consumption must be implemented"
    return await function(session, token, **{"now": NOW, **changes})


async def token_for(session: AsyncSession, record: RegistrationRequest) -> str:
    result = await issue(session, record.id)
    assert result is not None
    assert result[0] == record.email
    return result[1]


async def test_link_stores_only_a_digest_and_consumes_the_address_bound_proof(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    await session.refresh(record)
    assert len(token) >= 43
    assert record.email_token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert record.email_token_address == record.email
    assert record.email_token_expires == record.expires
    verified = NOW + timedelta(hours=1)
    assert await consume(session, token, now=verified)
    await session.refresh(record)
    assert record.status == RegistrationStatus.REVIEW_PENDING
    assert record.email_verified == verified
    assert (
        record.email_token_hash is record.email_token_address is record.email_token_expires is None
    )
    assert not await consume(session, token, now=verified + timedelta(minutes=1))
    assert await session.scalar(select(func.count()).select_from(User)) == 0


async def test_resending_invalidates_the_old_link_without_extending_the_request(
    session: AsyncSession,
) -> None:
    record = await submit(session, expires=NOW + timedelta(days=3))
    first = await token_for(session, record)
    await session.refresh(record)
    assert record.email_token_expires == NOW + timedelta(days=1)
    second = await issue(session, record.id, now=NOW + timedelta(hours=1))
    assert second is not None
    assert first != second[1]
    assert not await consume(session, first)
    assert await consume(session, second[1], now=NOW + timedelta(hours=2))
    await session.refresh(record)
    assert record.expires == NOW + timedelta(days=3)


async def test_an_expired_proof_does_not_expire_a_still_live_request(session: AsyncSession) -> None:
    record = await submit(session, expires=NOW + timedelta(days=3))
    token = await token_for(session, record)
    assert not await consume(session, token, now=NOW + timedelta(days=1))
    await session.refresh(record)
    assert record.status == RegistrationStatus.EMAIL_PENDING
    assert record.email_verified is None
    replacement = await issue(session, record.id, now=NOW + timedelta(days=1))
    assert replacement is not None
    assert await consume(session, replacement[1], now=NOW + timedelta(days=1))


async def test_request_expiry_also_revokes_its_link_and_releases_reservations(
    session: AsyncSession,
) -> None:
    record = await submit(session, expires=NOW + timedelta(hours=1))
    token = await token_for(session, record)
    await session.refresh(record)
    assert record.email_token_expires == record.expires
    assert not await consume(session, token, now=record.expires)
    await session.refresh(record)
    assert record.status == RegistrationStatus.EXPIRED
    assert record.reserved_username is record.reserved_email is record.email_token_hash is None
    assert await issue(session, record.id, now=record.expires) is None


async def test_aware_proof_times_are_compared_and_recorded_in_utc(session: AsyncSession) -> None:
    record = await submit(session)
    result = await issue(session, record.id, now=NOW.replace(tzinfo=UTC))
    assert result is not None
    assert await consume(session, result[1], now=NOW.replace(tzinfo=UTC))
    await session.refresh(record)
    assert record.email_verified == NOW


async def test_a_link_cannot_verify_a_different_address(session: AsyncSession) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    # Future address-edit callers must invalidate proofs; even an omitted reset
    # must not make an old mailbox link prove the new address.
    record.email = record.reserved_email = "changed@example.org"
    await session.commit()
    assert not await consume(session, token)
    await session.refresh(record)
    assert record.status == RegistrationStatus.EMAIL_PENDING
    assert record.email_verified is None


async def test_unknown_tokens_and_request_ids_do_not_advance_a_request(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    assert await issue(session, record.id + 100) is None
    for invalid in ["", "unknown", str(record.id), token + "x"]:
        assert not await consume(session, invalid)
    assert await consume(session, token)
    assert await issue(session, record.id) is None


@pytest.mark.parametrize("transition", ["cancel", "record_email_verification"])
async def test_other_transitions_revoke_outstanding_proofs(
    session: AsyncSession, transition: str
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    arguments = (
        [record.id, record.email] if transition == "record_email_verification" else [record.id]
    )
    assert await getattr(registrations, transition)(session, *arguments, now=NOW)
    assert not await consume(session, token)
    await session.refresh(record)
    assert (
        record.email_token_hash is record.email_token_address is record.email_token_expires is None
    )


async def test_competing_link_consumers_have_one_winner(
    app: FastAPI, session: AsyncSession
) -> None:
    record = await submit(session)
    token = await token_for(session, record)

    async def worker() -> bool:
        async with app.state.database.session_factory() as other:
            return await consume(other, token)

    assert sum(await asyncio.gather(worker(), worker())) == 1


async def test_competing_resends_leave_only_one_usable_link(
    app: FastAPI, session: AsyncSession
) -> None:
    record = await submit(session)

    async def worker() -> tuple[str, str] | None:
        async with app.state.database.session_factory() as other:
            return await issue(other, record.id)

    results = await asyncio.gather(worker(), worker())
    assert all(result is not None for result in results)
    assert sum([await consume(session, result[1]) for result in results if result]) == 1


async def test_cancellation_wins_against_a_link_consumer(
    app: FastAPI, session: AsyncSession
) -> None:
    record = await submit(session)
    token = await token_for(session, record)

    async def verify() -> bool:
        async with app.state.database.session_factory() as other:
            return await consume(other, token)

    async def cancel() -> bool:
        async with app.state.database.session_factory() as other:
            return await registrations.cancel(other, record.id, now=NOW)

    _, cancelled = await asyncio.gather(verify(), cancel())
    assert cancelled
    await session.refresh(record)
    assert record.status == RegistrationStatus.CANCELLED
    assert record.email_token_hash is None


@pytest.mark.parametrize("failure", ["commit", "scalar"])
@pytest.mark.parametrize("operation", ["issue", "consume"])
async def test_failed_commit_preserves_the_previous_link_and_request_state(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, operation: str, failure: str
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    key = record.id
    old = await submit(
        session, username="Old", email="old@example.org", now=NOW - timedelta(days=1), expires=NOW
    )

    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Injected transaction failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, failure, fail)
        attempt = issue(session, key) if operation == "issue" else consume(session, token)
        with pytest.raises(RuntimeError, match="Injected"):
            await attempt
    await session.rollback()
    await session.refresh(old)
    assert old.status == RegistrationStatus.EMAIL_PENDING
    assert old.reserved_username == "old"
    await session.refresh(record)
    assert record.status == RegistrationStatus.EMAIL_PENDING
    assert record.email_token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert await consume(session, token)
