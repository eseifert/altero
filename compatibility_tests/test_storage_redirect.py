"""ZFS constructs authorization, upload and registration and reads redirects."""

import base64
import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest

from tools.compatibility.storage import DesktopStorage


@pytest.mark.parametrize("compressed", [False, True])
async def test_zfs_transfers_bytes_and_reads_redirect_metadata(desktop, zotero_client, compressed):
    original = b"<html>Research</html>" if compressed else b"%PDF-1.4 research"
    if compressed:
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("snapshot.html", original)
        content = buffer.getvalue()
    else:
        content = original
    await desktop.upload(
        [
            {
                "key": "ABCD2345",
                "itemType": "attachment",
                "linkMode": "imported_url" if compressed else "imported_file",
                "contentType": "text/html" if compressed else "application/pdf",
                "filename": "snapshot.html" if compressed else "research.pdf",
            }
        ]
    )
    storage = DesktopStorage(zotero_client, desktop.api)
    options = {"original": original} if compressed else {}
    uploaded = await storage.transfer(
        "upload", desktop.kind, desktop.id, "ABCD2345", content, **options
    )
    assert uploaded["error"] is None, uploaded
    assert [r["status"] for r in uploaded["requests"]] == [200, 201, 204]
    assert uploaded["requests"][1]["authenticated"] is False
    assert uploaded["value"]["item"]["syncState"] == "in_sync"
    assert int(uploaded["value"]["item"]["version"]) == 2
    downloaded = await storage.transfer(
        "download", desktop.kind, desktop.id, "ABCD2345", content, **options
    )
    assert downloaded["error"] is None, downloaded["diagnostics"]
    assert [r["status"] for r in downloaded["requests"]] == [302, 200]
    assert downloaded["requests"][1]["authenticated"] is False
    assert downloaded["value"]["processed"] == {
        "mtime": 1785701798544,
        "md5": hashlib.md5(original, usedforsecurity=False).hexdigest(),
        "compressed": compressed,
        "bytes": base64.b64encode(content).decode(),
    }
    cached = await storage.transfer(
        "download",
        desktop.kind,
        desktop.id,
        "ABCD2345",
        content,
        local_mtime=1785701798544,
        **options,
    )
    assert cached["error"] is None
    assert len(cached["requests"]) == 1
    assert cached["value"]["processed"] is None
    assert cached["value"]["item"]["syncState"] == "in_sync"
    existing = await storage.transfer(
        "authorize",
        desktop.kind,
        desktop.id,
        "ABCD2345",
        content,
        synced_hash=hashlib.md5(original, usedforsecurity=False).hexdigest(),
        **options,
    )
    assert existing["error"] is None
    assert existing["value"]["result"]["exists"] == 1
