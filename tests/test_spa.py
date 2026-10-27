"""Serving the built web interface without standing on the v3 API."""

from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI

from altero.api import spa
from altero.app import create_app
from altero.settings import Settings


@pytest.fixture
def built(tmp_path: Path) -> Path:
    """A directory shaped like the frontend build's output."""
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><div id=app></div>")
    (root / "assets" / "index-abc123.js").write_text("console.log('altero')")
    (root / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    (root / "manifest.webmanifest").write_text('{"name": "altero"}')
    return root


@pytest.fixture
async def built_client(  # type: ignore[no-untyped-def]
    settings: Settings, built: Path, monkeypatch: pytest.MonkeyPatch
):
    """A server whose build output is the fixture directory.

    STATIC_ROOT is redirected rather than mounted a second time: create_app
    already mounts whatever has been built, and a second mount on the same
    prefix is simply ignored -- which made this fixture silently test the
    developer's own last `npm run build` instead of anything here.
    """
    monkeypatch.setattr(spa, "STATIC_ROOT", built)
    app = create_app(settings)
    await app.state.database.create_all()
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await app.state.database.dispose()


@pytest.fixture
async def unbuilt_client(  # type: ignore[no-untyped-def]
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(spa, "STATIC_ROOT", tmp_path / "never-built")
    app = create_app(settings)
    await app.state.database.create_all()
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await app.state.database.dispose()


class TestWhenBuilt:
    async def test_the_index_is_served(self, built_client: httpx2.AsyncClient) -> None:
        response = await built_client.get("/app/")

        assert response.status_code == 200
        assert "id=app" in response.text

    async def test_an_asset_is_served(self, built_client: httpx2.AsyncClient) -> None:
        response = await built_client.get("/app/assets/index-abc123.js")

        assert response.status_code == 200
        assert "altero" in response.text

    async def test_a_fingerprinted_asset_may_be_kept(
        self, built_client: httpx2.AsyncClient
    ) -> None:
        """Its name changes when its contents do, so there is nothing to recheck.

        This is what makes the interface's fonts cost one download rather than
        one conditional request per subset per page load.
        """
        response = await built_client.get("/app/assets/index-abc123.js")

        assert response.headers["cache-control"] == spa.ASSET_CACHE

    async def test_the_index_is_never_kept(self, built_client: httpx2.AsyncClient) -> None:
        """It is the file that names the current assets; a stale one pins the lot."""
        response = await built_client.get("/app/")

        assert "immutable" not in response.headers.get("cache-control", "")

    async def test_the_service_worker_is_checked_on_every_visit(
        self, built_client: httpx2.AsyncClient
    ) -> None:
        """Its bytes are how a deploy reaches an installed app; kept, they pin it."""
        response = await built_client.get("/app/sw.js")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["content-type"].startswith("text/javascript")

    async def test_the_manifest_is_served_as_one(self, built_client: httpx2.AsyncClient) -> None:
        response = await built_client.get("/app/manifest.webmanifest")

        assert response.headers["content-type"].startswith("application/manifest+json")
        assert response.headers["cache-control"] == "no-cache"

    async def test_a_client_side_route_falls_back_to_the_index(
        self, built_client: httpx2.AsyncClient
    ) -> None:
        """Reloading the page on /app/sign-in must not be a 404."""
        response = await built_client.get("/app/sign-in")

        assert response.status_code == 200
        assert "id=app" in response.text

    async def test_a_missing_asset_stays_a_404(self, built_client: httpx2.AsyncClient) -> None:
        """Answering HTML here would make a broken script look like a blank page."""
        response = await built_client.get("/app/assets/does-not-exist.js")

        assert response.status_code == 404

    async def test_the_v3_api_is_not_shadowed(self, built_client: httpx2.AsyncClient) -> None:
        """The interface must not capture the namespace the sync client uses."""
        assert (await built_client.get("/users/1/items")).status_code in (403, 404)
        assert (await built_client.get("/health")).status_code == 200
        assert (await built_client.get("/itemTypes")).status_code == 200

    async def test_the_web_api_is_not_shadowed(self, built_client: httpx2.AsyncClient) -> None:
        assert (await built_client.get("/web/config")).status_code == 200


class TestCompressedAssets:
    """The build writes Brotli and gzip copies beside each asset; the server picks one."""

    SOURCE = "console.log('altero');\n" * 200

    @pytest.fixture
    def compressed(self, built: Path) -> Path:
        import gzip

        asset = built / "assets" / "index-def456.js"
        asset.write_text(self.SOURCE)
        (built / "assets" / "index-def456.js.gz").write_bytes(gzip.compress(self.SOURCE.encode()))
        (built / "assets" / "index-def456.js.br").write_bytes(b"pretend brotli")
        return asset

    async def test_brotli_is_sent_to_a_browser_that_takes_it(
        self, built_client: httpx2.AsyncClient, compressed: Path
    ) -> None:
        response = await built_client.get(
            "/app/assets/index-def456.js", headers={"Accept-Encoding": "gzip, br"}
        )

        assert response.headers["content-encoding"] == "br"
        assert response.headers["content-type"].startswith("text/javascript")
        assert response.headers["vary"] == "Accept-Encoding"
        assert response.headers["cache-control"] == spa.ASSET_CACHE

    async def test_gzip_is_the_second_choice(
        self, built_client: httpx2.AsyncClient, compressed: Path
    ) -> None:
        response = await built_client.get(
            "/app/assets/index-def456.js", headers={"Accept-Encoding": "gzip"}
        )

        assert response.headers["content-encoding"] == "gzip"
        assert response.text == self.SOURCE

    async def test_an_encoding_refused_with_q_0_is_not_sent(
        self, built_client: httpx2.AsyncClient, compressed: Path
    ) -> None:
        response = await built_client.get(
            "/app/assets/index-def456.js", headers={"Accept-Encoding": "br;q=0, gzip"}
        )

        assert response.headers["content-encoding"] == "gzip"

    async def test_a_browser_that_takes_neither_gets_the_file(
        self, built_client: httpx2.AsyncClient, compressed: Path
    ) -> None:
        response = await built_client.get(
            "/app/assets/index-def456.js", headers={"Accept-Encoding": "identity"}
        )

        assert "content-encoding" not in response.headers
        assert response.text == self.SOURCE
        assert response.headers["vary"] == "Accept-Encoding"

    async def test_an_asset_with_no_copy_is_sent_as_it_is(
        self, built_client: httpx2.AsyncClient
    ) -> None:
        response = await built_client.get(
            "/app/assets/index-abc123.js", headers={"Accept-Encoding": "br, gzip"}
        )

        assert "content-encoding" not in response.headers
        assert "altero" in response.text


class TestWhenNotBuilt:
    async def test_the_server_still_starts_and_the_api_works(
        self, unbuilt_client: httpx2.AsyncClient
    ) -> None:
        """A checkout that has not run the frontend build is a normal state."""
        assert (await unbuilt_client.get("/health")).status_code == 200
        assert (await unbuilt_client.get("/web/config")).status_code == 200

    async def test_asking_for_the_interface_explains_itself(
        self, unbuilt_client: httpx2.AsyncClient
    ) -> None:
        response = await unbuilt_client.get("/app/")

        assert response.status_code == 503
        assert "npm run build" in response.text

    async def test_mounting_reports_that_it_did_nothing(self, tmp_path: Path) -> None:
        assert spa.mount_web_interface(FastAPI(), tmp_path / "nothing-here") is False
