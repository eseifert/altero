"""The original client constructs and sends requests over a real socket."""

import pytest
from tests.factories import make_api_key, make_user

from tools.compatibility.live import DesktopAPI


async def test_original_request_builder_and_headers_reach_the_server(
    session, socket_client, zotero_client
) -> None:
    await make_user(session)
    await make_api_key(session)
    api = DesktopAPI(zotero_client, str(socket_client.base_url), "P9NiFoyLeZu2bZNvvuQPDWsd")
    result = await api.call("getVersions", ["user", 1, "item", {"since": 0}])
    assert result["error"] is None
    assert result["value"] == {"libraryVersion": "0", "versions": {}}
    request = result["requests"][0]
    assert request["url"].endswith("/users/1/items?format=versions&since=0&includeTrashed=1")
    assert request["headers"]["Zotero-API-Version"] == "3"
    assert request["authenticated"] is True
    assert "Zotero-API-Key" not in request["headers"]


@pytest.mark.parametrize("status", [429, 503])
async def test_original_retry_logic_records_a_delay_then_succeeds(
    session, socket_client, zotero_client, status
) -> None:
    await make_user(session)
    await make_api_key(session)
    api = DesktopAPI(zotero_client, str(socket_client.base_url), "P9NiFoyLeZu2bZNvvuQPDWsd")
    result = await api.call(
        "getKeyInfo", [], faults=[{"status": status, "headers": {"Retry-After": "2"}}]
    )
    assert result["error"] is None
    assert result["value"]["userID"] == 1
    assert result["pauses"] == [2000]
    assert [request["status"] for request in result["requests"]] == [status, 200]
