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
    #: When this browser last proved it holds a credential of the account's --
    #: see :mod:`altero.services.reauth`. Distinct from ``created`` because a
    #: session lives for thirty days and the proof is good for minutes: signing
    #: in is not standing consent to replace the credentials afterwards.
    reauthenticated: Mapped[datetime | None] = mapped_column(DateTime, default=None)
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


class EmailFactor(Base):
    """An account that takes its second factor as a code by email.

    A row and nothing more: what would be stored on it -- the address, and
    whether anybody has proved they hold it -- is already on the user, and
    copying it here would let the two disagree. Enrolling therefore has no
    second step, unlike :class:`TotpCredential`: there is no new secret to
    prove works, only an address that was proved before this was enrolled.

    Kept as its own table rather than a flag on the user, so that a credential
    lives with the other credentials and ``models/library.py`` stays about
    libraries.
    """

    __tablename__ = "email_factors"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LoginCode(Base):
    """A code sent by mail, standing between a password and a session.

    Bound to the session rather than to the user, and cascaded with it: a code
    is an answer to one particular sign-in, and one that could be typed into a
    different browser's pending sign-in would let whoever intercepted the mail
    use it from their own machine rather than only from the one that asked.

    Only the SHA-256 is stored, as everywhere else here. Six digits is not much
    to grind, which is what :attr:`attempts` is for -- the row is spent after a
    few wrong guesses rather than standing until it expires.
    """

    __tablename__ = "login_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("web_sessions.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    #: Wrong guesses so far. The row goes when this reaches the limit.
    attempts: Mapped[int] = mapped_column(default=0)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)


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


class PasswordReset(Base):
    """An outstanding invitation to set a password.

    Issued by an instance administrator and by nobody else. There is
    deliberately no "I forgot my password" form: a self-service one is a
    decision about how much a mail relay is trusted and how hard the form is to
    hammer, and this server's answer is that whoever runs it does the resetting
    — see :mod:`altero.services.passwordreset`.

    Shaped like :class:`EmailVerification`, and separate from it on purpose:
    one proves an address, this one replaces a credential, and a row that could
    do either would be the wrong thing to hand out for the weaker of the two.
    """

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: SHA-256 of the token in the link. The token is never stored, so a copy
    #: of the database sets nobody's password.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: Who issued it. Kept because this is somebody changing somebody else's
    #: credential, which is a thing worth being able to account for.
    issued_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
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
    #: How far the membership being offered goes, one of
    #: :class:`~altero.models.MemberPermission`. Carried on the offer rather
    #: than applied afterwards, because "come and read this" and "come and help
    #: with this" are different invitations and the person accepting should be
    #: told which one they were sent.
    permission: Mapped[str] = mapped_column(String(16), default="inherit", server_default="inherit")
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
