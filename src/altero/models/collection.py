"""Collections, their membership, and the links that share one."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, true
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


class CollectionShare(Base):
    """A link that shows one collection to whoever holds it.

    "Share a collection, not an entire library" has been asked for since 2008
    and is the longest-running request in this space. It is ruled out as a
    *sync* feature -- the client's unit of sync is a library, and scoping below
    one means either lying about that library's contents, which breaks ``since``
    and version arithmetic, or patching clients -- so this is not one. Nothing
    here is reachable with an API key, nothing here moves a library version, and
    no sync client ever learns that a share exists.

    What it is instead is a page: a read-only view of one collection, served by
    :mod:`altero.api.routes.webshares` to whoever has the link, in the same
    shape the library view reads. The token is the whole credential, as it is
    for an invitation link, which is why it is long, why a share can be given an
    expiry, and why revoking one is a delete rather than a flag.
    """

    __tablename__ = "collection_shares"
    __table_args__ = (Index("ix_collection_shares_collection", "collection_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: The whole credential: ``secrets.token_urlsafe(32)``, unguessable and
    #: never derived from anything about the collection.
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"))
    #: Who made the link. Kept so the list can say so, and so that a share
    #: outliving its author's membership is visible rather than anonymous.
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created: Mapped[datetime] = mapped_column(DateTime)
    #: When the link stops working, or null for one that never does. An expired
    #: share answers exactly as a revoked one does.
    expires: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    #: Whether the items of the collections nested inside this one come along.
    #: On by default: somebody sharing a collection means the branch, which is
    #: what the sidebar shows when they click it.
    subcollections: Mapped[bool] = mapped_column(default=True, server_default=true())
    #: Whether attachment bytes are served. Separable from the metadata because
    #: a bibliography is not the same thing to give away as the PDFs.
    files: Mapped[bool] = mapped_column(default=True, server_default=true())
    #: When the link was last followed, or null. The only thing the list can say
    #: about whether a share is still in use; no address and no count are kept.
    last_used: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class CollectionItem(Base):
    """Membership of an item in a collection."""

    __tablename__ = "collection_items"
    # The primary key serves lookups by collection. Rendering an item asks which
    # collections hold it, which reads the other column.
    __table_args__ = (Index("ix_collection_items_item_id", "item_id"),)

    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
