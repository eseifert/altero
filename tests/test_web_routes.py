"""The web interface's own endpoints.

These live under ``/web`` and speak cookies. The v3 API speaks API keys and is
not touched by any of it -- there is a test below that holds that line, because
a session cookie that could drive the sync API would be a second way in to
every library and a CSRF target with the whole protocol behind it.
"""

from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from altero.services import admin, totp, webauth

PASSWORD = "correct horse battery staple"

#: Sent with every unsafe request the way the browser client does.
CSRF_HEADER = "X-CSRF-Token"


async def register(client: httpx.AsyncClient, username: str = "ada") -> httpx.Response:
    return await client.post(
        "/web/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "email": f"{username}@example.org",
            "displayName": "Ada",
        },
    )


def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """Return the double-submit header matching the cookie the client holds."""
    return {CSRF_HEADER: client.cookies.get("altero_csrf") or ""}


class TestRegistration:
    async def test_the_first_registration_succeeds_and_signs_the_browser_in(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await register(client)

        assert response.status_code == 201
        assert response.json()["user"]["username"] == "ada"
        assert client.cookies.get("altero_session")

    async def test_the_session_cookie_is_not_readable_by_script(
        self, client: httpx.AsyncClient
    ) -> None:
        """The token is the credential; script must not be able to lift it."""
        response = await register(client)

        cookie = next(
            h for h in response.headers.get_list("set-cookie") if "altero_session" in h
        ).lower()
        # Attribute names and values are case-insensitive per RFC 6265.
        assert "httponly" in cookie
        assert "samesite=lax" in cookie

    async def test_the_csrf_cookie_is_readable_by_script(self, client: httpx.AsyncClient) -> None:
        """It has to be, so the client can echo it back in a header."""
        response = await register(client)

        cookie = next(
            h for h in response.headers.get_list("set-cookie") if "altero_csrf" in h
        ).lower()
        assert "httponly" not in cookie

    async def test_a_second_registration_is_refused(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await register(client, username="grace")

        assert response.status_code == 403

    async def test_a_short_password_is_refused_with_a_readable_message(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/web/auth/register",
            json={"username": "ada", "password": "short", "email": "ada@example.org"},
        )

        assert response.status_code == 400
        assert "8" in response.json()["message"]


class TestConfig:
    async def test_the_client_can_ask_whether_registration_is_open(
        self, client: httpx.AsyncClient
    ) -> None:
        """So the sign-in page knows whether to offer a register link at all."""
        assert (await client.get("/web/config")).json()["registrationOpen"] is True

        await register(client)

        assert (await client.get("/web/config")).json()["registrationOpen"] is False

    async def test_the_config_endpoint_needs_no_credential(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/web/config")

        assert response.status_code == 200
        assert "totp" in response.json()["secondFactors"]


class TestLogin:
    async def test_the_right_password_signs_in(self, client: httpx.AsyncClient) -> None:
        await register(client)
        client.cookies.clear()

        response = await client.post(
            "/web/auth/login", json={"username": "ada", "password": PASSWORD}
        )

        assert response.status_code == 200
        assert response.json()["needsFactor"] is None
        assert client.cookies.get("altero_session")

    async def test_the_wrong_password_answers_401(self, client: httpx.AsyncClient) -> None:
        await register(client)
        client.cookies.clear()

        response = await client.post(
            "/web/auth/login", json={"username": "ada", "password": "wrong password"}
        )

        assert response.status_code == 401
        assert not client.cookies.get("altero_session")

    async def test_an_unknown_user_answers_exactly_the_same(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)
        client.cookies.clear()

        unknown = await client.post(
            "/web/auth/login", json={"username": "nobody", "password": PASSWORD}
        )
        wrong = await client.post(
            "/web/auth/login", json={"username": "ada", "password": "wrong password"}
        )

        assert unknown.status_code == wrong.status_code
        assert unknown.json() == wrong.json()


class TestSession:
    async def test_the_current_session_reports_the_signed_in_user(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.get("/web/auth/session")

        assert response.status_code == 200
        assert response.json()["user"]["username"] == "ada"
        assert response.json()["user"]["id"] == 1

    async def test_no_cookie_means_401(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/auth/session")).status_code == 401

    async def test_a_forged_cookie_means_401(self, client: httpx.AsyncClient) -> None:
        client.cookies.set("altero_session", "made up", domain="testserver")

        assert (await client.get("/web/auth/session")).status_code == 401

    async def test_signing_out_ends_the_session(self, client: httpx.AsyncClient) -> None:
        await register(client)
        headers = csrf_headers(client)

        response = await client.post("/web/auth/logout", headers=headers)

        assert response.status_code == 204
        assert (await client.get("/web/auth/session")).status_code == 401

    async def test_signing_out_twice_is_not_an_error(self, client: httpx.AsyncClient) -> None:
        await register(client)
        headers = csrf_headers(client)
        await client.post("/web/auth/logout", headers=headers)

        assert (await client.post("/web/auth/logout", headers=headers)).status_code == 204


class TestCrossSiteRequestForgery:
    async def test_an_unsafe_request_without_the_header_is_refused(
        self, client: httpx.AsyncClient
    ) -> None:
        """A form posted from another origin carries the cookie but cannot read it."""
        await register(client)

        response = await client.post("/web/auth/logout")

        assert response.status_code == 403
        assert (await client.get("/web/auth/session")).status_code == 200

    async def test_a_mismatched_token_is_refused(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.post("/web/auth/logout", headers={CSRF_HEADER: "not it"})

        assert response.status_code == 403

    async def test_a_safe_request_needs_no_token(self, client: httpx.AsyncClient) -> None:
        await register(client)

        assert (await client.get("/web/auth/session")).status_code == 200

    async def test_signing_in_needs_no_token(self, client: httpx.AsyncClient) -> None:
        """There is no session to forge a request against yet."""
        await register(client)
        client.cookies.clear()

        response = await client.post(
            "/web/auth/login", json={"username": "ada", "password": PASSWORD}
        )

        assert response.status_code == 200


class TestSecondFactor:
    async def test_a_pending_session_is_not_signed_in(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        user = await admin.get_user_by_name(session, "ada")
        secret = await webauth.enrol_totp(session, user, confirm_with=None)
        client.cookies.clear()

        response = await client.post(
            "/web/auth/login", json={"username": "ada", "password": PASSWORD}
        )

        assert response.status_code == 200
        assert response.json()["needsFactor"] == "totp"
        assert (await client.get("/web/auth/session")).status_code == 401
        assert secret

    async def test_the_right_code_finishes_signing_in(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        user = await admin.get_user_by_name(session, "ada")
        secret = await webauth.enrol_totp(session, user, confirm_with=None)
        client.cookies.clear()
        await client.post("/web/auth/login", json={"username": "ada", "password": PASSWORD})

        response = await client.post(
            "/web/auth/totp",
            json={"code": totp.code_at(secret, _now())},
            headers=csrf_headers(client),
        )

        assert response.status_code == 200
        assert (await client.get("/web/auth/session")).status_code == 200

    async def test_the_wrong_code_answers_401_and_leaves_it_pending(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        user = await admin.get_user_by_name(session, "ada")
        await webauth.enrol_totp(session, user, confirm_with=None)
        client.cookies.clear()
        await client.post("/web/auth/login", json={"username": "ada", "password": PASSWORD})

        response = await client.post(
            "/web/auth/totp", json={"code": "000000"}, headers=csrf_headers(client)
        )

        assert response.status_code == 401
        assert (await client.get("/web/auth/session")).status_code == 401


class TestTheV3ApiIsUntouched:
    """The sync API's contract is the reason this project exists.

    A session cookie must not reach it. If it did there would be two ways to
    authenticate every library endpoint, and the browser would attach one of
    them to any request an attacker could cause it to make.
    """

    async def test_a_session_cookie_does_not_authenticate_a_v3_request(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.get("/users/1/items")

        assert response.status_code == 403

    async def test_an_api_key_still_works_untouched(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        key = await admin.create_api_key(session, username="ada", name="laptop")

        response = await client.get("/users/1/items", headers={"Zotero-API-Key": key.key})

        assert response.status_code == 200

    async def test_an_api_key_does_not_authenticate_a_web_request(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """And not the other way round either: the web session is its own thing."""
        await register(client)
        key = await admin.create_api_key(session, username="ada", name="laptop")
        client.cookies.clear()

        response = await client.get("/web/auth/session", headers={"Zotero-API-Key": key.key})

        assert response.status_code == 401


def _now() -> int:
    return int(datetime.now(UTC).timestamp())
