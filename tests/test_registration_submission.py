"""Submission must not reserve an identity without its applicant credential."""

import asyncio
from datetime import timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError
from altero.models import RegistrationRequest, RegistrationStatus, User
from altero.services import registrationaccess
from tests.test_registrations import NOW, POLICY, submit


async def apply(session: AsyncSession, **changes: object) -> tuple[RegistrationRequest, str]:
    function = getattr(registrationaccess, "submit", None)
    assert callable(function), "Submission and applicant-token issuance must share one commit"
    return await function(
        session,
        **{
            "username": "Ada",
            "email": "ada@example.org",
            "expires": NOW + timedelta(days=1),
            "enabled": True,
            "policy": POLICY,
            "now": NOW,
            **changes,
        },
    )


async def test_submission_returns_one_committed_request_and_its_applicant_token(
    session: AsyncSession,
) -> None:
    record, token = await apply(session)
    assert record.id
    result = await registrationaccess.status(session, token, now=NOW)
    assert result is not None
    assert result.request_id == record.id
    await session.refresh(record)
    assert record.applicant_token_hash
    assert record.email_token_hash is record.email_verified is None
    assert await session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize("failure", ["token", "commit"])
async def test_failed_submission_preserves_prior_reservations_and_allows_retry(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    old = await submit(
        session, username="Old", email="old@example.org", now=NOW - timedelta(days=1), expires=NOW
    )

    def broken_token(*args: object) -> str:
        raise RuntimeError("Injected token failure")

    async def broken_commit() -> None:
        raise RuntimeError("Injected commit failure")

    with monkeypatch.context() as patch:
        if failure == "token":
            patch.setattr(registrationaccess.secrets, "token_urlsafe", broken_token)
        else:
            patch.setattr(session, "commit", broken_commit)
        with pytest.raises(RuntimeError, match="Injected"):
            await apply(session)
    # The operation must roll itself back; a caller rollback here would hide
    # a transaction left partly applied or an early cleanup commit.
    await session.refresh(old)
    assert old.status == RegistrationStatus.EMAIL_PENDING
    assert old.reserved_email == "old@example.org"
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 1
    assert (await apply(session))[0].username == "Ada"


async def test_competing_submissions_leave_one_request_with_a_usable_token(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    async def worker() -> str | None:
        async with app.state.database.session_factory() as other:
            try:
                return (await apply(other))[1]
            except InvalidInputError:
                return None

    tokens = [t for t in await asyncio.gather(worker(), worker()) if t]
    assert len(tokens) == 1
    assert await registrationaccess.status(session, tokens[0], now=NOW)
    assert await session.scalar(select(func.count()).select_from(RegistrationRequest)) == 1
