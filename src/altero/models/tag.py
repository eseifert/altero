"""Tags and their attachment to items."""

from enum import IntEnum

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base, Timestamped


class TagType(IntEnum):
    """How a tag came to exist."""

    MANUAL = 0
    AUTOMATIC = 1


class Tag(Base, Timestamped):
    """A tag within one library.

    The type belongs to the tag rather than to its attachment to an item, which
    is what the dataserver's ``UNIQUE (libraryID, name, type)`` encodes: the same
    name added by hand and by a translator is two tags, not one shared by two
    links.
    """

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("library_id", "name", "type", name="uq_tags_library_name_type"),
        UniqueConstraint("library_id", "key", name="uq_tags_library_key"),
        Index("ix_tags_library_version", "library_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    key: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[int] = mapped_column(default=int(TagType.MANUAL))
    version: Mapped[int] = mapped_column(default=1, index=True)


class ItemTag(Base):
    """Attachment of a tag to an item."""

    __tablename__ = "item_tags"
    # The primary key serves lookups by item. Tag listings and tag deletion go
    # the other way, and without this index each one scans the whole table.
    __table_args__ = (Index("ix_item_tags_tag_id", "tag_id"),)

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
