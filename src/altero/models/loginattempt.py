"""Durable budgets for password and second-factor guesses."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    #: SHA-256 of a namespaced account or address, never the credential.
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column()
    available: Mapped[datetime] = mapped_column(DateTime)
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
    #: Lets a completed proof clear its own reservation, not a newer guess.
    generation: Mapped[str] = mapped_column(String(32))
