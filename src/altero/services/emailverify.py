"""Confirming that somebody holds the address they gave.

What verification is *for* here is narrow, and worth stating because it decides
everything else: it gates security mail. An unverified account signs in, syncs
and reads its library exactly as a verified one does. What it does not get is a
message saying "your password was changed", because sending that to an address
nobody has proved they control delivers it to whoever typed it -- which, if the
address was typed by an attacker, is precisely the wrong person.

The token follows the same rule as a session token: it lives in the link and
nowhere else, and only its SHA-256 is stored. A dump of the database therefore
confirms nobody's address.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import EmailVerification, User

#: How long a confirmation link stays usable.
LIFETIME_HOURS = 24

#: Bytes of entropy in a token.
TOKEN_BYTES = 32

#: Deliberately permissive: one @, something either side, a dot in the domain,
#: no whitespace. Anything stricter rejects addresses that exist -- the real
#: grammar allows quoted local parts and the full RFC pattern is famously
#: unusable -- and the confirmation link is what actually proves the address.
_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Longest address accepted, from the SMTP path limit in RFC 5321.
MAX_LENGTH = 320


def normalise(email: str) -> str:
    """Return ``email`` folded and trimmed, or raise if it is not an address.

    Folded to lower case so that one address cannot be registered twice in
    different case and so a sign-in matches whatever the user typed. The domain
    is genuinely case-insensitive; the local part is not, in theory, but no
    mail system in practice treats it otherwise, and the alternative is two
    accounts nobody can tell apart.
    """
    candidate = email.strip().lower()
    if not candidate:
        raise InvalidInputError("An email address is required")
    if len(candidate) > MAX_LENGTH:
        raise InvalidInputError("That email address is too long")
    if not _ADDRESS.match(candidate):
        raise InvalidInputError("That does not look like an email address")
    return candidate


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue(session: AsyncSession, user: User, email: str) -> str:
    """Start a confirmation for ``email`` and return the token for the link.

    Any outstanding confirmation for this user is dropped first, so that
    "resend" does not leave the earlier link working -- a link mailed to an
    address that turned out to be wrong should stop being useful the moment a
    correction is requested.
    """
    address = normalise(email)

    await session.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
    # Expired rows elsewhere in the table go at the same time, which keeps it
    # bounded without a scheduled job.
    await session.execute(delete(EmailVerification).where(EmailVerification.expires < _now()))

    token = secrets.token_urlsafe(TOKEN_BYTES)
    session.add(
        EmailVerification(
            token_hash=hash_token(token),
            user_id=user.id,
            email=address,
            expires=_now() + timedelta(hours=LIFETIME_HOURS),
        )
    )
    await session.commit()
    return token


async def outstanding_for(session: AsyncSession, user: User) -> EmailVerification | None:
    """Return this user's pending confirmation, if there is one."""
    return await session.scalar(
        select(EmailVerification).where(EmailVerification.user_id == user.id)
    )


async def confirm(session: AsyncSession, token: str) -> User:
    """Apply the confirmation ``token`` identifies and return its user.

    The address recorded on the token is what gets adopted, not whatever the
    user's row currently says. That is what makes changing an address safe: the
    new one takes effect only once this link has been followed, so a typo never
    becomes the account's contact address and the notice about the change is
    still sent to the old one.
    """
    if not token:
        raise ForbiddenError("That confirmation link is not valid")

    pending = await session.scalar(
        select(EmailVerification).where(EmailVerification.token_hash == hash_token(token))
    )
    if pending is None or pending.expires < _now():
        raise ForbiddenError("That confirmation link is not valid or has expired")

    user = await session.get(User, pending.user_id)
    if user is None:  # pragma: no cover - defensive
        raise ForbiddenError("That confirmation link is not valid")

    user.email = pending.email
    user.email_verified = _now()
    # Single use: the row goes, so following the link twice fails the second
    # time rather than silently re-confirming.
    await session.delete(pending)
    await session.commit()
    return user


def is_verified(user: User) -> bool:
    """Return whether this account has an address worth writing to."""
    return user.email is not None and user.email_verified is not None
