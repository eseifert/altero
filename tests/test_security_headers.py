"""What a browser may do with what this server answers.

The interface under /app is the one place script runs, and only its own. Every
other answer is data: an attachment opened in a tab, a bibliography, the JSON
of the API. A browser shown one of those as a page must run nothing in it and
treat it as belonging to no origin -- otherwise an HTML file somebody synced
into a group would run with the session of whoever opened it.
"""

import hashlib
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.api import security, spa
from altero.app import create_app
from altero.models import Library, LibraryType
from altero.services.auth import get_library
from altero.settings import Settings
from tests.factories import make_api_key, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}

PAGE = b'<!doctype html><script>document.title = "ran"</script>'


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
    )


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    await session.commit()
    return library


async def store(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    library: Library,
    key: str,
    content: bytes,
    content_type: str,
    filename: str,
) -> None:
    """Attach ``content`` to a new attachment item through the v3 upload."""
    await make_item(session, library, key=key, item_type="attachment")
    authorized = (
        await client.post(
            f"/users/1/items/{key}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data={
                "md5": hashlib.md5(content, usedforsecurity=False).hexdigest(),
                "filename": filename,
                "filesize": str(len(content)),
                "mtime": "1700000000000",
                "contentType": content_type,
            },
        )
    ).json()
    await client.post(authorized["url"], content=content)
    await client.post(
        f"/users/1/items/{key}/file",
        headers=AUTH | {"If-None-Match": "*"},
        data={"upload": authorized["uploadKey"]},
    )


def policy(response: httpx2.Response) -> list[str]:
    return [part.strip() for part in response.headers["content-security-policy"].split(";")]


class TestAFileIsNeverAPage:
    async def test_an_html_attachment_runs_nothing(
        self, client: httpx2.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """`key` may be passed in the query, so this is a link anybody can send."""
        await store(client, session, library, "HTML2345", PAGE, "text/html", "page.html")

        response = await client.get(f"/users/1/items/HTML2345/file/view?key={KEY}")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "sandbox" in policy(response)
        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_an_svg_attachment_runs_nothing(
        self, client: httpx2.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        await store(client, session, library, "SVGG2345", svg, "image/svg+xml", "image.svg")

        response = await client.get(f"/users/1/items/SVGG2345/file/view?key={KEY}")

        assert "sandbox" in policy(response)

    async def test_the_download_the_client_is_sent_to_runs_nothing(
        self, client: httpx2.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await store(client, session, library, "HTML2345", PAGE, "text/html", "page.html")
        redirect = await client.get("/users/1/items/HTML2345/file", headers=AUTH)

        response = await client.get(redirect.headers["location"])

        assert response.status_code == 200
        assert "sandbox" in policy(response)

    async def test_a_pdf_is_left_out_of_the_sandbox(
        self, client: httpx2.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """A sandboxed document may not use a plugin, and Chrome's PDF viewer is
        one: the reader would see a refusal instead of the paper."""
        pdf = b"%PDF-1.4\n%%EOF\n"
        await store(client, session, library, "PDFF2345", pdf, "application/pdf", "paper.pdf")

        response = await client.get(f"/users/1/items/PDFF2345/file/view?key={KEY}")

        assert response.status_code == 200
        assert "content-security-policy" not in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"


class TestTheApiIsData:
    async def test_json_carries_the_sandbox(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items", headers=AUTH)

        assert "sandbox" in policy(response)
        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_a_bibliography_carries_the_sandbox(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        """HTML, and reachable with the key in the query."""
        response = await client.get(f"/users/1/items?format=bib&key={KEY}")

        assert response.headers["content-type"].startswith("text/html")
        assert "sandbox" in policy(response)

    async def test_an_error_carries_the_sandbox(self, client: httpx2.AsyncClient) -> None:
        response = await client.get("/web/libraries")

        assert response.status_code == 401
        assert "sandbox" in policy(response)


@pytest.fixture
async def interface(  # type: ignore[no-untyped-def]
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><div id=app></div>")
    (root / "assets" / "index-abc123.js").write_text("console.log('altero')")
    monkeypatch.setattr(spa, "STATIC_ROOT", root)
    app: FastAPI = create_app(settings)
    await app.state.database.create_all()
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await app.state.database.dispose()


class TestTheInterfaceRunsOnlyItsOwnScript:
    @pytest.mark.parametrize("path", ["/", "/app/", "/app/library", "/app/u/ada"])
    async def test_the_page_carries_the_interface_policy(
        self, interface: httpx2.AsyncClient, path: str
    ) -> None:
        response = await interface.get(path)

        assert response.status_code == 200
        assert response.headers["content-security-policy"] == security.INTERFACE_POLICY

    def test_the_policy_admits_no_script_but_its_own(self) -> None:
        directives = {
            part.split()[0]: part.split()[1:]
            for part in security.INTERFACE_POLICY.split(";")
            if part.strip()
        }

        assert directives["script-src"] == ["'self'"]
        assert directives["object-src"] == ["'none'"]
        assert directives["base-uri"] == ["'none'"]
        assert directives["frame-ancestors"] == ["'none'"]
        assert "'unsafe-inline'" not in directives["style-src"]
        assert all("'unsafe-eval'" not in sources for sources in directives.values())

    async def test_an_asset_is_not_sandboxed(self, interface: httpx2.AsyncClient) -> None:
        response = await interface.get("/app/assets/index-abc123.js")

        assert "sandbox" not in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
