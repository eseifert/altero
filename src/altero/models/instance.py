"""Settings belonging to the instance rather than to a library."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class InstanceSetting(Base):
    """One policy the operator has set, held by name.

    Deliberately not :class:`~altero.models.setting.Setting`, which it is
    shaped like: that one belongs to a library, is versioned, and syncs to
    every client. This one belongs to the server, syncs nowhere, and would be
    a strange thing to hand a Zotero client.

    A row exists only for a setting somebody has changed. What is not here
    falls back to the ``ALTERO_``-prefixed configuration, so an operator who
    prefers a config file keeps one and a fresh instance needs no rows at all
    -- see :mod:`altero.services.instancesettings`.
    """

    __tablename__ = "instance_settings"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: The value, encoded as JSON, so a setting that is not a number later on
    #: does not want a second column.
    value: Mapped[str] = mapped_column(Text, default="null")
    updated: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
