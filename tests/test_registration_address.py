"""An applicant changing mailboxes must prove the new one before review."""

import asyncio
from datetime import timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import RegistrationStatus
from altero.services import registrations
from tests.factories import make_user
from tests.test_registration_email import consume, token_for
from tests.test_registration_policy import policy
from tests.test_registrations import NOW, POLICY, submit


async def change(session: AsyncSession, key: int, email: str, **options: object) -> bool:
    function = getattr(registrations, "change_email", None)
    assert callable(function), "Pending mailbox changes must recheck eligibility and revoke proof"
    return await function(session, key, email, **{"policy": POLICY, "now": NOW, **options})


@pytest.mark.parametrize("verified", [False, True])
async def test_a_changed_address_requires_a_new_proof(
    session: AsyncSession, verified: bool
) -> None:
    record = await submit(session)
    first = await token_for(session, record)
    if verified:
        assert await consume(session, first)
    assert await change(session, record.id, " NEW@EXAMPLE.ORG ")
    await session.refresh(record)
    assert record.email == record.reserved_email == "new@example.org"
    assert record.status == RegistrationStatus.EMAIL_PENDING
    assert record.email_verified is record.email_token_hash is None
    assert record.email_token_address is record.email_token_expires is None
    assert record.expires == NOW + timedelta(days=1)
    assert not await consume(session, first)
    assert await consume(session, await token_for(session, record))
    assert (await submit(session, username="Other")).email == "ada@example.org"


async def test_the_same_normalized_address_keeps_its_proof_and_review_state(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    assert not await change(session, record.id, " ADA@EXAMPLE.ORG ")
    assert await consume(session, token)
    assert not await change(session, record.id, record.email)
    await session.refresh(record)
    assert record.status == RegistrationStatus.REVIEW_PENDING
    assert record.email_verified == NOW


@pytest.mark.parametrize("email", ["other@example.org", " ADA@EXAMPLE.ORG "])
async def test_address_changes_recheck_the_current_domain_policy(
    session: AsyncSession, email: str
) -> None:
    record = await submit(session)
    token = await token_for(session, record)
    with pytest.raises(ForbiddenError):
        await change(session, record.id, email, policy=policy("elsewhere.example"))
    assert await consume(session, token)


async def test_an_address_reserved_by_another_request_is_unavailable(session: AsyncSession) -> None:
    record = await submit(session)
    other = await submit(session, username="Other", email="other@example.org")
    token = await token_for(session, record)
    with pytest.raises(InvalidInputError, match="unavailable"):
        await change(session, record.id, other.email)
    assert await consume(session, token)


async def test_an_existing_accounts_address_cannot_be_reserved(session: AsyncSession) -> None:
    await make_user(session, email="other@example.org")
    await session.commit()
    record = await submit(session)
    token = await token_for(session, record)
    with pytest.raises(InvalidInputError, match="unavailable"):
        await change(session, record.id, " OTHER@EXAMPLE.ORG ")
    assert await consume(session, token)


async def test_competing_changes_reserve_one_mailbox(app: FastAPI, session: AsyncSession) -> None:
    first = await submit(session)
    second = await submit(session, username="Other", email="other@example.org")

    async def worker(key: int) -> bool:
        async with app.state.database.session_factory() as other:
            try:
                return await change(other, key, "shared@example.org")
            except InvalidInputError:
                return False

    assert sum(await asyncio.gather(worker(first.id), worker(second.id))) == 1


async def test_changing_address_races_safely_with_old_proof_consumption(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    record = await submit(session)
    token = await token_for(session, record)

    async def edit() -> bool:
        async with app.state.database.session_factory() as other:
            return await change(other, record.id, "new@example.org")

    async def verify() -> bool:
        async with app.state.database.session_factory() as other:
            return await consume(other, token)

    edited, _ = await asyncio.gather(edit(), verify())
    assert edited
    await session.refresh(record)
    assert record.email == "new@example.org"
    assert record.status == RegistrationStatus.EMAIL_PENDING
    assert record.email_verified is record.email_token_hash is None


async def test_failed_address_commit_preserves_proof_and_expiry_cleanup(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = await submit(session)
    key = record.id
    token = await token_for(session, record)
    old = await submit(
        session, username="Old", email="old@example.org", now=NOW - timedelta(days=1), expires=NOW
    )

    async def fail() -> None:
        raise RuntimeError("Injected commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            await change(session, key, "new@example.org")
    await session.rollback()
    await session.refresh(old)
    assert old.status == RegistrationStatus.EMAIL_PENDING
    assert old.reserved_email == "old@example.org"
    assert await consume(session, token)


async def test_cancelled_expired_and_missing_requests_cannot_change_address(
    session: AsyncSession,
) -> None:
    record = await submit(session)
    assert not await change(session, record.id + 100, "new@example.org")
    assert not await change(session, record.id, "new@example.org", now=record.expires)
    await session.refresh(record)
    assert record.status == RegistrationStatus.EXPIRED
    fresh = await submit(session)
    assert await registrations.cancel(session, fresh.id, now=NOW)
    assert not await change(session, fresh.id, "new@example.org")
