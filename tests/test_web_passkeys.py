"""Passkeys over HTTP, with a software authenticator answering for real.

The last class is the one that matters: whatever a passkey is worth as a
credential, it opens a browser session and nothing more. The v3 API still takes
an API key and nothing else.
"""

from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ApiKey, PasskeyCredential, User
from altero.settings import Settings
from tests.authenticator import Authenticator
from tests.test_web_routes import PASSWORD, csrf_headers, register

PUBLIC_URL = "http://testserver"
ORIGIN = "http://testserver"
RP_ID = "testserver"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """An instance whose public URL is the one the test client uses.

    A passkey is bound to it, so the two have to agree or nothing verifies --
    which is the whole reason the server refuses to guess this.
    """
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
        public_url=PUBLIC_URL,
    )


async def enrol(
    client: httpx.AsyncClient, device: Authenticator | None = None, *, name: str = "Laptop"
) -> Authenticator:
    """Run a whole enrolment over HTTP."""
    device = device or Authenticator()
    options = (
        await client.post(
            "/web/account/passkeys/options",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
    ).json()
    answer = device.register(options, origin=ORIGIN, rp_id=RP_ID)
    response = await client.post(
        "/web/account/passkeys",
        json={"credential": answer, "name": name},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return device


async def sign_in(client: httpx.AsyncClient, device: Authenticator) -> httpx.Response:
    """No CSRF header anywhere here: a browser that has never signed in has no
    token to send, and that is exactly the browser this pair is for."""
    options = (await client.post("/web/auth/passkey/options")).json()
    answer = device.authenticate(options, origin=ORIGIN, rp_id=RP_ID)
    return await client.post("/web/auth/passkey/verify", json={"credential": answer})


class TestEnrolling:
    async def test_a_signed_in_account_can_add_one(self, client: httpx.AsyncClient) -> None:
        await register(client)

        await enrol(client)

        body = (await client.get("/web/account/passkeys")).json()
        assert len(body["passkeys"]) == 1
        assert body["passkeys"][0]["name"] == "Laptop"

    async def test_it_takes_the_password_first(self, client: httpx.AsyncClient) -> None:
        """A passkey is a way *in*, so adding one asks for proof exactly as
        making an API key does -- and asks before the authenticator is touched,
        so a refusal does not arrive after a fingerprint."""
        await register(client)

        response = await client.post(
            "/web/account/passkeys/options", json={}, headers=csrf_headers(client)
        )

        assert response.status_code == 403

    async def test_the_wrong_password_is_refused(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post(
            "/web/account/passkeys/options",
            json={"currentPassword": "not it"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403

    async def test_it_needs_the_csrf_token(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post(
            "/web/account/passkeys/options", json={"currentPassword": PASSWORD}
        )

        assert response.status_code == 403


class TestSigningIn:
    async def test_a_browser_that_has_never_signed_in_can_use_one(
        self, client: httpx.AsyncClient
    ) -> None:
        """The CSRF cookie is only set by a sign-in, so requiring the token
        here would make a passkey unusable by exactly the browser it is for."""
        await register(client)
        device = await enrol(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))
        client.cookies.clear()

        options = (await client.post("/web/auth/passkey/options")).json()
        answer = device.authenticate(options, origin=ORIGIN, rp_id=RP_ID)
        response = await client.post("/web/auth/passkey/verify", json={"credential": answer})

        assert response.status_code == 200

    async def test_a_passkey_alone_opens_a_session(self, client: httpx.AsyncClient) -> None:
        await register(client)
        device = await enrol(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        response = await sign_in(client, device)

        assert response.status_code == 200
        assert response.json()["needsFactor"] is None
        assert (await client.get("/web/auth/session")).json()["user"]["username"] == "ada"

    async def test_no_username_is_taken_anywhere(self, client: httpx.AsyncClient) -> None:
        """Which is what makes this page unable to answer whether an account
        exists."""
        await register(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        options = (await client.post("/web/auth/passkey/options")).json()

        assert not options.get("allowCredentials")

    async def test_the_options_look_the_same_whether_or_not_anyone_is_enrolled(
        self, client: httpx.AsyncClient
    ) -> None:
        """Before and after an enrolment, the same shape -- so the endpoint
        cannot be used to ask whether anybody here has a passkey."""
        await register(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))
        before = (await client.post("/web/auth/passkey/options")).json()

        await client.post("/web/auth/login", json={"username": "ada", "password": PASSWORD})
        await enrol(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))
        after = (await client.post("/web/auth/passkey/options")).json()

        assert set(before) == set(after)
        assert before.get("allowCredentials") == after.get("allowCredentials")

    async def test_it_can_change_things_straight_away(self, client: httpx.AsyncClient) -> None:
        """A passkey is the stronger credential, so it counts as proof: making
        an API key right afterwards does not ask for anything more."""
        await register(client)
        device = await enrol(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))
        await sign_in(client, device)

        response = await client.post(
            "/web/account/keys", json={"name": "Zotero"}, headers=csrf_headers(client)
        )

        assert response.status_code == 201

    async def test_a_passkey_nobody_enrolled_is_refused(self, client: httpx.AsyncClient) -> None:
        await register(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))
        stranger = Authenticator(credential_id=b"never-seen-before-0")

        response = await sign_in(client, stranger)

        assert response.status_code == 401


class TestManagingThem:
    async def test_one_can_be_renamed(self, client: httpx.AsyncClient) -> None:
        await register(client)
        await enrol(client)
        stored = (await client.get("/web/account/passkeys")).json()["passkeys"][0]

        response = await client.patch(
            f"/web/account/passkeys/{stored['id']}",
            json={"name": "Yubikey"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 200
        assert response.json()["passkey"]["name"] == "Yubikey"

    async def test_one_can_be_removed_with_the_password(self, client: httpx.AsyncClient) -> None:
        await register(client)
        await enrol(client)
        stored = (await client.get("/web/account/passkeys")).json()["passkeys"][0]

        response = await client.request(
            "DELETE",
            f"/web/account/passkeys/{stored['id']}",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 204
        assert (await client.get("/web/account/passkeys")).json()["passkeys"] == []

    async def test_somebody_elses_is_not_removable(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        from altero.services import admin, webauth, websessions

        await register(client)
        await enrol(client)
        stored = (await client.get("/web/account/passkeys")).json()["passkeys"][0]

        other = await admin.create_user(session, username="grace")
        await webauth.set_password(session, other, PASSWORD)
        token, _ = await websessions.create(session, other)
        client.cookies.set("altero_session", token)

        response = await client.request(
            "DELETE",
            f"/web/account/passkeys/{stored['id']}",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403


class TestTheConfigSaysWhetherTheyWork:
    async def test_an_instance_with_a_public_url_offers_them(
        self, client: httpx.AsyncClient
    ) -> None:
        assert (await client.get("/web/config")).json()["passkeysAvailable"] is True

    async def test_webauthn_is_listed_as_a_factor(self, client: httpx.AsyncClient) -> None:
        assert "webauthn" in (await client.get("/web/config")).json()["secondFactors"]


class TestWithoutAPublicUrl:
    """A passkey is bound to the address it was made at, so an instance that
    cannot say what that is cannot hold one."""

    @pytest.fixture
    def settings(self, tmp_path: Path) -> Settings:
        return Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
            storage_path=tmp_path / "storage",
        )

    async def test_the_page_is_told_not_to_offer_them(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/config")).json()["passkeysAvailable"] is False

    async def test_enrolling_is_refused_rather_than_guessed_at(
        self, client: httpx.AsyncClient
    ) -> None:
        """Guessing would make a passkey that silently stops working the day
        the address changes."""
        await register(client)

        response = await client.post(
            "/web/account/passkeys/options",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 400


class TestTheV3ApiIsStillUntouched:
    async def test_a_passkey_session_does_not_authenticate_a_v3_request(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        device = await enrol(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))
        await sign_in(client, device)
        user = await session.scalar(select(User).where(User.username == "ada"))
        assert user is not None

        response = await client.get(f"/users/{user.id}/items")

        assert response.status_code in (401, 403)

    async def test_signing_in_hands_out_no_api_key(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A desktop client still takes its key from Settings, as it always
        did -- a passkey changes what the browser accepts, not the sync API."""
        await register(client)
        device = await enrol(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))
        await sign_in(client, device)

        assert list(await session.scalars(select(ApiKey))) == []

    async def test_the_credential_row_holds_no_secret(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        device = await enrol(client)

        stored = await session.scalar(select(PasskeyCredential))

        assert stored is not None
        private = device.key.private_numbers().private_value.to_bytes(32, "big")
        from tests.authenticator import b64

        assert b64(private) not in stored.public_key
