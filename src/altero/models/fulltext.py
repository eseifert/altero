"""Full-text content extracted from attachments."""

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class FullText(Base):
    """The searchable text of one attachment.

    The client extracts this from a PDF or web page and uploads it so that
    searching works on every device, not only the one holding the file.
    """

    __tablename__ = "item_fulltext"
    __table_args__ = (Index("ix_item_fulltext_library_version", "library_id", "version"),)

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(default=1, index=True)

    #: How much of the document was indexed. Which pair applies depends on the
    #: document: pages for paginated formats, characters otherwise.
    indexed_chars: Mapped[int | None] = mapped_column()
    total_chars: Mapped[int | None] = mapped_column()
    indexed_pages: Mapped[int | None] = mapped_column()
    total_pages: Mapped[int | None] = mapped_column()
