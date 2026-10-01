"""A disposable live server shared by generated and desktop acceptance runs."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
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


@asynccontextmanager
async def disposable_server(root: Path) -> AsyncIterator[TestServer]:
    """All database and storage writes stay under a newly created directory."""
    root.mkdir(parents=True, exist_ok=False)
    app = create_app(
        Settings(
            database_url=f"sqlite+aiosqlite:///{root / 'server.sqlite'}",
            storage_path=root / "storage",
        )
    )
    await app.state.database.create_all()
    async with app.state.database.session_factory() as session:
        session.add(User(id=1, username="compatibility", display_name="Compatibility"))
        await session.flush()
        session.add(Library(type=LibraryType.USER, owner_id=1, name="Compatibility"))
        await session.flush()
        session.add(
            ApiKey(
                key=KEY,
                user_id=1,
                name="Disposable compatibility test",
                library_read=True,
                library_write=True,
                notes_read=True,
                files_read=True,
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
        yield TestServer(f"http://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        await task
        await app.state.database.dispose()
