"""These ordinary assertions pass intact and fail under named protocol mutations."""

from tests.factories import make_api_key, make_group, make_user

from compatibility_tests.helpers import KEY
from tools.compatibility.live import DesktopAPI


async def test_versions(desktop):
    await desktop.upload([{"key": key, "itemType": "book"} for key in ("ABCD2345", "EFGH2345")])
    result = await desktop.value("getVersions", "item", {})
    assert int(result["libraryVersion"]) > 0
    assert set(result["versions"]) == {"ABCD2345", "EFGH2345"}


async def test_write_report(desktop):
    result = await desktop.value(
        "uploadObjects", "POST", 0, "item", [{"key": "ABCD2345", "itemType": "book"}]
    )
    assert set(result["results"].get("successful", {})) == {"0"}


async def test_deletion(desktop):
    await desktop.upload([{"key": "ABCD2345", "itemType": "book"}])
    await desktop.value("uploadDeletions", 1, "item", ["ABCD2345"])
    result = await desktop.value("getDeleted", 0)
    assert result["deleted"].get("items") == ["ABCD2345"]


async def test_clearing(desktop):
    await desktop.upload([{"key": "ABCD2345", "itemType": "book", "tags": [{"tag": "研究"}]}])
    await desktop.upload([{"key": "ABCD2345", "version": 1, "tags": []}], 1)
    result = await desktop.value("downloadObjects", "item", ["ABCD2345"])
    assert result[0]["json"][0]["data"]["tags"] == []


async def test_roster(session, socket_client, zotero_client):
    await make_user(session)
    await make_user(session, user_id=2, username="bob")
    await make_group(session, members={2: "member"})
    await make_api_key(session, all_groups_read=True)
    api = DesktopAPI(zotero_client, str(socket_client.base_url), KEY)
    result = await api.call("getGroup", [100])
    assert result["error"] is None
    decision = zotero_client.call("group_permissions", [result["value"]["data"], 2])
    assert decision["editable"] is True
