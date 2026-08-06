"""Migrations in flight, so the browser can start one and come back to it.

Reading a library out of zotero.org is minutes of work, not milliseconds: a few
thousand items at a hundred a page, a full-text body per indexed attachment, and
one download per stored file, all at the pace somebody else's server allows. A
request cannot wait for that, so the request starts it and answers, and the page
asks afterwards how it is getting on.

The register is in memory, like the streaming broker and for the same reason:
it holds something that only exists while this process does. An instance behind
several workers can therefore start a migration on one and be asked about it on
another, which answers "nothing running" -- so a migration is a single-process
operation, said plainly here and in the documentation rather than discovered.
A restart loses the record of a migration but not its effect: the archive is
written, and the restore is one transaction that either happened or did not.

One at a time per account. Two migrations into one library would race for the
same rows, and the second would be restoring over what the first was still
writing.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from altero.errors import InvalidInputError
from altero.services.zoteroimport import Progress, Summary

logger = logging.getLogger("altero.migrations")


@dataclass
class Migration:
    """One migration, running or finished."""

    user_id: int
    started: datetime
    stage: str = "starting"
    done: int = 0
    total: int | None = None
    detail: str = ""
    finished: datetime | None = None
    #: What it read, once there is something to say.
    summary: Summary | None = None
    #: Why it stopped, if it stopped badly. A message for a person, not a
    #: traceback: what reaches here has already been turned into one.
    error: str | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self.finished is None

    def observe(self, progress: Progress) -> None:
        self.stage = progress.stage
        self.done = progress.done
        self.total = progress.total
        self.detail = progress.detail

    def render(self) -> dict[str, Any]:
        """Return what the browser polls for."""
        body: dict[str, Any] = {
            "running": self.running,
            "stage": self.stage,
            "done": self.done,
            "total": self.total,
            "detail": self.detail,
            "started": self.started.isoformat(),
            "finished": self.finished.isoformat() if self.finished else None,
            "error": self.error,
        }
        if self.summary is not None:
            body["summary"] = {
                "userID": self.summary.user_id,
                "username": self.summary.username,
                "libraryVersion": self.summary.library_version,
                "items": self.summary.items,
                "collections": self.summary.collections,
                "searches": self.summary.searches,
                "tags": self.summary.tags,
                "settings": self.summary.settings,
                "fulltext": self.summary.fulltext,
                "deleted": self.summary.deleted,
                "files": self.summary.files,
                "filesMissing": self.summary.files_missing,
                "skipped": [{"key": key, "reason": reason} for key, reason in self.summary.skipped],
                "rewritten": self.summary.rewritten,
                "complete": self.summary.complete,
            }
        return body


class Register:
    """The migrations this process knows about, one per account."""

    def __init__(self) -> None:
        self._by_user: dict[int, Migration] = {}

    def get(self, user_id: int) -> Migration | None:
        return self._by_user.get(user_id)

    def start(self, user_id: int) -> Migration:
        """Claim the slot for this account, or refuse because one is in it."""
        existing = self._by_user.get(user_id)
        if existing is not None and existing.running:
            raise InvalidInputError("A migration is already running for this account")

        migration = Migration(user_id=user_id, started=datetime.now(UTC))
        self._by_user[user_id] = migration
        return migration

    def finish(self, migration: Migration, *, error: str | None = None) -> None:
        migration.error = error
        migration.finished = datetime.now(UTC)
        migration.stage = "failed" if error else "done"
        migration.task = None


#: The register this process uses. One object rather than one per application,
#: which is what the streaming broker does and for the same reason: there is
#: only ever one process's worth of them.
register = Register()
