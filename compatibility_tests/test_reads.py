"""Actual desktop API calls cover sync listing and download boundaries."""

import pytest
from tests.factories import make_api_key, make_user

from compatibility_tests.helpers import object_key
from tools.compatibility.live import DesktopAPI

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"


async def test_key_permissions_and_invalid_credentials(session, socket_client, zotero_client):
    await make_user(session)
    await make_api_key(session, library_write=False, notes_read=False, files_read=False)
    api = DesktopAPI(zotero_client, str(socket_client.base_url), KEY)
    result = await api.call("getKeyInfo", [])
    assert result["error"] is None
    assert result["value"]["access"]["user"] == {
        "library": True,
        "write": False,
        "notes": False,
        "files": False,
    }
    assert "key" not in result["value"]
    invalid = DesktopAPI(zotero_client, str(socket_client.base_url), "invalid-key")
    assert (await invalid.call("getKeyInfo", []))["value"] is False


@pytest.mark.parametrize("kind", ["item", "collection", "search"])
async def test_versions_downloads_and_incremental_reads(desktop, kind):
    payload = {
        "item": {"itemType": "book", "title": "Über 東京"},
        "collection": {"name": "Über 東京", "parentCollection": False},
        "search": {
            "name": "Über 東京",
            "conditions": [{"condition": "title", "operator": "contains", "value": "東京"}],
        },
    }[kind]
    written = await desktop.upload([{"key": "ABCD2345", "version": 0, **payload}], kind=kind)
    assert set(written["results"]["successful"]) == {"0"}
    versions = await desktop.value("getVersions", kind, {"since": 0})
    assert versions == {"libraryVersion": "1", "versions": {"ABCD2345": 1}}
    unchanged = await desktop.value("getVersions", kind, {"since": 1})
    assert unchanged["versions"] == {}
    batches = await desktop.value("downloadObjects", kind, ["ABCD2345", "ZZZZ9999"])
    assert len(batches) == 1
    assert [obj["key"] for obj in batches[0]["json"]] == ["ABCD2345"]
    assert await desktop.value("downloadObjects", kind, []) == []


@pytest.mark.parametrize("count", [99, 100, 101])
async def test_download_batches_preserve_every_key(desktop, count):
    keys = [object_key(i) for i in range(count)]
    version = 0
    for start in range(0, count, 50):
        upload = await desktop.upload(
            [
                {"key": key, "version": 0, "itemType": "book", "title": key}
                for key in keys[start : start + 50]
            ],
            version,
        )
        version = int(upload["libraryVersion"])
    result = await desktop.call("downloadObjects", "item", keys)
    assert result["error"] is None
    assert len(result["requests"]) == (1 if count <= 100 else 2)
    assert {obj["key"] for batch in result["value"] for obj in batch["json"]} == set(keys)
    assert set((await desktop.value("getVersions", "item", {}))["versions"]) == set(keys)
    assert set((await desktop.value("getKeys", {"target": "items"}))["keys"]) == set(keys)


async def test_parent_child_trash_and_top_listing(desktop):
    await desktop.upload(
        [
            {"key": "PARENT22", "itemType": "book", "title": "parent"},
            {"key": "CHILD222", "itemType": "note", "parentItem": "PARENT22", "note": "<p>子</p>"},
            {"key": "TRASH222", "itemType": "book", "title": "trash", "deleted": 1},
        ]
    )
    all_items = await desktop.value("getVersions", "item", {})
    assert set(all_items["versions"]) == {"PARENT22", "CHILD222", "TRASH222"}
    top = await desktop.value("getVersions", "item", {"top": True})
    assert set(top["versions"]) == {"PARENT22", "TRASH222"}
    batch = await desktop.value("downloadObjects", "item", ["CHILD222"])
    assert batch[0]["json"][0]["data"]["parentItem"] == "PARENT22"


async def test_settings_conditional_reads_and_empty_delete_log(desktop):
    empty = await desktop.value("getSettings", 0)
    assert empty == {"libraryVersion": "0", "settings": {}}
    written = await desktop.value(
        "uploadSettings", 0, {"tagColors": {"value": [{"name": "研究", "color": "#123456"}]}}
    )
    current = int(written["libraryVersion"])
    settings = await desktop.value("getSettings", 0)
    assert settings["settings"]["tagColors"]["value"][0]["name"] == "研究"
    assert await desktop.value("getSettings", current) is False
    assert (await desktop.value("getDeleted", 0))["deleted"] == {
        "items": [],
        "collections": [],
        "searches": [],
        "tags": [],
        "settings": [],
    }
