"""Live notifications feed the original desktop streaming message handler."""

import asyncio
import json

import pytest
from websockets.asyncio.client import connect

from compatibility_tests.helpers import KEY


async def test_live_notifications_schedule_only_outdated_selected_libraries(desktop, zotero_client):
    messages = []
    async with connect(
        desktop.api.base_url.rstrip("/").replace("http:", "ws:") + "/stream"
    ) as socket:
        async with asyncio.timeout(10):
            messages.append(json.loads(await socket.recv()))
            await socket.send(
                json.dumps({"action": "createSubscriptions", "subscriptions": [{"apiKey": KEY}]})
            )
            messages.append(json.loads(await socket.recv()))
            await desktop.upload([{"key": "ABCD2345", "itemType": "book"}])
            changed = json.loads(await socket.recv())
            messages.append(changed)
            await socket.send(
                json.dumps({"action": "deleteSubscriptions", "subscriptions": [{"apiKey": KEY}]})
            )
            messages.append(json.loads(await socket.recv()))
    library = {"libraryID": desktop.id, "libraryVersion": 0}
    result = zotero_client.call(
        "streamer_connect",
        [],
        fixtures={"messages": messages, "libraries": {desktop.prefix: library}},
    )
    assert result["syncs"] == [{"background": True, "libraries": [desktop.id]}]
    assert result["ready"] is True
    assert result["subscriptions"] == []
    assert result["errors"] == []
    for options in ({"libraryVersion": 1}, {"skipped": True}):
        result = zotero_client.call(
            "streamer_connect",
            [],
            fixtures={"messages": [changed], "libraries": {desktop.prefix: library | options}},
        )
        assert result["syncs"] == []


@pytest.mark.parametrize(("code", "delays"), [(1006, [2000]), (4401, [])])
def test_original_reconnect_policy_uses_virtual_delay(zotero_client, code, delays):
    result = zotero_client.call(
        "streamer_connect",
        [],
        fixtures={"messages": [], "libraries": {}, "close": {"code": code, "reason": "test"}},
    )
    assert result["delays"] == delays
    assert result["updates"] == len(delays)
