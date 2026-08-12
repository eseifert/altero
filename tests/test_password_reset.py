"""Asking for a link to set a new password, without an administrator.

`services/passwordreset.py` used to say this did not exist and why: it makes an
email address a way in to an account, so the relay becomes part of the
authentication, and the form needs a rate limit and an answer to what it tells
an address that has no account here. Those are the three things being tested.
"""

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import PasswordReset, User
from altero.services import admin, emailverify, passwordreset, webauth
from altero.services.mail import Message
from altero.settings import Settings
from tests.test_web_routes import PASSWORD, register


class Outbox:
    """A mailer that keeps what it was given."""

    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, message: Message) -> bool:
        self.sent.append(message)
        return True


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """An instance that offers the form: asked for, and with somewhere to send."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
        password_reset=True,
        smtp_url="smtp://localhost:2525",
    )


@pytest.fixture
def outbox(app: FastAPI) -> Outbox:
    """Replaces the mailer on the running app, so nothing reaches a relay."""
    box = Outbox()
    app.state.mailer = box
    return box


async def confirmed_account(session: AsyncSession, username: str = "grace") -> User:
    """An account whose address has been proved, which is what this needs."""
    if await admin.count_administrators(session) == 0:
        await admin.create_user(session, username="ada")

    user = await admin.create_user(session, username=username)
    address = f"{username}@example.org"
    user.email = address
    await session.commit()
    token = await emailverify.issue(session, user, address)
    await emailverify.confirm(session, token)
    await webauth.set_password(session, user, PASSWORD)
    return user


class TestAskingForOne:
    async def test_a_confirmed_address_is_sent_a_link(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        user = await confirmed_account(session)

        response = await client.post("/web/auth/forgot", json={"email": user.email})

        assert response.status_code == 202
        assert len(outbox.sent) == 1
        assert "/app/reset?token=" in outbox.sent[0].body
        assert outbox.sent[0].to == "grace@example.org"

    async def test_the_link_it_sends_actually_works(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """End to end: the thing in the mail sets the password."""
        user = await confirmed_account(session)
        await client.post("/web/auth/forgot", json={"email": user.email})
        token = outbox.sent[0].body.split("token=")[1].split("\n")[0].strip()

        response = await client.post(
            "/web/auth/reset", json={"token": token, "password": "a password of my own"}
        )

        assert response.status_code == 200
        session.expire_all()
        assert await webauth.login(session, username="grace", password="a password of my own")

    async def test_the_address_is_matched_whatever_case_it_is_typed_in(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await confirmed_account(session)

        await client.post("/web/auth/forgot", json={"email": "GRACE@Example.ORG"})

        assert len(outbox.sent) == 1

    async def test_it_needs_no_session_and_no_csrf_token(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """Whoever is looking at this form is by definition not signed in."""
        await confirmed_account(session)
        client.cookies.clear()

        response = await client.post("/web/auth/forgot", json={"email": "grace@example.org"})

        assert response.status_code == 202


class TestItSaysNothingAboutWhoHasAnAccount:
    """The form must not become a way of asking which addresses are here."""

    async def test_an_unknown_address_answers_the_same(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await confirmed_account(session)

        known = await client.post("/web/auth/forgot", json={"email": "grace@example.org"})
        unknown = await client.post("/web/auth/forgot", json={"email": "nobody@example.org"})

        assert known.status_code == unknown.status_code == 202
        assert known.content == unknown.content
        assert len(outbox.sent) == 1

    async def test_something_that_is_not_an_address_answers_the_same(
        self, client: httpx.AsyncClient, outbox: Outbox
    ) -> None:
        response = await client.post("/web/auth/forgot", json={"email": "not an address"})

        assert response.status_code == 202
        assert outbox.sent == []

    async def test_an_unconfirmed_address_gets_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """Nobody proved they hold it, so a mistyped registration is not a way in."""
        await register(client)
        # Registration sends its own confirmation; this is about what follows.
        outbox.sent.clear()

        response = await client.post("/web/auth/forgot", json={"email": "ada@example.org"})

        assert response.status_code == 202
        assert outbox.sent == []

    async def test_a_suspended_account_cannot_let_itself_back_in(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        user = await confirmed_account(session)
        await admin.set_disabled(session, user, disabled=True)

        response = await client.post("/web/auth/forgot", json={"email": user.email})

        assert response.status_code == 202
        assert outbox.sent == []


class TestTheRateLimit:
    async def test_one_address_cannot_be_mailed_without_end(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await confirmed_account(session)

        for _ in range(passwordreset.REQUESTS_PER_WINDOW + 3):
            await client.post("/web/auth/forgot", json={"email": "grace@example.org"})

        assert len(outbox.sent) == passwordreset.REQUESTS_PER_WINDOW

    async def test_being_refused_still_answers_202(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        """A 429 here would say the address is one worth limiting."""
        await confirmed_account(session)
        for _ in range(passwordreset.REQUESTS_PER_WINDOW):
            await client.post("/web/auth/forgot", json={"email": "grace@example.org"})

        response = await client.post("/web/auth/forgot", json={"email": "grace@example.org"})

        assert response.status_code == 202

    async def test_one_address_being_hammered_does_not_block_another(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        await confirmed_account(session)
        await confirmed_account(session, username="alan")
        for _ in range(passwordreset.REQUESTS_PER_WINDOW + 2):
            await client.post("/web/auth/forgot", json={"email": "grace@example.org"})

        await client.post("/web/auth/forgot", json={"email": "alan@example.org"})

        assert outbox.sent[-1].to == "alan@example.org"


class TestTheSignInPageIsToldWhetherToOfferIt:
    async def test_an_instance_that_offers_it_says_so(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/config")).json()["passwordResetOpen"] is True


class TestWithoutARelay:
    """A self-service link written to the log is one anybody who reads logs can use."""

    @pytest.fixture
    def settings(self, tmp_path: Path) -> Settings:
        return Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
            storage_path=tmp_path / "storage",
            password_reset=True,
        )

    async def test_no_link_is_made_at_all(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        user = await confirmed_account(session)

        response = await client.post("/web/auth/forgot", json={"email": user.email})

        assert response.status_code == 202
        assert outbox.sent == []
        # Not merely unsent: no link exists to be found in a log or a backup.
        outstanding = select(PasswordReset).where(PasswordReset.user_id == user.id)
        assert await session.scalar(outstanding) is None

    async def test_the_page_is_told_not_to_offer_it(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/config")).json()["passwordResetOpen"] is False


class TestWhenTheOperatorHasNotTurnedItOn:
    @pytest.fixture
    def settings(self, tmp_path: Path) -> Settings:
        return Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
            storage_path=tmp_path / "storage",
            smtp_url="smtp://localhost:2525",
        )

    async def test_nothing_is_sent(
        self, client: httpx.AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        user = await confirmed_account(session)

        response = await client.post("/web/auth/forgot", json={"email": user.email})

        assert response.status_code == 202
        assert outbox.sent == []

    async def test_the_page_is_told_not_to_offer_it(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/config")).json()["passwordResetOpen"] is False
