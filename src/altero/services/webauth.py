"""Registration, sign-in and second factors for the web interface.

Kept apart from :mod:`altero.services.auth`, which answers what an API key may
do. This module answers who a person is. The two meet only in the routes, and
the v3 API's key-based path is untouched by anything here -- a sync client's
credential must go on working exactly as it did, since that compatibility is
the reason this project exists.

Registration is closed by default and opens for three cases: the deployment
said so (``ALTERO_OPEN_REGISTRATION``), the instance has no users at all, or
the address being registered has an invitation waiting. The second is what
makes a fresh container reachable by its owner without shell access; the third
is what makes inviting somebody who is not here yet work at all.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import TotpCredential, User, WebSession
from altero.services import admin, emailverify, invitations, passwords, totp, websessions
from altero.services.mail import Message

logger = logging.getLogger("altero.webauth")

#: Something that attempts to deliver a message. Injected rather than built
#: here so that this module stays free of configuration and of I/O in tests.
Notifier = Callable[[Message], Awaitable[bool]]

#: What a failed sign-in says, whatever the reason. A message that told a wrong
#: password from an unknown account would turn the form into a list of who has
#: one.
BAD_CREDENTIALS = "That username and password do not match"


@dataclass(frozen=True, slots=True)
class LoginResult:
    """The outcome of a successful first factor."""

    token: str
    session: WebSession
    #: The factor still to come, or ``None`` when the session is complete.
    needs_factor: str | None


def validate_username(username: str) -> str:
    """Return ``username`` trimmed, or raise if it cannot be one.

    The bar on "@" is what keeps sign-in unambiguous. A single field accepts
    either a username or an address, and the shape of what was typed picks the
    column; a username containing "@" could therefore name somebody else's
    address, and one of the two accounts would stop being reachable by the
    identifier its owner expects.
    """
    candidate = username.strip()
    if not candidate:
        raise InvalidInputError("A username is required")
    if "@" in candidate:
        raise InvalidInputError(
            "A username may not contain '@', because sign-in accepts either a "
            "username or an email address"
        )
    return candidate


async def no_accounts_yet(session: AsyncSession) -> bool:
    """Return whether this instance has no users at all."""
    return (await session.scalar(select(func.count()).select_from(User))) == 0


async def registration_open(
    session: AsyncSession, *, allow: bool = False, email: str | None = None
) -> bool:
    """Return whether an account may be registered right now.

    Three ways in, in the order they are checked:

    - ``allow``, the deployment's own setting.
    - The very first account, always, because otherwise a fresh instance can
      only be set up from a shell.
    - An unanswered invitation to ``email``. Inviting an address that has no
      account here is the documented way to bring somebody into a group, and
      without this the link they receive lands on a registration form that
      refuses them -- which made the whole path unreachable on any instance
      that had not opened registration outright.
    """
    if allow:
        return True
    if await no_accounts_yet(session):
        return True
    if email:
        return await invitations.pending_for_email(session, email)
    return False


async def register(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    email: str,
    display_name: str = "",
    allow_registration: bool = False,
) -> User:
    """Create an account and its personal library, with a password and address.

    The address is required and starts unverified. Confirming it is a separate
    step, and one that gates only whether security mail is sent -- see
    :mod:`altero.services.emailverify`.
    """
    username = validate_username(username)

    # Everything is validated before the user is created, so a refused
    # password or a mistyped address does not leave a half-made account behind.
    address = emailverify.normalise(email)
    passwords.validate_password(password)

    # Checked with the address in hand, because an invitation to it is one of
    # the three things that opens the door.
    if not await registration_open(session, allow=allow_registration, email=address):
        raise ForbiddenError("Registration is closed on this server")

    taken = await session.scalar(select(User).where(func.lower(User.email) == address))
    if taken is not None:
        raise InvalidInputError("That email address is already registered")

    user = await admin.create_user(
        session, username=username, display_name=display_name or username
    )
    user.email = address
    await session.commit()
    await set_password(session, user, password)
    return user


async def set_password(
    session: AsyncSession,
    user: User,
    password: str,
    *,
    keep: WebSession | None = None,
    notify: Notifier | None = None,
) -> None:
    """Set ``user``'s password and end their other sessions.

    A password is replaced because it might be known to someone else. Leaving
    the sessions it opened alive would make the change cosmetic, so they go --
    all but ``keep``, which is the browser doing the changing.

    The owner is told, if there is a confirmed address to tell. That notice is
    the thing that turns a silent takeover into a noticed one, which is why it
    is sent here rather than left to the caller to remember.
    """
    passwords.validate_password(password)
    user.password_hash = passwords.hash_password(password)
    user.password_changed = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await websessions.revoke_all(session, user, keep=keep)

    await notify_security(
        user,
        notify,
        subject="Your altero password was changed",
        body=(
            f"The password on the altero account '{user.username}' was just changed, "
            "and every other signed-in browser was signed out.\n\n"
            "If this was you, there is nothing to do.\n\n"
            "If it was not, whoever changed it can now sign in as you. Ask "
            "whoever runs this server to reset the password from the command "
            "line with `altero user password`."
        ),
    )


async def notify_security(
    user: User,
    notify: Notifier | None,
    *,
    subject: str,
    body: str,
) -> bool:
    """Tell ``user`` about a change to their account, if that is possible.

    Silent for an account with no address, and for one whose address has not
    been confirmed: nobody has proved they hold it, so a notice sent there may
    be going to whoever typed it rather than to the owner.

    Never raises. What this reports has already happened, and a relay that is
    down is not a reason to fail the request that changed it -- that would
    discard the change and keep the problem.
    """
    if notify is None or not emailverify.is_verified(user):
        return False

    assert user.email is not None
    try:
        return await notify(Message(to=user.email, subject=subject, body=body))
    except Exception:
        logger.exception("Could not send a security notification to %s", user.email)
        return False


async def login(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    user_agent: str = "",
) -> LoginResult:
    """Check a username and password and open a session.

    The session that comes back may still be pending a second factor; see
    :attr:`LoginResult.needs_factor`. It exists either way, so that the factor
    can be presented against something rather than against a re-sent password.
    """
    # One field, two columns, and the shape of what was typed decides which.
    # Searching both at once would make a username equal to somebody else's
    # address match two rows, with an arbitrary winner; usernames may not
    # contain "@" (see validate_username), so this is unambiguous.
    identifier = username.strip().lower()
    column = User.email if "@" in identifier else User.username
    user = await session.scalar(select(User).where(func.lower(column) == identifier))

    # Verified even when there is no such user, against a dummy hash, so that
    # an unknown name does not answer faster than a known one.
    if not passwords.verify_password(user.password_hash if user else None, password):
        raise ForbiddenError(BAD_CREDENTIALS)
    assert user is not None  # implied by the check above; narrows the type

    # The plain password is in hand exactly here, so this is the only moment a
    # hash made at older parameters can be brought up to the current ones.
    if user.password_hash and passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
        await session.commit()

    pending = await _outstanding_factor(session, user)
    token, record = await websessions.create(
        session, user, pending_factor=pending, user_agent=user_agent
    )
    return LoginResult(token=token, session=record, needs_factor=pending)


async def _outstanding_factor(session: AsyncSession, user: User) -> str | None:
    """Return the second factor ``user`` must still present, if any.

    Only a *confirmed* enrolment counts. A secret stored while somebody was
    part-way through setting up an authenticator must not start being demanded,
    or an interrupted setup is an account nobody can sign in to.
    """
    enrolled = await session.get(TotpCredential, user.id)
    return "totp" if enrolled is not None and enrolled.confirmed else None


async def enrol_totp(
    session: AsyncSession,
    user: User,
    *,
    confirm_with: str | None,
) -> str:
    """Enrol an authenticator app and return the secret to display.

    ``confirm_with`` is a code produced from the secret being enrolled. Passing
    one is how a caller proves the app is working before the factor starts
    being required; enrolling without that check is how someone locks
    themselves out of their own library. ``None`` skips the proof and is meant
    for tests and for the command line.
    """
    secret = totp.generate_secret()

    if confirm_with is not None and totp.verify(secret, confirm_with) is None:
        raise ForbiddenError("That code does not match the secret being enrolled")

    existing = await session.get(TotpCredential, user.id)
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    # Confirmed outright: this path is the command line and the tests, where
    # there is no second step to come. The interface uses
    # altero.services.account, which stores it unconfirmed first.
    session.add(TotpCredential(user_id=user.id, secret=secret, confirmed=True))
    await session.commit()
    return secret


async def complete_totp(session: AsyncSession, record: WebSession, code: str) -> None:
    """Clear the outstanding TOTP factor on ``record``.

    Refuses a code at or below the last accepted step. A code is valid for its
    whole step and the window either side, so without that check whoever else
    saw it -- over a shoulder, in a log -- gets a second login out of it.
    """
    if record.pending_factor != "totp":
        raise ForbiddenError("This session is not waiting for a code")

    enrolled = await session.get(TotpCredential, record.user_id)
    if enrolled is None:  # pragma: no cover - defensive
        raise ForbiddenError("No authenticator is enrolled")

    step = totp.verify(enrolled.secret, code)
    if step is None or step <= enrolled.last_step:
        raise ForbiddenError("That code is not valid")

    enrolled.last_step = step
    record.pending_factor = None
    await session.commit()
