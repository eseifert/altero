"""Generated graphs must stay valid and assertions must detect state loss."""

import pytest

from tools.compatibility.protocol_sequences import ProtocolModel, generate_protocol_sequence


async def test_protocol_oracle_detects_a_truncated_version_list_after_intact_baseline(desktop):
    from tools.compatibility.protocol_sequences import (
        assert_protocol_state,
        check_protocol_sequence,
    )

    operations = [
        dict(action="item", key="PARENT23", data=dict(itemType="book", title="Independent"))
    ]
    await check_protocol_sequence(desktop, operations)
    model = ProtocolModel()
    model.apply(operations[0])
    original = desktop.value

    async def changed(method, *args):
        value = await original(method, *args)
        if method == "getVersions" and args[0] == "item":
            value["versions"] = {}
        return value

    desktop.value = changed
    with pytest.raises(AssertionError, match="versions"):
        await assert_protocol_state(desktop, model, 0)


@pytest.mark.parametrize("seed", [4, 14, 91])
async def test_protocol_graph_sequence_over_original_desktop_api(desktop, seed, session):
    from sqlalchemy import update
    from tests.factories import make_api_key

    from altero.models import ApiKey
    from tools.compatibility.library import LibraryReplay
    from tools.compatibility.live import DesktopAPI
    from tools.compatibility.protocol_sequences import check_protocol_sequence

    alternate = await make_api_key(
        session, key="SequenceAlternateKey23456", all_groups_read=True, all_groups_write=True
    )
    peer = LibraryReplay(
        DesktopAPI(desktop.api.client, desktop.api.base_url, alternate.key),
        desktop.kind,
        desktop.id,
    )

    async def change(actor, allowed):
        key = desktop.api.key if actor == "A" else peer.api.key
        await session.execute(
            update(ApiKey)
            .where(ApiKey.key == key)
            .values(library_write=allowed, all_groups_write=allowed)
        )
        await session.commit()

    await check_protocol_sequence(
        desktop, generate_protocol_sequence(seed, 48), peer=peer, access_change=change
    )
