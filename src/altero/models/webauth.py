"""Credentials and sessions belonging to the web interface.

Deliberately separate from :class:`~altero.models.apikey.ApiKey`. An API key is
a long-lived bearer credential a sync client stores on disk; a web session is
short-lived, tied to a browser, and can be standing halfway through a login
while a second factor is outstanding. Sharing one table would mean one of those
two sets of rules bending to the other.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class WebSession(Base):
    """A browser session, authenticated or awaiting a second factor."""

    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: SHA-256 of the token handed to the browser. The token itself is never
    #: stored, so read access to this table does not yield working sessions.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: The factor still outstanding, or ``None`` once the session is complete.
    #: A session with this set has proved a password and nothing more.
    pending_factor: Mapped[str | None] = mapped_column(String(16), default=None)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
    #: Shown in the account's session list so an unfamiliar one is recognisable.
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class TotpCredential(Base):
    """An enrolled authenticator app."""

    __tablename__ = "totp_credentials"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    secret: Mapped[str] = mapped_column(String(64))
    #: The last step a code was accepted for. Nothing at or below it is
    #: accepted again, which is what stops a code being replayed inside the
    #: window it remains valid for.
    last_step: Mapped[int] = mapped_column(default=0)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EmailVerification(Base):
    """An outstanding request to confirm an address.

    Carries the address it was issued for rather than reading the user's
    current one, so that a change of address is only adopted once the new one
    has been proved. Otherwise a typo becomes the account's contact address the
    moment it is typed, and the notice about the change goes to it.
    """

    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: SHA-256 of the token in the link. The token itself is never stored, so
    #: a copy of the database confirms nobody's address.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
