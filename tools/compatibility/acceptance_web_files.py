"""Files put into a library by the browser reach both desktops, and so does a rename."""

import base64
import hashlib
import time

from tools.compatibility.acceptance_runtime import AcceptanceRun

PARENT = "WEBFILE2"
UPLOADED = b"%PDF-1.4\nUploaded in a browser\n%%EOF\n"
REPLACED = b"%PDF-1.4\nReplaced in a browser\n%%EOF\n"
FROM_DESKTOP = b"%PDF-1.4\nReplaced on a desktop\n%%EOF\n"
LINK = "https://example.org/papers/engine.pdf"


def encoded(content: bytes) -> str:
    return base64.b64encode(content).decode()


def downloads(requests: list[dict]) -> list[str]:
    """The requests among ``requests`` that fetched a file's bytes.

    A desktop receiving a rename still asks for the file: it looks for the
    new name before renaming its copy (`_checkAttachmentForDownload` runs
    first), marks the file for download, and drops the request once the
    redirect's headers match the copy it has. Only following the redirect
    fetches anything.
    """
    return [
        request["path"]
        for request in requests
        if request["method"] == "GET" and request["path"].startswith("/storage/download/")
    ]


async def web_files(run: AcceptanceRun) -> None:
    """Every file write the web interface makes, read back by the desktop's own sync.

    A file uploaded as a child attachment and one standalone, and a web link;
    both desktops download the bytes under the browser's name. A rename then
    renames each desktop's copy without fetching it again, and a replacement
    brings the new bytes. Afterwards a desktop replaces the file, and the
    browser's replacement stating the digest it had read is refused.
    """
    await run.phase(
        "A", [dict(action="create", key=PARENT, data=dict(itemType="book", title="Engines"))]
    )
    await run.phase("B")
    mtime = time.time_ns() // 1_000_000

    async with run.browser() as browser:

        async def upload(content: bytes, **query) -> dict:
            made = await browser.post(
                "/attachments",
                params=dict(mtime=mtime, **query),
                content=content,
                headers={"Content-Type": "application/pdf"},
            )
            made.raise_for_status()
            return made.json()

        child = (await upload(UPLOADED, filename="Bericht 東京.pdf", parentItem=PARENT))["key"]
        standalone = (await upload(REPLACED, filename="Loose.pdf"))["key"]
        linked = await browser.post(
            "/items",
            json=dict(itemType="attachment", linkMode="linked_url", url=LINK, parentItem=PARENT),
        )
        linked.raise_for_status()
        link = linked.json()["key"]

        left, right = await run.phase("A"), await run.phase("B")
        await run.converged(left, right)
        for snapshot in (left, right):
            assert snapshot["file_entries"][child] == {"Bericht 東京.pdf": encoded(UPLOADED)}, (
                "A desktop does not hold the browser's file under its name"
            )
            assert snapshot["file_entries"][standalone] == {"Loose.pdf": encoded(REPLACED)}
            assert snapshot["storage_states"][child] == "in_sync"
            items = {item["key"]: item for item in snapshot["items"]}
            assert items[child]["parentItem"] == PARENT
            assert items[child]["contentType"] == "application/pdf"
            assert items[child]["md5"] == hashlib.md5(UPLOADED).hexdigest()
            assert not items[standalone]["parentItem"]
            assert items[link]["linkMode"] == "linked_url"
            assert items[link]["url"] == LINK
            assert items[link]["parentItem"] == PARENT

        # A rename is a changed `filename`: each desktop renames its own copy.
        version = (await browser.get(f"/items/{child}")).json()["version"]
        renamed = await browser.patch(
            f"/items/{child}", json=dict(version=version, fields=dict(filename="Renamed 研究.pdf"))
        )
        renamed.raise_for_status()
        start = len(run.server.barrier.requests)
        left, right = await run.phase("A"), await run.phase("B")
        await run.converged(left, right)
        assert not downloads(run.server.barrier.requests[start:]), (
            "A desktop fetched a renamed file again"
        )
        for snapshot in (left, right):
            assert snapshot["file_entries"][child] == {"Renamed 研究.pdf": encoded(UPLOADED)}, (
                "A desktop did not rename its copy"
            )
            assert snapshot["storage_states"][child] == "in_sync"
            # The desktop would still not fetch bytes whose digest it holds,
            # so ask directly that the rename left the file's description alone.
            item = next(item for item in snapshot["items"] if item["key"] == child)
            assert (item["mtime"], item["md5"]) == (mtime, hashlib.md5(UPLOADED).hexdigest()), (
                "A rename changed what describes the bytes"
            )

        replaced = await browser.put(
            f"/items/{child}/file",
            params=dict(filename="Second draft.pdf", mtime=mtime + 1000),
            content=REPLACED,
            headers={
                "Content-Type": "application/pdf",
                "If-Match": hashlib.md5(UPLOADED).hexdigest(),
            },
        )
        replaced.raise_for_status()
        left, right = await run.phase("A"), await run.phase("B")
        await run.converged(left, right)
        for snapshot in (left, right):
            assert snapshot["files"][child] == encoded(REPLACED), (
                "A desktop kept the bytes the browser replaced"
            )
            assert snapshot["file_entries"][child] == {"Second draft.pdf": encoded(REPLACED)}
            assert snapshot["storage_states"][child] == "in_sync"

        # The race: the browser has read the digest; a desktop replaces the file first.
        source = run.root / "from-desktop.pdf"
        source.write_bytes(FROM_DESKTOP)
        await run.phase(
            "B",
            [dict(action="replace-file", key=child, path=str(source), mtime=mtime + 2000)],
        )
        refused = await browser.put(
            f"/items/{child}/file",
            params=dict(filename="Third draft.pdf", mtime=mtime + 3000),
            content=UPLOADED,
            headers={
                "Content-Type": "application/pdf",
                "If-Match": hashlib.md5(REPLACED).hexdigest(),
            },
        )
        assert refused.status_code == 412, refused.text
        served = await browser.get(f"/items/{child}/file")
        served.raise_for_status()
        assert served.content == FROM_DESKTOP, "The desktop's file was written over"

    await run.settled()
