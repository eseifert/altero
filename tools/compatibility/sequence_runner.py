"""Persist generated failures and shrink them against fresh disposable servers."""

from pathlib import Path

from tools.compatibility.client import CompatibilityError, ZoteroClient
from tools.compatibility.library import LibraryReplay
from tools.compatibility.live import DesktopAPI
from tools.compatibility.runtime import disposable_server
from tools.compatibility.sequences import check_sequence, minimize, valid_sequence


def invariant_identity(detail, model):
    """Keep object family, key and field; a different state error is not a reproducer."""
    if not isinstance(detail, tuple):
        return str(detail)
    return list(detail[1:]) if model == "protocol" else detail[-1]


async def run_sequence(
    client: ZoteroClient, operations: list[dict], root: Path, *, model="items"
) -> dict:
    from tools.compatibility.protocol_sequences import (
        check_protocol_sequence,
        valid_protocol_sequence,
    )

    if model not in {"items", "protocol"}:
        raise CompatibilityError("Unknown sequence model")
    validate = valid_protocol_sequence if model == "protocol" else valid_sequence
    if not validate(operations):
        raise CompatibilityError("Cannot replay an invalid or ineffective operation sequence")
    root.mkdir(parents=True, exist_ok=False)
    trial = 0

    async def attempt(steps):
        nonlocal trial
        if not validate(steps):
            return None
        trial += 1
        async with disposable_server(root / f"trial-{trial}") as server:
            desktop = LibraryReplay(DesktopAPI(client, server.url, server.key), "user", 1)
            try:
                if model == "protocol":
                    from sqlalchemy import update

                    from altero.models import ApiKey

                    assert server.session_factory is not None
                    alternate = "SequenceAlternateKey23456"
                    async with server.session_factory() as session:
                        session.add(
                            ApiKey(
                                key=alternate,
                                user_id=1,
                                name="Sequence peer",
                                library_read=True,
                                library_write=True,
                                files_read=True,
                                notes_read=True,
                            )
                        )
                        await session.commit()
                    peer = LibraryReplay(DesktopAPI(client, server.url, alternate), "user", 1)

                    async def change(actor, allowed):
                        assert server.session_factory is not None
                        async with server.session_factory() as session:
                            await session.execute(
                                update(ApiKey)
                                .where(ApiKey.key == (server.key if actor == "A" else alternate))
                                .values(library_write=allowed)
                            )
                            await session.commit()

                    await check_protocol_sequence(desktop, steps, peer=peer, access_change=change)
                else:
                    await check_sequence(desktop, steps)
            except AssertionError as error:
                detail = error.args[0] if error.args else "assertion"
                invariant = invariant_identity(detail, model)
                return {"invariant": invariant, "detail": repr(detail)}
        return None

    failure = await attempt(operations)
    result = {
        "passed": failure is None,
        "operations": operations,
        "failure": failure,
        "model": model,
    }
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
