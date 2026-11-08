"""SSO session and proof provenance survives enabling a stricter browser policy."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.services import admin, reauth, webauth, websessions
from tests.test_web_routes import PASSWORD


async def test_only_explicit_sso_sessions_carry_the_sso_marker(session: AsyncSession) -> None:
    user = await admin.create_user(session, username="ada")
    _, local = await websessions.create(session, user)
    token, federated = await websessions.create(session, user, sso=True)
    assert local.sso_authenticated is False
    assert federated.sso_authenticated is True
    await session.close()
    loaded = await websessions.lookup(session, token)
    assert loaded is not None
    assert loaded.sso_authenticated


async def test_a_local_proof_cannot_extend_an_sso_proof(session: AsyncSession) -> None:
    user = await admin.create_user(session, username="ada")
    await webauth.set_password(session, user, PASSWORD)
    _, record = await websessions.create(session, user, sso=True)
    await reauth.stamp(session, record, sso=True)
    assert reauth.is_fresh(record, sso_only=True)
    record.sso_reauthenticated = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=6)
    await reauth.stamp(session, record)
    assert reauth.is_fresh(record)
    assert not reauth.is_fresh(record, sso_only=True)
    with pytest.raises(reauth.ReauthenticationRequired):
        await reauth.require(session, user, record, password=PASSWORD, sso_only=True)
    await reauth.stamp(session, record, sso=True)
    await reauth.require(session, user, record, sso_only=True)
