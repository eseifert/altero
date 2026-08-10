"""The streaming API.

A WebSocket that says which library changed and to what version, so a client
can sync on being told rather than on a timer. It carries no library data: what
a subscriber gets is a topic and a number, and it fetches through the ordinary
v3 endpoints with the credential it already holds.

Two ways in, both documented:

- **Single key.** The handshake carries ``Zotero-API-Key``. The connection is
  subscribed to everything that key can reach, and the ``connected`` event
  lists it.
- **Several keys.** The connection starts bare and the client sends
  ``createSubscriptions``. This is the one the Zotero client uses: it sends one
  subscription naming its key and no topics, which means "everything this key
  can reach, and keep it up to date".

The address is not derived from ``api.url``. The client compiles in
``wss://stream.zotero.org`` and only ``extensions.zotero.streaming.url``
overrides it, so a deployment has to set that preference explicitly -- see
``docs/clients.md``. Until it is set, the client opens a socket to zotero.org
and hands it an API key, which is why ``clients.md`` says to turn streaming off
rather than leave it pointing there.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect

from altero.api.deps import API_KEY_HEADER
from altero.errors import ForbiddenError, NotFoundError
from altero.models import ApiKey, LibraryType
from altero.services import auth, groups, login
from altero.services.streaming import (
    LOGIN_TOPIC_PREFIX,
    RETRY_MILLISECONDS,
    AccessChanged,
    Event,
    LoginResolved,
    TopicUpdated,
    broker,
    topic_for,
)

logger = logging.getLogger("altero.streaming")

router = APIRouter(tags=["streaming"])

#: Path the socket is served at. Upstream's is the root of a host of its own;
#: altero has one application, so it gets a path under it.
STREAM_PATH = "/stream"

#: Close codes, as the documentation lists them. 4409 ("no such subscription")
#: is documented and deliberately never sent -- see `Connection.delete`.
INVALID_KEY = 4403
TOO_MANY_SUBSCRIPTIONS = 4413

#: Topics that are nobody's library and that this server never publishes to.
#: The client subscribes to both whenever it is set to update translators and
#: styles automatically; refusing them put an error in its log on every
#: connection and changed nothing, because its own repository timer is what
#: fetches those.
PUBLIC_TOPICS = frozenset({"styles", "translators"})

#: Sent for a message that is not JSON, or names no action this server has.
#: The documentation does not give a code for it; 4400 continues the series and
#: is recorded as altero's own in docs/compatibility.md.
INVALID_MESSAGE = 4400

#: Most subscriptions one connection may hold. Upstream has a limit and does
#: not publish the number; this one is far above what a client needs -- the
#: Zotero client holds exactly one -- and low enough to bound the work a single
#: socket can ask for.
MAX_SUBSCRIPTIONS = 50


@dataclass(slots=True)
class Subscription:
    """What one connection is watching, for one credential.

    ``automatic`` is the mode the Zotero client uses: it named no topics, so
    the set follows what the key can reach and the connection reports what it
    gains and loses.
    """

    api_key: str | None
    topics: set[str] = field(default_factory=set)
    automatic: bool = False

    def rendered(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"topics": sorted(self.topics)}
        if self.api_key is not None:
            payload = {"apiKey": self.api_key, **payload}
        return payload


async def _may_watch(session: AsyncSession, topic: str, allowed: set[str]) -> bool:
    """Say whether this connection may subscribe to ``topic``.

    Three kinds, and only the first is a library. The Zotero client names the
    other two on every connection and logged an error for each one until they
    were accepted here.
    """
    if topic in allowed or topic in PUBLIC_TOPICS:
        return True

    if topic.startswith(LOGIN_TOPIC_PREFIX):
        # The token is the credential: it is what `GET /keys/sessions/<token>`
        # is authenticated by, so knowing it is what watching it takes. One
        # that names no session is refused rather than accepted and silent,
        # which would leave a client waiting on an event that cannot come.
        try:
            await login.get_session(session, topic.removeprefix(LOGIN_TOPIC_PREFIX))
        except NotFoundError:
            return False
        return True

    return False


async def _readable_topics(session: AsyncSession, api_key: ApiKey | None) -> set[str]:
    """Return every topic ``api_key`` may read.

    An anonymous connection can still watch a public library, which is the only
    thing it could read through the API either.
    """
    topics: set[str] = set()

    if api_key is None:
        for library in await groups.list_public_libraries(session):
            topics.add(topic_for(library))
        return topics

    personal = await auth.get_library(session, LibraryType.USER, api_key.user_id)
    if (await auth.get_access(session, personal, api_key)).read:
        topics.add(topic_for(personal))

    for library, _ in await groups.list_groups_for_user(session, api_key.user_id):
        if (await auth.get_access(session, library, api_key)).read:
            topics.add(topic_for(library))

    return topics


class Connection:
    """One open socket and the subscriptions it holds."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        #: Keyed by API key, with ``None`` for the anonymous subscription.
        self.subscriptions: dict[str | None, Subscription] = {}

    def _session(self) -> Any:
        return self.websocket.app.state.database.session_factory()

    async def send(self, payload: dict[str, Any]) -> None:
        await self.websocket.send_text(json.dumps(payload))

    def watching(self, topic: str) -> bool:
        return any(topic in entry.topics for entry in self.subscriptions.values())

    # -- the client's half ------------------------------------------------

    async def handle(self, message: str) -> None:
        """Act on one message from the client."""
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            await self.close(INVALID_MESSAGE, "Invalid message")
            return

        if not isinstance(payload, dict):
            await self.close(INVALID_MESSAGE, "Invalid message")
            return

        action = payload.get("action")
        if action == "createSubscriptions":
            await self.create(payload.get("subscriptions") or [])
        elif action == "deleteSubscriptions":
            await self.delete(payload.get("subscriptions") or [])
        else:
            await self.close(INVALID_MESSAGE, f"Invalid action '{action}'")

    async def create(self, requested: list[Any]) -> None:
        """Add subscriptions and report what was added and what was refused."""
        errors: list[dict[str, Any]] = []

        async with self._session() as session:
            for entry in requested:
                if not isinstance(entry, dict):
                    errors.append({"error": "Invalid subscription"})
                    continue
                await self._create_one(session, entry, errors)

        await self.send(
            {
                "event": "subscriptionsCreated",
                "subscriptions": [entry.rendered() for entry in self.subscriptions.values()],
                "errors": errors,
            }
        )

    async def _create_one(
        self, session: AsyncSession, entry: dict[str, Any], errors: list[dict[str, Any]]
    ) -> None:
        key_value = entry.get("apiKey")
        api_key: ApiKey | None = None

        if key_value is not None:
            try:
                api_key = await auth.authenticate(session, str(key_value))
            except ForbiddenError:
                errors.append({"apiKey": key_value, "error": "Invalid API key"})
                return

        allowed = await _readable_topics(session, api_key)
        asked = entry.get("topics")

        if asked is None:
            topics, automatic = allowed, True
        else:
            topics, automatic = set(), False
            for topic in asked:
                if await _may_watch(session, str(topic), allowed):
                    topics.add(str(topic))
                else:
                    errors.append(
                        {
                            **({"apiKey": key_value} if key_value is not None else {}),
                            "topic": topic,
                            "error": "Topic is not valid for provided API key",
                        }
                    )

        if not topics and asked is not None:
            return

        existing = self.subscriptions.get(key_value)
        if existing is None:
            existing = Subscription(api_key=key_value)
            self.subscriptions[key_value] = existing
        existing.topics |= topics
        existing.automatic = existing.automatic or automatic

        if sum(len(entry.topics) for entry in self.subscriptions.values()) > MAX_SUBSCRIPTIONS:
            await self.close(TOO_MANY_SUBSCRIPTIONS, "Too many subscriptions")

    async def delete(self, requested: list[Any]) -> None:
        """Drop subscriptions and report which ones went.

        Naming one that is not held is ignored rather than answered with 4409.
        The client's own login flow produces exactly that: it asks to watch
        ``login-session:<token>``, and unsubscribes when the login is over
        whether the subscription was granted or not. Closing the socket there
        is worse than useless -- the client reads a close code of its own
        making as its bug, logs "Not reconnecting to WebSocket due to client
        error", and stops trying.
        """
        removed: list[dict[str, Any]] = []

        for entry in requested:
            if not isinstance(entry, dict):
                await self.close(INVALID_MESSAGE, "Invalid subscription")
                return

            key_value = entry.get("apiKey")
            held = self.subscriptions.get(key_value)
            if held is None:
                continue

            topic = entry.get("topic")
            if topic is None:
                removed.append(held.rendered())
                del self.subscriptions[key_value]
                continue
            if topic not in held.topics:
                continue
            held.topics.discard(str(topic))
            removed.append(Subscription(api_key=key_value, topics={str(topic)}).rendered())
            # A subscription that named topics and has none left is gone; one
            # that tracks a key automatically stays, because access can return.
            if not held.topics and not held.automatic:
                del self.subscriptions[key_value]

        # `streamer.js` walks `data.subscriptions` to take them out of its own
        # set, and throws on an event that has not got them.
        await self.send({"event": "subscriptionsDeleted", "subscriptions": removed})

    # -- the broker's half ------------------------------------------------

    async def deliver(self, message: Event) -> None:
        if isinstance(message, LoginResolved):
            # Only to the connection that named the token, which is the one
            # waiting to be linked.
            if self.watching(message.topic):
                await self.send({"event": message.event, "topic": message.topic, **message.payload})
            return

        if isinstance(message, TopicUpdated):
            if self.watching(message.topic):
                await self.send(
                    {
                        "event": "topicUpdated",
                        "topic": message.topic,
                        "version": message.version,
                    }
                )
            return

        await self._resync(message)

    async def _resync(self, message: AccessChanged) -> None:
        """Re-resolve the automatic subscriptions and report what moved.

        Only the ones that named no topics: a client that listed its topics
        chose them, and adding one it did not ask for would be this server
        deciding what it watches.
        """
        async with self._session() as session:
            for entry in self.subscriptions.values():
                if not entry.automatic:
                    continue
                api_key = (
                    await auth.authenticate(session, entry.api_key)
                    if entry.api_key is not None
                    else None
                )
                if api_key is not None and api_key.user_id != message.user_id:
                    continue

                current = await _readable_topics(session, api_key)
                for topic in sorted(current - entry.topics):
                    await self._announce("topicAdded", entry, topic)
                for topic in sorted(entry.topics - current):
                    await self._announce("topicRemoved", entry, topic)
                entry.topics = current

    async def _announce(self, event: str, entry: Subscription, topic: str) -> None:
        payload: dict[str, Any] = {"event": event, "topic": topic}
        if entry.api_key is not None:
            payload = {"event": event, "apiKey": entry.api_key, "topic": topic}
        await self.send(payload)

    async def close(self, code: int, reason: str) -> None:
        await self.websocket.close(code=code, reason=reason)
        raise WebSocketDisconnect(code=code, reason=reason)


@router.websocket(STREAM_PATH)
async def stream(websocket: WebSocket) -> None:
    """Serve one streaming connection."""
    await websocket.accept()
    connection = Connection(websocket)

    credential = websocket.headers.get(API_KEY_HEADER)
    greeting: dict[str, Any] = {"event": "connected", "retry": RETRY_MILLISECONDS}

    if credential:
        async with websocket.app.state.database.session_factory() as session:
            try:
                api_key = await auth.authenticate(session, credential)
            except ForbiddenError:
                # The documented code for a key the server does not know. Sent
                # before anything else, so a misconfigured client learns why
                # rather than seeing a socket that closes for no stated reason.
                await websocket.close(code=INVALID_KEY, reason="Invalid API key")
                return

            topics = await _readable_topics(session, api_key)

        connection.subscriptions[credential] = Subscription(
            api_key=credential, topics=topics, automatic=True
        )
        # In single-key mode the topics belong to the connection rather than to
        # a named subscription, so they are listed on the greeting itself.
        greeting["topics"] = sorted(topics)

    await connection.send(greeting)

    # Two halves that both block: one on the socket, one on the broker. The
    # first to finish ends the connection, which is what makes a client hanging
    # up stop the writer rather than leave it waiting on a queue for ever.
    with broker.attach() as queue:
        reader = asyncio.create_task(_read(connection))
        writer = asyncio.create_task(_write(connection, queue))
        done, pending = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()
        for task in done:
            try:
                task.result()
            except WebSocketDisconnect, asyncio.CancelledError:
                # The ordinary end of a connection: the client hung up, or
                # this server closed on it and raised to unwind.
                pass
            except Exception:  # pragma: no cover - defensive
                logger.exception("Streaming connection failed")


async def _read(connection: Connection) -> None:
    """Act on the client's messages until it goes away."""
    while True:
        await connection.handle(await connection.websocket.receive_text())


async def _write(connection: Connection, queue: asyncio.Queue[Event]) -> None:
    """Forward what the broker publishes, filtered by what this socket holds."""
    while True:
        await connection.deliver(await queue.get())
