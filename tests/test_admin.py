"""Provisioning users, libraries and API keys."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.keys import API_KEY_ALPHABET, API_KEY_LENGTH, generate_api_key
from altero.models import LibraryType
from altero.services import admin
from altero.services.auth import get_library


class TestApiKeyGeneration:
    def test_a_generated_key_has_the_documented_shape(self) -> None:
        for _ in range(50):
            key = generate_api_key()
            assert len(key) == API_KEY_LENGTH
            assert set(key) <= set(API_KEY_ALPHABET)

    def test_generated_keys_differ(self) -> None:
        assert len({generate_api_key() for _ in range(50)}) == 50


class TestUsers:
    async def test_a_user_gets_a_personal_library(self, session: AsyncSession) -> None:
        user = await admin.create_user(session, username="octocat", display_name="Mona")

        library = await get_library(session, LibraryType.USER, user.id)

        assert user.username == "octocat"
        assert library.owner_id == user.id
        assert library.version == 0

    async def test_user_ids_are_assigned_in_sequence(self, session: AsyncSession) -> None:
        first = await admin.create_user(session, username="one")
        second = await admin.create_user(session, username="two")

        assert second.id > first.id

    async def test_an_explicit_id_is_honoured(self, session: AsyncSession) -> None:
        user = await admin.create_user(session, username="octocat", user_id=5000)

        assert user.id == 5000

    async def test_a_duplicate_username_is_rejected(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="octocat")

        with pytest.raises(InvalidInputError, match="already exists"):
            await admin.create_user(session, username="octocat")

    async def test_an_empty_username_is_rejected(self, session: AsyncSession) -> None:
        with pytest.raises(InvalidInputError):
            await admin.create_user(session, username="")


class TestApiKeys:
    async def test_a_key_is_issued_for_a_user(self, session: AsyncSession) -> None:
        user = await admin.create_user(session, username="octocat")

        key = await admin.create_api_key(session, username="octocat", name="laptop")

        assert key.user_id == user.id
        assert key.name == "laptop"
        assert len(key.key) == API_KEY_LENGTH

    async def test_permissions_are_settable(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="octocat")

        key = await admin.create_api_key(session, username="octocat", name="read-only", write=False)

        assert key.library_read
        assert not key.library_write

    async def test_a_key_for_an_unknown_user_is_rejected(self, session: AsyncSession) -> None:
        with pytest.raises(NotFoundError):
            await admin.create_api_key(session, username="nobody", name="x")

    async def test_keys_can_be_listed(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="octocat")
        await admin.create_api_key(session, username="octocat", name="one")
        await admin.create_api_key(session, username="octocat", name="two")

        listed = await admin.list_api_keys(session)

        assert sorted(key.name for key in listed) == ["one", "two"]

    async def test_a_key_can_be_revoked(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="octocat")
        key = await admin.create_api_key(session, username="octocat", name="one")

        await admin.revoke_api_key(session, key.key)

        assert await admin.list_api_keys(session) == []

    async def test_revoking_an_unknown_key_is_rejected(self, session: AsyncSession) -> None:
        with pytest.raises(NotFoundError):
            await admin.revoke_api_key(session, "nosuchkey")


class TestLibraryVersion:
    """Lifting a library's counter over what its clients already remember.

    A client refuses to move its stored library version backwards, so a library
    recreated from an empty database — or restored from an export — locks out
    every client that synced against the original. Raising the counter past
    theirs is the way back, and the reason the version may only ever go up.
    """

    async def test_the_version_can_be_raised(self, session: AsyncSession) -> None:
        user = await admin.create_user(session, username="octocat")

        library = await admin.set_library_version(
            session, library_type=LibraryType.USER, owner_id=user.id, version=100
        )

        assert library.version == 100
        assert (await get_library(session, LibraryType.USER, user.id)).version == 100

    async def test_lowering_the_version_is_refused(self, session: AsyncSession) -> None:
        user = await admin.create_user(session, username="octocat")
        await admin.set_library_version(
            session, library_type=LibraryType.USER, owner_id=user.id, version=100
        )

        with pytest.raises(InvalidInputError, match="cannot be lowered"):
            await admin.set_library_version(
                session, library_type=LibraryType.USER, owner_id=user.id, version=99
            )

        assert (await get_library(session, LibraryType.USER, user.id)).version == 100

    async def test_the_current_version_is_accepted(self, session: AsyncSession) -> None:
        user = await admin.create_user(session, username="octocat")

        library = await admin.set_library_version(
            session, library_type=LibraryType.USER, owner_id=user.id, version=0
        )

        assert library.version == 0

    async def test_a_group_library_can_be_raised(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="octocat")
        group = await admin.create_group(session, name="Research", owner_username="octocat")

        library = await admin.set_library_version(
            session, library_type=LibraryType.GROUP, owner_id=group.owner_id, version=42
        )

        assert library.version == 42

    async def test_an_unknown_library_is_rejected(self, session: AsyncSession) -> None:
        with pytest.raises(NotFoundError):
            await admin.set_library_version(
                session, library_type=LibraryType.USER, owner_id=999, version=1
            )


class TestGroups:
    async def test_a_group_library_is_created_with_its_owner_as_member(
        self, session: AsyncSession
    ) -> None:
        owner = await admin.create_user(session, username="octocat")

        library = await admin.create_group(session, name="Research", owner_username="octocat")

        assert library.type is LibraryType.GROUP
        assert library.name == "Research"
        members = await admin.list_group_members(session, library)
        assert [(m.user_id, m.role) for m in members] == [(owner.id, "admin")]

    async def test_a_member_can_be_added(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="octocat")
        other = await admin.create_user(session, username="other")
        library = await admin.create_group(session, name="Research", owner_username="octocat")

        await admin.add_group_member(session, library, username="other")

        members = await admin.list_group_members(session, library)
        assert other.id in {m.user_id for m in members}
