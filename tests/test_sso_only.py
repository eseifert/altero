"""The instance's SSO-only policy must hold on direct HTTP requests too."""

from datetime import timedelta

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import WebSession
from altero.services import admin, passwordreset, reauth
from tests.test_web_identity import Directory, reauthenticate, signed_in_through_the_directory
from tests.test_web_identity import directory as directory
from tests.test_web_identity import settings as settings
from tests.test_web_routes import PASSWORD, csrf_headers, register


def enable(app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(update={"sso_only": True})


async def test_public_config_closes_every_local_sign_in_path(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    enable(app)
    config = (await client.get("/web/config")).json()
    assert config["ssoOnly"] is True
    assert config["registrationOpen"] is False
    assert config["passwordResetOpen"] is False
    assert config["passkeysAvailable"] is False
    assert config["secondFactors"] == []
    response = await client.post(
        "/web/auth/register",
        json={
            "username": "ada",
            "password": PASSWORD,
            "email": "ada@example.org",
        },
    )
    assert response.status_code == 403  # even the first account


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/web/auth/login", {"username": "ada", "password": PASSWORD}),
        (
            "/web/auth/register",
            {"username": "grace", "password": PASSWORD, "email": "grace@example.org"},
        ),
        ("/web/auth/passkey/options", {}),
        ("/web/auth/passkey/verify", {"credential": {}}),
    ],
)
async def test_local_credentials_are_refused(
    app: FastAPI, client: httpx2.AsyncClient, path: str, body: dict
) -> None:
    await register(client)
    client.cookies.clear()
    enable(app)
    response = await client.post(path, json=body)
    assert response.status_code == 403
    assert "altero_session" not in response.cookies


async def test_existing_local_sessions_and_reset_tokens_cannot_bypass_the_policy(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    await register(client)
    user = await admin.get_user_by_name(session, "ada")
    token = await passwordreset.issue(session, user, issued_by=user)
    enable(app)
    assert (await client.get("/web/auth/session")).status_code == 401
    assert (await client.get(f"/web/auth/reset/{token}")).status_code == 403
    assert (
        await client.post("/web/auth/reset", json={"token": token, "password": PASSWORD + "new"})
    ).status_code == 403
    assert (await client.post("/web/auth/forgot", json={"email": user.email})).status_code == 202


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/web/account/password", {"currentPassword": PASSWORD, "newPassword": PASSWORD + "new"}),
        ("/web/account/email", {"email": "new@example.org", "currentPassword": PASSWORD}),
        ("/web/account/totp", {}),
        ("/web/account/totp/confirm", {"code": "123456"}),
        ("/web/account/email-codes", {"currentPassword": PASSWORD}),
        ("/web/account/passkeys/options", {"currentPassword": PASSWORD}),
        ("/web/auth/verify", {"token": "old-email-token"}),
    ],
)
async def test_sso_sessions_cannot_create_local_authentication_methods(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    directory: Directory,
    path: str,
    body: dict,
) -> None:
    await signed_in_through_the_directory(client, directory, session)
    enable(app)
    assert (await client.get("/web/auth/session")).status_code == 200
    response = await client.post(path, json=body, headers=csrf_headers(client))
    assert response.status_code == 403


async def test_keys_need_recent_sso_proof_even_if_a_password_still_exists(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    directory: Directory,
) -> None:
    await signed_in_through_the_directory(client, directory, session)
    user = await admin.get_user_by_name(session, "grace")
    # Model a linked account that still has a local password, without revoking its session.
    from altero.services.passwords import hash_password

    user.password_hash = hash_password(PASSWORD)
    record = await session.scalar(select(WebSession).where(WebSession.user_id == user.id))
    assert record is not None
    await reauth.stamp(session, record)  # a recent local proof before enabling the flag
    enable(app)
    proof = (await client.get("/web/account/proof")).json()
    assert proof["password"] is False
    assert proof["fresh"] is False
    assert proof["providers"] == [{"slug": "campus", "displayName": "Campus"}]
    body = {"name": "Zotero", "currentPassword": PASSWORD}
    refused = await client.post("/web/account/keys", json=body, headers=csrf_headers(client))
    assert refused.status_code == 403
    await reauthenticate(client, directory)
    created = await client.post(
        "/web/account/keys", json={"name": "Zotero"}, headers=csrf_headers(client)
    )
    assert created.status_code == 201
    key = created.json()["key"]
    assert (
        await client.get(f"/users/{user.id}/items", headers={"Zotero-API-Key": key})
    ).status_code == 200
    assert (await client.get(f"/users/{user.id}/items")).status_code == 403
    await session.refresh(record)
    assert record.sso_reauthenticated is not None
    record.sso_reauthenticated -= timedelta(minutes=6)
    await session.commit()
    expired = await client.post(
        "/web/account/keys", json={"name": "Too late"}, headers=csrf_headers(client)
    )
    assert expired.status_code == 403


@pytest.mark.parametrize("extra_disabled", [False, True])
async def test_sso_only_cannot_unlink_the_last_enabled_provider(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    directory: Directory,
    extra_disabled: bool,
) -> None:
    await signed_in_through_the_directory(client, directory, session)
    from altero.services import federation, passwords
    from tests.test_federation import asserts, make_provider

    user = await admin.get_user_by_name(session, "grace")
    user.password_hash = passwords.hash_password(PASSWORD)
    await session.commit()
    if extra_disabled:
        disabled = await make_provider(session, slug="retired", enabled=False)
        await federation.link(session, user, disabled, asserts(subject="retired-subject"))
    enable(app)
    await reauthenticate(client, directory)
    identities = (await client.get("/web/account/identities")).json()["identities"]
    response = await client.delete(
        f"/web/account/identities/{identities[0]['id']}", headers=csrf_headers(client)
    )
    assert response.status_code == 403


async def test_passwordless_sso_proof_can_restore_a_library(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    directory: Directory,
) -> None:
    from tests.test_web_transfer import personal, seed

    await signed_in_through_the_directory(client, directory, session)
    enable(app)
    user_id = (await client.get("/web/auth/session")).json()["user"]["id"]
    library = await personal(session, user_id)
    await seed(session, library, "SSO restore")
    content = (await client.get(f"/web/libraries/{library.id}/archive")).content
    files = {"archive": ("library.zip", content, "application/zip")}
    data = {"replace": "true"}
    headers = csrf_headers(client)
    url = f"/web/libraries/{library.id}/archive"
    assert (await client.post(url, files=files, data=data, headers=headers)).status_code == 403
    await reauthenticate(client, directory)
    response = await client.post(url, files=files, data=data, headers=headers)
    assert response.status_code == 200, response.text


async def test_sso_policy_survives_disabling_it_again(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    await register(client)
    enable(app)
    assert (await client.get("/web/auth/session")).status_code == 401
    app.state.settings = app.state.settings.model_copy(update={"sso_only": False})
    assert (await client.get("/web/auth/session")).status_code == 200
    client.cookies.clear()
    response = await client.post("/web/auth/login", json={"username": "ada", "password": PASSWORD})
    assert response.status_code == 200


async def test_a_provider_must_still_permit_the_account_when_reauthenticating(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    directory: Directory,
) -> None:
    from altero.models import IdentityProvider

    await signed_in_through_the_directory(client, directory, session)
    enable(app)
    provider = await session.scalar(select(IdentityProvider))
    assert provider is not None
    provider.required_claim = "groups"
    provider.required_value = "staff"
    await session.commit()
    response = await reauthenticate(client, directory)
    assert "error=not-permitted" in response.headers["location"]
    assert (await client.get("/web/account/proof")).json()["fresh"] is False
