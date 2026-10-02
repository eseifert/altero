"""A disposable live server shared by generated and desktop acceptance runs."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import uvicorn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from altero.app import create_app
from altero.models import ApiKey, Library, LibraryType, User
from altero.services import login
from altero.services.ratelimit import RateLimiter
from altero.settings import Settings
from tools.compatibility.barriers import HTTPBarrier
from tools.compatibility.databases import fresh_database

KEY = "CompatibilityTestKey23456"


@dataclass
class TestServer:
    url: str
    key: str = KEY
    user_id: int = 1
    keys: dict[int, str] = field(default_factory=lambda: {1: KEY})
    barrier: HTTPBarrier = field(default_factory=HTTPBarrier)
    approve_login: Callable[[str], Awaitable[None]] | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    storage_path: Path | None = None
    limiter: RateLimiter | None = None
    database_url: str | None = field(default=None, repr=False)
    crash: Callable[[], Awaitable[int]] | None = None
    restart: Callable[[], Awaitable[int]] | None = None


@asynccontextmanager
async def disposable_server(
    root: Path, *, accounts: int = 1, postgres_url: str | None = None
) -> AsyncIterator[TestServer]:
    """Use a fresh SQLite file or a newly created, isolated PostgreSQL database."""
    root.mkdir(parents=True, exist_ok=False)
    database_url = (
        await fresh_database(root, postgres_url)
        if postgres_url
        else f"sqlite+aiosqlite:///{root / 'server.sqlite'}"
    )
    app = create_app(
        Settings(
            database_url=database_url,
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
    control = HTTPBarrier()

    async def approve_login(token: str) -> None:
        async with app.state.database.session_factory() as session:
            key = ApiKey(
                key=uuid4().hex[:24],
                user_id=1,
                name="Disposable desktop linking",
                library_read=True,
                library_write=True,
                notes_read=True,
                files_read=True,
            )
            session.add(key)
            await session.flush()
            await login.approve_session(session, token, key)

    server = uvicorn.Server(
        uvicorn.Config(
            control.wrap(app), host="127.0.0.1", port=0, log_level="error", access_log=False
        )
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
        yield TestServer(
            f"http://127.0.0.1:{port}",
            keys=keys,
            barrier=control,
            approve_login=approve_login,
            session_factory=app.state.database.session_factory,
            storage_path=root / "storage",
            limiter=app.state.rate_limiter,
            database_url=database_url,
        )
    finally:
        control.release.set()
        server.should_exit = True
        await task
        await app.state.database.dispose()
