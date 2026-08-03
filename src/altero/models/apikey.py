"""API keys and the access they grant."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
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
    #: When the key was issued. Null for keys that predate this column: they
    #: are left unknown rather than backfilled with the time of the migration,
    #: which would be a date that means nothing.
    created: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())
    #: When this key was last seen, and where from. Written at most once an
    #: interval per key rather than on every request -- a syncing client makes
    #: a great many, and this is a convenience for deciding what to revoke,
    #: not an audit log.
    last_used: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    #: The address the request came from. Behind a proxy this is the proxy
    #: unless forwarded_allow_ips names it.
    last_address: Mapped[str | None] = mapped_column(String(45), default=None)
    last_user_agent: Mapped[str | None] = mapped_column(String(255), default=None)

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
