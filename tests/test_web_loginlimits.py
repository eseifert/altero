"""Credential backoff through the actual browser endpoints."""

from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.models import User
from altero.services import logincodes, loginlimits, passwords, totp, webauth
from tests.factories import make_api_key
from tests.test_login_codes import Outbox, code_from
from tests.test_web_routes import PASSWORD, csrf_headers, register


@pytest.fixture
def moment(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    clock = [datetime.now(UTC).replace(tzinfo=None)]
    monkeypatch.setattr(loginlimits, "_now", lambda: clock[0])
    return clock


async def login(client: httpx2.AsyncClient, username: str = "ada", password: str = "wrong"):
    return await client.post("/web/auth/login", json={"username": username, "password": password})


async def test_password_aliases_share_one_budget_and_wait_before_hashing(
    client: httpx2.AsyncClient,
    moment: list[datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register(client)
    client.cookies.clear()
    for name in ["ada", "ADA", " ada ", "ADA@EXAMPLE.ORG", "ada@example.org"]:
        assert (await login(client, name)).status_code == 401

    def unexpected_hash(*args):
        pytest.fail("A refused guess must not run Argon2")

    with monkeypatch.context() as patch:
        patch.setattr(passwords, "verify_password", unexpected_hash)
        response = await login(client, password=PASSWORD)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.json() == {"message": "Too many sign-in attempts. Try again shortly."}
    assert not client.cookies.get("altero_session")

    moment[0] += timedelta(seconds=1)
    assert (await login(client, password=PASSWORD)).status_code == 200
    # Success resets the account and refunds itself, so a typo can be retried.
    assert (await login(client)).status_code == 401
    assert (await login(client, password=PASSWORD)).status_code == 200


@pytest.mark.parametrize("name", ["ada", "nobody"])
async def test_unknown_and_known_accounts_have_the_same_backoff(
    client: httpx2.AsyncClient,
    moment: list[datetime],
    name: str,
) -> None:
    await register(client)
    for _ in range(5):
        assert (await login(client, name)).status_code == 401
    assert (await login(client, name)).status_code == 429


async def test_spoofed_forwarding_headers_cannot_buy_a_fresh_address_budget(
    client: httpx2.AsyncClient,
    moment: list[datetime],
) -> None:
    for number in range(20):
        response = await client.post(
            "/web/auth/login",
            json={"username": f"unknown-{number}", "password": "wrong"},
            headers={"X-Forwarded-For": f"192.0.2.{number}"},
        )
        assert response.status_code == 401
    response = await login(client, "another")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/web/config")).status_code == 200


async def test_another_application_instance_sees_failed_logins(
    app: FastAPI,
    client: httpx2.AsyncClient,
    moment: list[datetime],
) -> None:
    for _ in range(5):
        assert (await login(client, "unknown")).status_code == 401
    other = create_app(app.state.settings)
    try:
        # Also change address: the account budget, not just the address, persists.
        transport = httpx2.ASGITransport(app=other, client=("192.0.2.2", 12345))
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as worker:
            response = await login(worker, "UNKNOWN")
            assert response.status_code == 429
    finally:
        await other.state.database.dispose()


async def test_a_login_pause_does_not_revoke_existing_sessions_or_api_keys(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    moment: list[datetime],
) -> None:
    await register(client)
    key = "L" * 24
    await make_api_key(session, key=key, user_id=1)
    for _ in range(5):
        assert (await login(client)).status_code == 401
    assert (await login(client)).status_code == 429
    assert (await client.get("/web/libraries")).status_code == 200
    response = await client.get("/users/1/items", headers={"Zotero-API-Key": key})
    assert response.status_code == 200


@pytest.mark.parametrize("factor", ["totp", "email"])
async def test_second_factor_budget_survives_a_new_session_and_resends(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    moment: list[datetime],
    factor: str,
) -> None:
    await register(client)
    user = await session.scalar(select(User).where(User.username == "ada"))
    assert user is not None
    if factor == "totp":
        await webauth.enrol_totp(session, user, confirm_with=None)
    else:
        user.email_verified = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()
        await logincodes.enrol(session, user)
    wrong = "invalid"
    path = "/web/auth/totp" if factor == "totp" else "/web/auth/code"
    response = await login(client, password=PASSWORD)
    assert response.json()["needsFactor"] == factor
    for _ in range(5):
        response = await client.post(path, json={"code": wrong}, headers=csrf_headers(client))
        assert response.status_code == 401
    assert (await login(client, password=PASSWORD)).json()["needsFactor"] == factor
    if factor == "email":
        assert (
            await client.post("/web/auth/code/resend", headers=csrf_headers(client))
        ).status_code == 202
    response = await client.post(path, json={"code": wrong}, headers=csrf_headers(client))
    assert response.status_code == 429
    assert (await client.get("/web/libraries")).status_code == 401
    moment[0] += timedelta(seconds=1)
    response = await client.post(path, json={"code": wrong}, headers=csrf_headers(client))
    assert response.status_code == 401
    response = await client.post(path, json={"code": wrong}, headers=csrf_headers(client))
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"


async def test_switching_second_factor_cannot_reset_the_budget(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    moment: list[datetime],
) -> None:
    await register(client)
    user = await session.scalar(select(User))
    assert user is not None
    await webauth.enrol_totp(session, user, confirm_with=None)
    user.email_verified = moment[0]
    await session.commit()
    await logincodes.enrol(session, user)
    assert (await login(client, password=PASSWORD)).json()["needsFactor"] == "totp"
    for _ in range(5):
        assert (
            await client.post(
                "/web/auth/totp",
                json={"code": "invalid"},
                headers=csrf_headers(client),
            )
        ).status_code == 401
    assert (
        await client.post(
            "/web/auth/factor",
            json={"factor": "email"},
            headers=csrf_headers(client),
        )
    ).status_code == 200
    response = await client.post(
        "/web/auth/code",
        json={"code": "invalid"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 429


async def test_csrf_failure_does_not_spend_a_factor_attempt(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    moment: list[datetime],
) -> None:
    await register(client)
    user = await session.scalar(select(User))
    assert user is not None
    secret = await webauth.enrol_totp(session, user, confirm_with=None)
    await login(client, password=PASSWORD)
    for _ in range(6):
        assert (await client.post("/web/auth/totp", json={"code": "invalid"})).status_code == 403
    code = totp.code_at(secret, int(datetime.now(UTC).timestamp()))
    response = await client.post(
        "/web/auth/totp", json={"code": code}, headers=csrf_headers(client)
    )
    assert response.status_code == 200


@pytest.mark.parametrize("factor", ["totp", "email"])
async def test_successful_second_factor_resets_its_account_budget(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    moment: list[datetime],
    factor: str,
) -> None:
    outbox = Outbox()
    app.state.mailer = outbox
    await register(client)
    user = await session.scalar(select(User))
    assert user is not None
    if factor == "totp":
        secret = await webauth.enrol_totp(session, user, confirm_with=None)
    else:
        user.email_verified = moment[0]
        await session.commit()
        await logincodes.enrol(session, user)
    path = "/web/auth/totp" if factor == "totp" else "/web/auth/code"
    await login(client, password=PASSWORD)
    for _ in range(4):
        assert (
            await client.post(
                path,
                json={"code": "invalid"},
                headers=csrf_headers(client),
            )
        ).status_code == 401
    right = (
        totp.code_at(secret, int(datetime.now(UTC).timestamp()))
        if factor == "totp"
        else code_from(outbox)
    )
    assert (
        await client.post(
            path,
            json={"code": right},
            headers=csrf_headers(client),
        )
    ).status_code == 200
    assert (await client.get("/web/libraries")).status_code == 200
    await login(client, password=PASSWORD)
    for _ in range(5):
        assert (
            await client.post(
                path,
                json={"code": "invalid"},
                headers=csrf_headers(client),
            )
        ).status_code == 401
    assert (
        await client.post(
            path,
            json={"code": "invalid"},
            headers=csrf_headers(client),
        )
    ).status_code == 429
