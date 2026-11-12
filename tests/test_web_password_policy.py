"""Every browser password-setting path uses this app's policy, not global defaults."""

from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import User
from altero.services import admin, passwordreset, webauth
from altero.settings import Settings

STRONG = "this is a sufficiently long and uncommon passphrase"
SHORT = "uncommon secret"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/db.sqlite",
        storage_path=tmp_path / "storage",
        password_min_length=24,
    )


async def test_registration_applies_the_instance_floor_before_creating_an_account(
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    assert (await client.get("/web/config")).json()["passwordMinimumLength"] == 24
    response = await client.post(
        "/web/auth/register",
        json={"username": "ada", "email": "ada@example.org", "password": SHORT},
    )
    assert response.status_code == 400
    assert await session.scalar(select(func.count()).select_from(User)) == 0


async def test_refused_reset_preserves_the_link_for_a_policy_compliant_password(
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    user = await admin.create_user(session, username="ada")
    token = await passwordreset.issue(session, user, issued_by=user)
    refused = await client.post("/web/auth/reset", json={"token": token, "password": SHORT})
    assert refused.status_code == 400
    assert (
        await client.post("/web/auth/reset", json={"token": token, "password": STRONG})
    ).status_code == 200


async def test_app_specific_blocklist_opt_out_applies_during_both_validation_and_storage(
    app: FastAPI,
    client: httpx2.AsyncClient,
) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"password_min_length": 8, "password_block_common": False}
    )
    response = await client.post(
        "/web/auth/register",
        json={"username": "ada", "email": "ada@example.org", "password": "password123"},
    )
    assert response.status_code == 201


async def test_admin_creation_and_account_changes_use_the_same_floor(
    client: httpx2.AsyncClient,
    session: AsyncSession,
) -> None:
    user = await admin.create_user(session, username="operator")
    await webauth.set_password(session, user, STRONG)
    assert (
        await client.post("/web/auth/login", json={"username": "operator", "password": STRONG})
    ).status_code == 200
    headers = {"X-CSRF-Token": client.cookies.get("altero_csrf") or ""}
    body = {"username": "new", "password": SHORT, "currentPassword": STRONG}
    assert (await client.post("/web/admin/users", json=body, headers=headers)).status_code == 400
    assert await session.scalar(select(func.count()).select_from(User)) == 1
    assert (
        await client.post(
            "/web/account/password",
            json={"currentPassword": STRONG, "newPassword": SHORT},
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.post(
            f"/web/admin/users/{user.id}/password",
            json={"password": SHORT, "currentPassword": STRONG},
            headers=headers,
        )
    ).status_code == 400
