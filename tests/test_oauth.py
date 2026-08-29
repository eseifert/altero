"""The authorization server, exercised mostly by trying to break it.

The happy path is one class here and the other nine are attacks, which is the
proportion the subject deserves: an OAuth server that works is easy, and an
OAuth server that works *and refuses everything else* is the entire job. Each
class below names the thing it stops, and several of them exist because the
implementation this replaces did not stop them.
"""

import base64
import hashlib
import json
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.errors import InvalidInputError
from altero.models import TotpCredential, User
from altero.models.oauth import OAuthClient, OAuthCode, OAuthToken
from altero.services import admin, jws, oauthclients, oauthserver, webauth
from altero.settings import Settings
from tests.factories import make_group, make_user

CSRF_HEADER = "X-CSRF-Token"
PASSWORD = "correct horse battery staple"
PUBLIC_URL = "https://library.example.org"
REDIRECT = "https://app.example.com/callback"
SIGNED_OUT = "https://app.example.com/signed-out"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with a public URL, which the authorization server requires.

    Required rather than defaulted: see :func:`altero.services.oauthserver.issuer`.
    ``TestTheIssuerIsNotTakenFromTheRequest`` below is the test that holds it.
    """
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
        public_url=PUBLIC_URL,
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    await application.state.database.create_all()
    yield application
    await application.state.database.dispose()


def pkce() -> tuple[str, str]:
    """Return a verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return verifier, challenge


async def make_client(
    session: AsyncSession,
    *,
    client_id: str = "notebook",
    redirect_uris: list[str] | None = None,
    scopes: str = "openid profile email groups library.read library.write files.read notes.read",
    confidential: bool = False,
    post_logout_redirect_uris: list[str] | None = None,
) -> tuple[OAuthClient, str | None]:
    return await oauthclients.create(
        session,
        client_id=client_id,
        name="Notebook",
        redirect_uris=redirect_uris or [REDIRECT],
        scopes=scopes,
        description="Reads your library into a notebook",
        confidential=confidential,
        post_logout_redirect_uris=(
            [SIGNED_OUT] if post_logout_redirect_uris is None else post_logout_redirect_uris
        ),
    )


async def make_account(client: httpx.AsyncClient, username: str = "ada") -> int:
    """Register an account through the interface and leave the browser signed in."""
    response = await client.post(
        "/web/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "email": f"{username}@example.org",
            "displayName": "Ada Lovelace",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies.get("altero_csrf") or ""}


async def authorize(
    client: httpx.AsyncClient,
    *,
    challenge: str,
    client_id: str = "notebook",
    redirect_uri: str = REDIRECT,
    scope: str = "openid library.read",
    state: str = "opaque-state",
    nonce: str = "",
    method: str = "S256",
) -> httpx.Response:
    return await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": method,
            **({"nonce": nonce} if nonce else {}),
        },
        follow_redirects=False,
    )


async def grant(client: httpx.AsyncClient, handle: str, approve: bool = True) -> str:
    """Approve a pending authorization and return where the browser is sent."""
    response = await client.post(
        f"/web/oauth/pending/{handle}",
        json={"approve": approve},
        headers=csrf(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["redirect"]


def code_from(redirect: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(redirect).query)["code"][0]


async def full_flow(
    client: httpx.AsyncClient,
    session: AsyncSession,
    *,
    scope: str = "openid library.read",
    nonce: str = "",
) -> dict:
    """Register a client and an account, walk the whole flow, return the tokens."""
    await make_client(session)
    await make_account(client)
    return await walk_flow(client, scope=scope, nonce=nonce)


async def walk_flow(
    client: httpx.AsyncClient,
    *,
    scope: str = "openid library.read",
    nonce: str = "",
) -> dict:
    """Walk the flow for a client and an account that already exist."""
    verifier, challenge = pkce()

    started = await authorize(client, challenge=challenge, scope=scope, nonce=nonce)
    handle = started.headers["location"].split("request=")[1]
    redirect = await grant(client, handle)

    tokens = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "notebook",
            "code": code_from(redirect),
            "code_verifier": verifier,
            "redirect_uri": REDIRECT,
        },
    )
    assert tokens.status_code == 200, tokens.text
    return tokens.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def claims_of(id_token: str) -> dict:
    """Return an ID token's payload without verifying it.

    Only for tests that are about *what* is claimed. That the signature holds
    is ``TestTheIdToken`` above, and it does the verification properly.
    """
    payload = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


async def only_user(session: AsyncSession) -> User:
    """Return the one account these tests make."""
    user = await session.scalar(select(User))
    assert user is not None
    return user


# --------------------------------------------------------------------------


class TestTheRedirectUriIsMatchedAgainstTheRegistration:
    """The check that decides whether this is an authorization server or a phish.

    The code is handed to the browser. The only thing that keeps it from being
    handed to somebody else is that its destination was written down before the
    request arrived.
    """

    async def test_an_unregistered_redirect_uri_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        _, challenge = pkce()

        response = await authorize(
            client, challenge=challenge, redirect_uri="https://attacker.example/steal"
        )

        assert response.status_code == 403
        assert "not a redirect URI registered" in response.text

    async def test_the_refusal_does_not_redirect_to_the_address_it_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """RFC 6749 §4.1.2.1. Bouncing the error off it makes an open redirector."""
        await make_client(session)
        _, challenge = pkce()

        response = await authorize(
            client, challenge=challenge, redirect_uri="https://attacker.example/steal"
        )

        assert "location" not in response.headers

    async def test_an_unknown_client_is_refused_and_does_not_register_itself(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        _, challenge = pkce()

        response = await authorize(client, challenge=challenge, client_id="invented")

        assert response.status_code == 404
        assert (
            await session.scalar(select(OAuthClient).where(OAuthClient.client_id == "invented"))
            is None
        )

    async def test_a_disabled_client_stops_working(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        registered, _ = await make_client(session)
        registered.disabled_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()
        _, challenge = pkce()

        assert (await authorize(client, challenge=challenge)).status_code == 404

    async def test_a_loopback_port_may_differ_as_rfc_8252_requires(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A native application is given its port by the operating system."""
        await make_client(session, redirect_uris=["http://127.0.0.1:1/callback"])
        await make_account(client)
        _, challenge = pkce()

        response = await authorize(
            client, challenge=challenge, redirect_uri="http://127.0.0.1:54321/callback"
        )

        assert response.status_code == 303
        assert "/app/authorize?request=" in response.headers["location"]

    async def test_the_loopback_exception_does_not_widen_the_path(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session, redirect_uris=["http://127.0.0.1:1/callback"])
        _, challenge = pkce()

        response = await authorize(
            client, challenge=challenge, redirect_uri="http://127.0.0.1:54321/elsewhere"
        )

        assert response.status_code == 403

    async def test_the_loopback_exception_does_not_widen_to_another_host(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session, redirect_uris=["http://127.0.0.1:1/callback"])
        _, challenge = pkce()

        response = await authorize(
            client, challenge=challenge, redirect_uri="http://attacker.example:80/callback"
        )

        assert response.status_code == 403

    async def test_plain_http_to_the_open_internet_cannot_be_registered(
        self, session: AsyncSession
    ) -> None:
        with pytest.raises(Exception, match="plain http"):
            await make_client(session, redirect_uris=["http://app.example.com/callback"])

    async def test_a_redirect_uri_with_a_fragment_cannot_be_registered(
        self, session: AsyncSession
    ) -> None:
        with pytest.raises(Exception, match="fragment"):
            await make_client(session, redirect_uris=["https://app.example.com/cb#token"])


class TestSigningInGoesThroughTheOneDoor:
    """``/oauth/authorize`` authenticates nobody, which is why it is safe.

    A second password form would be a second place for the second factor to be
    forgotten. Here there is no form at all: the browser is handed to the
    interface, which signs people in the way everything else does.
    """

    async def test_authorize_takes_no_credentials_and_hands_over_to_the_interface(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        _, challenge = pkce()

        response = await authorize(client, challenge=challenge)

        assert response.status_code == 303
        assert response.headers["location"].startswith("/app/authorize?request=")
        assert "password" not in response.text.lower()

    async def test_a_pending_authorization_cannot_be_read_without_a_cookie(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        _, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]

        response = await client.get(f"/web/oauth/pending/{handle}")

        assert response.status_code == 401

    async def test_an_account_with_a_second_factor_cannot_be_bypassed_here(
        self, client: httpx.AsyncClient, session: AsyncSession, app: FastAPI
    ) -> None:
        """The hole this replaces: a password-only form beside the real one.

        There is no way to express the bypass as a request, because there is no
        endpoint that takes a password. Approving requires a session, and a
        session for an account with a confirmed authenticator is one that
        answered it.
        """
        await make_client(session)
        user_id = await make_account(client)
        user = await session.get(User, user_id)
        assert user is not None
        await webauth.enrol_totp(session, user, confirm_with=None)
        credential = await session.get(TotpCredential, user_id)
        assert credential is not None
        credential.confirmed = True
        await session.commit()

        # A fresh browser: signing in now owes a second factor.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as fresh:
            signed_in = await fresh.post(
                "/web/auth/login", json={"username": "ada", "password": PASSWORD}
            )
            assert signed_in.status_code == 200
            assert signed_in.json()["needsFactor"] == "totp"

            _, challenge = pkce()
            started = await authorize(fresh, challenge=challenge)
            handle = started.headers["location"].split("request=")[1]

            refused = await fresh.post(
                f"/web/oauth/pending/{handle}", json={"approve": True}, headers=csrf(fresh)
            )

        assert refused.status_code == 401

    async def test_approving_needs_the_csrf_token(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        await make_account(client)
        _, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]

        response = await client.post(
            f"/web/oauth/pending/{handle}", json={"approve": True}, headers={CSRF_HEADER: "not it"}
        )

        assert response.status_code == 403


class TestTheConsentScreenDescribesTheStoredRequest:
    """What is shown comes from the store, never from the link that opened it."""

    async def test_it_reports_what_was_asked_for(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        await make_account(client)
        _, challenge = pkce()
        started = await authorize(client, challenge=challenge, scope="openid library.read")
        handle = started.headers["location"].split("request=")[1]

        described = (await client.get(f"/web/oauth/pending/{handle}")).json()

        assert described["name"] == "Notebook"
        assert described["clientId"] == "notebook"
        assert described["scopes"] == ["openid", "library.read"]
        assert described["alreadyGranted"] is False

    async def test_a_handle_that_was_never_issued_is_not_found(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_account(client)

        response = await client.get("/web/oauth/pending/invented")

        assert response.status_code == 404

    async def test_a_second_authorization_for_the_same_scopes_is_already_granted(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await full_flow(client, session)
        _, challenge = pkce()
        started = await authorize(client, challenge=challenge, scope="openid library.read")
        handle = started.headers["location"].split("request=")[1]

        described = (await client.get(f"/web/oauth/pending/{handle}")).json()

        assert described["alreadyGranted"] is True
        assert described["newScopes"] == []

    async def test_asking_for_more_reports_only_what_is_new(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await full_flow(client, session)
        _, challenge = pkce()
        started = await authorize(
            client, challenge=challenge, scope="openid library.read library.write"
        )
        handle = started.headers["location"].split("request=")[1]

        described = (await client.get(f"/web/oauth/pending/{handle}")).json()

        assert described["alreadyGranted"] is False
        assert described["newScopes"] == ["library.write"]


class TestScopesGrantExactlyWhatTheySay:
    """The hole this replaces let ``openid`` read every library on the instance."""

    async def test_openid_alone_reaches_no_library(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")
        user_id = (await only_user(session)).id

        response = await client.get(
            f"/users/{user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert tokens["scope"] == "openid"
        assert response.status_code == 403

    async def test_openid_alone_reaches_no_file(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")
        user_id = (await only_user(session)).id

        response = await client.get(
            f"/users/{user_id}/items/AAAAAAAA/file", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 403

    async def test_openid_alone_answers_a_subject_and_nothing_else(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")

        claims = (
            await client.get("/oauth/userinfo", headers=bearer(tokens["access_token"]))
        ).json()

        assert set(claims) == {"sub"}

    async def test_profile_adds_a_name_and_email_adds_an_address(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid profile email")

        claims = (
            await client.get("/oauth/userinfo", headers=bearer(tokens["access_token"]))
        ).json()

        assert claims["preferred_username"] == "ada"
        assert claims["name"] == "Ada Lovelace"
        assert claims["email"] == "ada@example.org"
        assert claims["email_verified"] is False

    async def test_library_read_reads_and_does_not_write(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid library.read")
        user_id = (await only_user(session)).id
        headers = bearer(tokens["access_token"])

        assert (await client.get(f"/users/{user_id}/items", headers=headers)).status_code == 200
        wrote = await client.post(
            f"/users/{user_id}/items",
            headers={**headers, "Zotero-Write-Token": "0" * 32},
            json=[{"itemType": "book", "title": "Refused"}],
        )
        assert wrote.status_code == 403

    async def test_library_write_reaches_the_library(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid library.read library.write")
        user_id = (await only_user(session)).id

        wrote = await client.post(
            f"/users/{user_id}/items",
            headers={**bearer(tokens["access_token"]), "Zotero-Write-Token": "0" * 32},
            json=[{"itemType": "book", "title": "Allowed"}],
        )

        assert wrote.status_code == 200

    async def test_write_without_read_is_refused_rather_than_silently_useless(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        _, challenge = pkce()

        response = await authorize(client, challenge=challenge, scope="openid library.write")

        assert response.status_code == 303
        assert "error=invalid_scope" in response.headers["location"]

    async def test_a_scope_the_client_is_not_registered_for_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session, scopes="openid library.read")
        _, challenge = pkce()

        response = await authorize(
            client, challenge=challenge, scope="openid library.read library.write"
        )

        assert "error=invalid_scope" in response.headers["location"]

    async def test_an_unknown_scope_is_refused_rather_than_dropped(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """An application asking for annotations.write has a belief about this server."""
        await make_client(session)
        _, challenge = pkce()

        response = await authorize(client, challenge=challenge, scope="openid annotations.write")

        assert "error=invalid_scope" in response.headers["location"]

    async def test_a_scope_error_goes_to_the_registered_address(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Once the address is known good, the application is told at it."""
        await make_client(session)
        _, challenge = pkce()

        response = await authorize(client, challenge=challenge, scope="openid nonsense")

        assert response.headers["location"].startswith(REDIRECT)
        assert "state=opaque-state" in response.headers["location"]


class TestPkceCannotBeTurnedOff:
    async def test_plain_is_refused(self, client: httpx.AsyncClient, session: AsyncSession) -> None:
        await make_client(session)
        _, challenge = pkce()

        response = await authorize(client, challenge=challenge, method="plain")

        assert "error=invalid_request" in response.headers["location"]

    async def test_plain_is_not_advertised(self, client: httpx.AsyncClient) -> None:
        document = (await client.get("/.well-known/openid-configuration")).json()

        assert document["code_challenge_methods_supported"] == ["S256"]

    async def test_a_missing_challenge_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)

        response = await authorize(client, challenge="")

        assert "error=invalid_request" in response.headers["location"]

    async def test_the_wrong_verifier_does_not_redeem_the_code(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        await make_account(client)
        _, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]
        redirect = await grant(client, handle)

        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "notebook",
                "code": code_from(redirect),
                "code_verifier": secrets.token_urlsafe(48),
                "redirect_uri": REDIRECT,
            },
        )

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"


class TestTheAuthorizationCode:
    async def test_the_whole_flow_produces_a_working_token(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session)
        user_id = (await only_user(session)).id

        response = await client.get(
            f"/users/{user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 200
        assert tokens["token_type"] == "Bearer"
        assert tokens["expires_in"] == 3600

    async def test_a_code_is_single_use(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        await make_account(client)
        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]
        redirect = await grant(client, handle)
        body = {
            "grant_type": "authorization_code",
            "client_id": "notebook",
            "code": code_from(redirect),
            "code_verifier": verifier,
            "redirect_uri": REDIRECT,
        }
        assert (await client.post("/oauth/token", data=body)).status_code == 200

        replayed = await client.post("/oauth/token", data=body)

        assert replayed.status_code == 400
        assert replayed.json()["error"] == "invalid_grant"

    async def test_replaying_a_code_revokes_what_the_first_exchange_produced(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """RFC 6749 §4.1.2. The assertion, not just that the replay is refused."""
        await make_client(session)
        user_id = await make_account(client)
        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]
        redirect = await grant(client, handle)
        body = {
            "grant_type": "authorization_code",
            "client_id": "notebook",
            "code": code_from(redirect),
            "code_verifier": verifier,
            "redirect_uri": REDIRECT,
        }
        first = (await client.post("/oauth/token", data=body)).json()
        assert (
            await client.get(f"/users/{user_id}/items", headers=bearer(first["access_token"]))
        ).status_code == 200

        await client.post("/oauth/token", data=body)

        after = await client.get(f"/users/{user_id}/items", headers=bearer(first["access_token"]))
        assert after.status_code == 403

    async def test_a_mismatched_redirect_uri_is_refused_at_the_exchange(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session, redirect_uris=[REDIRECT, "https://app.example.com/other"])
        await make_account(client)
        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]
        redirect = await grant(client, handle)

        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "notebook",
                "code": code_from(redirect),
                "code_verifier": verifier,
                "redirect_uri": "https://app.example.com/other",
            },
        )

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    async def test_another_client_cannot_spend_the_code(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        await make_client(session, client_id="thief", redirect_uris=["https://thief.example/cb"])
        await make_account(client)
        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]
        redirect = await grant(client, handle)

        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "thief",
                "code": code_from(redirect),
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
            },
        )

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    async def test_an_expired_code_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        await make_account(client)
        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]
        redirect = await grant(client, handle)

        stored = await session.scalar(select(OAuthCode))
        assert stored is not None
        stored.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "notebook",
                "code": code_from(redirect),
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
            },
        )

        assert response.json()["error"] == "invalid_grant"

    async def test_refusing_tells_the_application_rather_than_leaving_it_waiting(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        await make_account(client)
        _, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]

        redirect = await grant(client, handle, approve=False)

        assert redirect.startswith(REDIRECT)
        assert "error=access_denied" in redirect
        assert "state=opaque-state" in redirect


class TestTheIdToken:
    async def test_it_is_issued_only_when_openid_was_asked_for(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        with_openid = await full_flow(client, session, scope="openid library.read")
        assert "id_token" in with_openid

    async def test_it_verifies_under_the_published_key_set(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The check a client makes. Anything less does not test a signature."""
        tokens = await full_flow(client, session, scope="openid")
        keys = (await client.get("/oauth/jwks.json")).json()["keys"]

        header_segment, payload_segment, signature_segment = tokens["id_token"].split(".")
        header = json.loads(base64.urlsafe_b64decode(header_segment + "=="))
        jwk = next(key for key in keys if key["kid"] == header["kid"])
        public = rsa.RSAPublicNumbers(
            e=int.from_bytes(base64.urlsafe_b64decode(jwk["e"] + "=="), "big"),
            n=int.from_bytes(base64.urlsafe_b64decode(jwk["n"] + "==="), "big"),
        ).public_key()

        public.verify(
            base64.urlsafe_b64decode(signature_segment + "=" * (-len(signature_segment) % 4)),
            f"{header_segment}.{payload_segment}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        assert header["alg"] == "RS256"

    async def test_a_tampered_id_token_does_not_verify(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """What gives the test above its teeth."""
        from cryptography.exceptions import InvalidSignature

        tokens = await full_flow(client, session, scope="openid")
        keys = (await client.get("/oauth/jwks.json")).json()["keys"]
        header_segment, _, signature_segment = tokens["id_token"].split(".")
        header = json.loads(base64.urlsafe_b64decode(header_segment + "=="))
        jwk = next(key for key in keys if key["kid"] == header["kid"])
        public = rsa.RSAPublicNumbers(
            e=int.from_bytes(base64.urlsafe_b64decode(jwk["e"] + "=="), "big"),
            n=int.from_bytes(base64.urlsafe_b64decode(jwk["n"] + "==="), "big"),
        ).public_key()
        forged = base64.urlsafe_b64encode(b'{"sub":"999"}').decode().rstrip("=")

        with pytest.raises(InvalidSignature):
            public.verify(
                base64.urlsafe_b64decode(signature_segment + "=" * (-len(signature_segment) % 4)),
                f"{header_segment}.{forged}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )

    async def test_its_claims_say_who_issued_it_and_for_whom(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid", nonce="n-0S6_WzA2Mj")
        user_id = (await only_user(session)).id

        claims = json.loads(base64.urlsafe_b64decode(tokens["id_token"].split(".")[1] + "=="))

        assert claims["iss"] == PUBLIC_URL
        assert claims["aud"] == "notebook"
        assert claims["sub"] == str(user_id)
        assert claims["nonce"] == "n-0S6_WzA2Mj"
        assert claims["exp"] > claims["iat"]
        assert "auth_time" in claims

    async def test_the_at_hash_ties_it_to_the_access_token(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")

        claims = json.loads(base64.urlsafe_b64decode(tokens["id_token"].split(".")[1] + "=="))

        digest = hashlib.sha256(tokens["access_token"].encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest[:16]).decode().rstrip("=")
        assert claims["at_hash"] == expected

    async def test_identity_claims_are_gated_by_scope(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")

        claims = json.loads(base64.urlsafe_b64decode(tokens["id_token"].split(".")[1] + "=="))

        assert "email" not in claims
        assert "preferred_username" not in claims


class TestRefreshRotation:
    async def test_a_refresh_produces_a_new_pair(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        first = await full_flow(client, session)

        second = (
            await client.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": "notebook",
                    "refresh_token": first["refresh_token"],
                },
            )
        ).json()

        assert second["access_token"] != first["access_token"]
        assert second["refresh_token"] != first["refresh_token"]
        assert second["scope"] == first["scope"]

    async def test_replaying_a_rotated_refresh_token_kills_the_whole_family(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The assertion that matters: the token rotated *to* must also die."""
        first = await full_flow(client, session)
        user_id = (await only_user(session)).id
        second = (
            await client.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": "notebook",
                    "refresh_token": first["refresh_token"],
                },
            )
        ).json()
        assert (
            await client.get(f"/users/{user_id}/items", headers=bearer(second["access_token"]))
        ).status_code == 200

        replayed = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "notebook",
                "refresh_token": first["refresh_token"],
            },
        )

        assert replayed.status_code == 400
        after = await client.get(f"/users/{user_id}/items", headers=bearer(second["access_token"]))
        assert after.status_code == 403
        again = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "notebook",
                "refresh_token": second["refresh_token"],
            },
        )
        assert again.status_code == 400

    async def test_an_expired_refresh_token_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session)
        stored = await session.scalar(select(OAuthToken).where(OAuthToken.kind == "refresh"))
        assert stored is not None
        stored.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "notebook",
                "refresh_token": tokens["refresh_token"],
            },
        )

        assert response.json()["error"] == "invalid_grant"

    async def test_another_client_cannot_rotate_it(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session)
        await make_client(session, client_id="thief", redirect_uris=["https://thief.example/cb"])

        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "thief",
                "refresh_token": tokens["refresh_token"],
            },
        )

        assert response.json()["error"] == "invalid_grant"

    async def test_an_unsupported_grant_type_says_so(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        response = await client.post(
            "/oauth/token", data={"grant_type": "password", "client_id": "notebook"}
        )

        assert response.status_code == 400
        assert response.json()["error"] == "unsupported_grant_type"


class TestConfidentialClients:
    async def test_the_secret_is_required(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        _, secret = await make_client(session, confidential=True)
        assert secret is not None
        await make_account(client)
        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]
        redirect = await grant(client, handle)

        without = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "notebook",
                "code": code_from(redirect),
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
            },
        )

        assert without.status_code == 401
        assert without.json()["error"] == "invalid_client"

    async def test_the_right_secret_works(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        _, secret = await make_client(session, confidential=True)
        await make_account(client)
        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge)
        handle = started.headers["location"].split("request=")[1]
        redirect = await grant(client, handle)

        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "notebook",
                "client_secret": secret,
                "code": code_from(redirect),
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
            },
        )

        assert response.status_code == 200

    async def test_the_secret_is_stored_only_as_a_hash(self, session: AsyncSession) -> None:
        registered, secret = await make_client(session, confidential=True)

        assert secret is not None
        assert registered.secret_hash is not None
        assert secret not in registered.secret_hash


class TestRevocation:
    async def test_revoking_an_access_token_stops_it(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session)
        user_id = (await only_user(session)).id

        await client.post(
            "/oauth/revoke", data={"client_id": "notebook", "token": tokens["access_token"]}
        )

        response = await client.get(
            f"/users/{user_id}/items", headers=bearer(tokens["access_token"])
        )
        assert response.status_code == 403

    async def test_revoking_a_refresh_token_takes_the_access_token_with_it(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session)
        user_id = (await only_user(session)).id

        await client.post(
            "/oauth/revoke", data={"client_id": "notebook", "token": tokens["refresh_token"]}
        )

        response = await client.get(
            f"/users/{user_id}/items", headers=bearer(tokens["access_token"])
        )
        assert response.status_code == 403

    async def test_an_unknown_token_still_answers_200(self, client: httpx.AsyncClient) -> None:
        """RFC 7009 §2.2: an error here would answer whether a string is live."""
        response = await client.post(
            "/oauth/revoke", data={"client_id": "notebook", "token": "not a token"}
        )

        assert response.status_code == 200


class TestSuspensionReachesATokenToo:
    async def test_a_suspended_account_stops_the_token(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The half of a suspension that matters: enforced at every credential."""
        tokens = await full_flow(client, session)
        user_id = (await only_user(session)).id
        user = await session.get(User, user_id)
        assert user is not None
        user.disabled_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()

        response = await client.get(
            f"/users/{user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 403

    async def test_a_suspended_account_cannot_refresh(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session)
        user = await only_user(session)
        user.disabled_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()

        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "notebook",
                "refresh_token": tokens["refresh_token"],
            },
        )

        assert response.json()["error"] == "invalid_grant"


class TestConnectedApplications:
    async def test_the_grant_is_listed(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await full_flow(client, session)

        listed = (await client.get("/web/oauth/authorizations")).json()

        assert len(listed) == 1
        assert listed[0]["name"] == "Notebook"
        assert listed[0]["scopes"] == ["openid", "library.read"]
        assert listed[0]["activeTokens"] == 1

    async def test_disconnecting_stops_the_token_at_once(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session)
        user_id = (await only_user(session)).id
        listed = (await client.get("/web/oauth/authorizations")).json()

        removed = await client.delete(
            f"/web/oauth/authorizations/{listed[0]['id']}", headers=csrf(client)
        )

        assert removed.status_code == 204
        after = await client.get(f"/users/{user_id}/items", headers=bearer(tokens["access_token"]))
        assert after.status_code == 403

    async def test_disconnecting_needs_the_csrf_token(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await full_flow(client, session)
        listed = (await client.get("/web/oauth/authorizations")).json()

        response = await client.delete(
            f"/web/oauth/authorizations/{listed[0]['id']}", headers={CSRF_HEADER: "not it"}
        )

        assert response.status_code == 403

    async def test_somebody_elses_authorization_cannot_be_withdrawn(
        self, client: httpx.AsyncClient, session: AsyncSession, app: FastAPI
    ) -> None:
        await full_flow(client, session)
        listed = (await client.get("/web/oauth/authorizations")).json()
        theirs = listed[0]["id"]

        # Registration is open for the first account only, so the second one is
        # made the way an operator would and signs in through the usual door.
        grace = await admin.create_user(session, username="grace", display_name="Grace")
        await session.commit()
        await webauth.set_password(session, grace, PASSWORD)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as other:
            signed_in = await other.post(
                "/web/auth/login", json={"username": "grace", "password": PASSWORD}
            )
            assert signed_in.status_code == 200, signed_in.text
            response = await other.delete(
                f"/web/oauth/authorizations/{theirs}", headers=csrf(other)
            )

        assert response.status_code == 404

    async def test_authorizations_need_a_cookie(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/oauth/authorizations")).status_code == 401


class TestDiscovery:
    async def test_both_well_known_paths_serve_the_same_document(
        self, client: httpx.AsyncClient
    ) -> None:
        oidc = await client.get("/.well-known/openid-configuration")
        oauth = await client.get("/.well-known/oauth-authorization-server")

        assert oidc.status_code == 200
        assert oidc.json() == oauth.json()

    async def test_it_names_everything_a_client_needs(self, client: httpx.AsyncClient) -> None:
        document = (await client.get("/.well-known/openid-configuration")).json()

        for required in (
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "subject_types_supported",
            "id_token_signing_alg_values_supported",
            "response_types_supported",
        ):
            assert required in document, required
        assert document["id_token_signing_alg_values_supported"] == ["RS256"]

    async def test_the_key_set_holds_a_usable_key(self, client: httpx.AsyncClient) -> None:
        keys = (await client.get("/oauth/jwks.json")).json()["keys"]

        assert len(keys) == 1
        assert keys[0]["kty"] == "RSA"
        assert keys[0]["use"] == "sig"
        assert keys[0]["alg"] == "RS256"
        assert keys[0]["kid"]

    async def test_a_rotated_key_is_still_published(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Otherwise every token issued before a rotation stops verifying."""
        before = (await client.get("/oauth/jwks.json")).json()["keys"][0]["kid"]

        await oauthserver.rotate_signing_key(session)

        keys = (await client.get("/oauth/jwks.json")).json()["keys"]
        assert {key["kid"] for key in keys} >= {before}
        assert len(keys) == 2


class TestTheIssuerIsNotTakenFromTheRequest:
    """A ``Host`` header must not decide what this server calls itself."""

    async def test_the_issuer_comes_from_the_setting(self, client: httpx.AsyncClient) -> None:
        document = (
            await client.get(
                "/.well-known/openid-configuration", headers={"Host": "attacker.example"}
            )
        ).json()

        assert document["issuer"] == PUBLIC_URL
        assert document["token_endpoint"].startswith(PUBLIC_URL)

    async def test_without_the_setting_the_server_refuses_rather_than_guesses(
        self, tmp_path: Path
    ) -> None:
        bare = create_app(
            Settings(
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'bare.sqlite'}",
                storage_path=tmp_path / "storage",
            )
        )
        await bare.state.database.create_all()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=bare), base_url="http://testserver"
            ) as anonymous:
                response = await anonymous.get("/.well-known/openid-configuration")
        finally:
            await bare.state.database.dispose()

        assert response.status_code == 400
        assert "ALTERO_PUBLIC_URL" in response.text


class TestTheApiKeyPathIsUntouched:
    """The v3 API gained a credential; it did not lose one, and cookies still bounce."""

    async def test_an_api_key_still_works(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_account(client)
        key = await admin.create_api_key(session, username="ada", name="laptop")

        response = await client.get("/users/1/items", headers={"Zotero-API-Key": key.key})

        assert response.status_code == 200

    async def test_a_session_cookie_still_does_not_authenticate_a_v3_request(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The rule OAuth did not widen: a cookie is still not a v3 credential."""
        await full_flow(client, session)
        assert client.cookies.get("altero_session")

        response = await client.get("/users/1/items")

        assert response.status_code == 403

    async def test_an_access_token_does_not_authenticate_a_web_request(
        self, client: httpx.AsyncClient, session: AsyncSession, app: FastAPI
    ) -> None:
        """And not the other way round either: /web is the cookie's alone."""
        tokens = await full_flow(client, session)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as anonymous:
            response = await anonymous.get(
                "/web/auth/session", headers=bearer(tokens["access_token"])
            )

        assert response.status_code == 401

    async def test_a_token_cannot_manage_api_keys(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """/keys is about a key as an object, and a token is not one."""
        tokens = await full_flow(client, session)

        response = await client.get("/keys/current", headers=bearer(tokens["access_token"]))

        assert response.status_code == 403

    async def test_a_token_cannot_delete_a_key(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session)

        response = await client.delete("/keys/current", headers=bearer(tokens["access_token"]))

        assert response.status_code == 403


class TestHousekeeping:
    async def test_expired_rows_are_swept(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await full_flow(client, session)
        for row in await session.scalars(select(OAuthToken)):
            row.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        await session.commit()

        removed = await oauthserver.prune(session)

        assert removed >= 2
        assert (await session.scalars(select(OAuthToken))).all() == []


class TestTheGroupsClaim:
    """Which groups somebody is in, told to an application that may sign them in.

    An identity scope, so it sits beside ``profile`` and ``email`` and reaches
    no library at all -- which is the point. Role mapping in a relying party
    needs the *names* and nothing else; ``groups.read``, one line down the
    consent screen, is the different and much larger question of reading what
    is inside those libraries.
    """

    async def test_the_claim_is_absent_without_the_scope(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid profile")

        assert "groups" not in claims_of(tokens["id_token"])

    async def test_it_names_the_groups_the_account_belongs_to(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        user_id = await make_account(client)
        await make_group(session, group_id=100, owner_id=user_id, name="Reading Group")
        await make_group(session, group_id=101, owner_id=user_id, name="Lab Notebook")

        tokens = await walk_flow(client, scope="openid groups")

        assert claims_of(tokens["id_token"])["groups"] == ["Reading Group", "Lab Notebook"]

    async def test_a_group_somebody_else_is_in_is_not_named(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """What gives the test above its teeth: it is membership, not a listing."""
        await make_client(session)
        user_id = await make_account(client)
        stranger = await make_user(session, user_id=user_id + 1, username="grace")
        await make_group(session, group_id=100, owner_id=user_id, name="Reading Group")
        await make_group(session, group_id=101, owner_id=stranger.id, name="Somebody Else's")

        tokens = await walk_flow(client, scope="openid groups")

        assert claims_of(tokens["id_token"])["groups"] == ["Reading Group"]

    async def test_an_account_in_no_group_is_told_so_rather_than_left_guessing(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """An empty list, not an absent claim.

        A relying party mapping roles has to tell "no groups" from "this server
        did not say", and an omitted claim is the second one.
        """
        tokens = await full_flow(client, session, scope="openid groups")

        assert claims_of(tokens["id_token"])["groups"] == []

    async def test_userinfo_says_the_same_thing(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        user_id = await make_account(client)
        await make_group(session, group_id=100, owner_id=user_id, name="Reading Group")

        tokens = await walk_flow(client, scope="openid groups")
        claims = (
            await client.get("/oauth/userinfo", headers=bearer(tokens["access_token"]))
        ).json()

        assert claims["groups"] == ["Reading Group"]

    async def test_userinfo_does_not_say_it_without_the_scope(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_client(session)
        user_id = await make_account(client)
        await make_group(session, group_id=100, owner_id=user_id, name="Reading Group")

        tokens = await walk_flow(client, scope="openid profile")
        claims = (
            await client.get("/oauth/userinfo", headers=bearer(tokens["access_token"]))
        ).json()

        assert "groups" not in claims

    async def test_it_reaches_no_group_library(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The whole reason this is its own scope rather than part of groups.read."""
        await make_client(session)
        user_id = await make_account(client)
        library = await make_group(session, group_id=100, owner_id=user_id, name="Reading Group")

        tokens = await walk_flow(client, scope="openid groups")
        response = await client.get(
            f"/groups/{library.owner_id}/items", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 403

    async def test_groups_read_still_reaches_the_group_library(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """And the larger scope is unchanged by the smaller one existing."""
        await make_client(session, scopes="openid library.read groups.read")
        user_id = await make_account(client)
        library = await make_group(session, group_id=100, owner_id=user_id, name="Reading Group")

        tokens = await walk_flow(client, scope="openid library.read groups.read")
        response = await client.get(
            f"/groups/{library.owner_id}/items", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 200

    async def test_groups_read_alone_does_not_put_names_in_the_token(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """One scope, one thing. Reading the libraries is not being told the list."""
        await make_client(session, scopes="openid library.read groups.read")
        user_id = await make_account(client)
        await make_group(session, group_id=100, owner_id=user_id, name="Reading Group")

        tokens = await walk_flow(client, scope="openid library.read groups.read")

        assert "groups" not in claims_of(tokens["id_token"])

    async def test_the_scope_and_the_claim_are_advertised(self, client: httpx.AsyncClient) -> None:
        document = (await client.get("/.well-known/openid-configuration")).json()

        assert "groups" in document["scopes_supported"]
        assert "groups" in document["claims_supported"]


async def hint_for(
    session: AsyncSession, *, subject: str, audience: str = "notebook", issuer: str = PUBLIC_URL
) -> str:
    """Sign an ID token by hand, for the hints a flow cannot produce.

    An expired one, one naming somebody else, one issued elsewhere. Signed with
    this server's own key, so what each test varies is the claim under test and
    not the signature.
    """
    key = await oauthserver.signing_key(session)
    return jws.sign(
        {
            "iss": issuer,
            "sub": subject,
            "aud": audience,
            "iat": 1000,
            "exp": 2000,
        },
        key.private_pem,
        key.kid,
    )


async def signed_in(client: httpx.AsyncClient) -> bool:
    """Return whether the browser still holds a session."""
    return (await client.get("/web/auth/session")).status_code == 200


class TestRpInitiatedLogout:
    """Signing out of altero because an application asked, and only then.

    ``/oauth/logout`` is a navigation and therefore reachable from any page on
    the internet, which is why the ID token this server issued is *required*
    and its signature is checked. Without that, a hidden image on somebody
    else's site would sign people out of their library all day.
    """

    async def test_it_is_advertised(self, client: httpx.AsyncClient) -> None:
        document = (await client.get("/.well-known/openid-configuration")).json()

        assert document["end_session_endpoint"] == f"{PUBLIC_URL}/oauth/logout"

    async def test_it_ends_the_browser_session(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")
        assert await signed_in(client)

        await client.get(
            "/oauth/logout",
            params={"id_token_hint": tokens["id_token"]},
            follow_redirects=False,
        )

        assert not await signed_in(client)

    async def test_it_returns_to_the_registered_address_carrying_the_state(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")

        response = await client.get(
            "/oauth/logout",
            params={
                "id_token_hint": tokens["id_token"],
                "post_logout_redirect_uri": SIGNED_OUT,
                "state": "opaque-state",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith(SIGNED_OUT)
        assert "state=opaque-state" in response.headers["location"]

    async def test_with_nowhere_to_go_it_lands_on_the_interface(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")

        response = await client.get(
            "/oauth/logout",
            params={"id_token_hint": tokens["id_token"]},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/app/"

    async def test_post_works_as_well_as_get(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """RP-Initiated Logout 1.0 §2 allows either."""
        tokens = await full_flow(client, session, scope="openid")

        response = await client.post(
            "/oauth/logout",
            data={"id_token_hint": tokens["id_token"]},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert not await signed_in(client)

    async def test_an_unregistered_address_is_refused_and_not_redirected_to(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The same rule as the authorization endpoint: never bounce off an unverified address."""
        tokens = await full_flow(client, session, scope="openid")

        response = await client.get(
            "/oauth/logout",
            params={
                "id_token_hint": tokens["id_token"],
                "post_logout_redirect_uri": "https://attacker.example/landed",
            },
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "location" not in response.headers

    async def test_a_forged_hint_signs_nobody_out(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        tokens = await full_flow(client, session, scope="openid")
        header, _, signature = tokens["id_token"].split(".")
        forged = (
            base64.urlsafe_b64encode(
                json.dumps({"iss": PUBLIC_URL, "sub": "1", "aud": "notebook"}).encode()
            )
            .decode()
            .rstrip("=")
        )

        response = await client.get(
            "/oauth/logout",
            params={"id_token_hint": f"{header}.{forged}.{signature}"},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert await signed_in(client)

    async def test_a_hint_signed_by_somebody_else_signs_nobody_out(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await full_flow(client, session, scope="openid")
        stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = stranger.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        key = await oauthserver.signing_key(session)

        response = await client.get(
            "/oauth/logout",
            params={
                "id_token_hint": jws.sign(
                    {"iss": PUBLIC_URL, "sub": "1", "aud": "notebook"}, pem, key.kid
                )
            },
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert await signed_in(client)

    async def test_without_a_hint_it_refuses_rather_than_signing_anybody_out(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """What keeps this from being a sign-out anybody can provoke."""
        await full_flow(client, session, scope="openid")

        response = await client.get("/oauth/logout", follow_redirects=False)

        assert response.status_code == 400
        assert await signed_in(client)

    async def test_an_expired_hint_is_still_a_hint(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """An ID token lives an hour; signing out happens whenever somebody says so."""
        await full_flow(client, session, scope="openid")
        user = await only_user(session)

        response = await client.get(
            "/oauth/logout",
            params={"id_token_hint": await hint_for(session, subject=str(user.id))},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert not await signed_in(client)

    async def test_a_hint_issued_elsewhere_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await full_flow(client, session, scope="openid")
        user = await only_user(session)

        response = await client.get(
            "/oauth/logout",
            params={
                "id_token_hint": await hint_for(
                    session, subject=str(user.id), issuer="https://elsewhere.example"
                )
            },
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert await signed_in(client)

    async def test_a_hint_for_an_unregistered_client_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await full_flow(client, session, scope="openid")
        user = await only_user(session)

        response = await client.get(
            "/oauth/logout",
            params={
                "id_token_hint": await hint_for(session, subject=str(user.id), audience="invented")
            },
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert await signed_in(client)

    async def test_it_does_not_sign_out_somebody_else(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """RP-Initiated Logout 1.0 §2: not the session, if it is not that subject's."""
        await full_flow(client, session, scope="openid")
        user = await only_user(session)

        response = await client.get(
            "/oauth/logout",
            params={
                "id_token_hint": await hint_for(session, subject=str(user.id + 1)),
                "post_logout_redirect_uri": SIGNED_OUT,
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert await signed_in(client)

    async def test_signing_out_of_the_browser_leaves_the_application_working(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A session and a grant are different things, and this ends the session.

        Stopping the application is ``Settings -> Connected applications``, and
        `docs/oauth.md` says so rather than leaving somebody to find out.
        """
        tokens = await full_flow(client, session, scope="openid library.read")
        user_id = (await only_user(session)).id

        await client.get(
            "/oauth/logout",
            params={"id_token_hint": tokens["id_token"]},
            follow_redirects=False,
        )

        assert (
            await client.get(f"/users/{user_id}/items", headers=bearer(tokens["access_token"]))
        ).status_code == 200

    async def test_a_browser_that_was_never_signed_in_is_sent_on_its_way(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Nothing to end is not a failure: the RP wants its landing page either way."""
        tokens = await full_flow(client, session, scope="openid")
        await client.post("/web/auth/logout", headers=csrf(client))

        response = await client.get(
            "/oauth/logout",
            params={
                "id_token_hint": tokens["id_token"],
                "post_logout_redirect_uri": SIGNED_OUT,
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith(SIGNED_OUT)


class TestPostLogoutRedirectUrisAreRegistered:
    async def test_an_address_with_a_fragment_cannot_be_registered(
        self, session: AsyncSession
    ) -> None:
        with pytest.raises(InvalidInputError):
            await make_client(session, post_logout_redirect_uris=["https://app.example.com/#done"])

    async def test_plain_http_to_the_open_internet_cannot_be_registered(
        self, session: AsyncSession
    ) -> None:
        with pytest.raises(InvalidInputError):
            await make_client(session, post_logout_redirect_uris=["http://app.example.com/done"])

    async def test_a_client_may_register_none_at_all(self, session: AsyncSession) -> None:
        """Most applications have no landing page and only want the session ended."""
        registered, _ = await make_client(session, post_logout_redirect_uris=[])

        assert registered.post_logout_redirect_uris == ""
