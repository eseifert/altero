"""A disposable live server shared by generated and desktop acceptance runs."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn

from altero.app import create_app
from altero.models import ApiKey, Library, LibraryType, User
from altero.settings import Settings

KEY = "CompatibilityTestKey23456"


@dataclass
class TestServer:
    url: str
    key: str = KEY
    user_id: int = 1
    keys: dict[int, str] = field(default_factory=lambda: {1: KEY})


@asynccontextmanager
async def disposable_server(root: Path, *, accounts: int = 1) -> AsyncIterator[TestServer]:
    """All database and storage writes stay under a newly created directory."""
    root.mkdir(parents=True, exist_ok=False)
    app = create_app(
        Settings(
            database_url=f"sqlite+aiosqlite:///{root / 'server.sqlite'}",
            storage_path=root / "storage",
        )
    )
    await app.state.database.create_all()
    keys = {
        user_id: KEY if user_id == 1 else f"CompatibilityMemberKey{user_id:02d}"
        for user_id in range(1, accounts + 1)
    }
    async with app.state.database.session_factory() as session:
        for user_id, key in keys.items():
            username = "compatibility" if user_id == 1 else f"compatibility{user_id}"
            session.add(User(id=user_id, username=username, display_name=username))
            await session.flush()
            session.add(Library(type=LibraryType.USER, owner_id=user_id, name=username))
            await session.flush()
            session.add(
                ApiKey(
                    key=key,
                    user_id=user_id,
                    name="Disposable compatibility test",
                    library_read=True,
                    library_write=True,
                    notes_read=True,
                    files_read=True,
                    all_groups_read=accounts > 1,
                    all_groups_write=accounts > 1,
                )
            )
        await session.commit()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False)
    )
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    task.result()
                    raise RuntimeError("Disposable server exited before binding")
                await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield TestServer(f"http://127.0.0.1:{port}", keys=keys)
    finally:
        server.should_exit = True
        await task
        await app.state.database.dispose()
