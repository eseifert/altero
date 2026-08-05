"""Items and everything hanging off them."""

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from altero.db import Base, Timestamped


class Item(Base, Timestamped):
    """A bibliographic item, note or attachment."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("library_id", "key", name="uq_items_library_key"),
        Index("ix_items_library_version", "library_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    key: Mapped[str] = mapped_column(String(8))
    #: Library version at which this item last changed; drives ``since``.
    version: Mapped[int] = mapped_column(default=1, index=True)
    item_type: Mapped[str] = mapped_column(String(32), index=True)
    #: Parent of a note or attachment, expressed as ``parentItem`` in JSON.
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), index=True)
    #: Whether the item sits in the trash.
    deleted: Mapped[bool] = mapped_column(default=False, index=True)
    #: Whether the item is in the owner's My Publications, which only a personal
    #: library has. Indexed because the publications listing filters on it.
    in_publications: Mapped[bool] = mapped_column(default=False, index=True)

    # Who wrote this, in a group library. Both are null in a personal library:
    # it has one author, and upstream keeps these in a `groupItems` table that
    # only group libraries have rows in.
    #
    # Nulled rather than cascaded when an account goes, because the item stays
    # and "added by somebody who has since left" is true and worth keeping. It
    # is also what upstream's serialiser expects: it swallows the lookup and
    # emits nothing when the user no longer exists.
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    last_modified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    # Sort keys derived from the item's data whenever it is written. Each item
    # type names its title, creator and date differently, so sorting straight
    # off `item_fields` would need a per-type join; these keep it to a column.
    sort_title: Mapped[str] = mapped_column(String(500), default="", index=True)
    sort_creator: Mapped[str] = mapped_column(String(255), default="", index=True)
    sort_date: Mapped[str] = mapped_column(String(32), default="", index=True)

    fields: Mapped[list[ItemField]] = relationship(
        back_populates="item", lazy="selectin", cascade="all, delete-orphan"
    )
    creators: Mapped[list[ItemCreator]] = relationship(
        back_populates="item",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ItemCreator.position",
    )
    relations: Mapped[list[ItemRelation]] = relationship(
        back_populates="item", lazy="selectin", cascade="all, delete-orphan"
    )

    def field_values(self) -> dict[str, str]:
        """Return the item's field values keyed by field name."""
        return {field.field: field.value for field in self.fields}


class ItemField(Base):
    """One field value of an item.

    Fields are stored as rows rather than columns because the 40 item types
    accept overlapping subsets of 121 fields.
    """

    __tablename__ = "item_fields"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    field: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

    item: Mapped[Item] = relationship(back_populates="fields")


class ItemCreator(Base):
    """A creator of an item, in the order the client supplied them.

    A creator is written either as a first/last pair or as a single ``name``;
    which one is in use is recorded by leaving the other columns null.
    """

    __tablename__ = "item_creators"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    creator_type: Mapped[str] = mapped_column(String(32))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))

    item: Mapped[Item] = relationship(back_populates="creators")

    @property
    def sort_name(self) -> str:
        """Return the name used for display and for sorting by creator."""
        return self.name or self.last_name or self.first_name or ""


class ItemRelation(Base):
    """One entry of an item's ``relations`` map."""

    __tablename__ = "item_relations"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    predicate: Mapped[str] = mapped_column(String(64), primary_key=True)
    object: Mapped[str] = mapped_column(String(255), primary_key=True)

    item: Mapped[Item] = relationship(back_populates="relations")
