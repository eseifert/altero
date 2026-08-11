"""Offering somebody membership of a group library.

Addressed to an email address rather than to an account, because the usual
reason to invite someone is that they are not here yet. When the address does
match an account the invitation is linked to it and raised as a notification,
so it can be answered in the interface; when it does not, the emailed token is
the credential and whoever later registers with that address can accept.

Only an admin of the library may invite. Membership and the ability to hand
membership out are different things, and a group where every member can add
anyone is a group nobody can keep track of.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import GroupMember, Invitation, Library, LibraryType, MemberPermission, User
from altero.services import emailverify, groups, notifications
from altero.services.groups import MEMBER_PERMISSIONS

PENDING = "pending"
ACCEPTED = "accepted"
DECLINED = "declined"
REVOKED = "revoked"

#: How long an invitation stays answerable.
LIFETIME_DAYS = 14

TOKEN_BYTES = 32

#: Roles an invitation may offer.
ROLES = ("member", "admin")


def described(role: str, permission: str) -> str:
    """Say what is being offered, for the notification that offers it.

    A membership is two answers now, and somebody invited to read a library
    should be told that before they accept rather than after they try to add
    something.
    """
    if role == "admin":
        return "an administrator"
    return {
        MemberPermission.READ.value: "a member who can read it",
        MemberPermission.ADD.value: "a member who can add to it but not remove from it",
        MemberPermission.OWN.value: "a member who can work on their own items in it",
    }.get(permission, "a member")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def require_admin(session: AsyncSession, library: Library, user: User) -> None:
    """Raise unless ``user`` administers ``library``.

    Delegated, so that "who may hand membership out" has one definition however
    it is reached -- the API's group endpoints ask the same question.
    """
    await groups.require_admin(session, library, user.id)


async def pending_for_email(session: AsyncSession, email: str) -> bool:
    """Return whether ``email`` has an invitation still waiting to be answered.

    Asked during registration: an address somebody invited is allowed to make
    an account even where registration is otherwise closed, which is what makes
    inviting a person who is not here yet work.
    """
    address = emailverify.normalise(email)
    found = await session.scalar(
        select(Invitation).where(
            Invitation.email == address,
            Invitation.status == PENDING,
            Invitation.expires >= _now(),
        )
    )
    return found is not None


async def invite_with_token(
    session: AsyncSession,
    *,
    library: Library,
    inviter: User,
    email: str,
    role: str = "member",
    permission: str = MemberPermission.INHERIT.value,
) -> tuple[Invitation, str]:
    """Invite ``email`` and return the invitation with its token.

    The token is returned here and nowhere else. An outstanding invitation for
    the same address is reused rather than duplicated, so sending a reminder
    does not leave two live tokens and two rows to answer.
    """
    if library.type is not LibraryType.GROUP:
        raise InvalidInputError("Only a group library has members")
    if role not in ROLES:
        raise InvalidInputError(f"A role must be one of {', '.join(ROLES)}")
    if permission not in MEMBER_PERMISSIONS:
        raise InvalidInputError(f"A permission must be one of {', '.join(MEMBER_PERMISSIONS)}")
    if role == "admin" and permission != MemberPermission.INHERIT:
        raise InvalidInputError("An administrator of a group cannot be restricted")

    await require_admin(session, library, inviter)
    address = emailverify.normalise(email)

    invited = await session.scalar(select(User).where(User.email == address))
    if invited is not None:
        existing_member = await session.scalar(
            select(GroupMember).where(
                GroupMember.library_id == library.id, GroupMember.user_id == invited.id
            )
        )
        if existing_member is not None:
            raise InvalidInputError("They are already a member of this group")

    outstanding = await session.scalar(
        select(Invitation).where(
            Invitation.library_id == library.id,
            Invitation.email == address,
            Invitation.status == PENDING,
        )
    )

    token = secrets.token_urlsafe(TOKEN_BYTES)
    if outstanding is not None:
        # Re-issued rather than reused: the previous token may have gone to an
        # address that was mistyped, or into a mailbox somebody else reads.
        outstanding.token_hash = hash_token(token)
        outstanding.expires = _now() + timedelta(days=LIFETIME_DAYS)
        outstanding.role = role
        outstanding.permission = permission
        outstanding.user_id = invited.id if invited else None
        await session.commit()
        return outstanding, token

    invitation = Invitation(
        library_id=library.id,
        email=address,
        user_id=invited.id if invited else None,
        role=role,
        permission=permission,
        invited_by=inviter.id,
        token_hash=hash_token(token),
        status=PENDING,
        expires=_now() + timedelta(days=LIFETIME_DAYS),
    )
    session.add(invitation)
    await session.commit()

    if invited is not None:
        await notifications.raise_for(
            session,
            invited,
            kind="invitation",
            subject=f"{inviter.display_name or inviter.username} invited you to “{library.name}”",
            body=(
                f"You have been invited to join the group library “{library.name}” "
                f"as {described(role, permission)}."
            ),
            invitation_id=invitation.id,
        )

    return invitation, token


async def invite(
    session: AsyncSession,
    *,
    library: Library,
    inviter: User,
    email: str,
    role: str = "member",
    permission: str = MemberPermission.INHERIT.value,
) -> Invitation:
    """Invite ``email``, discarding the token.

    For callers that only deliver in-app; the emailed link needs
    :func:`invite_with_token`.
    """
    invitation, _ = await invite_with_token(
        session, library=library, inviter=inviter, email=email, role=role, permission=permission
    )
    return invitation


async def by_token(session: AsyncSession, token: str) -> Invitation:
    """Return the invitation an emailed link identifies."""
    if not token:
        raise NotFoundError("No such invitation")
    invitation = await session.scalar(
        select(Invitation).where(Invitation.token_hash == hash_token(token))
    )
    if invitation is None:
        raise NotFoundError("No such invitation")
    return invitation


async def pending_for_library(session: AsyncSession, library: Library) -> list[Invitation]:
    result = await session.scalars(
        select(Invitation).where(Invitation.library_id == library.id, Invitation.status == PENDING)
    )
    return list(result)


async def pending_for_user(session: AsyncSession, user: User) -> list[Invitation]:
    """Return invitations this person can answer.

    Matched on the address as well as the link, so one issued before they
    registered still reaches them.

    An account with no address -- one made by `altero user add` -- is matched on
    the link alone. The clause is left out rather than compared against an
    impossible value: the first version of this used "\\0" as that value, which
    SQLite accepts happily and PostgreSQL refuses outright, so every one of
    those accounts got a 500 from the notifications panel on a real deployment.
    """
    answerable = Invitation.user_id == user.id
    if user.email:
        answerable = or_(answerable, Invitation.email == user.email)

    result = await session.scalars(
        select(Invitation)
        .where(Invitation.status == PENDING, Invitation.expires >= _now())
        .where(answerable)
        .order_by(Invitation.created.desc())
    )
    return list(result)


def _require_answerable(invitation: Invitation, user: User) -> None:
    """Raise unless ``user`` may answer ``invitation`` right now."""
    if invitation.status != PENDING:
        raise ForbiddenError("That invitation has already been answered")
    if invitation.expires < _now():
        raise ForbiddenError("That invitation has expired")
    # The invitation names an address. Holding the row, or its id, is not the
    # same as being the person it was offered to.
    if invitation.user_id != user.id and invitation.email != (user.email or ""):
        raise ForbiddenError("That invitation was not addressed to you")


async def accept(session: AsyncSession, invitation: Invitation, user: User) -> GroupMember:
    """Take up an invitation, becoming a member at the role it offered."""
    _require_answerable(invitation, user)

    existing = await session.scalar(
        select(GroupMember).where(
            GroupMember.library_id == invitation.library_id,
            GroupMember.user_id == user.id,
        )
    )
    if existing is None:
        existing = GroupMember(
            library_id=invitation.library_id,
            user_id=user.id,
            role=invitation.role,
            permission=invitation.permission,
        )
        session.add(existing)

    invitation.status = ACCEPTED
    invitation.user_id = user.id
    invitation.answered = _now()
    await session.commit()

    await notifications.mark_read_for_invitation(session, user, invitation.id)
    return existing


async def decline(session: AsyncSession, invitation: Invitation, user: User) -> None:
    """Turn an invitation down, without joining anything."""
    _require_answerable(invitation, user)

    invitation.status = DECLINED
    invitation.user_id = user.id
    invitation.answered = _now()
    await session.commit()

    await notifications.mark_read_for_invitation(session, user, invitation.id)


async def revoke(session: AsyncSession, invitation: Invitation, actor: User) -> None:
    """Withdraw an invitation that has not been answered."""
    library = await session.get(Library, invitation.library_id)
    if library is None:  # pragma: no cover - defensive
        raise NotFoundError("No such library")
    await require_admin(session, library, actor)

    if invitation.status != PENDING:
        raise InvalidInputError("That invitation has already been answered")

    invitation.status = REVOKED
    invitation.answered = _now()
    await session.commit()
