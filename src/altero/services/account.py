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

from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import ApiKey, ProfileVisibility, TotpCredential, User, WebSession
from altero.services import (
    admin,
    emailverify,
    locales,
    passwords,
    totp,
    webauth,
    websessions,
)
from altero.services.webauth import Notifier

#: Issuer shown in an authenticator app.
TOTP_ISSUER = "altero"


@dataclass(frozen=True, slots=True)
class TotpEnrolment:
    """What the interface needs to show a QR code and take a code back."""

    secret: str
    uri: str


def require_password(user: User, password: str) -> None:
    """Raise unless ``password`` is this user's current one.

    Public because it is not only credentials that want it: restoring a library
    over an existing one is as irreversible as changing a password, and the
    transfer endpoints ask for the same proof. One implementation, so "the
    current password" means the same thing wherever it is demanded.
    """
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


async def set_profile_visibility(
    session: AsyncSession, user: User, visibility: ProfileVisibility
) -> User:
    """Change who may read the account's profile page.

    No password either, and for a related reason: this hides or shows work its
    owner chose to publish, and nothing about it reaches a credential. Closing
    the page leaves every item flagged, so reopening it publishes exactly what
    was there before.
    """
    user.profile_visibility = visibility
    await session.commit()
    return user


async def set_locale(
    session: AsyncSession,
    user: User,
    *,
    language: str | None,
    time_zone: str | None,
) -> User:
    """Set the interface language and time zone, or clear either to follow the browser.

    No password, for the same reason the display name needs none: neither is a
    credential, and getting the language wrong is a nuisance rather than a
    compromise.
    """
    user.language = locales.normalise_language(language)
    user.time_zone = locales.normalise_time_zone(time_zone)
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
    require_password(user, current_password)
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
    require_password(user, current_password)
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
    require_password(user, current_password)

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


# --------------------------------------------------------------------------
# API keys
#
# Creating one asks for the password; revoking one does not. Creating hands out
# a new credential, and belongs with every other credential change here.
# Revoking only takes access away, and the moment somebody reaches for it is
# the moment a key has leaked -- making them find their password first is
# friction in precisely the wrong place.
# --------------------------------------------------------------------------

#: Longest name accepted for a key.
MAX_KEY_NAME = 255


async def list_keys(session: AsyncSession, user: User) -> list[ApiKey]:
    """Return this account's API keys, newest first.

    Keys with no recorded date sort last: they predate the column and there is
    nothing to order them by.
    """
    result = await session.scalars(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created.desc().nullslast(), ApiKey.id.desc())
    )
    return list(result)


async def create_key(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    current_password: str,
    write: bool = True,
    groups: bool = True,
) -> ApiKey:
    """Issue a key for this account and return it, once.

    The value is readable on the object that comes back and is not offered
    again afterwards, which is the same promise `altero key add` makes.

    Full access by default, because the overwhelmingly common reason to make
    one here is to sync a Zotero client, and a key that cannot write or cannot
    see groups presents to that client as a server which has lost things.
    """
    require_password(user, current_password)

    label = name.strip()
    if not label:
        # A list of unnamed keys is a list nobody can act on; if you cannot
        # tell which is which you cannot safely revoke any of them.
        raise InvalidInputError("A key needs a name, so you can tell it apart later")
    if len(label) > MAX_KEY_NAME:
        raise InvalidInputError("That name is too long")

    return await admin.create_api_key(
        session,
        username=user.username,
        name=label,
        read=True,
        write=write,
        notes=True,
        files=True,
        all_groups_read=groups,
        all_groups_write=groups and write,
    )


async def revoke_key(session: AsyncSession, user: User, key_id: int) -> None:
    """Delete one of this account's keys, so it stops working immediately."""
    record = await session.get(ApiKey, key_id)
    if record is None:
        raise NotFoundError("No such key")
    if record.user_id != user.id:
        raise ForbiddenError("That key is not yours")

    await session.delete(record)
    await session.commit()
