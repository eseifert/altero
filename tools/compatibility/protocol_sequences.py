"""Original desktop API replay against an independent graph model."""

import base64
import copy

from tools.compatibility.library import LibraryReplay
from tools.compatibility.live import DesktopAPI
from tools.compatibility.protocol_generate import (
    generate_protocol_sequence as generate_protocol_sequence,
)
from tools.compatibility.protocol_model import ProtocolModel
from tools.compatibility.protocol_model import valid_protocol_sequence as valid_protocol_sequence
from tools.compatibility.storage import DesktopStorage


async def check_protocol_sequence(
    desktop: LibraryReplay, operations: list[dict], *, peer=None, access_change=None
) -> None:
    """Replay API methods; the model specifies state independently of returned JSON."""
    if not valid_protocol_sequence(operations):
        raise ValueError("Invalid or ineffective protocol sequence")
    clients = {
        "A": desktop,
        "B": peer
        or LibraryReplay(
            DesktopAPI(desktop.api.client, desktop.api.base_url, desktop.api.key),
            desktop.kind,
            desktop.id,
        ),
    }
    model = ProtocolModel()
    for index, operation in enumerate(operations):
        action, actor = operation["action"], operation.get("client", "A")
        caller = clients[actor]
        before = copy.deepcopy(model)
        model.apply(operation)
        key = operation.get("key")
        if action in before.objects:
            payload = dict(key=key, **operation["data"])
            if key in before.objects[action]:
                payload["version"] = before.objects[action][key]["version"]
            await caller.upload([payload], before.version, kind=action)
        elif action == "delete":
            await caller.value(
                "uploadDeletions", before.version, operation.get("kind", "item"), [key]
            )
        elif action == "setting":
            if operation["value"] is None:
                await caller.value("deleteSettings", before.version, [operation["name"]])
            else:
                await caller.value(
                    "uploadSettings",
                    before.version,
                    {operation["name"]: dict(value=operation["value"])},
                )
        elif action == "fulltext":
            value = model.fulltext[key]
            result = await caller.value(
                "setFullTextForItems",
                before.version,
                [dict(key=key, **{k: v for k, v in value.items() if k != "version"})],
            )
            assert not result["results"]["failed"], (index, "fulltext-upload")
        elif action == "file":
            assert isinstance(key, str)
            storage = DesktopStorage(caller.api.client, caller.api)
            previous = before.objects["item"][key].get("md5")
            result = await storage.transfer(
                "upload",
                caller.kind,
                caller.id,
                key,
                base64.b64decode(operation["content"]),
                mtime=operation["mtime"],
                synced_hash=previous,
            )
            assert result["error"] is None, (index, "file-upload", result["error"])
        elif action == "access":
            if access_change is None:
                raise ValueError("Credential operations need a real permission controller")
            await access_change(actor, operation["value"])
            if not operation["value"]:
                denied = await caller.call(
                    "uploadSettings", before.version, {"tagColors": dict(value=[])}
                )
                assert denied["error"], (index, "permission")
                assert denied["error"]["status"] == 403, (index, "permission")
        elif action == "flush":
            queued = before.pending[actor]
            payload = [dict(key=p["key"], version=p["version"], **p["data"]) for p in queued]
            result = await caller.call("uploadObjects", "POST", queued[0]["base"], "item", payload)
            if queued[0]["base"] != before.version:
                assert result["error"], (index, "stale-precondition")
                assert result["error"]["status"] == 412, (
                    index,
                    "stale-precondition",
                )
                payload = [
                    dict(
                        key=p["key"],
                        version=before.objects["item"][p["key"]]["version"],
                        **p["data"],
                    )
                    for p in queued
                ]
                await caller.upload(payload, before.version)
            else:
                assert result["error"] is None, (index, "flush")
                assert not result["value"]["results"]["failed"], (index, "flush")
        await assert_protocol_state(desktop, model, index)


async def assert_protocol_state(desktop: LibraryReplay, model: ProtocolModel, index: int) -> None:
    for kind, expected in model.objects.items():
        listing = await desktop.value("getVersions", kind, {})
        assert int(listing["libraryVersion"]) == model.version, (index, "watermark")
        assert listing["versions"] == {k: v["version"] for k, v in expected.items()}, (
            index,
            kind,
            "versions",
        )
        batches = await desktop.value("downloadObjects", kind, sorted(expected))
        actual = {value["key"]: value["data"] for batch in batches for value in batch["json"]}
        assert actual.keys() == expected.keys(), (index, kind, "keys")
        for key, fields in expected.items():
            for field, value in fields.items():
                received = actual[key].get(
                    field,
                    []
                    if field in {"tags", "collections", "creators"}
                    else {}
                    if field == "relations"
                    else False,
                )
                if field == "mtime":
                    received = int(received)
                assert received == value, (index, kind, key, field, "object-state")
    assert (await desktop.value("getSettings", 0))["settings"] == model.settings, (
        index,
        "settings",
    )
    deleted = (await desktop.value("getDeleted", 0))["deleted"]
    for kind, keys in model.deleted.items():
        assert set(deleted[kind]) == keys, (index, kind, "deletion-log")
    versions = await desktop.value("getFullTextVersions", 0)
    assert versions["versions"] == {k: v["version"] for k, v in model.fulltext.items()}, (
        index,
        "fulltext-versions",
    )
    for key, expected in model.fulltext.items():
        result = await desktop.value("getFullTextForItem", key)
        assert int(result["version"]) == expected["version"], (index, "fulltext-version")
        assert result["data"] == {k: v for k, v in expected.items() if k != "version"}, (
            index,
            "fulltext-state",
        )
    for key, expected in model.files.items():
        storage = DesktopStorage(desktop.api.client, desktop.api)
        result = await storage.transfer(
            "download", desktop.kind, desktop.id, key, b"", mtime=expected["mtime"]
        )
        assert result["error"] is None, (index, "file-download")
        assert result["value"]["processed"]["bytes"] == expected["content"], (index, "file-bytes")
