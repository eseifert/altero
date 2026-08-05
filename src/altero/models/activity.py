"""What happened in a group library, awaiting delivery to its members."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    #: Loaded only where it is wanted. The sweep that sends digests reads the
    #: counts and never the names, and ``selectin`` here would make every sweep
    #: fetch every object row it is not going to look at. ``raise_on_sql``
    #: keeps that honest: reading this without having asked for it is an error
    #: rather than a query nobody meant to run.
    objects: Mapped[list[GroupActivityObject]] = relationship(
        back_populates="activity", lazy="raise_on_sql", cascade="all, delete-orphan"
    )


class GroupActivityObject(Base):
    """One object an activity row touched, named as it was at the time.

    The name is a snapshot rather than a join, for the reason
    :mod:`altero.services.notifications` gives for holding rendered text: a
    record of something that happened should say what was true when it
    happened. An item renamed afterwards must not rewrite history, and one
    deleted afterwards must not turn its entry into a blank row -- which is
    also the only way a deletion can be shown at all, since there is nothing
    left to look the name up from.

    Bounded by the API rather than by a cap here: a write request carries at
    most ``writes.MAX_OBJECTS`` objects, so one activity row can never hold
    more than fifty of these however large the library.
    """

    __tablename__ = "group_activity_objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(
        ForeignKey("group_activity.id", ondelete="CASCADE"), index=True
    )
    #: The object's key, for the interface to link to. Not a foreign key: the
    #: object may be gone, and that is exactly the case worth showing.
    object_key: Mapped[str] = mapped_column(String(8))
    #: What it was called. Long enough for a note's opening, which is what the
    #: item list shows in place of the title a note does not have.
    name: Mapped[str] = mapped_column(String(500), default="")

    activity: Mapped[GroupActivity] = relationship(back_populates="objects")
