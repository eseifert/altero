"""Bookkeeping that supports syncing: write tokens and the delete log."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class DeletedObjectType(StrEnum):
    """Object kinds recorded in the delete log.

    Mirrors the enum on the dataserver's ``syncDeleteLogKeys`` table.
    """

    COLLECTION = "collection"
    ITEM = "item"
    SEARCH = "search"
    SETTING = "setting"
    TAG = "tag"


class DeletedObject(Base):
    """One removed object, so that ``/deleted?since=`` can report it.

    Keyed by object type and key, so deleting a key that was deleted before
    updates the existing row instead of adding a second one.
    """

    __tablename__ = "deleted_objects"
    __table_args__ = (
        UniqueConstraint(
            "library_id", "object_type", "key", name="uq_deleted_objects_library_type_key"
        ),
        Index("ix_deleted_objects_library_version", "library_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(16))
    #: The object's key, or the name for tags and settings.
    key: Mapped[str] = mapped_column(String(255))
    #: Library version at which the deletion happened.
    version: Mapped[int] = mapped_column(default=1, index=True)
    deleted: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WriteToken(Base):
    """A ``Zotero-Write-Token`` that has already been honoured.

    Remembering these lets a client safely retry a request whose outcome it
    never saw, without the objects being created a second time.
    """

    __tablename__ = "write_tokens"
    __table_args__ = (
        UniqueConstraint("library_id", "token", name="uq_write_tokens_library_token"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    token: Mapped[str] = mapped_column(String(32))
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
