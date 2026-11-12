"""Internal pending-request operations; public gated registration is not enabled.

Use a session without unrelated pending writes: these operations own their
commit/rollback boundaries. An application is not an account or a credential.
The later activation operation must check account availability again, since an
operator may provision an account while somebody has a pending reservation.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, case, func, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from altero.db import UNICODE_LOWER
from altero.errors import ForbiddenError, InvalidInputError
from altero.models import RegistrationRequest, RegistrationStatus, User
from altero.services import emailverify, webauth
from altero.services.registrationpolicy import RegistrationPolicy

PENDING = (RegistrationStatus.EMAIL_PENDING, RegistrationStatus.REVIEW_PENDING)
UNAVAILABLE = "That username or email address is unavailable"
EMAIL_PROOF_LIFETIME = timedelta(hours=24)
_CLEAR_EMAIL_TOKEN = {
    "email_token_hash": None,
    "email_token_address": None,
    "email_token_expires": None,
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is None else moment.astimezone(UTC).replace(tzinfo=None)


def _require_policy(policy: RegistrationPolicy | None) -> RegistrationPolicy:
    if policy is None:
        raise ForbiddenError("Gated registration requires an explicit eligibility policy")
    return policy


def _eligible(policy: RegistrationPolicy) -> ColumnElement[bool]:
    # Addresses are normalized before storage. Match the entire domain, with
    # its @ boundary, within the conditional write that changes the request.
    return (
        or_(*(RegistrationRequest.email.endswith("@" + d) for d in policy.allowed_domains))
        if policy.allowed_domains
        else true()
    )


async def _expire_due(session: AsyncSession, moment: datetime) -> int:
    keys = list(
        await session.scalars(
            update(RegistrationRequest)
            .where(RegistrationRequest.status.in_(PENDING), RegistrationRequest.expires <= moment)
            .values(
                status=RegistrationStatus.EXPIRED,
                reserved_username=None,
                reserved_email=None,
                **_CLEAR_EMAIL_TOKEN,
            )
            .returning(RegistrationRequest.id)
        )
    )
    return len(keys)


async def expire(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Release due reservations without deleting request history."""
    count = await _expire_due(session, _utc(now or _now()))
    await session.commit()
    return count


async def prepare_submission(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    expires: datetime,
    display_name: str = "",
    enabled: bool = False,
    policy: RegistrationPolicy | None = None,
    now: datetime | None = None,
) -> RegistrationRequest:
    """Stage a reservation and expiry cleanup without committing either.

    Internal composition point: the caller owns commit/rollback and must finish
    the operation before returning. No public caller enables registration yet.
    """
    if not enabled:
        raise ForbiddenError("Gated registration is not enabled")
    rules = _require_policy(policy)
    name = webauth.validate_username(username)
    display = display_name.strip() or name
    if len(name) > 255 or len(display) > 255:
        raise InvalidInputError("Username and display name must be at most 255 characters")
    address = rules.address(email)
    if any("\x00" in value for value in (name, display, address)):
        raise InvalidInputError("Registration fields may not contain null characters")
    moment, deadline = _utc(now or _now()), _utc(expires)
    if deadline <= moment:
        raise InvalidInputError("A registration request must expire in the future")

    await _expire_due(session, moment)
    # SQLite's built-in lower() folds ASCII only. Match the canonical Python
    # lower-case reservation even for an existing accented username.
    fold = (
        getattr(func, UNICODE_LOWER) if session.get_bind().dialect.name == "sqlite" else func.lower
    )
    existing = await session.scalar(
        select(User.id)
        .where(
            or_(
                fold(User.username) == name.lower(),
                fold(User.email) == address,
            )
        )
        .limit(1)
    )
    if existing is not None:
        raise InvalidInputError(UNAVAILABLE)
    record = RegistrationRequest(
        username=name,
        email=address,
        display_name=display,
        reserved_username=name.lower(),
        reserved_email=address,
        created=moment,
        expires=deadline,
    )
    session.add(record)
    return record


async def submit(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    expires: datetime,
    display_name: str = "",
    enabled: bool = False,
    policy: RegistrationPolicy | None = None,
    now: datetime | None = None,
) -> RegistrationRequest:
    """Commit an internal reservation without issuing an applicant credential."""
    try:
        record = await prepare_submission(
            session,
            username=username,
            email=email,
            expires=expires,
            display_name=display_name,
            enabled=enabled,
            policy=policy,
            now=now,
        )
        await session.commit()
    except IntegrityError:
        # The unique reservation columns choose one winner across workers;
        # a pre-insert SELECT alone cannot reserve an identity.
        await session.rollback()
        raise InvalidInputError(UNAVAILABLE) from None
    except Exception:
        await session.rollback()
        raise
    return record


async def record_email_verification(
    session: AsyncSession,
    request_id: int,
    email: str,
    *,
    policy: RegistrationPolicy | None = None,
    now: datetime | None = None,
) -> bool:
    """Record a mailbox proof consumed by a trusted caller in this same session.

    The token consumer must bind its proof to this request and address. An ID
    and address supplied by an applicant are not proof. Related token-consumption
    writes commit with this transition; no public route calls this primitive yet.
    """
    address = _require_policy(policy).address(email)
    moment = _utc(now or _now())
    await _expire_due(session, moment)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.id == request_id,
            RegistrationRequest.email == address,
            RegistrationRequest.status == RegistrationStatus.EMAIL_PENDING,
            RegistrationRequest.expires > moment,
        )
        .values(
            status=RegistrationStatus.REVIEW_PENDING, email_verified=moment, **_CLEAR_EMAIL_TOKEN
        )
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return key is not None


async def cancel(session: AsyncSession, request_id: int, *, now: datetime | None = None) -> bool:
    """Cancel a live request after the caller has authenticated its applicant.

    The row ID is not an authorization. Applicant authentication belongs to the
    later status/session flow; no public route calls this primitive yet.
    """
    moment = _utc(now or _now())
    await _expire_due(session, moment)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.id == request_id,
            RegistrationRequest.status.in_(PENDING),
            RegistrationRequest.expires > moment,
        )
        .values(
            status=RegistrationStatus.CANCELLED,
            reserved_username=None,
            reserved_email=None,
            **_CLEAR_EMAIL_TOKEN,
        )
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return key is not None


async def change_email(
    session: AsyncSession,
    request_id: int,
    email: str,
    *,
    policy: RegistrationPolicy | None = None,
    now: datetime | None = None,
) -> bool:
    """Change an authenticated applicant's pending mailbox, revoking its proof.

    The caller must authenticate the applicant; knowing a row ID is insufficient.
    Return whether a live pending request changed. An unchanged normalized address
    preserves verification, and terminal requests cannot be reopened. No public
    route calls this primitive. Final activation must recheck account conflicts.
    """
    address = _require_policy(policy).address(email)
    moment = _utc(now or _now())
    await _expire_due(session, moment)
    fold = (
        getattr(func, UNICODE_LOWER) if session.get_bind().dialect.name == "sqlite" else func.lower
    )
    existing = await session.scalar(select(User.id).where(fold(User.email) == address).limit(1))
    if existing is not None:
        # Expiry cleanup belongs to the same transaction as this operation.
        await session.rollback()
        raise InvalidInputError(UNAVAILABLE)
    try:
        key = await session.scalar(
            update(RegistrationRequest)
            .where(
                RegistrationRequest.id == request_id,
                RegistrationRequest.status.in_(PENDING),
                RegistrationRequest.expires > moment,
                RegistrationRequest.email != address,
            )
            .values(
                email=address,
                reserved_email=address,
                status=RegistrationStatus.EMAIL_PENDING,
                email_verified=None,
                **_CLEAR_EMAIL_TOKEN,
            )
            .returning(RegistrationRequest.id)
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise InvalidInputError(UNAVAILABLE) from None
    return key is not None


async def issue_email_verification(
    session: AsyncSession,
    request_id: int,
    *,
    policy: RegistrationPolicy | None = None,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    """Replace a live request's proof and return its (recipient, raw token).

    Only the digest is stored. Send to the returned recipient, not an address
    supplied separately by an applicant. This is an internal primitive: the
    trusted caller must supply the current policy and enforce applicant
    authorization and resend budgets. No public route or mail sender calls it yet.
    """
    rules = _require_policy(policy)
    moment = _utc(now or _now())
    await _expire_due(session, moment)
    deadline = moment + EMAIL_PROOF_LIFETIME
    token = secrets.token_urlsafe(32)
    address = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.id == request_id,
            RegistrationRequest.status == RegistrationStatus.EMAIL_PENDING,
            RegistrationRequest.expires > moment,
            _eligible(rules),
        )
        .values(
            email_token_hash=emailverify.hash_token(token),
            email_token_address=RegistrationRequest.email,
            email_token_expires=case(
                (RegistrationRequest.expires < deadline, RegistrationRequest.expires),
                else_=deadline,
            ),
        )
        .returning(RegistrationRequest.email_token_address)
    )
    await session.commit()
    return (address, token) if address is not None else None


async def consume_email_verification(
    session: AsyncSession,
    token: str,
    *,
    policy: RegistrationPolicy | None = None,
    now: datetime | None = None,
) -> bool:
    """Atomically spend an address-bound mailbox link and advance to review.

    Unknown, expired, replaced and already-consumed links all return false.
    Proof consumption and the lifecycle change are one conditional write, so
    resends and cancellation use the same row-lock order across workers.
    """
    if not token:
        return False
    rules = _require_policy(policy)
    moment = _utc(now or _now())
    await _expire_due(session, moment)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.email_token_hash == emailverify.hash_token(token),
            RegistrationRequest.email_token_address == RegistrationRequest.email,
            RegistrationRequest.email_token_expires > moment,
            RegistrationRequest.status == RegistrationStatus.EMAIL_PENDING,
            RegistrationRequest.expires > moment,
            _eligible(rules),
        )
        .values(
            status=RegistrationStatus.REVIEW_PENDING, email_verified=moment, **_CLEAR_EMAIL_TOKEN
        )
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return key is not None


def _reviewer_query(actor_id: int) -> Select[tuple[int]]:
    return select(User.id).where(
        User.id == actor_id, User.administrator.is_(True), User.disabled_at.is_(None)
    )


async def review_queue(
    session: AsyncSession,
    *,
    actor_id: int,
    after_id: int = 0,
    limit: int = 50,
    now: datetime | None = None,
) -> list[RegistrationRequest]:
    """Read a bounded page of live verified requests, oldest row ID first.

    This read commits nothing and does not sweep expiry. The actor must come
    from an authenticated administrator session in the future public caller.
    A request can expire or change after this read; decisions recheck its state.
    """
    if await session.scalar(_reviewer_query(actor_id)) is None:
        raise ForbiddenError("Only a current administrator can review registration")
    if not 1 <= limit <= 200 or after_id < 0:
        raise InvalidInputError("Review pages require limit 1-200 and a nonnegative cursor")
    rows = await session.scalars(
        select(RegistrationRequest)
        .where(
            RegistrationRequest.status == RegistrationStatus.REVIEW_PENDING,
            RegistrationRequest.expires > _utc(now or _now()),
            RegistrationRequest.id > after_id,
            _reviewer_query(actor_id).exists(),
        )
        .order_by(RegistrationRequest.id)
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def reject(
    session: AsyncSession,
    request_id: int,
    *,
    actor_id: int,
    now: datetime | None = None,
) -> bool:
    """Record a current administrator's rejection of a live verified request.

    No public route calls this yet. The future route must authenticate its
    browser session and check CSRF before supplying the actor ID. PostgreSQL
    locks the reviewer against concurrent demotion, suspension or deletion;
    the decision predicate repeats authorization on both databases. These
    operations own their transaction, as the other request transitions do.
    """
    if await session.scalar(_reviewer_query(actor_id).with_for_update()) is None:
        raise ForbiddenError("Only a current administrator can review registration")
    moment = _utc(now or _now())
    await _expire_due(session, moment)
    key = await session.scalar(
        update(RegistrationRequest)
        .where(
            RegistrationRequest.id == request_id,
            RegistrationRequest.status == RegistrationStatus.REVIEW_PENDING,
            RegistrationRequest.expires > moment,
            _reviewer_query(actor_id).exists(),
        )
        .values(
            status=RegistrationStatus.REJECTED,
            decided_by=actor_id,
            decided_at=moment,
            reserved_username=None,
            reserved_email=None,
            **_CLEAR_EMAIL_TOKEN,
        )
        .returning(RegistrationRequest.id)
    )
    await session.commit()
    return key is not None
