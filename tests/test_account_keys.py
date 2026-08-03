"""Managing one's own API keys.

The rule that decides the shape of this: creating a key needs the password,
revoking one does not. Creating hands out a new credential, so it belongs with
every other credential change in the account. Revoking only takes access away,
and the moment somebody wants to do it is the moment a key has leaked -- making
them find their password first is friction in exactly the wrong place.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import User
from altero.services import account, admin, webauth

PASSWORD = "correct horse battery staple"


async def make_user(session: AsyncSession, username: str = "ada") -> User:
    return await webauth.register(
        session,
        username=username,
        password=PASSWORD,
        email=f"{username}@example.org",
        allow_registration=True,
    )


class TestListing:
    async def test_it_lists_this_account_s_keys(self, session: AsyncSession) -> None:
        user = await make_user(session)
        await admin.create_api_key(session, username="ada", name="laptop")
        await admin.create_api_key(session, username="ada", name="phone")

        listed = await account.list_keys(session, user)

        assert {entry.name for entry in listed} == {"laptop", "phone"}

    async def test_it_lists_nobody_else_s(self, session: AsyncSession) -> None:
        user = await make_user(session)
        await make_user(session, "grace")
        await admin.create_api_key(session, username="grace", name="theirs")

        assert await account.list_keys(session, user) == []

    async def test_an_account_with_no_keys_lists_nothing(self, session: AsyncSession) -> None:
        user = await make_user(session)

        assert await account.list_keys(session, user) == []


class TestCreating:
    async def test_it_returns_the_key_once(self, session: AsyncSession) -> None:
        user = await make_user(session)

        created = await account.create_key(session, user, name="laptop", current_password=PASSWORD)

        assert created.key
        assert created.name == "laptop"

    async def test_it_records_when_it_was_issued(self, session: AsyncSession) -> None:
        """Otherwise three keys called "Zotero client" are indistinguishable."""
        user = await make_user(session)

        created = await account.create_key(session, user, name="laptop", current_password=PASSWORD)

        assert created.created is not None

    async def test_it_needs_the_current_password(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(ForbiddenError):
            await account.create_key(session, user, name="laptop", current_password="not it")

        assert await account.list_keys(session, user) == []

    async def test_it_belongs_to_the_account_that_made_it(self, session: AsyncSession) -> None:
        user = await make_user(session)

        created = await account.create_key(session, user, name="laptop", current_password=PASSWORD)

        assert created.user_id == user.id

    async def test_full_access_is_the_default_because_that_is_what_zotero_needs(
        self, session: AsyncSession
    ) -> None:
        user = await make_user(session)

        created = await account.create_key(
            session, user, name="Zotero client", current_password=PASSWORD
        )

        assert created.library_read is True
        assert created.library_write is True
        assert created.notes_read is True
        assert created.files_read is True
        assert created.all_groups_read is True
        assert created.all_groups_write is True

    async def test_a_read_only_key_can_be_asked_for(self, session: AsyncSession) -> None:
        user = await make_user(session)

        created = await account.create_key(
            session, user, name="a script", current_password=PASSWORD, write=False
        )

        assert created.library_read is True
        assert created.library_write is False
        assert created.all_groups_write is False

    async def test_groups_can_be_left_out(self, session: AsyncSession) -> None:
        user = await make_user(session)

        created = await account.create_key(
            session, user, name="personal only", current_password=PASSWORD, groups=False
        )

        assert created.all_groups_read is False
        assert created.all_groups_write is False
        assert created.library_read is True

    async def test_a_nameless_key_is_refused(self, session: AsyncSession) -> None:
        """A list of unnamed keys is a list nobody can act on."""
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.create_key(session, user, name="  ", current_password=PASSWORD)

    async def test_an_absurd_name_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.create_key(session, user, name="a" * 300, current_password=PASSWORD)

    async def test_every_key_is_different(self, session: AsyncSession) -> None:
        user = await make_user(session)

        keys = {
            (
                await account.create_key(
                    session, user, name=f"key {index}", current_password=PASSWORD
                )
            ).key
            for index in range(10)
        }

        assert len(keys) == 10


class TestRevoking:
    async def test_it_stops_the_key_working(self, session: AsyncSession) -> None:
        user = await make_user(session)
        created = await account.create_key(session, user, name="laptop", current_password=PASSWORD)

        await account.revoke_key(session, user, created.id)

        assert await account.list_keys(session, user) == []

    async def test_it_needs_no_password(self, session: AsyncSession) -> None:
        """A leaked key has to be killable without a detour."""
        user = await make_user(session)
        created = await account.create_key(session, user, name="laptop", current_password=PASSWORD)

        await account.revoke_key(session, user, created.id)

        assert await account.list_keys(session, user) == []

    async def test_another_account_s_key_cannot_be_revoked(self, session: AsyncSession) -> None:
        user = await make_user(session)
        await make_user(session, "grace")
        theirs = await admin.create_api_key(session, username="grace", name="theirs")

        with pytest.raises(ForbiddenError):
            await account.revoke_key(session, user, theirs.id)

        assert len(await admin.list_api_keys(session)) == 1

    async def test_a_key_that_does_not_exist_is_a_404(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(NotFoundError):
            await account.revoke_key(session, user, 9999)

    async def test_revoking_twice_is_a_404_the_second_time(self, session: AsyncSession) -> None:
        user = await make_user(session)
        created = await account.create_key(session, user, name="laptop", current_password=PASSWORD)
        await account.revoke_key(session, user, created.id)

        with pytest.raises(NotFoundError):
            await account.revoke_key(session, user, created.id)
