"""What happened in a group library, awaiting delivery to its members."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class ActivityKind(StrEnum):
    """A kind of change a member can ask to hear about.

    Stored as the string rather than an id, because these are read by the sweep
    that renders them and by a member's preferences, and a number in either
    place would need a lookup table to stay legible.
    """

    ITEMS_CHANGED = "items_changed"
    ITEMS_DELETED = "items_deleted"
    MEMBERS_CHANGED = "members_changed"
    COLLECTIONS_CHANGED = "collections_changed"


class GroupActivity(Base):
    """One thing that happened in a group library, not yet delivered.

    A row per write request per kind, not per object and not per recipient. Per
    request because that is the granularity of a library version, so fifty
    items uploaded together are one event; per kind because a member subscribes
    to kinds separately and they cannot be added together. Not per recipient
    because a large group would then cost fifty inserts on the sync path --
    the fan-out is the sweep's job, off anybody's request.

    Rows survive delivery, stamped with ``flushed`` rather than deleted. What
    is left is a per-library record of who changed what and when, which is the
    substrate an activity log would be built from.
    """

    __tablename__ = "group_activity"
    __table_args__ = (
        # The sweep's query: unflushed rows, oldest first, by library.
        Index("ix_group_activity_pending", "flushed", "library_id", "created"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    #: Who did it, or null for a write that reached the library without a key
    #: naming a person. Nulled rather than cascaded if the account goes, so the
    #: record of the change survives the departure of whoever made it.
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    kind: Mapped[str] = mapped_column(String(32))
    #: How many objects the request touched. Summed across rows when rendered,
    #: so a burst reads as one number rather than a list of requests.
    count: Mapped[int] = mapped_column(default=0)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    #: When the sweep took this row. Null means it is still waiting, and is
    #: what the sweep claims against so two of them cannot send the same digest.
    flushed: Mapped[datetime | None] = mapped_column(DateTime, default=None)
