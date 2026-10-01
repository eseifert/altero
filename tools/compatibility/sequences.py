"""Seeded valid operation sequences, an independent state model and shrinking."""

import math
import random
from collections.abc import Awaitable, Callable
from typing import Any


def generate_sequence(seed: int, steps: int) -> list[dict]:
    if steps < 2:
        raise ValueError("A sequence needs at least two operations")
    rng = random.Random(seed)
    result = [{"action": "collection", "key": "CNLLECT2"}]
    state = {}
    for index in range(steps - 1):
        action = rng.choice(["create", "edit", "file", "trash", "delete"]) if state else "create"
        key = (
            rng.choice(sorted(state))
            if action != "create"
            else "SEQ" + f"{index + 2:05d}".translate(str.maketrans("01", "AB"))
        )
        operation = {"action": action, "key": key}
        if action == "create":
            state[key] = {"filed": False, "deleted": False}
        elif action == "delete":
            del state[key]
        elif action in {"file", "trash"}:
            field = "filed" if action == "file" else "deleted"
            state[key][field] = not state[key][field]
            operation["value"] = state[key][field]
        if action in {"create", "edit"}:
            operation["title"] = f"seed {seed}, step {index}: Über 東京"
        result.append(operation)
    return result


def valid_sequence(operations: list[dict]) -> bool:
    keys, collection = set(), False
    for operation in operations:
        action, key = operation["action"], operation["key"]
        if action == "collection":
            if collection:
                return False
            collection = True
        elif action == "create":
            if key in keys:
                return False
            keys.add(key)
        else:
            if key not in keys or (action == "file" and not collection):
                return False
            if action == "delete":
                keys.remove(key)
    return True


async def check_sequence(desktop: Any, operations: list[dict]) -> None:
    """Check state after each operation, never construct expected state from results."""
    assert valid_sequence(operations), "Invalid sequence"
    state, deleted, version = {}, set(), 0
    for index, operation in enumerate(operations):
        action, key = operation["action"], operation["key"]
        if action == "collection":
            await desktop.upload([{"key": key, "name": "Research"}], version, kind="collection")
        elif action == "delete":
            await desktop.value("uploadDeletions", version, "item", [key])
            del state[key]
            deleted.add(key)
        else:
            if action == "create":
                state[key] = {"title": operation["title"], "collections": [], "deleted": False}
                payload = {"key": key, "itemType": "book", "title": operation["title"]}
            else:
                payload = {"key": key, "version": state[key]["version"]}
                if action == "edit":
                    state[key]["title"] = payload["title"] = operation["title"]
                elif action == "file":
                    state[key]["collections"] = payload["collections"] = (
                        ["CNLLECT2"] if operation["value"] else []
                    )
                elif action == "trash":
                    state[key]["deleted"] = payload["deleted"] = operation["value"]
                else:
                    raise ValueError(f"Unknown sequence operation: {action}")
            await desktop.upload([payload], version)
            state[key]["version"] = version + 1
        version = index + 1
        versions = await desktop.value("getVersions", "item", {})
        assert int(versions["libraryVersion"]) == version, (index, "watermark")
        assert versions["versions"] == {key: value["version"] for key, value in state.items()}, (
            index,
            "versions",
        )
        batches = await desktop.value("downloadObjects", "item", sorted(state))
        received = {item["key"]: item["data"] for batch in batches for item in batch["json"]}
        assert set(received) == set(state), (index, "keys")
        for key, expected in state.items():
            for field, value in expected.items():
                assert received[key].get(field, False) == value, (index, key, field)
        log = await desktop.value("getDeleted", 0)
        assert set(log["deleted"]["items"]) == deleted, (index, "deletions")


async def minimize(steps: list, fails: Callable[[list], Awaitable[bool]]) -> list:
    """Delta debugging: the predicate must reject invalid or unrelated failures."""
    current, parts = list(steps), 2
    while len(current) >= 2:
        width = math.ceil(len(current) / parts)
        for start in range(0, len(current), width):
            candidate = current[:start] + current[start + width :]
            if await fails(candidate):
                current, parts = candidate, max(2, parts - 1)
                break
        else:
            if parts >= len(current):
                break
            parts = min(len(current), parts * 2)
    return current
