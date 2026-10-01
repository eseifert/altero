"""Keep the desktop checkout and Node dependency out of the default test suite."""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from tests.conftest import (
    _forget_key_usage_throttle as _forget_key_usage_throttle,
)
from tests.conftest import (
    app as app,
)
from tests.conftest import (
    client as client,
)
from tests.conftest import (
    session as session,
)
from tests.conftest import (
    settings as settings,
)

from tools.compatibility.client import CompatibilityError, ZoteroClient
from tools.compatibility.live import DesktopAPI


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--zotero-source", default=os.environ.get("ALTERO_ZOTERO_SOURCE"))


@pytest.fixture(scope="session")
def zotero_client(pytestconfig: pytest.Config) -> ZoteroClient:
    path = pytestconfig.getoption("zotero_source")
    if not path:
        raise pytest.UsageError("Pass --zotero-source or set ALTERO_ZOTERO_SOURCE; no checks skip")
    result = ZoteroClient(Path(path))
    try:
        result.verify_revision()
    except CompatibilityError as error:
        raise pytest.UsageError(str(error)) from error
    return result


@pytest.fixture
async def socket_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Exercise the same database fixtures over an actual HTTP connection."""
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False)
    )
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    task.result()
                    raise RuntimeError("Compatibility server exited before binding")
                await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            yield client
    finally:
        server.should_exit = True
        await task


@pytest.fixture(params=["user", "group"])
async def desktop(request, session, socket_client, zotero_client):
    """Run the same protocol scenarios against personal and group libraries."""
    from tests.factories import make_api_key, make_group, make_user

    from compatibility_tests.helpers import KEY, LibraryReplay

    await make_user(session)
    await make_api_key(session, all_groups_read=True, all_groups_write=True)
    kind = request.param
    if kind == "group":
        await make_group(session)
    return LibraryReplay(
        DesktopAPI(zotero_client, str(socket_client.base_url), KEY),
        kind,
        1 if kind == "user" else 100,
    )
