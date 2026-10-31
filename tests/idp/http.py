"""Provider-independent HTTP forms and a disposable live altero instance."""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from html.parser import HTMLParser
from pathlib import Path

import httpx2
import uvicorn
from tests.test_web_routes import register

from altero.app import create_app
from altero.settings import Settings

ALTERO_URL = "http://127.0.0.1:18765"


class Form(HTMLParser):
    """Read a named form, or the sole form, including escaped action values."""

    def __init__(self, document: str, *, identifier: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.identifier = identifier
        self.action = ""
        self.fields: dict[str, str] = {}
        self.inside = False
        self.feed(document)
        assert self.action, f"The IdP did not return the expected form ({identifier})"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self.inside = self.identifier is None or self.identifier in (
                attributes.get("id"),
                attributes.get("name"),
            )
            if self.inside:
                assert not self.action, "More than one form matched"
                assert (attributes.get("method") or "").lower() == "post"
                self.action = attributes.get("action") or ""
        if self.inside and tag == "input" and attributes.get("name"):
            self.fields[str(attributes["name"])] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.inside = False


def new_browser(*, headers: dict[str, str] | None = None) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(base_url=ALTERO_URL, timeout=20, headers=headers)


@asynccontextmanager
async def live_browser(
    root: Path, *, headers: dict[str, str] | None = None
) -> AsyncIterator[httpx2.AsyncClient]:
    """Serve a fresh database/store on the registered loopback callback port."""
    app = create_app(
        Settings(
            database_url=f"sqlite+aiosqlite:///{root / 'identity.sqlite'}",
            storage_path=root / "storage",
            public_url=ALTERO_URL,
        )
    )
    await app.state.database.create_all()
    running = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, lifespan="on")
    )
    with closing(socket.socket()) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 18765))
        task = asyncio.create_task(running.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(15):
                while not running.started:
                    if task.done():
                        task.result()
                        raise RuntimeError("altero stopped before accepting requests")
                    await asyncio.sleep(0.01)
            async with new_browser(headers=headers) as client:
                assert (await register(client)).status_code == 201
                yield client
        finally:
            running.should_exit = True
            await asyncio.wait_for(task, timeout=15)
