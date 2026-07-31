"""Saved searches."""

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from altero.db import Base


class SavedSearch(Base):
    """A stored search definition."""

    __tablename__ = "searches"
    __table_args__ = (
        UniqueConstraint("library_id", "key", name="uq_searches_library_key"),
        Index("ix_searches_library_version", "library_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    key: Mapped[str] = mapped_column(String(8))
    version: Mapped[int] = mapped_column(default=0, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    deleted: Mapped[bool] = mapped_column(default=False, index=True)

    conditions: Mapped[list[SearchCondition]] = relationship(
        back_populates="search",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="SearchCondition.position",
    )


class SearchCondition(Base):
    """One clause of a saved search, in the order it was supplied."""

    __tablename__ = "search_conditions"

    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    condition: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(32), default="")
    value: Mapped[str] = mapped_column(Text, default="")

    search: Mapped[SavedSearch] = relationship(back_populates="conditions")
