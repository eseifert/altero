"""Registration, sign-in and second factors for the web interface.

Kept apart from :mod:`altero.services.auth`, which answers what an API key may
do. This module answers who a person is. The two meet only in the routes, and
the v3 API's key-based path is untouched by anything here -- a sync client's
credential must go on working exactly as it did, since that compatibility is
the reason this project exists.

Registration is closed by default and opens for exactly one case: an instance
with no users at all. A fresh container has to be reachable by its owner
without shell access, and the moment that first account exists the door shuts
again. Opening it deliberately is a setting.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import TotpCredential, User, WebSession
from altero.services import admin, passwords, totp, websessions

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


async def registration_open(session: AsyncSession, *, allow: bool = False) -> bool:
    """Return whether an account may be registered right now.

    ``allow`` is the deployment's own setting. Regardless of it, the very first
    account is always permitted, because otherwise a fresh instance can only be
    set up from a shell.
    """
    if allow:
        return True
    return (await session.scalar(select(func.count()).select_from(User))) == 0


async def register(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str = "",
    allow_registration: bool = False,
) -> User:
    """Create an account and its personal library, with a password set."""
    if not await registration_open(session, allow=allow_registration):
        raise ForbiddenError("Registration is closed on this server")

    username = username.strip()
    if not username:
        raise InvalidInputError("A username is required")

    # Validated before the user is created, so a refused password does not
    # leave a passwordless account behind.
    passwords.validate_password(password)

    user = await admin.create_user(
        session, username=username, display_name=display_name or username
    )
    await set_password(session, user, password)
    return user


async def set_password(
    session: AsyncSession,
    user: User,
    password: str,
    *,
    keep: WebSession | None = None,
) -> None:
    """Set ``user``'s password and end their other sessions.

    A password is replaced because it might be known to someone else. Leaving
    the sessions it opened alive would make the change cosmetic, so they go --
    all but ``keep``, which is the browser doing the changing.
    """
    passwords.validate_password(password)
    user.password_hash = passwords.hash_password(password)
    user.password_changed = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await websessions.revoke_all(session, user, keep=keep)


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
    user = await session.scalar(
        select(User).where(func.lower(User.username) == username.strip().lower())
    )

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
    """Return the second factor ``user`` must still present, if any."""
    enrolled = await session.get(TotpCredential, user.id)
    return "totp" if enrolled is not None else None


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

    session.add(TotpCredential(user_id=user.id, secret=secret))
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
