"""Turning a directory's assertion into an account here.

The part of single sign-on that is altero's own policy rather than a protocol.
Four decisions are recorded in the code below, and each is the kind that is
hard to change later.

**The subject identifies somebody, and nothing else does.** An email claim
looks like it would serve -- it is readable and already on the account -- and
matching on one means any directory that can assert an address can take the
account holding it. That is the classic way federated sign-in is broken into,
and it is worse here than elsewhere because an operator adding a second
provider would silently hand it everybody. So a first sign-in that matches no
:class:`~altero.models.FederatedIdentity` either creates an account or is
refused; it never adopts an existing one.

**Linking an existing account is something the account does**, signed in, from
settings -- the same shape as enrolling an authenticator. That is the supported
path for an instance that had local accounts before it had a directory.

**Provisioning is off unless the operator turned it on.** Letting a directory
create accounts means everybody in it may have a library here, which is a
policy and not a detail.

**Deprovisioning is a check at sign-in, and that is all it is.** Somebody who
has left stops signing in, so the check that would catch them is the one that
never runs again. This is stated plainly in ``docs/administration.md`` rather
than dressed up: it catches the person who left the department and still works
here, not the person who left the organisation entirely. For that, the
operator's own screen is the tool.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import FederatedIdentity, IdentityProvider, User
from altero.services import admin, oidc, webauth
from altero.services.oidc import Assertion

logger = logging.getLogger("altero.federation")


@dataclass(frozen=True, slots=True)
class Outcome:
    """Who the assertion signed in, and whether the account is new."""

    user: User
    created: bool


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def find(
    session: AsyncSession, provider: IdentityProvider, subject: str
) -> FederatedIdentity | None:
    return await session.scalar(
        select(FederatedIdentity).where(
            FederatedIdentity.provider_id == provider.id,
            FederatedIdentity.subject == subject,
        )
    )


async def identities_for(session: AsyncSession, user: User) -> list[FederatedIdentity]:
    result = await session.scalars(
        select(FederatedIdentity).where(FederatedIdentity.user_id == user.id)
    )
    return list(result)


async def link(
    session: AsyncSession,
    user: User,
    provider: IdentityProvider,
    assertion: Assertion,
) -> FederatedIdentity:
    """Attach a directory identity to an account that is already signed in.

    Refused when the subject already belongs to somebody else here: one
    identity, one account, or signing in through the directory would have two
    answers and pick one of them arbitrarily.
    """
    existing = await find(session, provider, assertion.subject)
    if existing is not None:
        if existing.user_id != user.id:
            raise ForbiddenError(
                "That account at the identity provider is already linked to somebody else here"
            )
        existing.asserted_name = assertion.display_name
        existing.last_seen = _now()
        await session.commit()
        return existing

    identity = FederatedIdentity(
        user_id=user.id,
        provider_id=provider.id,
        subject=assertion.subject,
        asserted_name=assertion.display_name,
        last_seen=_now(),
    )
    session.add(identity)
    await session.commit()
    return identity


async def unlink(session: AsyncSession, user: User, identity: FederatedIdentity) -> None:
    """Detach an identity, refusing to leave an account with no way in.

    An account with no password and one link would otherwise be able to remove
    its only credential and lock itself out of a library nobody else can reach.
    """
    if identity.user_id != user.id:
        raise ForbiddenError("That is not yours to remove")

    remaining = await session.scalar(
        select(func.count())
        .select_from(FederatedIdentity)
        .where(FederatedIdentity.user_id == user.id, FederatedIdentity.id != identity.id)
    )
    if not remaining and not user.password_hash:
        raise ForbiddenError("Set a password first: this is the only way you have of signing in")

    await session.delete(identity)
    await session.commit()


async def _unique_username(session: AsyncSession, wanted: str) -> str:
    """Return a free username near ``wanted``.

    A directory's usernames are unique in the directory and not here, and two
    directories certainly disagree. Rather than refusing the second person
    called ``ada``, a suffix is added -- the account is named for a person's
    convenience, and the identity that matters is the subject.
    """
    base = "".join(character for character in wanted if character not in "@ \t\n")[:200]
    base = webauth.validate_username(base or "user")

    candidate = base
    suffix = 2
    while await session.scalar(select(User).where(func.lower(User.username) == candidate.lower())):
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


async def sign_in(
    session: AsyncSession,
    provider: IdentityProvider,
    assertion: Assertion,
    *,
    notify: webauth.Notifier | None = None,
) -> Outcome:
    """Resolve an assertion to an account, creating one where allowed.

    The required-claim check comes first and applies to everybody, including a
    linked account: losing the claim has to stop a sign-in that would otherwise
    have worked, or it is not a check at all.
    """
    identity = await find(session, provider, assertion.subject)

    if not oidc.satisfies_requirement(assertion.claims, provider):
        if identity is not None:
            await _deprovision(session, provider, identity, notify=notify)
        raise ForbiddenError(
            "Your account at the identity provider is no longer permitted to "
            "use this server. Ask whoever runs it."
        )

    if identity is not None:
        user = await session.get(User, identity.user_id)
        if user is None:  # pragma: no cover - the row cascades with the user
            raise ForbiddenError("That account no longer exists")
        if user.disabled_at is not None:
            raise ForbiddenError(
                "This account has been suspended. Ask whoever runs this server about it."
            )
        identity.last_seen = _now()
        identity.asserted_name = assertion.display_name
        await session.commit()
        return Outcome(user=user, created=False)

    if not provider.create_accounts:
        raise ForbiddenError(
            "There is no account here for that sign-in. Sign in with a password "
            "and connect it under Settings, or ask whoever runs this server."
        )

    return Outcome(user=await _provision(session, provider, assertion), created=True)


async def _provision(
    session: AsyncSession, provider: IdentityProvider, assertion: Assertion
) -> User:
    """Make an account for a subject nobody here has linked.

    Through :func:`altero.services.admin.create_user`, so an account a
    directory made is the same object as one ``altero user add`` made -- same
    id assignment, same personal library, and the first account on an instance
    administers it whichever way it arrived.

    The address is copied but **not** marked confirmed. A directory asserting
    an address is not this server having proved it, and treating it as proved
    would let a provider aim somebody's security notices and password-reset
    links wherever it liked.
    """
    username = await _unique_username(session, assertion.username)
    user = await admin.create_user(
        session, username=username, display_name=assertion.display_name or username
    )

    if assertion.email:
        taken = await session.scalar(
            select(User).where(func.lower(User.email) == assertion.email, User.id != user.id)
        )
        # An address another account already holds is left off rather than
        # fought over: the column is unique, and the sign-in matters more than
        # the contact address, which its owner can set later.
        if taken is None:
            user.email = assertion.email
            await session.commit()

    session.add(
        FederatedIdentity(
            user_id=user.id,
            provider_id=provider.id,
            subject=assertion.subject,
            asserted_name=assertion.display_name,
            last_seen=_now(),
        )
    )
    await session.commit()
    logger.info("Created account %s from provider %s", username, provider.slug)
    return user


async def _deprovision(
    session: AsyncSession,
    provider: IdentityProvider,
    identity: FederatedIdentity,
    *,
    notify: webauth.Notifier | None = None,
) -> None:
    """Suspend an account whose directory no longer vouches for it.

    Suspension rather than deletion, and rather than merely refusing this one
    sign-in: :func:`altero.services.admin.set_disabled` refuses *both*
    credentials, so the API key a desktop client is still syncing with stops
    working too. Refusing only the browser would leave the client of somebody
    who has left the organisation syncing exactly as before, which is the whole
    thing this is for.

    Their data is untouched and reinstating them is clearing the flag.
    """
    user = await session.get(User, identity.user_id)
    if user is None or user.disabled_at is not None:
        return

    try:
        await admin.set_disabled(session, user, disabled=True)
    except Exception:
        # The last administrator cannot be suspended, and a directory must not
        # be able to lock an instance out of its own administration. Refusing
        # the sign-in is still right; the suspension simply does not happen.
        logger.warning(
            "Could not suspend %s after losing the required claim at %s",
            user.username,
            provider.slug,
        )
        return

    logger.info("Suspended %s: no longer holds %s", user.username, provider.required_claim)

    if provider.revoke_keys_on_loss:
        keys, sessions = await admin.revoke_credentials(session, user)
        logger.info("Revoked %d key(s) and %d session(s) for %s", keys, sessions, user.username)

    await webauth.notify_security(
        user,
        notify,
        subject="Your altero account has been suspended",
        body=(
            f"Your account '{user.username}' on this altero server has been "
            "suspended, because the identity provider it signs in through no "
            "longer lists you as permitted to use it.\n\n"
            "Nothing has been deleted. Whoever runs this server can restore "
            "your access.\n"
        ),
    )
