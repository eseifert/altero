"""Tags and their attachment to items."""

from enum import IntEnum

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class TagType(IntEnum):
    """How a tag came to be attached to an item."""

    MANUAL = 0
    AUTOMATIC = 1


class Tag(Base):
    """A tag name within one library."""

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("library_id", "name", name="uq_tags_library_name"),
        Index("ix_tags_library_version", "library_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(default=0, index=True)


class ItemTag(Base):
    """Attachment of a tag to an item."""

    __tablename__ = "item_tags"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    type: Mapped[int] = mapped_column(default=int(TagType.MANUAL))
