"""Passkeys, driven with a software authenticator that signs for real.

`tests/authenticator.py` produces genuine CBOR and genuine ES256 signatures, so
what runs here is the `webauthn` library's verification rather than a stand-in
for it. Only the hardware is simulated.

The decisions worth holding still: a passkey signs in on its own, no username
is ever asked for, a challenge answers once, and an account cannot delete its
last way in.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import PasskeyCredential, User, WebAuthnChallenge
from altero.services import admin, passkeys, webauth
from tests.authenticator import Authenticator
from tests.test_web_routes import PASSWORD

PUBLIC_URL = "https://altero.example.org"
PARTY = passkeys.relying_party(PUBLIC_URL)


async def account(session: AsyncSession, username: str = "ada") -> User:
    user = await admin.create_user(session, username=username)
    await webauth.set_password(session, user, PASSWORD)
    return user


async def enrol(
    session: AsyncSession, user: User, device: Authenticator | None = None, *, name: str = "Laptop"
) -> tuple[Authenticator, PasskeyCredential]:
    """Run a whole enrolment ceremony and return the device and the record."""
    device = device or Authenticator()
    options = await passkeys.begin_registration(session, user, party=PARTY)
    answer = device.register(options, origin=PARTY.origin, rp_id=PARTY.id)
    stored = await passkeys.finish_registration(session, user, answer, party=PARTY, name=name)
    return device, stored


async def sign_in(
    session: AsyncSession, device: Authenticator, *, user: User | None = None, advance: bool = True
) -> tuple[User, PasskeyCredential]:
    options = await passkeys.begin_authentication(session, party=PARTY, user=user)
    answer = device.authenticate(options, origin=PARTY.origin, rp_id=PARTY.id, advance=advance)
    return await passkeys.finish_authentication(session, answer, party=PARTY)


class TestTheRelyingParty:
    async def test_it_comes_from_the_public_url(self) -> None:
        party = passkeys.relying_party("https://altero.example.org")

        assert party.id == "altero.example.org"
        assert party.origin == "https://altero.example.org"

    async def test_a_port_stays_in_the_origin_but_not_the_id(self) -> None:
        """The id is a domain; the origin is what the browser reports."""
        party = passkeys.relying_party("http://127.0.0.1:8000")

        assert party.id == "127.0.0.1"
        assert party.origin == "http://127.0.0.1:8000"

    async def test_it_refuses_to_guess(self) -> None:
        """A passkey enrolled under one id is silently useless under another,
        and the failure turns up weeks later as "my passkey stopped working"."""
        with pytest.raises(InvalidInputError):
            passkeys.relying_party("")

    async def test_something_that_is_not_an_address_is_refused(self) -> None:
        with pytest.raises(InvalidInputError):
            passkeys.relying_party("not an address")


class TestEnrolling:
    async def test_a_passkey_can_be_added(self, session: AsyncSession) -> None:
        user = await account(session)

        _, stored = await enrol(session, user)

        assert stored.name == "Laptop"
        assert stored.user_id == user.id

    async def test_no_secret_is_stored(self, session: AsyncSession) -> None:
        """The whole point of the thing: there is nothing here to leak."""
        user = await account(session)
        device, stored = await enrol(session, user)

        private = device.key.private_numbers().private_value.to_bytes(32, "big")
        assert passkeys._b64(private) not in stored.public_key

    async def test_the_authenticator_is_asked_to_verify_a_person(
        self, session: AsyncSession
    ) -> None:
        """Which is what makes one passkey enough on its own."""
        user = await account(session)

        options = await passkeys.begin_registration(session, user, party=PARTY)

        assert options["authenticatorSelection"]["userVerification"] == "required"
        assert options["authenticatorSelection"]["residentKey"] == "required"

    async def test_one_already_enrolled_is_offered_for_exclusion(
        self, session: AsyncSession
    ) -> None:
        """So an authenticator says "you already have one" rather than quietly
        making a second."""
        user = await account(session)
        await enrol(session, user)

        options = await passkeys.begin_registration(session, user, party=PARTY)

        assert len(options["excludeCredentials"]) == 1

    async def test_the_same_passkey_cannot_be_enrolled_twice(self, session: AsyncSession) -> None:
        user = await account(session)
        device, _ = await enrol(session, user)

        options = await passkeys.begin_registration(session, user, party=PARTY)
        answer = device.register(options, origin=PARTY.origin, rp_id=PARTY.id)

        with pytest.raises(InvalidInputError):
            await passkeys.finish_registration(session, user, answer, party=PARTY)

    async def test_an_answer_from_another_origin_is_refused(self, session: AsyncSession) -> None:
        """The origin check is what stops a phishing page from enrolling one."""
        user = await account(session)
        device = Authenticator()
        options = await passkeys.begin_registration(session, user, party=PARTY)
        answer = device.register(
            options, origin="https://altero.example.org.evil.test", rp_id=PARTY.id
        )

        with pytest.raises(ForbiddenError):
            await passkeys.finish_registration(session, user, answer, party=PARTY)

    async def test_an_authenticator_that_only_checks_a_touch_is_refused(
        self, session: AsyncSession
    ) -> None:
        """User verification is what makes one passkey enough on its own. An
        authenticator that merely noticed a finger has proved presence and not
        identity, and enrolling it would quietly weaken the credential."""
        user = await account(session)
        device = Authenticator(verifies_user=False)
        options = await passkeys.begin_registration(session, user, party=PARTY)
        answer = device.register(options, origin=PARTY.origin, rp_id=PARTY.id)

        with pytest.raises(ForbiddenError):
            await passkeys.finish_registration(session, user, answer, party=PARTY)

    async def test_a_name_is_given_when_none_was_asked_for(self, session: AsyncSession) -> None:
        user = await account(session)

        _, stored = await enrol(session, user, name="")

        assert stored.name == "Passkey"


class TestSigningIn:
    async def test_a_passkey_signs_in_on_its_own(self, session: AsyncSession) -> None:
        user = await account(session)
        device, _ = await enrol(session, user)

        found, _ = await sign_in(session, device)

        assert found.id == user.id

    async def test_no_username_is_needed(self, session: AsyncSession) -> None:
        """A sign-in asks for no credential ids and no name, so the options
        cannot be used to ask whether an account exists."""
        await account(session)

        options = await passkeys.begin_authentication(session, party=PARTY)

        assert not options.get("allowCredentials")

    async def test_it_finds_the_account_from_the_assertion(self, session: AsyncSession) -> None:
        """Two accounts, one passkey each, and nobody said who they were."""
        first = await account(session, "ada")
        second = await account(session, "grace")
        await enrol(session, first, Authenticator(credential_id=b"first-credential-00"))
        theirs, _ = await enrol(
            session, second, Authenticator(credential_id=b"second-credential-0")
        )

        found, _ = await sign_in(session, theirs)

        assert found.id == second.id

    async def test_a_passkey_that_is_not_enrolled_is_refused(self, session: AsyncSession) -> None:
        await account(session)
        stranger = Authenticator(credential_id=b"never-seen-before-0")
        options = await passkeys.begin_authentication(session, party=PARTY)
        answer = stranger.authenticate(options, origin=PARTY.origin, rp_id=PARTY.id)

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY)

    async def test_a_bad_signature_is_refused(self, session: AsyncSession) -> None:
        user = await account(session)
        device, _ = await enrol(session, user)
        options = await passkeys.begin_authentication(session, party=PARTY)
        answer = device.authenticate_with_a_broken_signature(
            options, origin=PARTY.origin, rp_id=PARTY.id
        )

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY)

    async def test_an_answer_from_another_origin_is_refused(self, session: AsyncSession) -> None:
        user = await account(session)
        device, _ = await enrol(session, user)
        options = await passkeys.begin_authentication(session, party=PARTY)
        answer = device.authenticate(
            options, origin="https://altero.example.org.evil.test", rp_id=PARTY.id
        )

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY)

    async def test_an_assertion_without_user_verification_is_refused(
        self, session: AsyncSession
    ) -> None:
        """Enrolled properly, then presented by something that only checked a
        touch -- the sign-in has to insist as firmly as the enrolment did."""
        user = await account(session)
        device, _ = await enrol(session, user)
        device.verifies_user = False
        options = await passkeys.begin_authentication(session, party=PARTY)
        answer = device.authenticate(options, origin=PARTY.origin, rp_id=PARTY.id)

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY)

    async def test_a_suspended_account_cannot_sign_in(self, session: AsyncSession) -> None:
        await account(session, "keeper")
        user = await account(session)
        device, _ = await enrol(session, user)
        await admin.set_disabled(session, user, disabled=True)

        with pytest.raises(ForbiddenError):
            await sign_in(session, device)

    async def test_the_last_used_time_is_recorded(self, session: AsyncSession) -> None:
        user = await account(session)
        device, stored = await enrol(session, user)
        assert stored.last_used is None

        await sign_in(session, device)

        assert stored.last_used is not None


class TestTheChallenge:
    async def test_it_answers_once(self, session: AsyncSession) -> None:
        """Replaying an assertion finds no challenge the second time.

        The authenticator deliberately keeps no counter here: with one, the
        library's own counter check would refuse the replay first and this
        would pass whether or not the challenge was ever spent.
        """
        user = await account(session)
        device, _ = await enrol(session, user, Authenticator(credential_id=b"no-counter-00000000"))
        options = await passkeys.begin_authentication(session, party=PARTY)
        answer = device.authenticate(options, origin=PARTY.origin, rp_id=PARTY.id, advance=False)
        await passkeys.finish_authentication(session, answer, party=PARTY)

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY)

    async def test_one_issued_for_enrolling_cannot_answer_a_sign_in(
        self, session: AsyncSession
    ) -> None:
        """Otherwise a ceremony started for one purpose finishes another."""
        user = await account(session)
        device, _ = await enrol(session, user)
        options = await passkeys.begin_registration(session, user, party=PARTY)
        answer = device.authenticate(options, origin=PARTY.origin, rp_id=PARTY.id)

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY)

    async def test_an_expired_one_is_refused(self, session: AsyncSession) -> None:
        user = await account(session)
        device, _ = await enrol(session, user)
        options = await passkeys.begin_authentication(session, party=PARTY)
        stored = await session.scalar(select(WebAuthnChallenge))
        assert stored is not None
        stored.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        await session.commit()
        answer = device.authenticate(options, origin=PARTY.origin, rp_id=PARTY.id)

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY)

    async def test_an_invented_one_is_refused(self, session: AsyncSession) -> None:
        user = await account(session)
        device, _ = await enrol(session, user)
        answer = device.authenticate(
            {"challenge": passkeys._b64(b"a challenge nobody issued")},
            origin=PARTY.origin,
            rp_id=PARTY.id,
        )

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY)

    async def test_a_ceremony_for_one_account_is_not_answered_by_another(
        self, session: AsyncSession
    ) -> None:
        """Proving a signed-in session again must not be answerable by
        anybody's passkey."""
        first = await account(session, "ada")
        second = await account(session, "grace")
        await enrol(session, first, Authenticator(credential_id=b"first-credential-00"))
        theirs, _ = await enrol(
            session, second, Authenticator(credential_id=b"second-credential-0")
        )

        options = await passkeys.begin_authentication(
            session, party=PARTY, user=first, purpose="reauth"
        )
        answer = theirs.authenticate(options, origin=PARTY.origin, rp_id=PARTY.id)

        with pytest.raises(ForbiddenError):
            await passkeys.finish_authentication(session, answer, party=PARTY, purpose="reauth")


class TestTheSignCounter:
    async def test_it_advances(self, session: AsyncSession) -> None:
        user = await account(session)
        device, stored = await enrol(session, user)

        await sign_in(session, device)

        assert stored.sign_count > 0

    async def test_an_authenticator_that_keeps_no_counter_still_works(
        self, session: AsyncSession
    ) -> None:
        """Touch ID, Windows Hello and every keychain-backed passkey send zero
        every time. Refusing that would lock out the commonest ones there are."""
        user = await account(session)
        device, _ = await enrol(session, user)

        await sign_in(session, device, advance=False)
        found, _ = await sign_in(session, device, advance=False)

        assert found.id == user.id


class TestManagingThem:
    async def test_one_can_be_renamed(self, session: AsyncSession) -> None:
        user = await account(session)
        _, stored = await enrol(session, user)

        await passkeys.rename(session, user, stored, "Yubikey on the keyring")

        assert stored.name == "Yubikey on the keyring"

    async def test_an_empty_name_is_refused(self, session: AsyncSession) -> None:
        """A list of indistinguishable passkeys is one nobody can safely
        remove from."""
        user = await account(session)
        _, stored = await enrol(session, user)

        with pytest.raises(InvalidInputError):
            await passkeys.rename(session, user, stored, "   ")

    async def test_somebody_elses_is_not_renamable(self, session: AsyncSession) -> None:
        owner = await account(session, "ada")
        other = await account(session, "grace")
        _, stored = await enrol(session, owner)

        with pytest.raises(ForbiddenError):
            await passkeys.rename(session, other, stored, "mine now")

    async def test_one_can_be_removed(self, session: AsyncSession) -> None:
        user = await account(session)
        _, stored = await enrol(session, user)

        await passkeys.remove(session, user, stored)

        assert await passkeys.credentials_for(session, user) == []

    async def test_the_last_way_in_cannot_be_removed(self, session: AsyncSession) -> None:
        """An account with no password would lock itself out of a library
        nobody else can reach."""
        user = await admin.create_user(session, username="grace")
        _, stored = await enrol(session, user)

        with pytest.raises(ForbiddenError):
            await passkeys.remove(session, user, stored)

    async def test_it_can_be_removed_when_a_password_remains(self, session: AsyncSession) -> None:
        user = await account(session)
        _, stored = await enrol(session, user)

        await passkeys.remove(session, user, stored)

        assert await passkeys.credentials_for(session, user) == []

    async def test_the_second_of_two_can_always_go(self, session: AsyncSession) -> None:
        user = await admin.create_user(session, username="grace")
        await enrol(session, user, Authenticator(credential_id=b"first-credential-00"))
        _, second = await enrol(session, user, Authenticator(credential_id=b"second-credential-0"))

        await passkeys.remove(session, user, second)

        assert len(await passkeys.credentials_for(session, user)) == 1

    async def test_deleting_an_account_takes_its_passkeys(self, session: AsyncSession) -> None:
        await account(session, "keeper")
        user = await account(session)
        await enrol(session, user)

        await admin.delete_user(session, user)

        assert list(await session.scalars(select(PasskeyCredential))) == []
