"""Applicant cookies authenticate no account and authorize only their own request."""

from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.services import registrationaccess
from tests.factories import make_user
from tests.test_registrations import POLICY
from tests.test_web_routes import register

COOKIE = "altero_applicant"
CSRF = "altero_applicant_csrf"
PATH = "/web/registration"


async def applicant(session: AsyncSession, *, expires: datetime | None = None) -> tuple[int, str]:
    now = datetime.now(UTC).replace(tzinfo=None)
    record, token = await registrationaccess.submit(
        session,
        username="Ada",
        email="ada@example.org",
        expires=expires or now + timedelta(days=2),
        enabled=True,
        policy=POLICY,
    )
    return record.id, token


async def test_status_reaches_only_its_application_and_sets_separate_csrf(
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    await make_user(session)
    key, token = await applicant(session)
    client.cookies.set(COOKIE, token)
    result = await client.get(PATH)
    assert result.status_code == 200
    assert set(result.json()) == {"requestID", "status", "expires"}
    assert result.json()["requestID"] == key
    assert result.json()["status"] == "email_pending"
    assert result.headers["cache-control"] == "no-store"
    assert client.cookies.get(CSRF)
    assert not client.cookies.get("altero_session")
    assert not client.cookies.get("altero_csrf")
    assert (await client.get("/web/auth/session")).status_code == 401
    assert (await client.get("/web/libraries")).status_code == 401
    assert (await client.get("/users/1/items")).status_code == 403


@pytest.mark.parametrize("credential", [None, "unknown", "account"])
async def test_non_applicant_credentials_cannot_read_status(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    credential: str | None,
) -> None:
    _, token = await applicant(session)
    if credential == "account":
        client.cookies.set("altero_session", token)
    elif credential:
        client.cookies.set(COOKIE, credential)
    assert (
        await client.get(
            PATH, headers={"Zotero-API-Key": token, "Authorization": "Bearer " + token}
        )
    ).status_code == 401


@pytest.mark.parametrize("action", ["cancel", "logout"])
async def test_applicant_writes_require_their_own_csrf_and_then_succeed(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    action: str,
) -> None:
    _, token = await applicant(session)
    client.cookies.set(COOKIE, token)
    assert (await client.get(PATH)).status_code == 200
    assert (await client.post(PATH + "/" + action)).status_code == 403
    assert (
        await client.post(PATH + "/" + action, headers={"X-CSRF-Token": "wrong"})
    ).status_code == 403
    # An attacker-chosen matching pair must not authorize a write.
    genuine = client.cookies.get(CSRF)
    assert genuine
    client.cookies.clear()
    client.cookies.set(COOKIE, token)
    client.cookies.set(CSRF, "chosen")
    assert (
        await client.post(PATH + "/" + action, headers={"X-CSRF-Token": "chosen"})
    ).status_code == 403
    client.cookies.clear()
    client.cookies.set(COOKIE, token)
    client.cookies.set(CSRF, genuine)
    result = await client.post(PATH + "/" + action, headers={"X-CSRF-Token": genuine})
    assert result.status_code == 204
    if action == "cancel":
        assert (await client.get(PATH)).json()["status"] == "cancelled"
    else:
        assert await registrationaccess.status(session, token) is None
        assert (await client.get(PATH)).status_code == 401


async def test_applicant_logout_preserves_an_existing_account_session(
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    _, token = await applicant(session)
    assert (await register(client, "operator")).status_code == 201
    account_cookie = client.cookies.get("altero_session")
    account_csrf = client.cookies.get("altero_csrf")
    client.cookies.set(COOKIE, token)
    assert (await client.get(PATH)).status_code == 200
    csrf = client.cookies.get(CSRF)
    assert csrf
    assert (await client.post(PATH + "/logout", headers={"X-CSRF-Token": csrf})).status_code == 204
    assert client.cookies.get("altero_session") == account_cookie
    assert client.cookies.get("altero_csrf") == account_csrf
    assert (await client.get("/web/auth/session")).status_code == 200


async def test_rotated_applicant_token_cannot_read_or_cancel(
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    key, token = await applicant(session)
    client.cookies.set(COOKIE, token)
    assert (await client.get(PATH)).status_code == 200
    csrf = client.cookies.get(CSRF)
    assert csrf
    assert await registrationaccess.issue(session, key)
    assert (await client.get(PATH)).status_code == 401
    assert (await client.post(PATH + "/cancel", headers={"X-CSRF-Token": csrf})).status_code == 401
