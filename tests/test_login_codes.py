"""A second factor that arrives by mail.

The alternative to an authenticator app for somebody who has none, and — more
sharply — the way back in for somebody who had one and lost the phone. Before
this, that person's only route was to find whoever runs the server.

Six digits is not much to grind, so the three things that make it a credential
rather than a formality get their own class each: it is bound to the session
that asked for it, it expires in minutes, and the row is spent after a few
wrong guesses.
"""

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import EmailFactor, LoginCode, User
from altero.services import admin, emailverify, logincodes, webauth, websessions
from altero.services.mail import Message
from altero.settings import Settings
from tests.test_web_routes import CSRF_HEADER, PASSWORD, csrf_headers

USERNAME = "grace"
ADDRESS = "grace@example.org"


class Outbox:
    """A mailer that keeps what it was given."""

    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, message: Message) -> bool:
        self.sent.append(message)
        return True


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
        smtp_url="smtp://localhost:2525",
    )


@pytest.fixture
def outbox(app: FastAPI) -> Outbox:
    box = Outbox()
    app.state.mailer = box
    return box


async def enrolled_account(session: AsyncSession, *, totp_too: bool = False) -> User:
    """An account with a confirmed address that takes its factor by mail."""
    user = await admin.create_user(session, username=USERNAME, display_name="Grace")
    user.email = ADDRESS
    await session.commit()
    await emailverify.confirm(session, await emailverify.issue(session, user, ADDRESS))
    await webauth.set_password(session, user, PASSWORD)
    await logincodes.enrol(session, user)
    if totp_too:
        await webauth.enrol_totp(session, user, confirm_with=None)
    return user


def code_from(outbox: Outbox) -> str:
    """Pull the six digits out of the message that was sent."""
    return outbox.sent[-1].subject.split(" ", 1)[0]


async def sign_in(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post("/web/auth/login", json={"username": USERNAME, "password": PASSWORD})


class TestSigningInWithOne:
    async def test_the_password_alone_does_not_sign_in(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """The whole claim: a stolen password stops being enough."""
        await enrolled_account(session)

        body = (await sign_in(client)).json()

        assert body["needsFactor"] == "email"
        assert body["user"] is None
        assert (await client.get("/web/auth/session")).status_code == 401

    async def test_a_code_is_sent_to_the_confirmed_address(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)

        await sign_in(client)

        assert len(outbox.sent) == 1
        assert outbox.sent[0].to == ADDRESS
        assert code_from(outbox).isdigit()

    async def test_the_code_is_in_the_subject_so_a_phone_can_show_it(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)

        await sign_in(client)

        assert outbox.sent[0].subject.startswith(code_from(outbox))

    async def test_the_right_code_finishes_signing_in(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)

        response = await client.post(
            "/web/auth/code", json={"code": code_from(outbox)}, headers=csrf_headers(client)
        )

        assert response.status_code == 200
        assert response.json()["user"]["username"] == USERNAME
        assert (await client.get("/web/auth/session")).status_code == 200

    async def test_the_wrong_code_answers_401_and_leaves_it_pending(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)

        response = await client.post(
            "/web/auth/code", json={"code": "000000"}, headers=csrf_headers(client)
        )

        assert response.status_code == 401
        assert (await client.get("/web/auth/session")).status_code == 401

    async def test_it_needs_the_csrf_token(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)

        response = await client.post("/web/auth/code", json={"code": code_from(outbox)})

        assert response.status_code == 403

    async def test_a_code_works_once(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)
        code = code_from(outbox)
        await client.post("/web/auth/code", json={"code": code}, headers=csrf_headers(client))
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        await sign_in(client)
        again = await client.post(
            "/web/auth/code", json={"code": code}, headers=csrf_headers(client)
        )

        # A second sign-in made a second code; the first is gone either way.
        assert again.status_code == 401


class TestItIsBoundToOneSignIn:
    async def test_a_code_from_another_browser_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox, app: FastAPI
    ) -> None:
        """Whoever read the mail must not be able to use it from their machine."""
        user = await enrolled_account(session)
        await sign_in(client)
        theirs = code_from(outbox)

        # A second pending sign-in, as another browser would produce.
        token, elsewhere = await websessions.create(session, user, pending_factor="email")
        await logincodes.issue(session, elsewhere)

        with pytest.raises(ForbiddenError):
            await logincodes.verify(session, elsewhere, theirs)
        assert token

    async def test_asking_again_replaces_the_code_rather_than_adding_one(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """Two live codes would double what an interceptor has to work with."""
        await enrolled_account(session)
        await sign_in(client)
        first = code_from(outbox)

        await client.post("/web/auth/code/resend", headers=csrf_headers(client))
        second = code_from(outbox)

        stale = await client.post(
            "/web/auth/code", json={"code": first}, headers=csrf_headers(client)
        )
        assert stale.status_code == 401
        fresh = await client.post(
            "/web/auth/code", json={"code": second}, headers=csrf_headers(client)
        )
        assert fresh.status_code == 200

    async def test_the_code_goes_when_the_session_does(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """Cascaded, so an abandoned sign-in leaves no live credential behind."""
        user = await enrolled_account(session)
        await sign_in(client)
        assert await session.scalar(select(LoginCode)) is not None

        await websessions.revoke_all(session, user)

        session.expire_all()
        assert await session.scalar(select(LoginCode)) is None


class TestItCannotBeGuessed:
    async def test_the_code_is_spent_after_a_few_wrong_guesses(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """Six digits would be walkable otherwise."""
        await enrolled_account(session)
        await sign_in(client)
        right = code_from(outbox)

        for _ in range(logincodes.MAX_ATTEMPTS):
            await client.post(
                "/web/auth/code", json={"code": "000000"}, headers=csrf_headers(client)
            )

        response = await client.post(
            "/web/auth/code", json={"code": right}, headers=csrf_headers(client)
        )
        assert response.status_code == 401

    async def test_an_expired_code_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)
        stored = await session.scalar(select(LoginCode))
        assert stored is not None
        stored.expires -= timedelta(minutes=logincodes.LIFETIME_MINUTES + 1)
        await session.commit()

        response = await client.post(
            "/web/auth/code", json={"code": code_from(outbox)}, headers=csrf_headers(client)
        )

        assert response.status_code == 401

    async def test_only_the_digest_is_stored(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)

        stored = await session.scalar(select(LoginCode))

        assert stored is not None
        assert stored.code_hash != code_from(outbox)
        assert stored.code_hash == logincodes.hash_code(code_from(outbox))


class TestWhenBothFactorsAreEnrolled:
    async def test_the_authenticator_is_asked_for(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """The stronger of the two wins without being asked about."""
        await enrolled_account(session, totp_too=True)

        body = (await sign_in(client)).json()

        assert body["needsFactor"] == "totp"
        assert outbox.sent == []

    async def test_the_email_code_is_offered_as_the_other_way(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session, totp_too=True)

        body = (await sign_in(client)).json()

        assert body["alternativeFactors"] == ["email"]

    async def test_asking_for_it_sends_a_code_and_signs_in(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """The answer to a lost phone, end to end."""
        await enrolled_account(session, totp_too=True)
        await sign_in(client)

        switched = await client.post(
            "/web/auth/factor", json={"factor": "email"}, headers=csrf_headers(client)
        )

        assert switched.status_code == 200
        assert switched.json()["needsFactor"] == "email"
        finished = await client.post(
            "/web/auth/code", json={"code": code_from(outbox)}, headers=csrf_headers(client)
        )
        assert finished.status_code == 200

    async def test_a_factor_the_account_does_not_have_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        user = await admin.create_user(session, username="ada")
        await webauth.set_password(session, user, PASSWORD)
        await webauth.enrol_totp(session, user, confirm_with=None)
        await client.post("/web/auth/login", json={"username": "ada", "password": PASSWORD})

        response = await client.post(
            "/web/auth/factor", json={"factor": "email"}, headers=csrf_headers(client)
        )

        assert response.status_code == 401
        assert outbox.sent == []

    async def test_a_finished_session_cannot_be_put_back_into_a_factor(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """Otherwise this is a way of re-opening a session to present a code at."""
        await enrolled_account(session)
        await sign_in(client)
        await client.post(
            "/web/auth/code", json={"code": code_from(outbox)}, headers=csrf_headers(client)
        )

        response = await client.post(
            "/web/auth/factor", json={"factor": "email"}, headers=csrf_headers(client)
        )

        assert response.status_code == 401


class TestTurningItOn:
    async def test_it_needs_a_confirmed_address(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """A factor sent where nobody proved they can read is no factor at all."""
        from tests.test_web_routes import register

        await register(client)

        response = await client.post(
            "/web/account/email-codes",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 400
        assert await session.scalar(select(EmailFactor)) is None

    async def test_a_confirmed_address_can_turn_it_on(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        user = await enrolled_account(session)
        await logincodes.disable(session, user)
        await sign_in(client)

        response = await client.post(
            "/web/account/email-codes",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 204
        enrolled = await session.get(EmailFactor, user.id)
        assert enrolled is not None

    async def test_turning_it_on_needs_the_password(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        user = await enrolled_account(session)
        await logincodes.disable(session, user)
        await sign_in(client)

        response = await client.post(
            "/web/account/email-codes", json={}, headers=csrf_headers(client)
        )

        assert response.status_code == 403

    async def test_the_settings_screen_says_whether_it_is_on(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)
        await client.post(
            "/web/auth/code", json={"code": code_from(outbox)}, headers=csrf_headers(client)
        )

        body = (await client.get("/web/account")).json()

        assert body["emailCodesEnabled"] is True

    async def test_turning_it_off_stops_it_being_asked_for(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)
        await client.post(
            "/web/auth/code", json={"code": code_from(outbox)}, headers=csrf_headers(client)
        )

        removed = await client.request(
            "DELETE",
            "/web/account/email-codes",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        assert removed.status_code == 204
        assert (await sign_in(client)).json()["needsFactor"] is None

    async def test_the_owner_is_told_when_it_changes(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """A silent change to a credential is one nobody notices being made."""
        user = await enrolled_account(session)
        await logincodes.disable(session, user)
        await sign_in(client)
        outbox.sent.clear()

        await client.post(
            "/web/account/email-codes",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert any("turned on" in message.subject for message in outbox.sent)


class TestTheConfigListsIt:
    async def test_the_sign_in_page_is_told_it_exists(self, client: httpx.AsyncClient) -> None:
        """Named rather than compared to the whole list, which grows as factors
        are added and is not what this test is about."""
        body = (await client.get("/web/config")).json()

        assert "email" in body["secondFactors"]


class TestTheCsrfHeaderIsStillRequired:
    async def test_resending_needs_it(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await enrolled_account(session)
        await sign_in(client)

        response = await client.post("/web/auth/code/resend", headers={CSRF_HEADER: "not it"})

        assert response.status_code == 403
