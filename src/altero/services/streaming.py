"""The streaming API's event broker.

The v3 API tells a client *what* changed only when it asks. The streaming API
tells it *that* something changed, so it can ask straight away instead of
polling. What travels over the socket is a library and its new version, never
an object: a client that hears about a change runs its ordinary sync, which is
the code path that already handles conflicts and permissions.

There is no reference implementation to copy. Grepping the dataserver source
for a WebSocket route returns nothing -- the service behind
``wss://stream.zotero.org`` is something else -- so the protocol here is built
from the published documentation, and ``docs/compatibility.md`` records which
parts of it are inferred.

**One process.** The broker is in memory, so a deployment running several
workers delivers an event only to the clients attached to the worker that
served the write. Sync still works: the client polls as it always did, and the
socket is an optimisation on top. A multi-worker deployment that wants
streaming needs a shared bus, which this is deliberately not.
"""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from altero.models import Library, LibraryType

logger = logging.getLogger("altero.streaming")

#: How long the client is asked to wait before reconnecting, in milliseconds.
#: The documented value.
RETRY_MILLISECONDS = 10000

#: Events held for one connection before the oldest is dropped. A connection
#: that cannot keep up is one that has stopped reading; dropping the oldest
#: event is safe because every event says the same thing -- ask again -- and
#: the newest one says it with the current version.
QUEUE_SIZE = 64

#: Key under which a session collects the topics its transaction has moved.
#: They are published on commit rather than as they happen, so a write that
#: rolls back does not announce a version nobody can fetch.
_PENDING = "altero.streaming.pending"


@dataclass(frozen=True, slots=True)
class TopicUpdated:
    """A library's version moved."""

    topic: str
    version: int


@dataclass(frozen=True, slots=True)
class AccessChanged:
    """What one user may reach has changed, so their topics need re-checking."""

    user_id: int


#: Anything the broker carries.
Event = TopicUpdated | AccessChanged


def topic_for(library: Library) -> str:
    """Return the topic naming ``library``.

    The same ``/users/<id>`` or ``/groups/<id>`` prefix the API is addressed
    by, which is what the documentation uses and what a client already holds.
    """
    prefix = "users" if library.type is LibraryType.USER else "groups"
    return f"/{prefix}/{library.owner_id}"


class Broker:
    """Fan-out of events to the connections currently attached.

    Every event goes to every connection, which then decides whether it holds a
    subscription that covers it. Filtering here instead would have to be redone
    each time a connection changes its subscriptions; filtering there is one
    place, next to the state that decides it. Nothing leaves a connection that
    it does not hold a subscription for.
    """

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[Event]] = set()

    @contextmanager
    def attach(self) -> Iterator[asyncio.Queue[Event]]:
        """Yield a queue receiving events for as long as the caller holds it."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    def publish(self, message: Event) -> None:
        """Deliver ``message`` to every attached connection.

        Synchronous on purpose: it is called from SQLAlchemy's ``after_commit``,
        which is not a coroutine, and putting onto an unbounded-wait queue there
        would mean a stalled reader could hold up a database transaction.
        """
        for queue in list(self._queues):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Drop the oldest and try once more. See QUEUE_SIZE.
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except asyncio.QueueEmpty, asyncio.QueueFull:  # pragma: no cover - racy
                    logger.debug("Dropped a streaming event for a stalled connection")

    @property
    def connections(self) -> int:
        return len(self._queues)


#: The process-wide broker. A module-level singleton rather than something on
#: the application state, because the write path that feeds it takes a database
#: session and knows nothing about the application.
broker = Broker()


def _pending(session: Session | Any) -> dict[str, Event]:
    return session.info.setdefault(_PENDING, {})


def note_change(session: Session | Any, library: Library, version: int) -> None:
    """Record that ``library`` is now at ``version``, to announce on commit.

    Keyed by topic, so a request that moves one library once -- which is every
    request, since the version counter moves once per request -- announces it
    once however many objects it wrote.
    """
    topic = topic_for(library)
    _pending(session)[topic] = TopicUpdated(topic=topic, version=version)


def note_access_change(session: Session | Any, user_id: int) -> None:
    """Record that what ``user_id`` may reach has changed.

    Joining or leaving a group does not move any library's version, so nothing
    else on the write path would notice. A connection subscribed without naming
    topics re-resolves them when it sees this, and reports what it gained or
    lost.
    """
    _pending(session)[f"access:{user_id}"] = AccessChanged(user_id=user_id)


@event.listens_for(Session, "after_commit")
def _publish_pending(session: Session) -> None:
    """Announce what the committed transaction changed.

    On ``after_commit`` rather than at the point of change, because a
    transaction that rolls back must announce nothing: a client told about a
    version that never existed would ask for it, be told the library is
    older, and have no way to tell that from a server that had gone backwards.
    """
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    for message in pending.values():
        broker.publish(message)


@event.listens_for(Session, "after_soft_rollback")
def _discard_pending(session: Session, previous_transaction: Any) -> None:
    """Drop what a rolled-back transaction would have announced."""
    if not session.is_active:
        session.info.pop(_PENDING, None)
