"""Collections and their membership."""

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    relations: Mapped[list[CollectionRelation]] = relationship(
        back_populates="collection", lazy="selectin", cascade="all, delete-orphan"
    )


class CollectionRelation(Base):
    """One entry of a collection's ``relations`` map.

    Shaped like ``ItemRelation``: a predicate may name several objects, so the
    object is part of the key rather than a column that gets overwritten.
    """

    __tablename__ = "collection_relations"

    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), primary_key=True)
    predicate: Mapped[str] = mapped_column(String(64), primary_key=True)
    object: Mapped[str] = mapped_column(String(255), primary_key=True)

    collection: Mapped[Collection] = relationship(back_populates="relations")


class CollectionItem(Base):
    """Membership of an item in a collection."""

    __tablename__ = "collection_items"
    # The primary key serves lookups by collection. Rendering an item asks which
    # collections hold it, which reads the other column.
    __table_args__ = (Index("ix_collection_items_item_id", "item_id"),)

    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
