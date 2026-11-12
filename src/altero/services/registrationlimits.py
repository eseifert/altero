"""Fixed-window registration/mail budgets, shared by workers and restarts."""

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import RegistrationLimitError
from altero.models import RegistrationBudget


@dataclass(frozen=True, slots=True)
class Budget:
    namespace: str
    value: str
    limit: int
    window: timedelta

    def __post_init__(self) -> None:
        if self.limit < 1 or self.window <= timedelta(0) or not self.namespace:
            raise ValueError("A budget needs a namespace, positive allowance and window")

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.namespace}\0{self.value}".encode()).hexdigest()


async def lock_capacity(session: AsyncSession) -> None:
    """Serialize pending-count checks with inserts, without committing."""
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    statement = insert(RegistrationBudget).values(
        key=hashlib.sha256(b"altero registration capacity").hexdigest(),
        used=1,
        expires=datetime.max,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[RegistrationBudget.key], set_={"used": RegistrationBudget.used}
        )
    )


async def reserve(session: AsyncSession, *budgets: Budget, now: datetime | None = None) -> None:
    """Spend all buckets or none; commit before attempting delivery or work.

    A crashed worker or failed SMTP attempt still spends its reservation.
    Expired buckets reset at equality; refused attempts do not extend expiry.
    Keys are acquired in sorted order to avoid overlapping-budget deadlocks.
    Call before unrelated writes: this operation owns commit and rollback.
    """
    moment = now or datetime.now(UTC)
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    if len({b.key for b in budgets}) != len(budgets):
        raise ValueError("Each budget may be charged only once per reservation")
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    try:
        await session.execute(
            delete(RegistrationBudget).where(RegistrationBudget.expires <= moment)
        )
        for budget in sorted(budgets, key=lambda b: b.key):
            statement = insert(RegistrationBudget).values(
                key=budget.key, used=1, expires=moment + budget.window
            )
            key = await session.scalar(
                statement.on_conflict_do_update(
                    index_elements=[RegistrationBudget.key],
                    set_={"used": RegistrationBudget.used + 1},
                    where=RegistrationBudget.used < budget.limit,
                ).returning(RegistrationBudget.key)
            )
            if key is None:
                expires = await session.scalar(
                    select(RegistrationBudget.expires).where(RegistrationBudget.key == budget.key)
                )
                assert expires is not None
                raise RegistrationLimitError(max(1, math.ceil((expires - moment).total_seconds())))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
