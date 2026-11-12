"""Only an approved applicant can set the first password, once."""

import asyncio
from datetime import timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import User
from altero.services import passwords, registrationaccess, registrationadmission
from tests.test_registration_review import reviewer, verified
from tests.test_registrations import NOW, POLICY

SECRET = "this is an uncommon enrollment passphrase"


async def approved(session: AsyncSession) -> tuple[int, str]:
    actor = await reviewer(session)
    record = await verified(session)
    token = await registrationaccess.issue(session, record.id, now=NOW)
    assert token
    key = await registrationadmission.approve(
        session, record.id, actor_id=actor.id, policy=POLICY, now=NOW
    )
    assert key
    return key, token


async def enroll(
    session: AsyncSession, token: str, secret: str = SECRET, **options: object
) -> bool:
    function = getattr(registrationadmission, "enroll", None)
    assert callable(function), "Approved applicant enrollment must be implemented"
    return await function(session, token, secret, **{"now": NOW, **options})


async def test_enrollment_sets_the_password_once_and_revokes_applicant_access(
    session: AsyncSession,
) -> None:
    key, token = await approved(session)
    assert await enroll(session, token)
    user = await session.get(User, key)
    assert user
    assert passwords.verify_password(user.password_hash, SECRET)
    assert await registrationaccess.status(session, token, now=NOW) is None
    assert not await enroll(session, token, "a different long enrollment passphrase")


async def test_expired_or_revoked_tokens_cannot_enroll(session: AsyncSession) -> None:
    key, token = await approved(session)
    assert not await enroll(session, token, now=NOW + timedelta(days=7))
    assert await registrationaccess.revoke(session, token)
    assert not await enroll(session, token)
    user = await session.get(User, key)
    assert user
    assert user.password_hash is None


async def test_operator_password_and_suspension_cannot_be_overridden(session: AsyncSession) -> None:
    key, token = await approved(session)
    user = await session.get(User, key)
    assert user
    user.disabled_at = NOW
    await session.commit()
    assert not await enroll(session, token)
    user.disabled_at = None
    user.password_hash = passwords.hash_password("an operator provisioned long passphrase")
    await session.commit()
    assert not await enroll(session, token)


async def test_failed_enrollment_preserves_the_token_and_passwordless_account(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, token = await approved(session)

    async def fail() -> None:
        raise RuntimeError("Injected commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            await enroll(session, token)
    user = await session.get(User, key)
    assert user
    assert user.password_hash is None
    assert await registrationaccess.status(session, token, now=NOW)
    assert await enroll(session, token)


async def test_competing_enrollments_cannot_replace_the_winning_password(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    key, token = await approved(session)

    async def worker(suffix: str) -> bool:
        async with app.state.database.session_factory() as other:
            return await enroll(other, token, SECRET + suffix)

    results = await asyncio.gather(worker(" first"), worker(" second"))
    assert sum(results) == 1
    user = await session.get(User, key)
    assert user
    winning = " first" if results[0] else " second"
    assert passwords.verify_password(user.password_hash, SECRET + winning)
