"""Pending file uploads."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class StorageUpload(Base):
    """An upload that has been authorized but not yet registered.

    The file protocol is three requests: the client asks permission, sends the
    bytes, then tells the server the bytes arrived. This row carries what it
    declared in the first step through to the third, so the server can check
    that what turned up is what was promised.
    """

    __tablename__ = "storage_uploads"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"))

    md5: Mapped[str] = mapped_column(String(32))
    #: Digest of the archive, when the client zipped the file before sending.
    #: `md5` still describes the original file.
    zip_md5: Mapped[str | None] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(255))
    filesize: Mapped[int] = mapped_column()
    mtime: Mapped[int] = mapped_column()
    content_type: Mapped[str] = mapped_column(String(255), default="")
    charset: Mapped[str] = mapped_column(String(64), default="")

    #: Whether the bytes have arrived and matched what was declared.
    received: Mapped[bool] = mapped_column(default=False)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
