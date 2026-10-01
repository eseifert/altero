"""Client-visible writes, cache transitions and retry outcomes over HTTP."""

import pytest

from compatibility_tests.helpers import object_key


async def test_success_unchanged_failure_and_stale_versions(desktop):
    created = await desktop.upload([{"key": "ABCD2345", "itemType": "book", "title": "old"}])
    stored = created["results"]["successful"]["0"]["data"]
    result = await desktop.value(
        "uploadObjects",
        "POST",
        1,
        "item",
        [
            stored,
            {"key": "EFGH2345", "itemType": "book", "title": "new"},
            {"key": "JKLM2345", "itemType": "notAnItemType"},
        ],
    )
    assert result["libraryVersion"] == "2"
    assert result["results"]["unchanged"] == {"0": "ABCD2345"}
    assert set(result["results"]["successful"]) == {"1"}
    assert result["results"]["failed"]["2"]["code"] == 400
    again = await desktop.value("uploadObjects", "POST", 2, "item", [stored])
    assert again["libraryVersion"] == "2"
    stale = await desktop.call("uploadObjects", "POST", 1, "item", [{**stored, "title": "lost"}])
    assert stale["error"]["status"] == 412
    assert (await desktop.value("getVersions", "item", {}))["libraryVersion"] == "2"
    updated = await desktop.upload([{**stored, "title": "updated"}], 2)
    stale_object = await desktop.value("uploadObjects", "POST", 3, "item", [stored])
    assert stale_object["results"]["failed"]["0"]["code"] == 412
    assert updated["results"]["successful"]["0"]["data"]["title"] == "updated"


async def test_absent_properties_preserve_and_empty_properties_clear(desktop):
    await desktop.upload([{"key": "CNLLECT2", "name": "Research"}], kind="collection")
    properties = {
        "creators": [{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}],
        "tags": [{"tag": "研究", "type": 1}],
        "collections": ["CNLLECT2"],
        "relations": {"dc:relation": "https://example.org/related"},
    }
    await desktop.upload(
        [{"key": "ABCD2345", "itemType": "book", "title": "before", **properties}], 1
    )
    patched = await desktop.value(
        "uploadObjects", "POST", 2, "item", [{"key": "ABCD2345", "version": 2, "title": "after"}]
    )
    assert not patched["results"]["failed"]
    batches = await desktop.value("downloadObjects", "item", ["ABCD2345"])
    data = batches[0]["json"][0]["data"]
    for name, expected in properties.items():
        assert data[name] == expected
    cleared = await desktop.value(
        "uploadObjects",
        "POST",
        3,
        "item",
        [
            {
                "key": "ABCD2345",
                "version": 3,
                "creators": [],
                "tags": [],
                "collections": [],
                "relations": {},
            }
        ],
    )
    assert not cleared["results"]["failed"]
    data = (await desktop.value("downloadObjects", "item", ["ABCD2345"]))[0]["json"][0]["data"]
    for name in properties:
        empty = {} if name == "relations" else []
        assert data.get(name, empty) == empty
    assert data["title"] == "after"


async def test_trash_restore_delete_and_settings_deletion_reach_the_log(desktop):
    await desktop.upload([{"key": "ABCD2345", "itemType": "book", "title": "kept"}])
    await desktop.upload([{"key": "ABCD2345", "version": 1, "deleted": 1}], 1)
    trashed = (await desktop.value("downloadObjects", "item", ["ABCD2345"]))[0]["json"][0]
    assert trashed["data"]["deleted"] == 1
    await desktop.upload([{"key": "ABCD2345", "version": 2, "deleted": 0}], 2)
    restored = (await desktop.value("downloadObjects", "item", ["ABCD2345"]))[0]["json"][0]
    assert not restored["data"].get("deleted")
    assert await desktop.value("uploadDeletions", 3, "item", ["ABCD2345"]) == "4"
    assert (await desktop.value("getDeleted", 3))["deleted"]["items"] == ["ABCD2345"]
    assert (await desktop.value("getVersions", "item", {}))["versions"] == {}
    await desktop.value("uploadSettings", 4, {"tagColors": {"value": []}})
    assert await desktop.value("deleteSettings", 5, ["tagColors"]) == "6"
    assert (await desktop.value("getDeleted", 4))["deleted"]["settings"] == ["tagColors"]
    assert (await desktop.value("getSettings", 0))["settings"] == {}


@pytest.mark.parametrize("kind", ["collection", "search"])
async def test_deleted_collections_and_searches_reach_the_log(desktop, kind):
    payload = {"key": "ABCD2345", "name": "研究"}
    if kind == "search":
        payload["conditions"] = [{"condition": "title", "operator": "contains", "value": "研究"}]
    await desktop.upload([payload], kind=kind)
    assert await desktop.value("uploadDeletions", 1, kind, ["ABCD2345"]) == "2"
    plural = "searches" if kind == "search" else "collections"
    assert (await desktop.value("getDeleted", 1))["deleted"][plural] == ["ABCD2345"]


@pytest.mark.parametrize("count", [49, 50, 51])
async def test_write_batch_limit_is_visible_to_the_client(desktop, count):
    result = await desktop.call(
        "uploadObjects",
        "POST",
        0,
        "item",
        [{"key": object_key(i), "itemType": "book", "title": "東京"} for i in range(count)],
    )
    if count > 50:
        assert result["error"]["status"] == 413
        assert (await desktop.value("getVersions", "item", {}))["versions"] == {}
    else:
        assert result["error"] is None
        assert len(result["value"]["results"]["successful"]) == count
        assert result["value"]["libraryVersion"] == "1"
    assert result["requests"][0]["headers"]["Content-Encoding"] == "gzip"


async def test_a_write_committed_before_disconnect_can_be_recovered(desktop):
    payload = [{"key": "ABCD2345", "itemType": "book", "title": "only once"}]
    interrupted = await desktop.call(
        "uploadObjects", "POST", 0, "item", payload, faults=[{"mutation": "disconnect-after-write"}]
    )
    assert interrupted["error"] is not None
    retry = await desktop.call("uploadObjects", "POST", 0, "item", payload)
    assert retry["error"]["status"] == 412
    versions = await desktop.value("getVersions", "item", {})
    assert versions == {"libraryVersion": "1", "versions": {"ABCD2345": 1}}
    stored = (await desktop.value("downloadObjects", "item", ["ABCD2345"]))[0]["json"][0]["data"]
    settled = await desktop.value("uploadObjects", "POST", 1, "item", [stored])
    assert settled["results"]["unchanged"] == {"0": "ABCD2345"}
    assert settled["libraryVersion"] == "1"
