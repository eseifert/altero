"""Shared machinery for write requests.

Holds the three things every write endpoint needs: the library version counter,
the version preconditions, and the per-object result report that a multi-object
request answers with.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import (
    InvalidInputError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
    RequestTooLargeError,
)
from altero.models import Library, WriteToken

#: Largest number of objects one write request may carry.
MAX_OBJECTS = 50

#: How long a write token is remembered, per the documentation.
WRITE_TOKEN_LIFETIME_HOURS = 12

#: Length of a write token, which clients generate as 32 random characters.
WRITE_TOKEN_LENGTH = 32


@dataclass(slots=True)
class WriteResults:
    """The per-object outcome of a multi-object write.

    The API answers ``200`` even when individual objects fail, so the caller
    inspects this report rather than the status code. ``success`` duplicates the
    keys from ``successful``; it is deprecated but still emitted in v3, and the
    desktop client is entitled to read either.
    """

    successful: dict[int, Any] = field(default_factory=dict)
    unchanged: dict[int, str] = field(default_factory=dict)
    failed: dict[int, dict[str, Any]] = field(default_factory=dict)

    def add_successful(self, index: int, obj: dict[str, Any]) -> None:
        self.successful[index] = obj

    def add_unchanged(self, index: int, key: str) -> None:
        self.unchanged[index] = key

    def add_failure(self, index: int, key: str, code: int, message: str) -> None:
        entry: dict[str, Any] = {"code": code, "message": message}
        # A failure before a key was known is reported without one.
        if key:
            entry = {"key": key, **entry}
        self.failed[index] = entry

    def report(self) -> dict[str, Any]:
        """Return the response body, with string indices as the API uses."""
        return {
            "successful": {str(i): obj for i, obj in self.successful.items()},
            "success": {str(i): obj["key"] for i, obj in self.successful.items()},
            "unchanged": {str(i): key for i, key in self.unchanged.items()},
            "failed": {str(i): entry for i, entry in self.failed.items()},
        }

    @property
    def any_succeeded(self) -> bool:
        return bool(self.successful)


async def lock_library(session: AsyncSession, library: Library) -> Library:
    """Take a row lock on ``library`` for the rest of the transaction.

    Writes to one library must not interleave: two requests that each read the
    version, add one and store the result would hand out the same version twice
    and lose one side's changes. Holding the lock from before the precondition
    check until commit makes a write request atomic with respect to the library.

    ``FOR UPDATE`` is emitted on backends that have it and dropped on SQLite,
    which serializes writers anyway.
    """
    locked = await session.scalar(
        select(Library)
        .where(Library.id == library.id)
        .with_for_update()
        # Without this the identity map would hand back the cached row, so the
        # lock would be held over a version read before it was taken.
        .execution_options(populate_existing=True)
    )
    return locked if locked is not None else library


async def bump_library_version(session: AsyncSession, library: Library) -> int:
    """Raise the library's version by one and return the new value.

    Every object written by the request is stamped with this, so one request
    produces exactly one new version no matter how many objects it touches. The
    increment is computed by the database rather than in Python, so it is right
    even without the row lock above.
    """
    version = await session.scalar(
        update(Library)
        .where(Library.id == library.id)
        .values(version=Library.version + 1)
        .returning(Library.version)
    )
    if version is None:  # pragma: no cover - the library was just resolved
        raise NotFoundError("Library not found")

    # Keep the in-memory object in step with the row we just changed.
    await session.refresh(library, ["version"])
    return version


def parse_object_list(payload: Any) -> list[dict[str, Any]]:
    """Return the objects of a write request body.

    A single object is accepted in place of a one-element array, which is what
    the API does for convenience.
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise InvalidInputError("Uploaded data must be a JSON array or object")
    if len(payload) > MAX_OBJECTS:
        raise RequestTooLargeError(f"Cannot process more than {MAX_OBJECTS} objects at a time")
    for entry in payload:
        if not isinstance(entry, dict):
            raise InvalidInputError("Invalid object")
    return payload


def parse_version_header(value: str | None) -> int | None:
    """Return the ``If-Unmodified-Since-Version`` value, if the client sent one."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        raise InvalidInputError("Invalid If-Unmodified-Since-Version value") from None


def check_library_version(library: Library, expected: int | None, *, required: bool) -> None:
    """Fail unless the library is still at the version the client last saw.

    Args:
        expected: The value of ``If-Unmodified-Since-Version``, if supplied.
        required: Whether its absence is itself an error, which it is for
            deletes.
    """
    if expected is None:
        if required:
            raise PreconditionRequiredError("If-Unmodified-Since-Version not provided")
        return

    if library.version > expected:
        raise PreconditionFailedError(
            "Library has been modified since specified version "
            f"(expected {expected}, found {library.version})"
        )


def check_object_version(
    current: int,
    supplied: int | None,
    *,
    required: bool = True,
) -> None:
    """Fail unless ``supplied`` matches the object's stored version.

    A key-based write must state which version it is replacing, either through
    the header or the object's own ``version`` property; ``0`` means "create
    this, it should not exist yet".
    """
    if supplied is None:
        if required:
            raise PreconditionRequiredError(
                "Either If-Unmodified-Since-Version or object version property "
                "must be provided for key-based writes"
            )
        return

    if supplied != current:
        raise PreconditionFailedError(
            f"Item has been modified since specified version (expected {supplied}, found {current})"
        )


async def claim_write_token(
    session: AsyncSession,
    library: Library,
    token: str | None,
) -> None:
    """Claim a ``Zotero-Write-Token``, rejecting one already used.

    Tokens let a client retry a request whose outcome it never saw without the
    objects being created twice. Claiming by insert rather than by looking first
    and inserting later closes the window in which two copies of the same
    request both find the token absent: the unique constraint decides, so the
    outcome does not depend on timing.

    The row is written inside this request's transaction, so a request that ends
    in a rollback releases the token as well — which is what makes a retry of a
    failed request work.
    """
    if token is None:
        return
    if len(token) != WRITE_TOKEN_LENGTH:
        raise InvalidInputError("Invalid Zotero-Write-Token value")

    try:
        async with session.begin_nested():
            session.add(
                WriteToken(
                    library_id=library.id,
                    token=token,
                    created=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            await session.flush()
    except IntegrityError:
        raise PreconditionFailedError("Write token already used") from None
