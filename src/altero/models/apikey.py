"""API keys and the access they grant."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from altero.db import Base


class ApiKey(Base):
    """A credential belonging to one user.

    Access to the owner's personal library is described by the ``library_*``,
    ``notes_read`` and ``files_read`` flags. Access to group libraries defaults to
    the ``all_groups_*`` flags and can be overridden per group.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")

    library_read: Mapped[bool] = mapped_column(default=True)
    library_write: Mapped[bool] = mapped_column(default=False)
    notes_read: Mapped[bool] = mapped_column(default=True)
    files_read: Mapped[bool] = mapped_column(default=True)

    all_groups_read: Mapped[bool] = mapped_column(default=False)
    all_groups_write: Mapped[bool] = mapped_column(default=False)

    group_access: Mapped[list[ApiKeyGroupAccess]] = relationship(
        back_populates="api_key",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class ApiKeyGroupAccess(Base):
    """Per-group access that overrides an API key's ``all_groups_*`` defaults."""

    __tablename__ = "api_key_group_access"

    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), primary_key=True)
    read: Mapped[bool] = mapped_column(default=False)
    write: Mapped[bool] = mapped_column(default=False)

    api_key: Mapped[ApiKey] = relationship(back_populates="group_access")
