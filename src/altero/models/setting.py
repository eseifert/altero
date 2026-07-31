"""Library settings."""

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class Setting(Base):
    """One named setting of a library.

    Settings hold whatever JSON the client puts in them — tag colours, feed
    definitions and the like — so the value is stored encoded rather than
    modelled. They are versioned like every other syncable object.
    """

    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("library_id", "name", name="uq_settings_library_name"),
        Index("ix_settings_library_version", "library_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    #: The setting's value, encoded as JSON.
    value: Mapped[str] = mapped_column(Text, default="null")
    version: Mapped[int] = mapped_column(default=1, index=True)
