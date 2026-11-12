"""Approval-required registration grants bootstrap administrator privileges once."""

import asyncio

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import User
from altero.services import webauth


async def test_competing_first_accounts_cannot_bypass_approval(
    app: FastAPI, session: AsyncSession
) -> None:
    async def worker(name: str) -> bool:
        async with app.state.database.session_factory() as other:
            try:
                await webauth.register(
                    other,
                    username=name,
                    email=name + "@example.org",
                    password="correct horse battery staple",
                    allow_registration=True,
                    approval_required=True,
                )
            except ForbiddenError:
                return False
            return True

    assert sum(await asyncio.gather(worker("First"), worker("Second"))) == 1
    assert await session.scalar(select(func.count()).select_from(User)) == 1
    assert (
        await session.scalar(
            select(func.count()).select_from(User).where(User.administrator.is_(True))
        )
        == 1
    )
