"""Smoke tests for the ASGI application."""

import httpx

from altero.app import create_app
from altero.settings import Settings


async def test_app_serves_the_api_version_header() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite://"))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.headers["Zotero-API-Version"] == "3"


async def test_unknown_routes_return_404() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite://"))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/no/such/endpoint")

    assert response.status_code == 404
