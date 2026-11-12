"""Durable, hashed registration and mail budget buckets."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class RegistrationBudget(Base):
    __tablename__ = "registration_budgets"
    __table_args__ = (CheckConstraint("used > 0", name="ck_registration_budgets_used"),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    used: Mapped[int] = mapped_column()
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)
