"""Credential-bearing links must never take their origin from a request."""

from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.errors import InvalidInputError
from altero.services import admin
from altero.settings import Settings
from tests.test_password_reset import Outbox
from tests.test_web_routes import PASSWORD, csrf_headers, register


def test_smtp_without_a_public_url_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="ALTERO_PUBLIC_URL"):
        create_app(Settings(smtp_url="smtp://localhost:2525", public_url=""))


@pytest.mark.parametrize("public_url", ["", "https://library.example.org/altero/"])
@pytest.mark.parametrize("kind", ["verification", "reset", "invitation"])
async def test_account_links_ignore_request_hosts(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    public_url: str,
    kind: str,
) -> None:
    # No SMTP here: without a configured origin, logs and the administrator's
    # reset screen get a relative path to open on the instance itself.
    app.state.settings = app.state.settings.model_copy(update={"public_url": public_url})
    outbox = Outbox()
    app.state.mailer = outbox
    await register(client)
    headers = csrf_headers(client) | {
        "Host": "attacker.example",
        "Forwarded": "host=attacker.example;proto=https",
        "X-Forwarded-Host": "attacker.example",
        "X-Forwarded-Proto": "https",
    }
    outbox.sent.clear()

    if kind == "verification":
        response = await client.post("/web/auth/verify/resend", headers=headers)
        assert response.status_code == 202
        path = "/app/verify"
    elif kind == "reset":
        user = await admin.get_user_by_name(session, "ada")
        response = await client.post(
            f"/web/admin/users/{user.id}/reset",
            json={"currentPassword": PASSWORD},
            headers=headers,
        )
        assert response.status_code == 200
        link = response.json()["link"]
        assert link.startswith(f"{public_url.rstrip('/')}/app/reset?token=")
        token = parse_qs(urlsplit(link).query)["token"][0]
        # A poisoned origin would expose a working password-setting token.
        reset = await client.post(
            "/web/auth/reset", json={"token": token, "password": "a new password for ada"}
        )
        assert reset.status_code == 200
        return
    else:
        library = await admin.create_group(session, name="Research", owner_username="ada")
        response = await client.post(
            f"/web/libraries/{library.id}/invitations",
            json={"email": "grace@example.org"},
            headers=headers,
        )
        assert response.status_code == 201
        path = "/app/invitations"

    assert len(outbox.sent) == 1
    body = outbox.sent[0].body
    assert f"    {public_url.rstrip('/')}{path}?token=" in body
    assert "attacker.example" not in body
