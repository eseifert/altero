"""Proving again, just now, that the browser holds a credential of the account.

Every operation that hands out or replaces a credential asks for proof that
whoever is driving the browser is the account holder rather than somebody who
borrowed an unlocked laptop. That reasoning is unchanged and is written out in
:mod:`altero.services.account`; what changes here is what counts as proof.

Until now it was the current password and nothing else, which was right while a
password was the only credential an account could have. It no longer is.
``User.password_hash`` has always been nullable -- an account created by
``altero user add`` has no password until one is set -- and single sign-on and
passkeys make passwordless accounts ordinary rather than an edge case. Asking
those accounts for a password they do not have would leave them unable to
change their own address, make an API key, link a desktop client or restore a
library: every credential-touching operation on the instance, locked, for
exactly the accounts the identity provider created.

So the question becomes "has this browser proved itself recently", and a
password is one way of answering it rather than the only one. The proof is
stamped on the session and stands for :data:`FRESHNESS`, which is short enough
that a borrowed laptop is still a borrowed laptop and long enough that a
settings page does not ask twice in one sitting.

The stamp is on the session and not on the user on purpose. Two browsers signed
in to one account are two claims to be that person, and one of them proving
itself says nothing about the other.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import User, WebSession
from altero.services import passwords

#: How long a proof stands before it has to be given again. Five minutes is
#: enough to change a password and then make a key without being asked twice,
#: and short enough that walking away from an unlocked screen does not leave
#: the account open to being taken over.
FRESHNESS = timedelta(minutes=5)

#: What a wrong password says. Unchanged from what it said when this was
#: ``account.require_password``, because it is a true and unhelpful-to-an-
#: attacker sentence and people have seen it.
WRONG_PASSWORD = "That password is not correct"


class ReauthenticationRequired(ForbiddenError):
    """The browser has to prove itself before this operation is allowed.

    Its own class because the interface answers it differently from an ordinary
    refusal: this one is a prompt rather than a dead end, and the client turns
    it into "confirm it is you" instead of "you may not do that".
    """


def _now() -> datetime:
    """Return the current time as the naive UTC the columns store."""
    return datetime.now(UTC).replace(tzinfo=None)


def has_password(user: User) -> bool:
    """Return whether this account has a password to be asked for at all."""
    return bool(user.password_hash)


def is_fresh(record: WebSession | None, *, now: datetime | None = None) -> bool:
    """Return whether ``record`` proved itself recently enough."""
    if record is None or record.reauthenticated is None:
        return False
    return (now or _now()) - record.reauthenticated < FRESHNESS


async def stamp(session: AsyncSession, record: WebSession | None) -> None:
    """Record that this browser has just proved itself.

    Called by every path that establishes a proof -- a password checked here, a
    passkey assertion, a code from an authenticator, a fresh trip through an
    identity provider -- so that there is one answer to when the proof was
    given and one place it is written.
    """
    if record is None:
        return
    record.reauthenticated = _now()
    await session.commit()


async def require(
    session: AsyncSession,
    user: User,
    record: WebSession | None,
    *,
    password: str | None = None,
) -> None:
    """Raise unless this browser has proved itself, or proves itself now.

    A password offered here is checked and, when it matches, stands as the
    proof -- so an account with a password sees exactly the behaviour it always
    saw, including the message a wrong one produces. Offering none falls back
    to a proof given in the last :data:`FRESHNESS`, which is how an account
    with no password gets through at all.

    ``record`` is optional so that the command line, which has no browser
    session and has already established who it is by having a shell on the
    server, can call the same function.
    """
    if password:
        if not passwords.verify_password(user.password_hash, password):
            raise ForbiddenError(WRONG_PASSWORD)
        await stamp(session, record)
        return

    if is_fresh(record):
        return

    if has_password(user):
        # Asking for the password is the thing the interface already knows how
        # to do, so say which of the two is missing rather than a sentence that
        # fits both.
        raise ReauthenticationRequired("This needs your password")
    raise ReauthenticationRequired("This needs you to confirm it is you before it can go ahead")
