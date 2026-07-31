"""Shared machinery for write requests.

Holds the three things every write endpoint needs: the library version counter,
the version preconditions, and the per-object result report that a multi-object
request answers with.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import (
    InvalidInputError,
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


async def bump_library_version(session: AsyncSession, library: Library) -> int:
    """Raise the library's version by one and return the new value.

    Every object written by the request is stamped with this, so one request
    produces exactly one new version no matter how many objects it touches.
    """
    library.version += 1
    await session.flush()
    return library.version


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


async def check_write_token(
    session: AsyncSession,
    library: Library,
    token: str | None,
) -> None:
    """Reject a replayed ``Zotero-Write-Token``.

    Tokens let a client retry a request that may or may not have been applied
    without creating the objects twice.
    """
    if token is None:
        return
    if len(token) != WRITE_TOKEN_LENGTH:
        raise InvalidInputError("Invalid Zotero-Write-Token value")

    existing = await session.scalar(
        select(WriteToken).where(WriteToken.library_id == library.id, WriteToken.token == token)
    )
    if existing is not None:
        raise PreconditionFailedError("Write token already used")


async def remember_write_token(
    session: AsyncSession,
    library: Library,
    token: str | None,
) -> None:
    """Record a write token so that a repeat of the request is rejected."""
    if token is None:
        return
    session.add(
        WriteToken(
            library_id=library.id,
            token=token,
            created=datetime.now(UTC).replace(tzinfo=None),
        )
    )
