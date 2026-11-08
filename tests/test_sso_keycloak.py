"""SSO-only policy against real HTTP and a real OIDC/SAML identity provider."""

from pathlib import Path

import pytest

from altero.app import create_app
from altero.settings import Settings
from tests.idp.http import ALTERO_URL, live_browser
from tests.test_keycloak import HTTP_USER_AGENT, configure, sign_in
from tests.test_keycloak import keycloak as keycloak
from tests.test_web_routes import PASSWORD, csrf_headers


@pytest.mark.parametrize("kind", ["oidc", "saml"])
async def test_real_sso_only_sessions_reauthenticate_without_a_local_password(
    keycloak: str,
    tmp_path: Path,
    kind: str,
) -> None:
    app = create_app(
        Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'sso.sqlite'}",
            storage_path=tmp_path / "storage",
            public_url=ALTERO_URL,
        )
    )
    async with live_browser(tmp_path, headers={"User-Agent": HTTP_USER_AGENT}, app=app) as browser:
        await configure(browser, keycloak, kind, createAccounts=False)
        await sign_in(browser, keycloak, kind, purpose="link")
        app.state.settings = app.state.settings.model_copy(update={"sso_only": True})
        assert (await browser.get("/web/auth/session")).status_code == 401
        assert (
            await browser.post("/web/auth/login", json={"username": "ada", "password": PASSWORD})
        ).status_code == 403
        browser.cookies.clear()
        response = await sign_in(browser, keycloak, kind)
        assert response.status_code == 303
        user = (await browser.get("/web/auth/session")).json()["user"]
        proof = (await browser.get("/web/account/proof")).json()
        assert proof["password"] is False
        assert proof["fresh"] is False
        assert (
            await browser.post(
                "/web/account/keys",
                json={"name": "desktop", "currentPassword": PASSWORD},
                headers=csrf_headers(browser),
            )
        ).status_code == 403
        proved = await sign_in(browser, keycloak, kind, purpose="reauth")
        assert proved.status_code == 303
        created = await browser.post(
            "/web/account/keys", json={"name": "desktop"}, headers=csrf_headers(browser)
        )
        assert created.status_code == 201
        auth = {"Zotero-API-Key": created.json()["key"]}
        written = await browser.post(
            f"/users/{user['id']}/items",
            headers=auth,
            json=[{"itemType": "book", "title": "SSO-only live HTTP"}],
        )
        assert written.status_code == 200
        library = (await browser.get("/web/libraries")).json()[0]
        url = f"/web/libraries/{library['id']}/archive"
        archive = await browser.get(url)
        assert archive.status_code == 200
        restored = await browser.post(
            url,
            files={"archive": ("library.zip", archive.content, "application/zip")},
            data={"replace": "true"},
            headers=csrf_headers(browser),
        )
        assert restored.status_code == 200, restored.text
