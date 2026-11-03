"""The last browser merge's inverse, private to its author and library."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class MergeUndo(Base):
    __tablename__ = "merge_undos"

    library_id: Mapped[int] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column()
    patches: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
