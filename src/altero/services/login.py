"""Login sessions for the desktop client.

The client starts a session, opens the returned URL for the user to
authenticate, and polls until the session reports a key. Upstream authenticates
in a browser against zotero.org; altero has no web interface and no passwords,
so a session is approved from the command line against a key that was already
provisioned there.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models import ApiKey, LoginSession, User

#: How long a client may take to complete a login before the session expires.
SESSION_LIFETIME_MINUTES = 30

#: Length of a session token.
TOKEN_LENGTH = 32

PENDING = "pending"
COMPLETED = "completed"
CANCELLED = "cancelled"


class SessionExpiredError(NotFoundError):
    """The session existed but is too old to complete.

    Distinct from a missing session because the client tells the user something
    different for each.
    """


def _cutoff() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=SESSION_LIFETIME_MINUTES)


async def start_session(session: AsyncSession, user_id: int | None = None) -> LoginSession:
    """Create a pending login session."""
    # Sessions are short-lived, so clearing the stale ones here keeps the table
    # bounded without a scheduled job.
    await session.execute(delete(LoginSession).where(LoginSession.created < _cutoff()))

    login = LoginSession(
        token=secrets.token_urlsafe(TOKEN_LENGTH)[:TOKEN_LENGTH],
        status=PENDING,
        requested_user_id=user_id,
    )
    session.add(login)
    await session.commit()
    return login


async def get_session(session: AsyncSession, token: str) -> LoginSession:
    """Return a session by token, reporting a stale one as expired."""
    login = await session.get(LoginSession, token)
    if login is None:
        raise NotFoundError("Login session not found")
    if login.status == PENDING and login.created < _cutoff():
        raise SessionExpiredError("Login session expired")
    return login


async def approve_session(session: AsyncSession, token: str, api_key: ApiKey) -> LoginSession:
    """Complete a session, handing the client ``api_key``."""
    login = await get_session(session, token)
    if login.status != PENDING:
        raise InvalidInputError(f"Login session is already {login.status}")

    if login.requested_user_id is not None and login.requested_user_id != api_key.user_id:
        # The client said which account it expects; handing it a different
        # user's key would silently attach the library to the wrong account.
        raise InvalidInputError(
            f"Session expects user {login.requested_user_id}, "
            f"but the key belongs to user {api_key.user_id}"
        )

    login.status = COMPLETED
    login.api_key_id = api_key.id
    await session.commit()
    return login


async def cancel_session(session: AsyncSession, token: str) -> None:
    """Mark a session cancelled, so the client stops waiting."""
    login = await session.get(LoginSession, token)
    if login is None:
        return
    login.status = CANCELLED
    await session.commit()


async def list_pending(session: AsyncSession) -> list[LoginSession]:
    """Return the sessions still waiting to be approved."""
    result = await session.scalars(
        select(LoginSession)
        .where(LoginSession.status == PENDING, LoginSession.created >= _cutoff())
        .order_by(LoginSession.created)
    )
    return list(result)


async def render(session: AsyncSession, login: LoginSession) -> dict[str, object]:
    """Return the poll response for a session.

    A completed session carries the key and the account it belongs to; the
    client refuses the response without all three.
    """
    if login.status != COMPLETED:
        return {"status": login.status}

    api_key = await session.get(ApiKey, login.api_key_id) if login.api_key_id else None
    if api_key is None:  # pragma: no cover - the key was revoked mid-login
        return {"status": CANCELLED}

    user = await session.get(User, api_key.user_id)
    return {
        "status": COMPLETED,
        "apiKey": api_key.key,
        "userID": api_key.user_id,
        "username": user.username if user else "",
    }
