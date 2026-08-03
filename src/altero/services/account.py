"""Changes a person makes to their own account.

Everything that alters a credential asks for the current password first. That
is not ceremony: a session cookie is what an attacker who borrowed an unlocked
laptop or landed a cross-site request already has, and without re-authentication
each of these is a one-request account takeover. Nothing here is reachable with
an API key, which is a sync credential and not a person.

Enrolling a second factor is two steps on purpose. A secret is stored
unconfirmed and does not affect sign-in until a code proves the authenticator
actually works; turning the requirement on first is how somebody locks
themselves out of their own library with a mistyped setup.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import TotpCredential, User, WebSession
from altero.services import emailverify, passwords, totp, webauth, websessions
from altero.services.webauth import Notifier

#: Issuer shown in an authenticator app.
TOTP_ISSUER = "altero"


@dataclass(frozen=True, slots=True)
class TotpEnrolment:
    """What the interface needs to show a QR code and take a code back."""

    secret: str
    uri: str


def _require_password(user: User, password: str) -> None:
    """Raise unless ``password`` is this user's current one."""
    if not passwords.verify_password(user.password_hash, password):
        raise ForbiddenError("That password is not correct")


async def set_display_name(session: AsyncSession, user: User, display_name: str) -> User:
    """Change the name shown in the interface.

    No password: this is not a credential, and it is the one thing on the
    settings page that should not feel like a security operation.
    """
    name = display_name.strip()
    if len(name) > 255:
        raise InvalidInputError("That display name is too long")
    user.display_name = name
    await session.commit()
    return user


async def change_password(
    session: AsyncSession,
    user: User,
    *,
    current_password: str,
    new_password: str,
    keep: WebSession | None = None,
    notify: Notifier | None = None,
) -> None:
    """Replace the password, keeping only the session that did it."""
    _require_password(user, current_password)
    if new_password == current_password:
        raise InvalidInputError("The new password is the same as the old one")
    await webauth.set_password(session, user, new_password, keep=keep, notify=notify)


async def request_email_change(
    session: AsyncSession,
    user: User,
    *,
    new_email: str,
    current_password: str,
) -> str:
    """Begin moving the account to ``new_email`` and return the token.

    The address does not change here. It changes when the link is followed,
    which is what stops a typo -- or somebody else's address typed by an
    attacker -- from becoming the account's contact address and taking the
    security notices with it.
    """
    _require_password(user, current_password)
    address = emailverify.normalise(new_email)

    if address == (user.email or ""):
        raise InvalidInputError("That is already your address")

    taken = await session.scalar(select(User).where(User.email == address))
    if taken is not None and taken.id != user.id:
        raise InvalidInputError("That email address is already registered")

    return await emailverify.issue(session, user, address)


async def begin_totp_enrolment(session: AsyncSession, user: User) -> TotpEnrolment:
    """Generate a secret and store it unconfirmed.

    Unconfirmed means sign-in ignores it. Starting enrolment therefore cannot
    lock anyone out, and starting it twice simply replaces the secret that was
    never proved.
    """
    if await is_totp_active(session, user):
        raise InvalidInputError("An authenticator is already enrolled")

    existing = await session.get(TotpCredential, user.id)
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    secret = totp.generate_secret()
    session.add(TotpCredential(user_id=user.id, secret=secret, confirmed=False))
    await session.commit()

    return TotpEnrolment(
        secret=secret,
        uri=totp.provisioning_uri(secret, account=user.username, issuer=TOTP_ISSUER),
    )


async def confirm_totp_enrolment(
    session: AsyncSession, user: User, code: str, *, notify: Notifier | None = None
) -> None:
    """Turn the enrolled authenticator on, once a code proves it works."""
    credential = await session.get(TotpCredential, user.id)
    if credential is None:
        raise InvalidInputError("There is no enrolment to confirm")
    if credential.confirmed:
        raise InvalidInputError("An authenticator is already enrolled")

    step = totp.verify(credential.secret, code)
    if step is None:
        raise ForbiddenError("That code is not valid")

    credential.confirmed = True
    credential.last_step = step
    await session.commit()

    await webauth.notify_security(
        user,
        notify,
        subject="An authenticator app was added to your altero account",
        body=(
            "Signing in to this altero account now asks for a code from an "
            "authenticator app.\n\nIf this was not you, change your password "
            "immediately.\n"
        ),
    )


async def disable_totp(
    session: AsyncSession,
    user: User,
    *,
    current_password: str,
    notify: Notifier | None = None,
) -> None:
    """Remove the second factor. Needs the password, since it weakens the account."""
    _require_password(user, current_password)

    credential = await session.get(TotpCredential, user.id)
    if credential is None:
        raise InvalidInputError("No authenticator is enrolled")

    await session.delete(credential)
    await session.commit()

    await webauth.notify_security(
        user,
        notify,
        subject="The authenticator app on your altero account was removed",
        body=(
            "Signing in to this altero account no longer asks for a code.\n\n"
            "If this was not you, change your password immediately.\n"
        ),
    )


async def is_totp_active(session: AsyncSession, user: User) -> bool:
    """Return whether a *confirmed* authenticator is enrolled."""
    credential = await session.get(TotpCredential, user.id)
    return credential is not None and credential.confirmed


async def list_sessions(session: AsyncSession, user: User) -> list[WebSession]:
    """Return this account's live browser sessions, most recent first."""
    result = await session.scalars(
        select(WebSession)
        .where(
            WebSession.user_id == user.id,
            WebSession.expires >= datetime.now(UTC).replace(tzinfo=None),
        )
        .order_by(WebSession.last_seen.desc())
    )
    return list(result)


async def revoke_session(
    session: AsyncSession, user: User, session_id: int, *, current: WebSession
) -> None:
    """End one of this account's sessions.

    Signing out the session making the request is allowed -- it is the same as
    signing out -- but it is the caller's job to clear the cookie afterwards.
    """
    record = await session.get(WebSession, session_id)
    if record is None or record.user_id != user.id:
        raise ForbiddenError("That session is not yours")
    await websessions.revoke(session, record)


async def revoke_other_sessions(session: AsyncSession, user: User, *, keep: WebSession) -> None:
    """Sign out everywhere except here."""
    await websessions.revoke_all(session, user, keep=keep)
