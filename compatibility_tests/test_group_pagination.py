"""Account preferences call getGroups, whose Link parser needs every page."""

import pytest
from tests.factories import make_api_key, make_group, make_user

from tools.compatibility.live import DesktopAPI


@pytest.mark.parametrize("count", [0, 1, 27])
async def test_the_desktop_reads_every_group_page(session, socket_client, zotero_client, count):
    await make_user(session)
    await make_api_key(session, all_groups_read=True)
    for group_id in range(100, 100 + count):
        await make_group(session, group_id=group_id)
    api = DesktopAPI(zotero_client, str(socket_client.base_url), "P9NiFoyLeZu2bZNvvuQPDWsd")
    result = await api.call("getGroups", [1])
    assert result["error"] is None
    assert {g["id"] for g in result["value"]} == set(range(100, 100 + count))
    assert len(result["requests"]) == (2 if count > 25 else 1)
    assert all("link" in r["responseHeaders"] for r in result["requests"])
    versions = await api.call("getGroupVersions", [1])
    assert set(versions["value"]) == {str(i) for i in range(100, 100 + count)}
    assert (await api.call("getGroup", [9999]))["value"] is False
