"""Admit credential guesses before doing expensive or security-sensitive work.

Reservations are committed before verification: a wrong guess, a crashed
worker and concurrent requests all spend the same durable budget. No database
lock is held while hashing a password. Call before making any other changes
in the supplied session; this module owns its transaction boundaries.

Account budgets distinguish password and second factor. The address budget is
shared by both. A success refunds only its own address reservation: knowing one
account's password cannot reset failures against other accounts.
"""

import hashlib
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import LoginBackoffError
from altero.models import LoginAttempt

ACCOUNT_ALLOWANCE = 5
ADDRESS_ALLOWANCE = 20
MAX_DELAY = 300
IDLE_EXPIRY = timedelta(minutes=15)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class Admission:
    key: str
    generation: str
    address_key: str
    address_generation: str


def _key(namespace: str, value: str) -> str:
    return hashlib.sha256(f"{namespace}:{value}".encode()).hexdigest()


async def reserve(
    session: AsyncSession,
    *,
    account: str,
    address: str,
    stage: str,
    now: datetime | None = None,
) -> Admission:
    """Spend both budgets or refuse without charging either.

    Upserts acquire each row's write lock even for its first simultaneous use.
    Sorted acquisition prevents deadlocks when two requests share one bucket.
    The fifth account attempt (twentieth per address) installs a one-second
    pause; subsequent admitted attempts double it, up to five minutes. Refused
    requests do not extend the pause. Fifteen idle minutes reset the budget.
    """
    moment = now or _now()
    account_key = _key(f"account:{stage}", account)
    address_key = _key("address", address)
    budgets = {account_key: ACCOUNT_ALLOWANCE, address_key: ADDRESS_ALLOWANCE}
    generation = secrets.token_hex(16)
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert

    # Indexed cleanup also takes SQLite's write lock before any reads.
    await session.execute(delete(LoginAttempt).where(LoginAttempt.expires <= moment))
    locked = []
    for key, allowance in sorted(budgets.items()):
        statement = insert(LoginAttempt).values(
            key=key,
            attempts=0,
            available=moment,
            expires=moment + IDLE_EXPIRY,
            generation=generation,
        )
        row = (
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[LoginAttempt.key], set_={"key": key}
                ).returning(LoginAttempt.attempts, LoginAttempt.available, LoginAttempt.generation)
            )
        ).one()
        locked.append((key, allowance, row.attempts, row.available, row.generation))

    wait = max((available - moment).total_seconds() for _, _, _, available, _ in locked)
    if wait > 0:
        await session.rollback()
        raise LoginBackoffError(max(1, math.ceil(wait)))

    address_generation = ""
    for key, allowance, previous, _, epoch in locked:
        count = min(previous + 1, allowance + 9)
        delay = 0 if count < allowance else min(MAX_DELAY, 2 ** (count - allowance))
        await session.execute(
            update(LoginAttempt)
            .where(LoginAttempt.key == key)
            .values(
                attempts=count,
                available=moment + timedelta(seconds=delay),
                expires=moment + IDLE_EXPIRY,
                generation=generation if key == account_key else epoch,
            )
        )
        if key == address_key:
            address_generation = epoch
    await session.commit()
    return Admission(account_key, generation, address_key, address_generation)


async def succeed(session: AsyncSession, admission: Admission) -> None:
    """Complete an admission once after proof, preserving other guesses.

    A late success cannot refund a new address window after expiry. Account
    success only resets its own generation; address success subtracts just one
    reservation, including when newer requests have already been admitted.
    """
    account = delete(LoginAttempt).where(
        LoginAttempt.key == admission.key,
        LoginAttempt.generation == admission.generation,
    )
    address = (
        update(LoginAttempt)
        .where(
            LoginAttempt.key == admission.address_key,
            LoginAttempt.generation == admission.address_generation,
            LoginAttempt.attempts > 0,
        )
        .values(
            attempts=LoginAttempt.attempts - 1,
            available=case(
                (LoginAttempt.attempts <= ADDRESS_ALLOWANCE, datetime.min),
                else_=LoginAttempt.available,
            ),
        )
    )
    # The same lock order as reserve, including a late concurrent success.
    for _, statement in sorted(((admission.key, account), (admission.address_key, address))):
        await session.execute(statement)
    await session.commit()
