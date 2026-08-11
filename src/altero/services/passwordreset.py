"""Setting a password from a link, when an administrator issues one.

The alternative to an administrator typing a password and telling somebody what
it is: the password is then known to two people, and the second of them chose
it. A link is single use, expires, and is set by its owner.

**Only an administrator issues one.** There is no "I forgot my password" form,
and adding one is not a small decision: it turns an email address into a way in
to an account, which means the relay is now part of the authentication and the
form needs a rate limit and a story about what it says to an address that has
no account here. That is a separate piece of work, and until it exists this
server's answer to a forgotten password is the person who runs it.

The token lives in the link and nowhere else; only its SHA-256 is stored, so a
dump of the database sets nobody's password. Following it does what
:func:`altero.services.webauth.set_password` does: the other sessions go, and
the owner is told if there is a confirmed address to tell.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import PasswordReset, User

#: How long a link stays usable. Shorter than a confirmation link: this one
#: replaces a credential rather than proving an address.
LIFETIME_HOURS = 12

#: Bytes of entropy in a token.
TOKEN_BYTES = 32


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue(session: AsyncSession, user: User, *, issued_by: User | None = None) -> str:
    """Start a reset for ``user`` and return the token for the link.

    Any earlier outstanding link for the same account is dropped, so issuing a
    second one stops the first from working -- an administrator who reissues
    because the first went to the wrong place should not leave it usable.
    """
    await session.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    # Expired rows elsewhere go with it, which keeps the table bounded even on
    # an instance whose retention sweep never runs.
    await session.execute(delete(PasswordReset).where(PasswordReset.expires < _now()))

    token = secrets.token_urlsafe(TOKEN_BYTES)
    session.add(
        PasswordReset(
            token_hash=hash_token(token),
            user_id=user.id,
            issued_by=issued_by.id if issued_by is not None else None,
            expires=_now() + timedelta(hours=LIFETIME_HOURS),
        )
    )
    await session.commit()
    return token


async def resolve(session: AsyncSession, token: str) -> User:
    """Return the account ``token`` is for, or refuse.

    Separate from :func:`consume` so the page behind the link can say whose
    password it is about to set before asking for one, and can say "this link
    has expired" rather than taking a password and then refusing it.
    """
    if not token:
        raise ForbiddenError("That link is not valid")

    pending = await session.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == hash_token(token))
    )
    if pending is None or pending.expires < _now():
        raise ForbiddenError("That link is not valid or has expired")

    user = await session.get(User, pending.user_id)
    if user is None:  # pragma: no cover - defensive
        raise ForbiddenError("That link is not valid")
    if user.disabled_at is not None:
        # A suspended account must not be able to come back in through a link
        # issued before it was suspended.
        raise ForbiddenError("That account has been suspended")
    return user


async def consume(session: AsyncSession, token: str) -> User:
    """Spend ``token`` and return its account, for the caller to set a password.

    Single use: the row goes here, so a link followed twice fails the second
    time rather than quietly setting a second password.
    """
    user = await resolve(session, token)
    await session.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    await session.commit()
    return user
