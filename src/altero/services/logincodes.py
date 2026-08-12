"""A second factor that arrives by mail.

The alternative to an authenticator app for somebody who has none, and the
recovery path for somebody who had one and lost the phone. Before this, an
account with TOTP enrolled and no access to it had exactly one way back in:
find whoever runs the server. That is a fine answer on an instance of six
people and a poor one on an instance of six hundred.

It is a genuinely weaker factor than TOTP and is not pretended otherwise --
what it proves is control of a mailbox, which for many people is itself behind
a password. It is still a second factor: a stolen altero password alone stops
being enough, which is the whole claim.

Three things keep six digits from being guessable. The code is bound to the
session that asked for it, so it cannot be typed into another browser's pending
sign-in by whoever read the mail; it expires in minutes rather than hours; and
the row is spent after :data:`MAX_ATTEMPTS` wrong guesses, so the search space
is not there to be walked. Only the SHA-256 is stored, as with every other
token here.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import EmailFactor, LoginCode, User, WebSession

#: Digits in a code. Six, like TOTP, because it is the length people expect to
#: be asked for and the length a phone offers to autofill.
DIGITS = 6

#: How long a code stays usable. Minutes, not hours: it is in an inbox, and the
#: person it was sent to is waiting on the screen that asked for it.
LIFETIME_MINUTES = 10

#: Wrong guesses before the code is thrown away. Five leaves a one in two
#: hundred thousand chance of walking into a live code, and is more attempts
#: than anybody typing from an inbox needs.
MAX_ATTEMPTS = 5

#: What a wrong or missing code says. One sentence for both, so that the form
#: does not report whether a code is outstanding at all.
BAD_CODE = "That code is not valid"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def generate_code() -> str:
    """Return a fresh code, zero-padded so every one is the same length.

    ``randbelow`` rather than ``randint``: this is a credential, and the
    ordinary random module is seeded predictably enough to matter.
    """
    return f"{secrets.randbelow(10**DIGITS):0{DIGITS}d}"


async def is_enrolled(session: AsyncSession, user: User) -> bool:
    """Return whether this account takes a code by mail."""
    return await session.get(EmailFactor, user.id) is not None


async def enrol(session: AsyncSession, user: User) -> None:
    """Turn the factor on for ``user``.

    No second step, unlike enrolling an authenticator: there is no new secret
    whose working has to be proved, only an address that was already confirmed
    -- and the caller is what checks that, since "may this account be mailed"
    is a question :mod:`altero.services.emailverify` already answers.
    """
    if await session.get(EmailFactor, user.id) is None:
        session.add(EmailFactor(user_id=user.id))
        await session.commit()


async def disable(session: AsyncSession, user: User) -> None:
    """Turn the factor off, and drop any code standing on it."""
    enrolled = await session.get(EmailFactor, user.id)
    if enrolled is not None:
        await session.delete(enrolled)
        await session.commit()


async def issue(session: AsyncSession, record: WebSession) -> str:
    """Make a code for this pending sign-in and return it, to be mailed.

    Any earlier code for the same session goes, so asking for a second one
    stops the first working. That matters when the first went astray: two live
    codes would double what an interceptor has to work with, for no benefit to
    the person waiting.
    """
    await session.execute(delete(LoginCode).where(LoginCode.session_id == record.id))
    # Expired rows anywhere go with it, so the table stays bounded on an
    # instance whose retention sweep never runs -- as elsewhere here.
    await session.execute(delete(LoginCode).where(LoginCode.expires < _now()))

    code = generate_code()
    session.add(
        LoginCode(
            session_id=record.id,
            code_hash=hash_code(code),
            expires=_now() + timedelta(minutes=LIFETIME_MINUTES),
        )
    )
    await session.commit()
    return code


async def verify(session: AsyncSession, record: WebSession, code: str) -> None:
    """Spend the code standing on this session, or refuse.

    Refusing costs an attempt, and the row goes when the attempts run out --
    which is what stops six digits from being enumerable. A correct code takes
    the row with it too, so it works once.
    """
    pending = await session.scalar(select(LoginCode).where(LoginCode.session_id == record.id))
    if pending is None or pending.expires < _now():
        raise ForbiddenError(BAD_CODE)

    if not secrets.compare_digest(pending.code_hash, hash_code(code.strip())):
        pending.attempts += 1
        if pending.attempts >= MAX_ATTEMPTS:
            await session.delete(pending)
        await session.commit()
        raise ForbiddenError(BAD_CODE)

    await session.delete(pending)
    await session.commit()
