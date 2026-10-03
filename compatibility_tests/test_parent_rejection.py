"""A rejected new parent cannot leave a child or discard unrelated success."""

import httpx

from tools.compatibility.runtime import disposable_server


async def test_server_validates_corrupted_parent_and_rejects_dependent_child(tmp_path):
    async with disposable_server(tmp_path / "server") as server:
        server.barrier.arm(
            "POST", "/users/1/items", rewrite_item={"key": "PARENT23", "itemType": "invalid"}
        )
        server.barrier.release.set()
        async with httpx.AsyncClient(
            base_url=server.url, headers={"Zotero-API-Key": server.key}
        ) as client:
            result = (
                await client.post(
                    "/users/1/items",
                    json=[
                        dict(key="PARENT23", itemType="book", title="Parent"),
                        dict(
                            key="CHILD234",
                            itemType="note",
                            parentItem="PARENT23",
                            note="<p>child</p>",
                        ),
                        dict(key="SUCCESS2", itemType="book", title="Unrelated"),
                    ],
                )
            ).json()
            assert set(result["failed"]) == {"0", "1"}
            assert result["failed"]["0"]["code"] == 400
            assert result["failed"]["1"]["code"] == 404
            assert list(result["successful"]) == ["2"]
            assert (await client.get("/users/1/items/PARENT23")).status_code == 404
            assert (await client.get("/users/1/items/CHILD234")).status_code == 404
