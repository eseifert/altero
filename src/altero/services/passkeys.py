"""Passkeys: signing in with what the device already checked.

The verification comes from the ``webauthn`` package rather than being written
here, and the difference from :mod:`altero.services.totp` -- which *is*
hand-rolled -- is evidence rather than taste. RFC 6238 publishes test vectors,
so a TOTP implementation can be held against the standard itself; that is what
``tests/test_totp.py`` does. WebAuthn publishes no such table, and the work is
CBOR decoding, COSE key parsing and attestation formats, which is precisely
where the bugs live. Reimplementing it would mean trusting a reading of the
specification with nothing to check it against.

**A passkey signs in on its own**, and that is the point of having one. The
authenticator has already established presence and, with user verification
required, identity -- a fingerprint, a face, a device PIN. Demanding a code
from an authenticator app afterwards would be theatre: it would add a factor
weaker than the one already presented and make the better credential the more
tedious one to use.

**No username is asked for.** The sign-in uses discoverable credentials, so the
browser offers whichever passkey it holds for this site and the assertion says
who it is. That sidesteps account enumeration completely: there is no form that
behaves differently for a name that exists.

The relying party id is the host of ``public_url`` and cannot be anything else.
A passkey is bound to it at enrolment, so changing it silently invalidates
every passkey on the instance -- which is why :func:`relying_party` refuses to
guess and ``app.py`` checks it at start-up rather than at first use.
"""

import base64
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import webauthn
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import structs

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import PasskeyCredential, User, WebAuthnChallenge

logger = logging.getLogger("altero.passkeys")

#: How long a ceremony may take. The browser's own timeout is 60s; this is the
#: server's, and is longer because a person may be fetching a security key from
#: a drawer.
CHALLENGE_LIFETIME = timedelta(minutes=5)

#: What the authenticator shows while asking. Not the instance's own name,
#: which an operator has not been asked for anywhere else.
RELYING_PARTY_NAME = "altero"

#: Longest label somebody may give a passkey.
MAX_NAME = 255


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True, slots=True)
class RelyingParty:
    """Who the authenticator thinks it is signing in to."""

    #: The registrable domain. A passkey is bound to this.
    id: str
    #: The exact origin the browser must report.
    origin: str


def relying_party(public_url: str) -> RelyingParty:
    """Return the relying party for this deployment, or refuse to guess.

    ``public_url`` decides it and nothing else does -- there is deliberately no
    fallback to the address a request arrived on. Behind a proxy that is the
    proxy's idea of it, and a passkey enrolled under one id is silently useless
    under another: the failure appears weeks later as "my passkey stopped
    working", with nothing in a log to connect it to a configuration change.
    An instance without the setting simply has no passkeys, and ``/web/config``
    says so rather than offering a button that cannot work.
    """
    source = public_url
    if not source:
        raise InvalidInputError(
            "Set ALTERO_PUBLIC_URL before enrolling a passkey: a passkey is "
            "bound to the address it was made at"
        )

    parsed = urlparse(source)
    if not parsed.hostname:
        raise InvalidInputError(f"{source} is not an address a passkey can be bound to")

    port = f":{parsed.port}" if parsed.port else ""
    return RelyingParty(id=parsed.hostname, origin=f"{parsed.scheme}://{parsed.hostname}{port}")


async def credentials_for(session: AsyncSession, user: User) -> list[PasskeyCredential]:
    result = await session.scalars(
        select(PasskeyCredential)
        .where(PasskeyCredential.user_id == user.id)
        .order_by(PasskeyCredential.created)
    )
    return list(result)


async def _remember(
    session: AsyncSession, challenge: bytes, *, purpose: str, user_id: int | None
) -> None:
    """Store a challenge so the answer can be checked against it."""
    # Expired rows go as new ones are made, keeping the table bounded without a
    # scheduled job -- as with sessions, login codes and auth requests.
    await session.execute(delete(WebAuthnChallenge).where(WebAuthnChallenge.expires < _now()))
    session.add(
        WebAuthnChallenge(
            challenge=_b64(challenge),
            user_id=user_id,
            purpose=purpose,
            expires=_now() + CHALLENGE_LIFETIME,
        )
    )
    await session.commit()


async def _spend(session: AsyncSession, challenge: str, *, purpose: str) -> WebAuthnChallenge:
    """Take the challenge row, or refuse.

    Deleted as it is read, so an assertion cannot be replayed: the second
    attempt finds nothing. ``purpose`` is checked because a challenge issued
    for enrolling must not answer a sign-in.
    """
    row = await session.scalar(
        select(WebAuthnChallenge).where(WebAuthnChallenge.challenge == challenge)
    )
    if row is None or row.expires < _now() or row.purpose != purpose:
        raise ForbiddenError("That did not answer a request from here")

    kept = WebAuthnChallenge(
        challenge=row.challenge,
        user_id=row.user_id,
        purpose=row.purpose,
        expires=row.expires,
    )
    await session.delete(row)
    await session.commit()
    return kept


async def begin_registration(
    session: AsyncSession, user: User, *, party: RelyingParty
) -> dict[str, Any]:
    """Return the options a browser needs to make a passkey."""
    existing = await credentials_for(session, user)

    options = webauthn.generate_registration_options(
        rp_id=party.id,
        rp_name=RELYING_PARTY_NAME,
        # The account id rather than the username: WebAuthn wants a handle that
        # does not change, and a username here can be changed.
        user_id=str(user.id).encode(),
        user_name=user.username,
        user_display_name=user.display_name or user.username,
        # So an authenticator that already holds one for this account says so
        # rather than quietly making a second.
        exclude_credentials=[
            structs.PublicKeyCredentialDescriptor(id=_unb64(entry.credential_id))
            for entry in existing
        ],
        authenticator_selection=structs.AuthenticatorSelectionCriteria(
            # Discoverable, so signing in can ask for no username at all.
            resident_key=structs.ResidentKeyRequirement.REQUIRED,
            # The authenticator checks a person, not merely a touch. This is
            # what makes one passkey enough on its own.
            user_verification=structs.UserVerificationRequirement.REQUIRED,
        ),
    )

    await _remember(session, options.challenge, purpose="register", user_id=user.id)
    return json.loads(webauthn.options_to_json(options))


async def finish_registration(
    session: AsyncSession,
    user: User,
    credential: dict[str, Any],
    *,
    party: RelyingParty,
    name: str = "",
) -> PasskeyCredential:
    """Check what the authenticator produced and store the passkey."""
    challenge = _client_challenge(credential)
    await _spend(session, challenge, purpose="register")

    try:
        verified = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=_unb64(challenge),
            expected_rp_id=party.id,
            expected_origin=party.origin,
            require_user_verification=True,
        )
    except Exception as failure:
        logger.info("A passkey enrolment did not verify: %s", failure)
        raise ForbiddenError("That passkey could not be verified") from failure

    identifier = _b64(verified.credential_id)
    taken = await session.scalar(
        select(PasskeyCredential).where(PasskeyCredential.credential_id == identifier)
    )
    if taken is not None:
        raise InvalidInputError("That passkey is already enrolled")

    label = name.strip()[:MAX_NAME] or "Passkey"
    stored = PasskeyCredential(
        user_id=user.id,
        credential_id=identifier,
        public_key=_b64(verified.credential_public_key),
        sign_count=verified.sign_count,
        transports=",".join(credential.get("response", {}).get("transports", []) or []),
        name=label,
        backed_up=bool(getattr(verified, "credential_backed_up", False)),
    )
    session.add(stored)
    await session.commit()
    return stored


async def begin_authentication(
    session: AsyncSession, *, party: RelyingParty, user: User | None = None, purpose: str = "login"
) -> dict[str, Any]:
    """Return the options a browser needs to present a passkey.

    ``user`` is left out for an ordinary sign-in, so no credential ids are
    disclosed and the browser offers whatever it holds. It is supplied only
    when the account is already known -- proving a signed-in session again.
    """
    allowed = None
    if user is not None:
        allowed = [
            structs.PublicKeyCredentialDescriptor(id=_unb64(entry.credential_id))
            for entry in await credentials_for(session, user)
        ]

    options = webauthn.generate_authentication_options(
        rp_id=party.id,
        allow_credentials=allowed,
        user_verification=structs.UserVerificationRequirement.REQUIRED,
    )

    await _remember(session, options.challenge, purpose=purpose, user_id=user.id if user else None)
    return json.loads(webauthn.options_to_json(options))


async def finish_authentication(
    session: AsyncSession,
    credential: dict[str, Any],
    *,
    party: RelyingParty,
    purpose: str = "login",
) -> tuple[User, PasskeyCredential]:
    """Check an assertion and return whose passkey it was.

    Nobody says who they are: the credential id in the assertion is what finds
    the account, which is why this can answer a sign-in that asked for no
    username.
    """
    challenge = _client_challenge(credential)
    row = await _spend(session, challenge, purpose=purpose)

    identifier = credential.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ForbiddenError("That passkey could not be verified")

    stored = await session.scalar(
        select(PasskeyCredential).where(PasskeyCredential.credential_id == identifier)
    )
    if stored is None:
        raise ForbiddenError("That passkey is not enrolled here")

    # A ceremony started for one account must not be finished by another's
    # passkey -- otherwise proving a session again could be answered by
    # anybody's.
    if row.user_id is not None and stored.user_id != row.user_id:
        raise ForbiddenError("That passkey belongs to a different account")

    try:
        verified = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=_unb64(challenge),
            expected_rp_id=party.id,
            expected_origin=party.origin,
            credential_public_key=_unb64(stored.public_key),
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except Exception as failure:
        logger.info("A passkey assertion did not verify: %s", failure)
        raise ForbiddenError("That passkey could not be verified") from failure

    # A counter that fails to advance is what a cloned authenticator looks
    # like -- but most real ones keep no counter at all and always send zero,
    # so this is recorded rather than refused. Refusing it would lock out Touch
    # ID, Windows Hello and every keychain-backed passkey there is.
    if verified.new_sign_count and verified.new_sign_count <= stored.sign_count:
        logger.warning(
            "Passkey %s for user %s did not advance its counter (%s <= %s)",
            stored.id,
            stored.user_id,
            verified.new_sign_count,
            stored.sign_count,
        )

    stored.sign_count = max(verified.new_sign_count, stored.sign_count)
    stored.last_used = _now()
    await session.commit()

    user = await session.get(User, stored.user_id)
    if user is None:  # pragma: no cover - the row cascades with the user
        raise ForbiddenError("That passkey is not enrolled here")
    if user.disabled_at is not None:
        raise ForbiddenError(
            "This account has been suspended. Ask whoever runs this server about it."
        )
    return user, stored


def _client_challenge(credential: dict[str, Any]) -> str:
    """Return the challenge the browser echoed back, base64url.

    Read out of ``clientDataJSON`` before anything is verified, and used only
    to find the row this ceremony belongs to. It proves nothing on its own --
    the library checks the same value against the assertion's signature.
    """
    response = credential.get("response")
    if not isinstance(response, dict):
        raise ForbiddenError("That passkey could not be verified")

    encoded = response.get("clientDataJSON")
    if not isinstance(encoded, str):
        raise ForbiddenError("That passkey could not be verified")

    try:
        client_data = json.loads(_unb64(encoded))
        challenge = client_data["challenge"]
    except (ValueError, TypeError, KeyError) as broken:
        raise ForbiddenError("That passkey could not be verified") from broken

    if not isinstance(challenge, str):
        raise ForbiddenError("That passkey could not be verified")
    return challenge


async def rename(
    session: AsyncSession, user: User, credential: PasskeyCredential, name: str
) -> None:
    if credential.user_id != user.id:
        raise ForbiddenError("That passkey is not yours")
    label = name.strip()[:MAX_NAME]
    if not label:
        raise InvalidInputError("A passkey needs a name, so you can tell it apart later")
    credential.name = label
    await session.commit()


async def remove(session: AsyncSession, user: User, credential: PasskeyCredential) -> None:
    """Remove a passkey, refusing to leave an account with no way in.

    The same rule as detaching the last federated identity: an account with no
    password and one passkey would otherwise be able to delete its only
    credential and lock itself out of a library nobody else can reach.
    """
    if credential.user_id != user.id:
        raise ForbiddenError("That passkey is not yours")

    remaining = [
        entry for entry in await credentials_for(session, user) if entry.id != credential.id
    ]
    if not remaining and not user.password_hash:
        from altero.services import federation

        if not await federation.identities_for(session, user):
            raise ForbiddenError(
                "Set a password first: this is the only way you have of signing in"
            )

    await session.delete(credential)
    await session.commit()


def generate_challenge() -> bytes:
    """For tests and for anything that wants one without a ceremony."""
    return secrets.token_bytes(32)
