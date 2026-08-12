"""Setting a password from a link.

The alternative to an administrator typing a password and telling somebody what
it is: the password is then known to two people, and the second of them chose
it. A link is single use, expires, and is set by its owner.

Two ways one is issued, and they are different decisions.

**An administrator issues one** for any account, whether or not it has an
address, and is shown the link either way -- most instances have no relay, and
a link readable only in the log would need the shell the screen replaces.

**The account asks for one itself**, through :func:`self_service`. That turns an
email address into a way in to an account, which is why it is off unless the
deployment says otherwise (``ALTERO_PASSWORD_RESET``) and why it insists on
three things the administrator's path does not need: a *confirmed* address, so
that a typo at registration is not a way in; an actual relay, since a
self-service link written to the container log is one anybody who can read logs
can use; and a rate limit, since the form is reachable by anyone. It answers
the same way whatever it finds, so it cannot be used to ask which addresses
have accounts here.

The token lives in the link and nowhere else; only its SHA-256 is stored, so a
dump of the database sets nobody's password. Following it does what
:func:`altero.services.webauth.set_password` does: the other sessions go, and
the owner is told if there is a confirmed address to tell.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import PasswordReset, User
from altero.services import emailverify

#: How long a link stays usable. Shorter than a confirmation link: this one
#: replaces a credential rather than proving an address.
LIFETIME_HOURS = 12

#: Bytes of entropy in a token.
TOKEN_BYTES = 32

#: How many self-service requests one address may produce per window, and how
#: long the window is. Not configurable: an operator has no way to know what
#: the right number is, and the failure of getting it wrong is either a form
#: that can be hammered or one that locks out the person it is for. Three an
#: hour is enough for somebody whose first mail went to spam.
REQUESTS_PER_WINDOW = 3
REQUEST_WINDOW_SECONDS = 3600


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


async def self_service(session: AsyncSession, email: str) -> tuple[User, str] | None:
    """Return the account and a token for a reset it asked for itself, or ``None``.

    ``None`` covers every reason not to send one -- the address is not an
    address, no account holds it, the account never confirmed it, the account
    is suspended -- because the caller answers identically in all of them and
    in the successful case too. Telling them apart is exactly what would turn
    this form into a way of asking which addresses have accounts here.

    A confirmed address is required and an unconfirmed one is not enough.
    Nobody has proved they hold an unconfirmed address, so honouring it would
    make a mistyped registration into somebody else's way in.

    Issuing here drops any link the account already had, including one an
    administrator issued -- see :func:`issue`. That is the price of one
    outstanding link per account, and the rate limit above is what keeps
    somebody from using it to invalidate an administrator's link repeatedly.
    """
    try:
        address = emailverify.normalise(email)
    except InvalidInputError:
        return None

    user = await session.scalar(select(User).where(func.lower(User.email) == address))
    if user is None or not emailverify.is_verified(user):
        return None
    if user.disabled_at is not None:
        # A suspended account must not be able to let itself back in, and the
        # answer is the same silence as for an address nobody here holds.
        return None

    return user, await issue(session, user)


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
