"""Shared fixtures."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at a database and a file store of this test's own.

    The storage path matters as much as the database one: a test that uploads
    an attachment writes real bytes, and without this it writes them into the
    checkout.
    """
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    await application.state.database.create_all()
    yield application
    await application.state.database.dispose()


@pytest.fixture
async def session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with app.state.database.session_factory() as session:
        yield session


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def as_if_built(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Make the web interface look built, whatever is on disk.

    Otherwise a test about the built state passes or fails depending on
    whether the developer has run `npm run build` -- and CI's test job does
    not, so it would be red there and green locally.
    """
    from altero.api import spa

    root = tmp_path / "static"
    root.mkdir(parents=True)
    (root / "index.html").write_text('<!doctype html><div id="app"></div>')
    monkeypatch.setattr(spa, "STATIC_ROOT", root)
    return root


@pytest.fixture
def as_if_not_built(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make the web interface look unbuilt, whatever is on disk."""
    from altero.api import spa

    monkeypatch.setattr(spa, "STATIC_ROOT", tmp_path / "never-built")


@pytest.fixture(autouse=True)
def _forget_key_usage_throttle() -> None:
    """Start every test with an empty key-usage throttle.

    It is deliberately process-global in production, which means it would
    otherwise leak between tests: a key id written in one test would suppress
    the write for the same id in the next, whose database is new.
    """
    from altero.services import keyusage

    keyusage.reset()
