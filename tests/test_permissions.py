"""Access control, exercised directly against the service layer."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, NotFoundError
from altero.models import ApiKeyGroupAccess, LibraryType
from altero.services.auth import (
    Credential,
    authenticate,
    get_access,
    get_library,
    require_read,
    require_write,
)
from tests.factories import make_api_key, make_group, make_library, make_user


async def test_authenticate_returns_none_without_a_credential(session: AsyncSession) -> None:
    assert await authenticate(session, None) is None
    assert await authenticate(session, "") is None


async def test_authenticate_finds_a_known_key(session: AsyncSession) -> None:
    await make_user(session)
    stored = await make_api_key(session, key="KNOWNKEY")

    credential = await authenticate(session, "KNOWNKEY")

    assert credential is not None
    assert credential.key_id == stored.id
    assert credential.user_id == stored.user_id


async def test_authenticate_rejects_an_unknown_key(session: AsyncSession) -> None:
    with pytest.raises(ForbiddenError, match="Invalid key"):
        await authenticate(session, "NOSUCHKEY")


async def test_get_library_finds_a_personal_library(session: AsyncSession) -> None:
    await make_user(session, user_id=42)

    library = await get_library(session, LibraryType.USER, 42)

    assert library.owner_id == 42
    assert library.type is LibraryType.USER


async def test_get_library_rejects_an_unknown_library(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await get_library(session, LibraryType.USER, 999)


async def test_a_user_library_is_not_reachable_via_the_group_prefix(session: AsyncSession) -> None:
    await make_user(session, user_id=7)

    with pytest.raises(NotFoundError):
        await get_library(session, LibraryType.GROUP, 7)


async def test_an_owner_key_reads_and_writes_its_personal_library(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    api_key = await make_api_key(session, user_id=1, library_read=True, library_write=True)

    access = await get_access(session, library, Credential.from_api_key(api_key))

    assert access.read
    assert access.write


async def test_a_read_only_key_cannot_write(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    api_key = await make_api_key(session, user_id=1, library_read=True, library_write=False)

    access = await get_access(session, library, Credential.from_api_key(api_key))

    assert access.read
    assert not access.write


async def test_write_permission_requires_read_permission(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    api_key = await make_api_key(session, user_id=1, library_read=False, library_write=True)

    access = await get_access(session, library, Credential.from_api_key(api_key))

    assert not access.read
    assert not access.write


async def test_a_key_cannot_reach_another_users_library(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    await make_user(session, user_id=2, username="other")
    other_library = await get_library(session, LibraryType.USER, 2)
    api_key = await make_api_key(session, user_id=1)

    access = await get_access(session, other_library, Credential.from_api_key(api_key))

    assert not access.read
    assert not access.write


async def test_a_public_library_is_readable_without_a_key(session: AsyncSession) -> None:
    library = await make_library(session, owner_id=5, public=True)

    access = await get_access(session, library, None)

    assert access.read
    assert not access.write


async def test_a_private_library_is_not_readable_without_a_key(session: AsyncSession) -> None:
    library = await make_library(session, owner_id=5, public=False)

    assert not (await get_access(session, library, None)).read


async def test_a_public_library_of_another_user_stays_read_only(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    other = await make_library(session, owner_id=2, public=True)
    api_key = await make_api_key(session, user_id=1)

    access = await get_access(session, other, Credential.from_api_key(api_key))

    assert access.read
    assert not access.write


async def test_group_access_falls_back_to_the_all_groups_defaults(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    group = await make_group(session, group_id=100, owner_id=1)
    api_key = await make_api_key(session, user_id=1, all_groups_read=True, all_groups_write=True)

    access = await get_access(session, group, Credential.from_api_key(api_key))

    assert access.read
    assert access.write


async def test_a_key_without_group_access_cannot_read_a_group(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    group = await make_group(session, group_id=100, owner_id=1)
    api_key = await make_api_key(session, user_id=1, all_groups_read=False)

    assert not (await get_access(session, group, Credential.from_api_key(api_key))).read


async def test_a_per_group_override_beats_the_defaults(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    group = await make_group(session, group_id=100, owner_id=1)
    api_key = await make_api_key(session, user_id=1, all_groups_read=False, all_groups_write=False)
    session.add(
        ApiKeyGroupAccess(api_key_id=api_key.id, library_id=group.id, read=True, write=True)
    )
    await session.commit()
    await session.refresh(api_key)

    access = await get_access(session, group, Credential.from_api_key(api_key))

    assert access.read
    assert access.write


async def test_an_override_can_also_withhold_access(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    group = await make_group(session, group_id=100, owner_id=1)
    api_key = await make_api_key(session, user_id=1, all_groups_read=True, all_groups_write=True)
    session.add(
        ApiKeyGroupAccess(api_key_id=api_key.id, library_id=group.id, read=False, write=False)
    )
    await session.commit()
    await session.refresh(api_key)

    assert not (await get_access(session, group, Credential.from_api_key(api_key))).read


async def test_require_read_raises_when_access_is_missing(session: AsyncSession) -> None:
    library = await make_library(session, owner_id=5)

    with pytest.raises(ForbiddenError):
        await require_read(session, library, None)


async def test_require_write_raises_for_a_read_only_key(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    api_key = await make_api_key(session, user_id=1, library_write=False)

    await require_read(session, library, Credential.from_api_key(api_key))
    with pytest.raises(ForbiddenError):
        await require_write(session, library, Credential.from_api_key(api_key))


async def test_a_key_carries_its_notes_and_files_permissions(session: AsyncSession) -> None:
    """The two permissions a key has always stored and nothing ever read."""
    await make_user(session, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    api_key = await make_api_key(session, user_id=1, notes_read=False, files_read=False)

    access = await get_access(session, library, Credential.from_api_key(api_key))

    assert access.read
    assert not access.notes
    assert not access.files


async def test_notes_and_files_follow_read_access(session: AsyncSession) -> None:
    """Neither is a way in of its own: both are narrowings of reading."""
    await make_user(session, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    api_key = await make_api_key(session, user_id=1, library_read=False, library_write=False)

    access = await get_access(session, library, Credential.from_api_key(api_key))

    assert not access.notes
    assert not access.files


async def test_a_published_library_keeps_its_notes_readable(session: AsyncSession) -> None:
    """A key must not see less of a published library than a stranger does.

    Upstream falls back to the owner's privacy settings when a key states no
    permission of its own, so what has been published stays published. altero
    has one flag for the whole library, so the fallback is that flag.
    """
    await make_user(session, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.public = True
    await session.commit()
    api_key = await make_api_key(session, user_id=1, notes_read=False, files_read=False)

    access = await get_access(session, library, Credential.from_api_key(api_key))

    assert access.notes
    # Files are not part of what publishing a library gives away: upstream's
    # privacy settings have no key for them, so `canAccess(files)` is false.
    assert not access.files


async def test_an_anonymous_reader_gets_notes_but_no_files(session: AsyncSession) -> None:
    library = await make_library(session, owner_id=5, public=True)

    access = await get_access(session, library, None)

    assert access.read
    assert access.notes
    assert not access.files


async def test_a_stranger_to_a_public_group_gets_no_files(session: AsyncSession) -> None:
    """ "Only members have file access" -- `Zotero_Permissions::canAccess`."""
    await make_user(session, user_id=1)
    await make_user(session, user_id=2, username="stranger")
    group = await make_group(session, group_id=100, owner_id=1, public=True)
    api_key = await make_api_key(session, user_id=2, all_groups_read=True, all_groups_write=True)

    access = await get_access(session, group, Credential.from_api_key(api_key))

    assert access.read
    assert not access.files


async def test_a_member_of_a_group_may_reach_its_files(session: AsyncSession) -> None:
    await make_user(session, user_id=1)
    group = await make_group(session, group_id=100, owner_id=1)
    api_key = await make_api_key(session, user_id=1, all_groups_read=True, all_groups_write=True)

    access = await get_access(session, group, Credential.from_api_key(api_key))

    assert access.read
    assert access.files
