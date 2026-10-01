"""Check API responses with the original permission and cache decision functions."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.factories import make_api_key, make_group, make_user

from altero.models import MemberPermission
from altero.services import admin, groups
from tools.compatibility.client import ZoteroClient

KEYS = {1: "AliceKeyAliceKeyAliceKey", 2: "BobKeyBobKeyBobKeyBobKey"}


@pytest.fixture
async def people(session: AsyncSession) -> None:
    for user_id, name in ((1, "alice"), (2, "bob")):
        await make_user(session, user_id=user_id, username=name)
        await make_api_key(
            session, user_id=user_id, key=KEYS[user_id], all_groups_read=True, all_groups_write=True
        )


@pytest.mark.parametrize("path", ["/groups/100", "/users/2/groups"])
@pytest.mark.parametrize(
    ("role", "editing", "files", "permission", "expected"),
    [
        ("member", "members", "members", "inherit", (True, True)),
        ("admin", "admins", "admins", "inherit", (True, True)),
        ("member", "admins", "members", "inherit", (False, False)),
        ("member", "members", "admins", "inherit", (True, False)),
        ("member", "members", "none", "inherit", (True, False)),
        ("member", "members", "members", "read", (False, False)),
    ],
)
async def test_the_client_sees_the_members_permission(
    people,
    session: AsyncSession,
    client: httpx.AsyncClient,
    zotero_client: ZoteroClient,
    path: str,
    role: str,
    editing: str,
    files: str,
    permission: str,
    expected: tuple[bool, bool],
) -> None:
    library = await make_group(session, members={2: role}, library_editing=editing)
    group = await groups.get_group(session, library)
    group.file_editing = files
    if permission != "inherit":
        bob = await admin.get_user_by_name(session, "bob")
        await groups.set_permission(session, library, bob, MemberPermission(permission).value)
    await session.commit()

    response = await client.get(path, headers={"Zotero-API-Key": KEYS[2]})
    assert response.status_code == 200
    body = response.json()
    data = (body[0] if isinstance(body, list) else body)["data"]
    decision = zotero_client.call("group_permissions", [data, 2])

    assert (decision["editable"], decision["filesEditable"]) == expected
    assert decision["isAdmin"] is (role == "admin")


@pytest.mark.parametrize("change", ["api", "command-line"])
async def test_an_existing_client_refreshes_changed_permissions(
    people,
    session: AsyncSession,
    socket_client: httpx.AsyncClient,
    zotero_client: ZoteroClient,
    change: str,
) -> None:
    library = await make_group(session, members={2: "member"})
    headers = {"Zotero-API-Key": KEYS[2]}
    initial_response = await socket_client.get("/groups/100", headers=headers)
    assert initial_response.status_code == 200
    initial = initial_response.json()
    key_response = await socket_client.get("/keys/current", headers=headers)
    assert key_response.status_code == 200
    cached = dict(
        id=100,
        version=initial["version"],
        **zotero_client.call("group_permissions", [initial["data"], 2]),
    )
    assert cached["editable"] is True

    if change == "api":
        response = await socket_client.put(
            "/groups/100/users/2",
            json={"permission": "read"},
            headers={"Zotero-API-Key": KEYS[1]},
        )
        assert response.status_code == 200
    else:
        await admin.set_group_member_permission(session, library, username="bob", permission="read")

    versions = await socket_client.get("/users/2/groups?format=versions", headers=headers)
    metadata = await socket_client.get("/groups/100", headers=headers)
    assert versions.status_code == metadata.status_code == 200
    fixtures = {
        "keyInfo": key_response.json(),
        "cached": [cached],
        "versions": versions.json(),
        "metadata": {"100": metadata.json()},
    }
    decision = zotero_client.call("group_refresh", [], fixtures=fixtures)
    assert decision["fetched"] == [100]
    assert decision["groups"][0]["editable"] is False

    # The same cached client ignores new metadata if its advertised version stays put.
    fixtures["versions"] = {"100": cached["version"]}
    stale = zotero_client.call("group_refresh", [], fixtures=fixtures)
    assert stale["fetched"] == []
    assert stale["groups"][0]["editable"] is True
