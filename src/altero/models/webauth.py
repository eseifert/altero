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
    #: False until the user has produced a code from this secret. An
    #: unconfirmed credential is not required at sign-in, so enrolling a
    #: factor and then losing the phone before proving it does not lock the
    #: account.
    confirmed: Mapped[bool] = mapped_column(default=False)
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


class Notification(Base):
    """Something the interface should show a person when they next look.

    Kept as rendered text rather than as a payload to interpret later: a
    notification is a record of what was true when it was raised, and a group
    renamed or a user deleted afterwards must not change what it says or turn
    it into a blank row.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: What raised it -- "invitation", "security". Decides the icon and
    #: whether the interface offers an action.
    kind: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(String, default="")
    #: The invitation this is about, when there is one. Nulled rather than
    #: cascaded when that invitation goes, so the notice survives as history.
    invitation_id: Mapped[int | None] = mapped_column(
        ForeignKey("invitations.id", ondelete="SET NULL"), default=None
    )
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    read: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class Invitation(Base):
    """An offer of membership in a group library.

    Addressed to an email address rather than to a user, because the point is
    frequently to invite somebody who has no account here yet. ``user_id`` is
    filled in when the address matches one, which is what lets the invitation
    appear in that person's notifications instead of only in their inbox.
    """

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    #: The account holding that address, if there is one.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")
    invited_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    #: SHA-256 of the token in the emailed link, for accepting without an
    #: account to sign in to first.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: pending, accepted, declined or revoked. Kept after the fact rather than
    #: deleted, so that re-inviting somebody who declined is a visible act.
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
    answered: Mapped[datetime | None] = mapped_column(DateTime, default=None)
