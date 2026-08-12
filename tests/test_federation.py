"""What a directory's assertion is allowed to do to an account here.

The protocol is in `test_oidc.py`. This is the policy, and the sharpest part of
it is the first class: an email claim must never adopt an existing account.
That is the classic way federated sign-in is broken into, and it is worse on a
self-hosted server than on a service, because an operator adding a second
provider would otherwise silently hand it everybody.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import ApiKey, FederatedIdentity, IdentityProvider, User
from altero.services import admin, emailverify, federation, webauth
from altero.services.oidc import Assertion
from tests.test_web_routes import PASSWORD


async def make_provider(session: AsyncSession, **overrides: object) -> IdentityProvider:
    values: dict = {
        "slug": "campus",
        "kind": "oidc",
        "display_name": "Campus",
        "issuer": "https://sso.example.org",
        "client_id": "altero",
        "create_accounts": False,
    }
    values.update(overrides)
    provider = IdentityProvider(**values)
    session.add(provider)
    await session.commit()
    return provider


def asserts(
    subject: str = "8f14e45f",
    *,
    username: str = "ada",
    email: str = "ada@example.org",
    **claims: object,
) -> Assertion:
    return Assertion(
        subject=subject,
        username=username,
        display_name="Ada Lovelace",
        email=email,
        claims={"sub": subject, **claims},
    )


async def local_account(
    session: AsyncSession, username: str = "ada", *, email: str | None = None
) -> User:
    """An account made here, with a confirmed address, before any directory existed."""
    email = email or f"{username}@example.org"
    user = await admin.create_user(session, username=username)
    user.email = email
    await session.commit()
    await emailverify.confirm(session, await emailverify.issue(session, user, email))
    await webauth.set_password(session, user, PASSWORD)
    return user


class TestAnEmailClaimNeverAdoptsAnAccount:
    """The decision this module exists to make."""

    async def test_a_matching_address_does_not_sign_into_the_local_account(
        self, session: AsyncSession
    ) -> None:
        existing = await local_account(session)
        provider = await make_provider(session, create_accounts=True)

        outcome = await federation.sign_in(session, provider, asserts(email=existing.email or ""))

        assert outcome.created is True
        assert outcome.user.id != existing.id

    async def test_a_matching_address_is_refused_where_creation_is_off(
        self, session: AsyncSession
    ) -> None:
        """Refused rather than quietly signing in as somebody with that address."""
        existing = await local_account(session)
        provider = await make_provider(session, create_accounts=False)

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts(email=existing.email or ""))

    async def test_a_provisioned_account_does_not_steal_the_address(
        self, session: AsyncSession
    ) -> None:
        """The column is unique; the sign-in matters more than the contact address."""
        existing = await local_account(session)
        provider = await make_provider(session, create_accounts=True)

        outcome = await federation.sign_in(session, provider, asserts(email=existing.email or ""))

        assert outcome.user.email is None
        kept = await session.scalar(select(User).where(User.id == existing.id))
        assert kept is not None
        assert kept.email == "ada@example.org"

    async def test_an_asserted_address_is_not_treated_as_confirmed(
        self, session: AsyncSession
    ) -> None:
        """A directory saying so is not this server having proved it -- otherwise
        a provider could aim somebody's reset links wherever it liked."""
        provider = await make_provider(session, create_accounts=True)

        outcome = await federation.sign_in(session, provider, asserts(email="grace@example.org"))

        assert outcome.user.email == "grace@example.org"
        assert outcome.user.email_verified is None


class TestProvisioning:
    async def test_it_is_off_unless_the_operator_turned_it_on(self, session: AsyncSession) -> None:
        provider = await make_provider(session, create_accounts=False)

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts())

    async def test_an_account_is_made_when_it_is_on(self, session: AsyncSession) -> None:
        provider = await make_provider(session, create_accounts=True)

        outcome = await federation.sign_in(session, provider, asserts())

        assert outcome.created is True
        assert outcome.user.username == "ada"

    async def test_the_first_account_administers_the_instance(self, session: AsyncSession) -> None:
        """Whichever way it arrived -- otherwise a fresh instance whose only way
        in is a directory has nobody who can configure it."""
        provider = await make_provider(session, create_accounts=True)

        outcome = await federation.sign_in(session, provider, asserts())

        assert outcome.user.administrator is True

    async def test_it_gets_a_personal_library(self, session: AsyncSession) -> None:
        """Through admin.create_user, so it is the same object `altero user add` makes."""
        from altero.models import Library, LibraryType

        provider = await make_provider(session, create_accounts=True)

        outcome = await federation.sign_in(session, provider, asserts())

        library = await session.scalar(
            select(Library).where(
                Library.type == LibraryType.USER, Library.owner_id == outcome.user.id
            )
        )
        assert library is not None

    async def test_a_username_already_taken_gets_a_suffix(self, session: AsyncSession) -> None:
        """A directory's usernames are unique there, not here, and two
        directories certainly disagree."""
        await local_account(session, "ada")
        provider = await make_provider(session, create_accounts=True)

        outcome = await federation.sign_in(session, provider, asserts(subject="other"))

        assert outcome.user.username == "ada2"

    async def test_a_username_with_an_at_sign_is_made_usable(self, session: AsyncSession) -> None:
        """`upn` is an address, and a username here may not hold '@'."""
        provider = await make_provider(session, create_accounts=True)

        outcome = await federation.sign_in(session, provider, asserts(username="ada@example.org"))

        assert "@" not in outcome.user.username

    async def test_signing_in_again_returns_the_same_account(self, session: AsyncSession) -> None:
        provider = await make_provider(session, create_accounts=True)
        first = await federation.sign_in(session, provider, asserts())

        second = await federation.sign_in(session, provider, asserts())

        assert second.created is False
        assert second.user.id == first.user.id

    async def test_the_subject_identifies_them_rather_than_the_username(
        self, session: AsyncSession
    ) -> None:
        """Somebody renamed at the directory is still the same person here."""
        provider = await make_provider(session, create_accounts=True)
        first = await federation.sign_in(session, provider, asserts())

        again = await federation.sign_in(session, provider, asserts(username="ada.lovelace"))

        assert again.user.id == first.user.id
        assert again.created is False


class TestLinkingAnExistingAccount:
    async def test_a_signed_in_account_can_attach_a_directory(self, session: AsyncSession) -> None:
        """The supported path for an instance that had accounts before a directory."""
        user = await local_account(session)
        provider = await make_provider(session)

        await federation.link(session, user, provider, asserts())

        outcome = await federation.sign_in(session, provider, asserts())
        assert outcome.user.id == user.id
        assert outcome.created is False

    async def test_a_subject_already_linked_elsewhere_is_refused(
        self, session: AsyncSession
    ) -> None:
        """One identity, one account, or signing in has two answers."""
        first = await local_account(session, "ada")
        second = await local_account(session, "grace", email="grace@example.org")
        provider = await make_provider(session)
        await federation.link(session, first, provider, asserts())

        with pytest.raises(ForbiddenError):
            await federation.link(session, second, provider, asserts())

    async def test_linking_the_same_one_twice_is_not_an_error(self, session: AsyncSession) -> None:
        user = await local_account(session)
        provider = await make_provider(session)
        await federation.link(session, user, provider, asserts())

        await federation.link(session, user, provider, asserts())

        assert len(await federation.identities_for(session, user)) == 1


class TestDetachingOne:
    async def test_it_can_be_removed(self, session: AsyncSession) -> None:
        user = await local_account(session)
        provider = await make_provider(session)
        identity = await federation.link(session, user, provider, asserts())

        await federation.unlink(session, user, identity)

        assert await federation.identities_for(session, user) == []

    async def test_the_last_way_in_cannot_be_removed(self, session: AsyncSession) -> None:
        """An account with no password would lock itself out of a library
        nobody else can reach."""
        provider = await make_provider(session, create_accounts=True)
        outcome = await federation.sign_in(session, provider, asserts())
        identity = (await federation.identities_for(session, outcome.user))[0]

        with pytest.raises(ForbiddenError):
            await federation.unlink(session, outcome.user, identity)

    async def test_somebody_elses_is_not_removable(self, session: AsyncSession) -> None:
        owner = await local_account(session, "ada")
        other = await local_account(session, "grace", email="grace@example.org")
        provider = await make_provider(session)
        identity = await federation.link(session, owner, provider, asserts())

        with pytest.raises(ForbiddenError):
            await federation.unlink(session, other, identity)


class TestTheRequiredClaim:
    async def test_a_sign_in_carrying_it_succeeds(self, session: AsyncSession) -> None:
        provider = await make_provider(
            session, create_accounts=True, required_claim="groups", required_value="zotero"
        )

        outcome = await federation.sign_in(session, provider, asserts(groups=["zotero"]))

        assert outcome.created is True

    async def test_a_sign_in_without_it_is_refused(self, session: AsyncSession) -> None:
        provider = await make_provider(
            session, create_accounts=True, required_claim="groups", required_value="zotero"
        )

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts(groups=["staff"]))

    async def test_losing_it_suspends_the_account(self, session: AsyncSession) -> None:
        """The deprovisioning half: suspension refuses *both* credentials, so
        the desktop client's key stops working too."""
        await local_account(session, "keeper")  # so this is not the last administrator
        provider = await make_provider(
            session, create_accounts=True, required_claim="groups", required_value="zotero"
        )
        outcome = await federation.sign_in(session, provider, asserts(groups=["zotero"]))

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts(groups=["alumni"]))

        again = await session.scalar(select(User).where(User.id == outcome.user.id))
        assert again is not None
        assert again.disabled_at is not None

    async def test_a_suspended_account_cannot_sign_in_again_by_regaining_it(
        self, session: AsyncSession
    ) -> None:
        """Reinstating somebody is the operator's decision, not the directory's."""
        await local_account(session, "keeper")
        provider = await make_provider(
            session, create_accounts=True, required_claim="groups", required_value="zotero"
        )
        await federation.sign_in(session, provider, asserts(groups=["zotero"]))
        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts(groups=["alumni"]))

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts(groups=["zotero"]))

    async def test_the_keys_stay_unless_the_provider_says_otherwise(
        self, session: AsyncSession
    ) -> None:
        """Which is what makes reinstating somebody restore their sync rather
        than make them set every client up again."""
        await local_account(session, "keeper")
        provider = await make_provider(
            session, create_accounts=True, required_claim="groups", required_value="zotero"
        )
        outcome = await federation.sign_in(session, provider, asserts(groups=["zotero"]))
        await admin.create_api_key(session, username=outcome.user.username, name="Zotero")

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts(groups=["alumni"]))

        keys = await session.scalars(select(ApiKey).where(ApiKey.user_id == outcome.user.id))
        assert len(list(keys)) == 1

    async def test_the_keys_go_when_it_does(self, session: AsyncSession) -> None:
        await local_account(session, "keeper")
        provider = await make_provider(
            session,
            create_accounts=True,
            required_claim="groups",
            required_value="zotero",
            revoke_keys_on_loss=True,
        )
        outcome = await federation.sign_in(session, provider, asserts(groups=["zotero"]))
        await admin.create_api_key(session, username=outcome.user.username, name="Zotero")

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts(groups=["alumni"]))

        keys = await session.scalars(select(ApiKey).where(ApiKey.user_id == outcome.user.id))
        assert list(keys) == []

    async def test_the_last_administrator_is_not_locked_out_by_a_directory(
        self, session: AsyncSession
    ) -> None:
        """A directory must not be able to leave an instance unadministrable.
        The sign-in is still refused; the suspension simply does not happen."""
        provider = await make_provider(
            session, create_accounts=True, required_claim="groups", required_value="zotero"
        )
        outcome = await federation.sign_in(session, provider, asserts(groups=["zotero"]))
        assert outcome.user.administrator is True

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts(groups=["alumni"]))

        again = await session.scalar(select(User).where(User.id == outcome.user.id))
        assert again is not None
        assert again.disabled_at is None


class TestASuspendedAccount:
    async def test_it_cannot_sign_in_through_a_directory(self, session: AsyncSession) -> None:
        """Suspension is a property of the account, not of one credential."""
        await local_account(session, "keeper")
        user = await local_account(session, "ada")
        provider = await make_provider(session)
        await federation.link(session, user, provider, asserts())
        await admin.set_disabled(session, user, disabled=True)

        with pytest.raises(ForbiddenError):
            await federation.sign_in(session, provider, asserts())


class TestTheIdentityGoesWithTheAccount:
    async def test_deleting_an_account_takes_its_links(self, session: AsyncSession) -> None:
        await local_account(session, "keeper")
        user = await local_account(session, "ada")
        provider = await make_provider(session)
        await federation.link(session, user, provider, asserts())

        await admin.delete_user(session, user)

        remaining = await session.scalars(select(FederatedIdentity))
        assert list(remaining) == []
