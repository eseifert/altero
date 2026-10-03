"""Expired login sessions and reduced key permissions retain desktop state."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from altero.models import ApiKey, LoginSession
from tools.compatibility.acceptance_runtime import AcceptanceRun


async def credential_limits(run: AcceptanceRun) -> None:
    await run.phase("A", [dict(action="create", key="SCNPED23")], files=False)
    await run.phase("B", files=False)
    assert run.server.session_factory is not None
    path = run.root / "login.json"
    await run.phase("B", [dict(action="login-start", path=str(path))], files=False, sync=False)
    token = json.loads(path.read_text())["sessionToken"]
    async with run.server.session_factory() as session:
        row = await session.get(LoginSession, token)
        assert row is not None
        row.created = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        await session.commit()
    await run.phase(
        "B",
        [dict(action="login-check", path=str(path), expected="expired")],
        files=False,
        sync=False,
    )
    await run.phase("B", [dict(action="login-start", path=str(path))], files=False, sync=False)
    await run.phase(
        "B",
        [
            dict(action="login-cancel", path=str(path)),
            dict(action="login-check", path=str(path), expected="cancelled"),
        ],
        files=False,
        sync=False,
    )
    await run.phase(
        "B",
        [dict(action="edit", key="SCNPED23", fields={"title": "Queued under reduced access"})],
        files=False,
        sync=False,
    )
    async with run.server.session_factory() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.key == run.server.key))
        assert key is not None
        key.library_read = False
        await session.commit()
    denied = await run.phase("B", files=False, all_libraries=True)
    assert denied["unsynced"]["item"], "Reduced key access discarded the local edit"
    async with run.server.session_factory() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.key == run.server.key))
        assert key is not None
        key.library_read = True
        await session.commit()
    assert (await run.request("GET", "/users/1/items/SCNPED23")).json()["data"][
        "title"
    ] == "Über 東京"
    left, right = await run.phase("B", files=False), await run.phase("A", files=False)
    await run.converged(left, right)
    assert left["items"][0]["title"] == "Queued under reduced access"
    await run.settled(files=False)
