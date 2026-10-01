"""Persist generated failures and shrink them against fresh disposable servers."""

from pathlib import Path

from tools.compatibility.client import ZoteroClient
from tools.compatibility.library import LibraryReplay
from tools.compatibility.live import DesktopAPI
from tools.compatibility.runtime import disposable_server
from tools.compatibility.sequences import check_sequence, minimize, valid_sequence


async def run_sequence(client: ZoteroClient, operations: list[dict], root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    trial = 0

    async def attempt(steps):
        nonlocal trial
        if not valid_sequence(steps):
            return None
        trial += 1
        async with disposable_server(root / f"trial-{trial}") as server:
            desktop = LibraryReplay(DesktopAPI(client, server.url, server.key), "user", 1)
            try:
                await check_sequence(desktop, steps)
            except AssertionError as error:
                detail = error.args[0] if error.args else "assertion"
                invariant = detail[-1] if isinstance(detail, tuple) else "protocol"
                return {"invariant": invariant, "detail": repr(detail)}
        return None

    failure = await attempt(operations)
    result = {"passed": failure is None, "operations": operations, "failure": failure}
    if failure:

        async def reproduces(steps):
            observed = await attempt(steps)
            return observed is not None and observed["invariant"] == failure["invariant"]

        reduced = await minimize(operations, reproduces)
        # Confirm the final reproducer independently, even if nothing was removed.
        confirmed = await attempt(reduced)
        assert confirmed is not None
        assert confirmed["invariant"] == failure["invariant"]
        result["minimized"] = reduced
    result["trials"] = trial
    return result
