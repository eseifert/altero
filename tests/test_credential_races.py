"""One-use credentials remain one-use when two requests read them together.

The barrier holds real database reads at the vulnerable boundary. It does not
hold atomic UPDATE/DELETE statements, which must decide the winner themselves.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import Database
from altero.errors import ForbiddenError, NotFoundError
from altero.models import (
    AuthRequest,
    EmailVerification,
    LoginCode,
    OAuthAuthorizationRequest,
    OAuthCode,
    OAuthDeviceCode,
    OAuthGrant,
    OAuthToken,
    PasswordReset,
    TotpCredential,
    WebAuthnChallenge,
    WebSession,
)
from altero.services import (
    admin,
    authrequests,
    emailverify,
    logincodes,
    oauthserver,
    oidc,
    passkeys,
    passwordreset,
    totp,
    webauth,
    websessions,
)
from tests.authenticator import Authenticator
from tests.test_federation import make_provider
from tests.test_oauth import PUBLIC_URL, REDIRECT, code_from, make_client, pkce
from tests.test_passkeys import PARTY, enrol

Redeem = Callable[[AsyncSession], Awaitable[object]]


async def prepare(session: AsyncSession, kind: str) -> tuple[type[Any], Redeem]:
    user = await admin.create_user(session, username="ada")
    if kind in {"federated", "saml_handoff"}:
        provider = await make_provider(session)
        pending = await authrequests.create(session, provider)
        if kind == "saml_handoff":
            pending.purpose = "link"
            pending.user_id = user.id
            pending = await authrequests.defer_saml(
                session, pending, oidc.Assertion("subject", "ada", "Ada", "")
            )

        async def redeem(session: AsyncSession) -> object:
            return await authrequests.consume(session, pending.state)

        return AuthRequest, redeem
    if kind == "passkey":
        device, _ = await enrol(session, user, Authenticator())
        options = await passkeys.begin_authentication(session, party=PARTY)
        answer = device.authenticate(options, origin=PARTY.origin, rp_id=PARTY.id, advance=False)

        async def redeem(session: AsyncSession) -> object:
            return await passkeys.finish_authentication(session, answer, party=PARTY)

        return WebAuthnChallenge, redeem
    if kind == "reset":
        token = await passwordreset.issue(session, user)

        async def redeem(session: AsyncSession) -> object:
            return await passwordreset.consume(session, token)

        return PasswordReset, redeem
    if kind == "verification":
        token = await emailverify.issue(session, user, "ada@example.org")

        async def redeem(session: AsyncSession) -> object:
            return await emailverify.confirm(session, token)

        return EmailVerification, redeem
    if kind == "email_code":
        _, record = await websessions.create(session, user, pending_factor="email")
        code = await logincodes.issue(session, record)

        async def redeem(session: AsyncSession) -> object:
            record_here = await session.get(WebSession, record.id)
            assert record_here is not None
            await logincodes.verify(session, record_here, code)
            return True

        return LoginCode, redeem
    if kind == "totp":
        secret = await webauth.enrol_totp(session, user, confirm_with=None)
        records = [
            (await websessions.create(session, user, pending_factor="totp"))[1].id for _ in range(2)
        ]
        code = totp.code_at(secret, int(datetime.now(UTC).timestamp()))

        async def redeem(session: AsyncSession) -> object:
            record_here = await session.get(WebSession, records.pop())
            assert record_here is not None
            await webauth.complete_totp(session, record_here, code)
            return True

        return TotpCredential, redeem

    client, _ = await make_client(session)
    session.add(OAuthGrant(user_id=user.id, client_id=client.id, scopes="library.read"))
    await session.commit()
    if kind == "device":
        device = await oauthserver.begin_device(session, client_id="notebook", scope="library.read")
        handle = await oauthserver.claim_user_code(session, device.user_code)
        await oauthserver.approve(session, handle, user)

        async def redeem(session: AsyncSession) -> object:
            return await oauthserver.exchange_device(
                session,
                client_id="notebook",
                client_secret=None,
                device_code=device.device_code,
                public_url=PUBLIC_URL,
            )

        return OAuthDeviceCode, redeem

    verifier, challenge = pkce()
    pending = await oauthserver.begin(
        session,
        client_id="notebook",
        redirect_uri=REDIRECT,
        response_type="code",
        scope="library.read",
        state="",
        nonce="",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    if kind == "consent":

        async def redeem(session: AsyncSession) -> object:
            user_here = await admin.get_user_by_name(session, "ada")
            return await oauthserver.approve(session, pending.handle, user_here)

        return OAuthAuthorizationRequest, redeem
    redirect = await oauthserver.approve(session, pending.handle, user)
    code = code_from(redirect.url)

    async def exchange(session: AsyncSession) -> dict[str, object]:
        return await oauthserver.exchange(
            session,
            client_id="notebook",
            client_secret=None,
            code=code,
            code_verifier=verifier,
            redirect_uri=REDIRECT,
            public_url=PUBLIC_URL,
        )

    if kind == "oauth_code":
        return OAuthCode, exchange
    assert kind == "refresh"
    tokens = await exchange(session)

    async def redeem(session: AsyncSession) -> object:
        return await oauthserver.refresh(
            session,
            client_id="notebook",
            client_secret=None,
            refresh_token=str(tokens["refresh_token"]),
            public_url=PUBLIC_URL,
        )

    return OAuthToken, redeem


def hold_reads(monkeypatch: pytest.MonkeyPatch, model: type[Any], *, count: int = 2) -> None:
    barrier = asyncio.Barrier(count)
    scalar, get = AsyncSession.scalar, AsyncSession.get

    async def held_scalar(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        answer = await scalar(self, statement, *args, **kwargs)
        if isinstance(statement, Select) and model.__table__ in statement.get_final_froms():
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return answer

    async def held_get(self: AsyncSession, entity: Any, *args: Any, **kwargs: Any) -> Any:
        answer = await get(self, entity, *args, **kwargs)
        if entity is model:
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return answer

    monkeypatch.setattr(AsyncSession, "scalar", held_scalar)
    monkeypatch.setattr(AsyncSession, "get", held_get)


@pytest.mark.parametrize(
    "kind",
    [
        "federated",
        "saml_handoff",
        "passkey",
        "reset",
        "verification",
        "email_code",
        "totp",
        "oauth_code",
        "refresh",
        "device",
        "consent",
    ],
)
async def test_a_credential_cannot_be_spent_by_two_requests(
    kind: str,
    session: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, redeem = await prepare(session, kind)
    hold_reads(monkeypatch, model)
    await assert_one_winner(app.state.database, redeem, kind=kind)


async def assert_one_winner(database: Database, redeem: Redeem, *, kind: str) -> None:

    async def attempt() -> object:
        async with database.session_factory() as request:
            try:
                return await redeem(request)
            except ForbiddenError, NotFoundError, oauthserver.OAuthError:
                return None

    outcomes = await asyncio.wait_for(asyncio.gather(attempt(), attempt()), timeout=20)
    assert sum(value is not None for value in outcomes) == 1, outcomes
    if kind in {"oauth_code", "refresh"}:
        # Replay detection must revoke even the winning request's family.
        async with database.session_factory() as fresh:
            active = list(
                await fresh.scalars(select(OAuthToken).where(OAuthToken.revoked_at.is_(None)))
            )
            assert active == []


async def test_parallel_wrong_email_codes_exhaust_the_attempt_budget(
    session: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await admin.create_user(session, username="ada")
    _, record = await websessions.create(session, user, pending_factor="email")
    code = await logincodes.issue(session, record)
    pending = await session.scalar(select(LoginCode))
    assert pending is not None
    pending.attempts = logincodes.MAX_ATTEMPTS - 2
    await session.commit()
    wrong = "000000" if code != "000000" else "111111"
    attempts = 2
    hold_reads(monkeypatch, LoginCode, count=attempts)

    async def guess() -> None:
        async with app.state.database.session_factory() as fresh:
            record_here = await fresh.get(WebSession, record.id)
            assert record_here is not None
            with pytest.raises(ForbiddenError):
                await logincodes.verify(fresh, record_here, wrong)

    await asyncio.wait_for(asyncio.gather(*(guess() for _ in range(attempts))), timeout=20)
    # Stop arranging reads; the next request must be refused even with the
    # real code. This checks the budget, not just the stored counter.
    monkeypatch.undo()
    async with app.state.database.session_factory() as fresh:
        record_here = await fresh.get(WebSession, record.id)
        assert record_here is not None
        with pytest.raises(ForbiddenError):
            await logincodes.verify(fresh, record_here, code)
