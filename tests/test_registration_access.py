"""An applicant credential reaches only its own application."""

import asyncio
import hashlib
import importlib
import importlib.util
from datetime import timedelta
from types import ModuleType

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import RegistrationStatus
from altero.services import websessions
from tests.test_registration_email import consume, token_for
from tests.test_registrations import NOW, submit


def access() -> ModuleType:
    assert importlib.util.find_spec("altero.services.registrationaccess"), (
        "Applicant authorization must be implemented"
    )
    return importlib.import_module("altero.services.registrationaccess")


async def test_applicant_token_is_hashed_scoped_and_not_an_account_session(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    token = await access().issue(session, record.id, now=NOW)
    assert token
    assert len(token) >= 43
    await session.refresh(record)
    assert record.applicant_token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert record.applicant_token_expires == NOW + timedelta(days=7)
    result = await access().status(session, token, now=NOW)
    assert result.request_id == record.id
    assert result.status == RegistrationStatus.EMAIL_PENDING
    assert not hasattr(result, "user_id")
    assert await websessions.lookup(session, token) is None
    assert await access().status(session, record.email, now=NOW) is None
    assert await access().status(session, str(record.id), now=NOW) is None
    mailbox_proof = await token_for(session, record)
    assert await access().status(session, mailbox_proof, now=NOW) is None
    assert not await consume(session, token)


async def test_token_replacement_and_revocation(session: AsyncSession) -> None:
    record = await submit(session)
    first = await access().issue(session, record.id, now=NOW)
    second = await access().issue(session, record.id, now=NOW)
    assert first != second
    assert await access().status(session, first, now=NOW) is None
    assert not await access().cancel(session, first, now=NOW)
    assert await access().revoke(session, second)
    assert not await access().revoke(session, second)
    assert await access().status(session, second, now=NOW) is None


async def test_expired_application_remains_visible_until_token_expiry(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    token = await access().issue(session, record.id, now=NOW)
    result = await access().status(session, token, now=record.expires)
    assert result.status == RegistrationStatus.EXPIRED
    assert not await access().cancel(session, token, now=record.expires)
    assert await access().status(session, token, now=NOW + timedelta(days=7)) is None
    assert await access().issue(session, record.id, now=record.expires) is None


async def test_cancellation_reaches_only_the_authenticated_request(session: AsyncSession) -> None:
    first = await submit(session)
    other = await submit(session, username="Other", email="other@example.org")
    token = await access().issue(session, first.id, now=NOW)
    assert await access().cancel(session, token, now=NOW)
    assert not await access().cancel(session, token, now=NOW)
    assert (await access().status(session, token, now=NOW)).status == RegistrationStatus.CANCELLED
    assert await access().issue(session, first.id, now=NOW) is None
    await session.refresh(first)
    await session.refresh(other)
    assert first.reserved_username is first.reserved_email is None
    assert other.status == RegistrationStatus.EMAIL_PENDING


async def test_expired_token_cannot_cancel_a_still_live_application(session: AsyncSession) -> None:
    record = await submit(session, expires=NOW + timedelta(days=30))
    token = await access().issue(session, record.id, now=NOW)
    assert not await access().cancel(session, token, now=NOW + timedelta(days=7))
    assert await access().status(session, token, now=NOW + timedelta(days=7)) is None
    await session.refresh(record)
    assert record.status == RegistrationStatus.EMAIL_PENDING


async def test_concurrent_token_cancellations_have_one_winner(
    app: FastAPI, session: AsyncSession
) -> None:
    record = await submit(session)
    token = await access().issue(session, record.id, now=NOW)

    async def worker() -> bool:
        async with app.state.database.session_factory() as other:
            return await access().cancel(other, token, now=NOW)

    assert sum(await asyncio.gather(worker(), worker())) == 1


@pytest.mark.parametrize("operation", ["issue", "cancel", "revoke"])
async def test_failed_commit_preserves_the_previous_credential(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    record = await submit(session)
    key = record.id
    token = await access().issue(session, key, now=NOW)

    async def fail() -> None:
        raise RuntimeError("Injected commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail)
        value = key if operation == "issue" else token
        options = {} if operation == "revoke" else {"now": NOW}
        with pytest.raises(RuntimeError, match="Injected"):
            await getattr(access(), operation)(session, value, **options)
    await session.rollback()
    assert (
        await access().status(session, token, now=NOW)
    ).status == RegistrationStatus.EMAIL_PENDING
