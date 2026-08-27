"""The streaming API.

Driven through Starlette's test client rather than the ``httpx`` one the rest
of the suite uses, because only that one speaks WebSocket. It runs the
application in a thread of its own, so a write made through it and the socket
watching for that write are genuinely concurrent -- which is the thing worth
testing here.
"""

import json
import threading
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from altero.api.routes.streaming import (
    INVALID_KEY,
    INVALID_MESSAGE,
    STREAM_PATH,
)
from altero.services import auth
from altero.services import login as login_service
from altero.services.streaming import RETRY_MILLISECONDS, broker
from tests import factories

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"

#: An item body the write endpoints accept, used to move a library's version.
ITEM = [{"itemType": "book", "title": "The Rings of Saturn"}]


@pytest.fixture
async def account(session: AsyncSession) -> None:
    """A user with a personal library and a key that can write to it."""
    await factories.make_user(session)
    await factories.make_api_key(session)


@pytest.fixture
def http(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


#: How long a test waits for a message before deciding one is not coming.
TIMEOUT = 10.0


def _read_into(socket, received: list[str]) -> None:  # type: ignore[no-untyped-def]
    received.append(socket.receive_text())


def receive(socket, count: int = 1) -> list[dict]:  # type: ignore[no-untyped-def]
    """Read ``count`` messages, failing rather than hanging if they do not come.

    The test client's own read has no timeout, so a regression that stops
    events being published makes every test here block for ever instead of
    failing -- which in CI is a job that runs until it is killed, with nothing
    said about why. Reading on a thread turns that back into an assertion.
    """
    messages = []
    for _ in range(count):
        # A daemon thread rather than an executor: the executor joins its
        # workers on the way out, so a read that never returns would hang at
        # exactly the point this is meant to prevent.
        received: list[str] = []
        reader = threading.Thread(target=_read_into, args=(socket, received), daemon=True)
        reader.start()
        reader.join(TIMEOUT)
        if not received:
            pytest.fail(f"No message arrived within {TIMEOUT} seconds")
        messages.append(json.loads(received[0]))
    return messages


class TestConnecting:
    async def test_a_bare_connection_is_greeted_with_the_retry_interval(
        self, account, http: TestClient
    ) -> None:
        with http.websocket_connect(STREAM_PATH) as socket:
            (greeting,) = receive(socket)

        assert greeting == {"event": "connected", "retry": RETRY_MILLISECONDS}

    async def test_a_key_in_the_handshake_subscribes_to_everything_it_reaches(
        self, account, http: TestClient
    ) -> None:
        """Single-key mode: the greeting lists the topics rather than waiting."""
        with http.websocket_connect(STREAM_PATH, headers={"Zotero-API-Key": KEY}) as socket:
            (greeting,) = receive(socket)

        assert greeting["topics"] == ["/users/1"]

    async def test_an_unknown_key_is_refused_with_the_documented_code(
        self, account, http: TestClient
    ) -> None:
        with (
            http.websocket_connect(STREAM_PATH, headers={"Zotero-API-Key": "nosuchkey"}) as socket,
            pytest.raises(WebSocketDisconnect) as refused,
        ):
            socket.receive_text()

        assert refused.value.code == INVALID_KEY

    async def test_a_group_the_key_cannot_read_is_not_offered(
        self, account, session: AsyncSession, http: TestClient
    ) -> None:
        """A key without group access sees its own library and nothing else."""
        await factories.make_group(session, group_id=7, owner_id=1)

        with http.websocket_connect(STREAM_PATH, headers={"Zotero-API-Key": KEY}) as socket:
            (greeting,) = receive(socket)

        assert greeting["topics"] == ["/users/1"]

    async def test_a_group_the_key_can_read_is_offered(
        self, account, session: AsyncSession, app: FastAPI, http: TestClient
    ) -> None:
        await factories.make_group(session, group_id=7, owner_id=1)
        await factories.make_api_key(
            session, key="GroupReaderKeyGroupReaderKey", all_groups_read=True
        )

        with http.websocket_connect(
            STREAM_PATH, headers={"Zotero-API-Key": "GroupReaderKeyGroupReaderKey"}
        ) as socket:
            (greeting,) = receive(socket)

        assert greeting["topics"] == ["/groups/7", "/users/1"]


class TestSubscriptions:
    async def test_a_key_with_no_topics_subscribes_to_all_of_them(
        self, account, http: TestClient
    ) -> None:
        """The mode the Zotero client uses: one key, no topics named."""
        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps({"action": "createSubscriptions", "subscriptions": [{"apiKey": KEY}]})
            )
            (created,) = receive(socket)

        assert created == {
            "event": "subscriptionsCreated",
            "subscriptions": [{"apiKey": KEY, "topics": ["/users/1"]}],
            "errors": [],
        }

    async def test_an_unknown_key_is_reported_rather_than_closing_the_socket(
        self, account, http: TestClient
    ) -> None:
        """In multi-key mode one bad key must not take the connection down.

        A client watching several libraries would otherwise lose all of them
        because one credential had been revoked.
        """
        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps(
                    {
                        "action": "createSubscriptions",
                        "subscriptions": [{"apiKey": "nosuchkey"}, {"apiKey": KEY}],
                    }
                )
            )
            (created,) = receive(socket)

        assert created["errors"] == [{"apiKey": "nosuchkey", "error": "Invalid API key"}]
        assert created["subscriptions"] == [{"apiKey": KEY, "topics": ["/users/1"]}]

    async def test_a_topic_the_key_cannot_reach_is_refused(self, account, http: TestClient) -> None:
        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps(
                    {
                        "action": "createSubscriptions",
                        "subscriptions": [{"apiKey": KEY, "topics": ["/groups/999"]}],
                    }
                )
            )
            (created,) = receive(socket)

        assert created["subscriptions"] == []
        assert created["errors"] == [
            {
                "apiKey": KEY,
                "topic": "/groups/999",
                "error": "Topic is not valid for provided API key",
            }
        ]

    async def test_a_subscription_can_be_deleted(self, account, http: TestClient) -> None:
        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps({"action": "createSubscriptions", "subscriptions": [{"apiKey": KEY}]})
            )
            receive(socket)
            socket.send_text(
                json.dumps({"action": "deleteSubscriptions", "subscriptions": [{"apiKey": KEY}]})
            )
            (deleted,) = receive(socket)

        # The event names what went: `streamer.js` walks `data.subscriptions`
        # to take them out of its own set, and throws on the bare event.
        assert deleted["event"] == "subscriptionsDeleted"
        assert deleted["subscriptions"] == [{"apiKey": KEY, "topics": ["/users/1"]}]

    async def test_deleting_one_that_is_not_held_is_ignored(
        self, account, http: TestClient
    ) -> None:
        # The client's own login flow produces this: it subscribes to a topic,
        # and unsubscribes when it is finished whether the subscription was
        # granted or not. Closing the socket makes it stop reconnecting --
        # "Not reconnecting to WebSocket due to client error".
        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps(
                    {
                        "action": "deleteSubscriptions",
                        "subscriptions": [{"topic": "login-session:nobody"}],
                    }
                )
            )
            (deleted,) = receive(socket)

            # Still open, and still usable.
            socket.send_text(
                json.dumps({"action": "createSubscriptions", "subscriptions": [{"apiKey": KEY}]})
            )
            (created,) = receive(socket)

        assert deleted == {"event": "subscriptionsDeleted", "subscriptions": []}
        assert created["subscriptions"] == [{"apiKey": KEY, "topics": ["/users/1"]}]

    async def test_an_unreadable_message_closes_the_connection(
        self, account, http: TestClient
    ) -> None:
        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text("not json at all")
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_text()

        assert closed.value.code == INVALID_MESSAGE


class TestWhatTheClientAsksFor:
    """The three topics the Zotero client names that are not libraries.

    Every one of them was refused, which put two error lines in the client's
    log on every connection and, for the login session, closed the socket when
    the client tidied up after itself. Read off two clients driven through
    docs/testing-two-clients.md.
    """

    async def test_the_bundled_file_topics_are_accepted(self, account, http: TestClient) -> None:
        # The client subscribes to these whenever `automaticScraperUpdates` is
        # on, without a key, and logs an error for each refusal. altero
        # publishes neither, so the subscription is accepted and never fires;
        # the client's own repository timer is what actually fetches updates.
        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps(
                    {
                        "action": "createSubscriptions",
                        "subscriptions": [{"topics": ["styles", "translators"]}],
                    }
                )
            )
            (created,) = receive(socket)

        assert created["errors"] == []
        assert created["subscriptions"] == [{"topics": ["styles", "translators"]}]

    async def test_a_login_session_can_be_watched(
        self, account, session: AsyncSession, http: TestClient
    ) -> None:
        login = await login_service.start_session(session)

        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps(
                    {
                        "action": "createSubscriptions",
                        "subscriptions": [{"topics": [f"login-session:{login.token}"]}],
                    }
                )
            )
            (created,) = receive(socket)

        assert created["errors"] == []
        assert created["subscriptions"] == [{"topics": [f"login-session:{login.token}"]}]

    async def test_a_login_session_that_does_not_exist_is_refused(
        self, account, http: TestClient
    ) -> None:
        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps(
                    {
                        "action": "createSubscriptions",
                        "subscriptions": [{"topics": ["login-session:nobody"]}],
                    }
                )
            )
            (created,) = receive(socket)

        assert created["subscriptions"] == []
        assert created["errors"] == [
            {"topic": "login-session:nobody", "error": "Topic is not valid for provided API key"}
        ]

    async def test_approving_a_login_tells_the_client_that_is_waiting(
        self, account, session: AsyncSession, http: TestClient
    ) -> None:
        # What the topic is for: `_subscribeToLoginSession` in the client's
        # preferences resolves on `loginComplete` and carries the same fields
        # the poll response does, so linking finishes on the event rather than
        # on the next three-second poll.
        login = await login_service.start_session(session)
        # The row itself, not the credential it resolves to: approving a login
        # writes the key's id and hands the client the key's value.
        api_key = await auth.get_api_key_by_value(session, KEY)

        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps(
                    {
                        "action": "createSubscriptions",
                        "subscriptions": [{"topics": [f"login-session:{login.token}"]}],
                    }
                )
            )
            receive(socket)

            await login_service.approve_session(session, login.token, api_key)
            (event,) = receive(socket)

        assert event["event"] == "loginComplete"
        assert event["topic"] == f"login-session:{login.token}"
        assert event["apiKey"] == KEY
        assert event["userID"] == 1

    async def test_cancelling_one_tells_the_client_too(
        self, account, session: AsyncSession, http: TestClient
    ) -> None:
        login = await login_service.start_session(session)

        with http.websocket_connect(STREAM_PATH) as socket:
            receive(socket)
            socket.send_text(
                json.dumps(
                    {
                        "action": "createSubscriptions",
                        "subscriptions": [{"topics": [f"login-session:{login.token}"]}],
                    }
                )
            )
            receive(socket)

            await login_service.cancel_session(session, login.token)
            (event,) = receive(socket)

        assert event["event"] == "loginCancelled"
        assert event["topic"] == f"login-session:{login.token}"

    async def test_nobody_else_hears_about_a_login(
        self, account, session: AsyncSession, http: TestClient
    ) -> None:
        # The token is the credential for the poll endpoint, so it is the
        # credential for the topic: a connection that has not named it is told
        # nothing, whatever key it holds.
        login = await login_service.start_session(session)
        # The row itself, not the credential it resolves to: approving a login
        # writes the key's id and hands the client the key's value.
        api_key = await auth.get_api_key_by_value(session, KEY)

        with http.websocket_connect(STREAM_PATH, headers={"Zotero-API-Key": KEY}) as socket:
            receive(socket)
            await login_service.approve_session(session, login.token, api_key)

            http.post("/users/1/items", json=ITEM, headers={"Zotero-API-Key": KEY})
            (event,) = receive(socket)

        # The write that followed is the next thing it hears, not the login.
        assert event["event"] == "topicUpdated"


class TestEvents:
    async def test_a_write_announces_the_library_and_its_new_version(
        self, account, http: TestClient
    ) -> None:
        """The whole point: a write on one connection reaches another."""
        with http.websocket_connect(STREAM_PATH, headers={"Zotero-API-Key": KEY}) as socket:
            receive(socket)

            response = http.post("/users/1/items", json=ITEM, headers={"Zotero-API-Key": KEY})
            assert response.status_code == 200

            (event,) = receive(socket)

        assert event == {"event": "topicUpdated", "topic": "/users/1", "version": 1}

    async def test_one_request_announces_one_version(self, account, http: TestClient) -> None:
        """A batch moves the counter once, so it announces once.

        The same guarantee ``services/writes.py`` gives the version counter. A
        client told twice would sync twice for one change.
        """
        with http.websocket_connect(STREAM_PATH, headers={"Zotero-API-Key": KEY}) as socket:
            receive(socket)
            http.post(
                "/users/1/items",
                json=[
                    {"itemType": "book", "title": "One"},
                    {"itemType": "book", "title": "Two"},
                ],
                headers={"Zotero-API-Key": KEY},
            )
            (event,) = receive(socket)

            # A second write proves the first produced exactly one event: a
            # spare one would arrive here instead of this.
            http.post("/users/1/items", json=ITEM, headers={"Zotero-API-Key": KEY})
            (second,) = receive(socket)

        assert event["version"] == 1
        assert second["version"] == 2

    async def test_a_refused_write_announces_nothing(self, account, http: TestClient) -> None:
        """A rolled-back transaction must not name a version nobody can fetch."""
        with http.websocket_connect(STREAM_PATH, headers={"Zotero-API-Key": KEY}) as socket:
            receive(socket)

            http.post("/users/1/items", json=ITEM, headers={"Zotero-API-Key": KEY})
            (first,) = receive(socket)

            # The library is at 1 now, so a write claiming it is still at 0 is
            # the conflict a second client would hit.
            refused = http.post(
                "/users/1/items",
                json=ITEM,
                headers={"Zotero-API-Key": KEY, "If-Unmodified-Since-Version": "0"},
            )
            assert refused.status_code == 412

            # The next event is the successful write's, not the refused one's.
            http.post("/users/1/items", json=ITEM, headers={"Zotero-API-Key": KEY})
            (second,) = receive(socket)

        assert (first["version"], second["version"]) == (1, 2)

    async def test_a_library_nobody_subscribed_to_is_not_announced(
        self, account, session: AsyncSession, http: TestClient
    ) -> None:
        """A connection hears about its own topics and no others."""
        await factories.make_user(session, user_id=2, username="hubot")
        await factories.make_api_key(session, key="SecondKeySecondKeySecond", user_id=2)

        with http.websocket_connect(STREAM_PATH, headers={"Zotero-API-Key": KEY}) as socket:
            receive(socket)

            http.post(
                "/users/2/items",
                json=ITEM,
                headers={"Zotero-API-Key": "SecondKeySecondKeySecond"},
            )
            http.post("/users/1/items", json=ITEM, headers={"Zotero-API-Key": KEY})
            (event,) = receive(socket)

        assert event["topic"] == "/users/1"


class TestTheBroker:
    def test_it_forgets_a_connection_that_has_gone(self) -> None:
        before = broker.connections
        with broker.attach():
            during = broker.connections
        assert (before, during, broker.connections) == (before, before + 1, before)
