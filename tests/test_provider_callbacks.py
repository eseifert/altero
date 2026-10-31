"""The administration screen must show the callback for the chosen protocol."""

from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI

from altero.settings import Settings
from tests.test_web_identity import Directory
from tests.test_web_routes import PASSWORD, csrf_headers, register

PUBLIC_URL = "https://bibliography.example.org"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
        public_url=PUBLIC_URL,
    )


@pytest.mark.parametrize("kind", ["oidc", "saml"])
@pytest.mark.parametrize("operation", ["create", "list", "update"])
async def test_provider_replies_show_the_protocols_callback(
    app: FastAPI,
    client: httpx2.AsyncClient,
    kind: str,
    operation: str,
) -> None:
    directory = Directory()
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(directory.handle)) as outbound:
        app.state.http_client = outbound
        await register(client)
        created = await client.post(
            "/web/admin/providers",
            headers=csrf_headers(client),
            json={
                "slug": "campus",
                "kind": kind,
                "issuer": "https://sso.example.org",
                "clientId": "altero",
                "idpEntityId": "https://saml.example.org",
                "ssoUrl": "https://saml.example.org/sso",
                "certificates": "fixture-certificate",
                "currentPassword": PASSWORD,
            },
        )
        assert created.status_code == 201
        if operation == "create":
            provider = created.json()["provider"]
        elif operation == "list":
            listed = await client.get("/web/admin/providers")
            assert listed.status_code == 200
            provider = listed.json()["providers"][0]
        else:
            updated = await client.patch(
                "/web/admin/providers/campus",
                headers=csrf_headers(client),
                json={"displayName": "Campus", "currentPassword": PASSWORD},
            )
            assert updated.status_code == 200
            provider = updated.json()["provider"]
    expected = "/web/auth/saml/campus/acs" if kind == "saml" else "/web/auth/sso/campus/callback"
    assert provider["redirectUri"] == PUBLIC_URL + expected
