"""Collections and their membership."""

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base, Timestamped


class Collection(Base, Timestamped):
    """A collection, which may be nested inside another."""

    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("library_id", "key", name="uq_collections_library_key"),
        Index("ix_collections_library_version", "library_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    key: Mapped[str] = mapped_column(String(8))
    version: Mapped[int] = mapped_column(default=1, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    #: ``parentCollection`` in JSON; null for a top-level collection.
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"), index=True)
    deleted: Mapped[bool] = mapped_column(default=False, index=True)


class CollectionItem(Base):
    """Membership of an item in a collection."""

    __tablename__ = "collection_items"

    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
