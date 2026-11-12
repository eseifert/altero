"""The public flow exposes mailbox proof, not account availability or pending accounts."""

from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.models import User
from altero.services import admin, invitations, webauth
from altero.services.mail import Message
from altero.settings import Settings
from tests.factories import make_group


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/db.sqlite",
        storage_path=tmp_path / "storage",
        smtp_url="smtp://localhost",
        public_url="https://trusted.example",
        registration_approval=True,
        open_registration=True,
    )


class Mailbox:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def send(self, message: Message) -> bool:
        self.messages.append(message)
        return True


@pytest.fixture(autouse=True)
async def seeded(app: FastAPI, session: AsyncSession) -> None:
    user = await admin.create_user(session, username="operator")
    user.email = "owner@example.org"
    await webauth.set_password(session, user, "correct horse battery staple")
    app.state.mailer = Mailbox()


async def test_public_submission_waits_for_mailbox_proof_without_issuing_a_cookie(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    response = await client.post(
        "/web/registration/apply", json={"username": "Ada", "email": "ada@example.org"}
    )
    assert response.status_code == 202
    assert not client.cookies.get("altero_applicant")
    assert await session.scalar(select(func.count()).select_from(User)) == 1
    proof = app.state.mailer.messages[0].body.split("#token=")[1].split()[0]
    verified = await client.post("/web/registration/verify", json={"token": proof})
    assert verified.status_code == 200
    assert client.cookies.get("altero_applicant")
    assert (await client.get("/web/registration")).json()["status"] == "review_pending"
    assert (await client.get("/web/auth/session")).status_code == 401
    assert (await client.post("/web/registration/verify", json={"token": proof})).status_code == 400


async def test_legacy_registration_cannot_bypass_approval(client: httpx2.AsyncClient) -> None:
    result = await client.post(
        "/web/auth/register",
        json={
            "username": "Ada",
            "email": "ada@example.org",
            "password": "correct horse battery staple",
        },
    )
    assert result.status_code == 403


async def test_new_and_existing_email_acknowledgments_have_identical_shape(
    client: httpx2.AsyncClient,
) -> None:
    first = await client.post(
        "/web/registration/apply", json={"username": "Ada", "email": "ada@example.org"}
    )
    other = await client.post(
        "/web/registration/apply", json={"username": "Other", "email": "owner@example.org"}
    )
    assert first.status_code == other.status_code == 202
    assert first.content == other.content
    assert first.headers.get_list("set-cookie") == other.headers.get_list("set-cookie") == []


async def test_closed_registration_acknowledges_without_sending_mail_or_reserving(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"open_registration": False})
    assert (
        await client.post(
            "/web/registration/apply", json={"username": "Ada", "email": "ada@example.org"}
        )
    ).status_code == 202
    assert app.state.mailer.messages == []


@pytest.mark.parametrize(
    ("field", "value"), [("username", "ada\x00"), ("email", "ada\x00@example.org")]
)
async def test_invalid_text_is_refused_before_sql_lookup(
    client: httpx2.AsyncClient,
    field: str,
    value: str,
) -> None:
    body = {"username": "Ada", "email": "ada@example.org", field: value}
    assert (await client.post("/web/registration/apply", json=body)).status_code == 400


async def test_links_use_public_url_and_https_cookies_have_the_right_scope(
    app: FastAPI,
    client: httpx2.AsyncClient,
) -> None:
    response = await client.post(
        "https://untrusted.example/web/registration/apply",
        json={"username": "Ada", "email": "ada@example.org"},
    )
    assert response.status_code == 202
    message = app.state.mailer.messages[0]
    assert "https://trusted.example/app/registration#token=" in message.body
    assert "untrusted.example" not in message.body
    proof = message.body.split("#token=")[1].split()[0]
    verified = await client.post(
        "https://untrusted.example/web/registration/verify", json={"token": proof}
    )
    cookie = next(
        h for h in verified.headers.get_list("set-cookie") if h.startswith("altero_applicant=")
    )
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "Path=/web/registration" in cookie


async def test_invitation_opens_a_gated_request_but_never_bypasses_approval(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    owner = await session.get(User, 1)
    assert owner
    group = await make_group(session, owner_id=owner.id)
    await invitations.invite(session, library=group, inviter=owner, email="ada@example.org")
    app.state.settings = app.state.settings.model_copy(update={"open_registration": False})
    body = {
        "username": "Ada",
        "email": "ada@example.org",
        "password": "correct horse battery staple",
    }
    assert (await client.post("/web/auth/register", json=body)).status_code == 403
    assert (await client.post("/web/registration/apply", json=body)).status_code == 202
    assert "#token=" in app.state.mailer.messages[0].body
    assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_first_account_bootstrap_remains_explicit_and_only_once(
    settings: Settings,
    tmp_path: Path,
) -> None:
    fresh = create_app(
        settings.model_copy(update={"database_url": f"sqlite+aiosqlite:///{tmp_path}/fresh.sqlite"})
    )
    await fresh.state.database.create_all()
    fresh.state.mailer = Mailbox()
    try:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=fresh), base_url="http://testserver"
        ) as browser:
            body = {
                "username": "owner",
                "email": "owner@example.org",
                "password": "correct horse battery staple",
            }
            response = await browser.post("/web/auth/register", json=body)
            assert response.status_code == 201
            assert response.json()["user"]["administrator"] is True
            assert (
                await browser.post(
                    "/web/auth/register",
                    json={**body, "username": "second", "email": "second@example.org"},
                )
            ).status_code == 403
    finally:
        await fresh.state.database.dispose()


async def verify_application(app: FastAPI, client: httpx2.AsyncClient) -> tuple[int, str]:
    assert (
        await client.post(
            "/web/registration/apply", json={"username": "Ada", "email": "ada@example.org"}
        )
    ).status_code == 202
    proof = app.state.mailer.messages[-1].body.split("#token=")[1].split()[0]
    assert (await client.post("/web/registration/verify", json={"token": proof})).status_code == 200
    status = await client.get("/web/registration")
    csrf = client.cookies.get("altero_applicant_csrf")
    assert csrf
    return status.json()["requestID"], csrf


async def test_approval_and_enrollment_keep_credential_realms_separate(
    app: FastAPI,
    client: httpx2.AsyncClient,
) -> None:
    key, applicant_csrf = await verify_application(app, client)
    assert (await client.get("/web/admin/registrations")).status_code == 401
    assert (
        await client.post(
            "/web/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
    ).status_code == 200
    queue = await client.get("/web/admin/registrations")
    assert [r["id"] for r in queue.json()["requests"]] == [key]
    assert (
        await client.post(f"/web/admin/registrations/{key}/approve", json={})
    ).status_code == 403
    headers = {"X-CSRF-Token": client.cookies.get("altero_csrf") or ""}
    assert (
        await client.post(
            f"/web/admin/registrations/{key}/approve",
            json={"currentPassword": "correct horse battery staple"},
            headers=headers,
        )
    ).status_code == 204
    assert (await client.get("/web/registration")).json()["status"] == "approved"
    password = "an uncommon new approved account password"
    assert (
        await client.post("/web/registration/enroll", json={"password": password}, headers=headers)
    ).status_code == 403
    assert (
        await client.post(
            "/web/registration/enroll",
            json={"password": password},
            headers={"X-CSRF-Token": applicant_csrf},
        )
    ).status_code == 200
    assert not client.cookies.get("altero_applicant")
    assert (await client.get("/web/auth/session")).json()["user"]["username"] == "operator"
    client.cookies.clear()
    signed = await client.post("/web/auth/login", json={"username": "Ada", "password": password})
    assert signed.status_code == 200
    assert signed.json()["user"]["administrator"] is False
    assert (await client.get("/web/libraries")).status_code == 200


async def test_rejection_remains_visible_and_never_allows_enrollment(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    key, applicant_csrf = await verify_application(app, client)
    assert (
        await client.post(
            "/web/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
    ).status_code == 200
    headers = {"X-CSRF-Token": client.cookies.get("altero_csrf") or ""}
    assert (
        await client.post(f"/web/admin/registrations/{key}/reject", headers=headers)
    ).status_code == 204
    assert (await client.get("/web/registration")).json()["status"] == "rejected"
    assert (
        await client.post(
            "/web/registration/enroll",
            json={"password": "an uncommon rejected account password"},
            headers={"X-CSRF-Token": applicant_csrf},
        )
    ).status_code == 409
    assert await session.scalar(select(func.count()).select_from(User)) == 1
