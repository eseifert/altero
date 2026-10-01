"""ZFS settles missing files using the actual file endpoint."""

from tools.compatibility.storage import DesktopStorage


async def test_zfs_treats_a_missing_remote_file_as_settled(desktop, zotero_client):
    await desktop.upload(
        [{"key": "ABCD2345", "itemType": "attachment", "linkMode": "imported_file"}]
    )
    storage = DesktopStorage(zotero_client, desktop.api)
    result = await storage.transfer("download", desktop.kind, desktop.id, "ABCD2345", b"missing")
    assert result["error"] is None
    assert result["requests"][0]["status"] == 404
    assert result["value"]["item"]["syncState"] == "in_sync"
