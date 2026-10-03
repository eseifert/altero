"""Reconnect controls close actual sockets and never retain credential payloads."""

import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError

from tools.compatibility.runtime import disposable_server


async def test_socket_close_and_resubscription_are_observable_without_api_keys(tmp_path):
    async with disposable_server(tmp_path / "server") as server:
        async with connect(server.url.replace("http:", "ws:") + "/stream") as socket:
            assert json.loads(await socket.recv())["event"] == "connected"
            await socket.send(
                json.dumps(
                    dict(action="createSubscriptions", subscriptions=[dict(apiKey=server.key)])
                )
            )
            assert json.loads(await socket.recv())["event"] == "subscriptionsCreated"
            await server.barrier.disconnect_websockets()
            with pytest.raises(ConnectionClosedError):
                await socket.recv()
        events = server.barrier.websocket_events
        assert [entry["event"] for entry in events] == [
            "accepted",
            "connected",
            "subscriptionsCreated",
            "closed",
        ]
        assert server.key not in str(events)
