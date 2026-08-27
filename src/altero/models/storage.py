"""Pending file uploads, and permission to fetch one file back."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
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
    #: Both are BigInteger rather than the default integer.
    #:
    #: `mtime` is what the client sends: milliseconds since the epoch, which
    #: has not fitted in 32 bits since January 1970. PostgreSQL's INTEGER is
    #: 32-bit and refuses it outright, so every file upload against a
    #: PostgreSQL deployment failed until this was widened. SQLite's INTEGER is
    #: 64-bit, which is why the tests never saw it.
    #:
    #: `filesize` is in range today only because api/routes/files.py caps an
    #: upload at a gibibyte. That constant is not this module's to rely on.
    filesize: Mapped[int] = mapped_column(BigInteger)
    mtime: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(255), default="")
    charset: Mapped[str] = mapped_column(String(64), default="")

    #: Whether the bytes have arrived and matched what was declared.
    received: Mapped[bool] = mapped_column(default=False)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class StorageDownload(Base):
    """Permission to fetch one attachment's bytes, and only those.

    Upstream's 302 lands on a presigned S3 URL, which is a credential in
    itself: it names one file and stops working shortly afterwards. altero has
    no S3, so the redirect points back here, and this row is what stands in for
    that signature -- the same shape as :class:`StorageUpload`, in the other
    direction.

    It exists so that the API key does not have to travel in the URL. A key
    grants the whole account and never expires; a reverse proxy writes every
    request line to its access log, and altero ships configurations for three
    of them.

    Bound to the digest as well as to the item, so a permission granted for one
    file cannot be spent on whatever the attachment holds later.
    """

    __tablename__ = "storage_downloads"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"))

    #: The digest the redirect promised, in the header the client reads.
    md5: Mapped[str] = mapped_column(String(32))
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
