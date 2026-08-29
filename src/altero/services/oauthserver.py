"""The authorization code flow, from the application's first redirect to a token.

Read this next to :mod:`altero.services.oidc`, which is the same protocol from
the other side. There, altero holds a secret and asks somebody else who a person
is. Here, altero is the one being asked, and every value that arrives is
somebody else's until it has been checked against something written down first.

Four checks carry the whole flow, and each of them is a documented way this goes
wrong when it is skipped:

**The redirect URI is matched against the registration**, in
:mod:`altero.services.oauthclients`, before anything else happens and before any
screen is drawn. A server that accepts the address it was handed is a phishing
page on its own origin: the person sees the real host, types the real password,
and the code goes wherever the link said.

**The person signs in through :func:`altero.services.webauth.login`** and
nowhere else. This module never sees a password. That is what makes a second
factor, a passkey and single sign-on work here without a line of code -- and
what stops this becoming the one door in the building with a weaker lock.

**PKCE is required of every client, S256 only.** Not offered, not negotiated:
``plain`` makes the challenge equal to the verifier, so a code intercepted with
its challenge can be spent, which is the thing PKCE exists to prevent.

**The code is bound to its client, its redirect URI and its challenge**, and a
second presentation revokes everything the first one produced. RFC 6749 §4.1.2
asks for that, and it is why :class:`~altero.models.oauth.OAuthCode` rows are
marked rather than deleted.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError, NotFoundError, OAuthError
from altero.models.library import User
from altero.models.oauth import (
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
    OAuthDeviceCode,
    OAuthGrant,
    OAuthSigningKey,
    OAuthToken,
)
from altero.services import groups, jws, oauthclients, oauthscopes

#: How long an unanswered authorization may sit on the consent screen. Long
#: enough to read it and to go through a second factor, short enough that a
#: link left open in a tab is not still live tomorrow.
REQUEST_LIFETIME = timedelta(minutes=15)

#: How long an authorization code is good for. RFC 6749 §4.1.2 says a maximum of
#: ten minutes and recommends under one; this is the round trip from the
#: browser's redirect to the application's back-channel call, which is fast.
CODE_LIFETIME = timedelta(seconds=60)

#: An access token's life. Short because it is a bearer credential that goes
#: into request headers and cannot be recalled once issued; the refresh token is
#: what makes an hour tolerable.
ACCESS_LIFETIME = timedelta(hours=1)

#: A refresh token's life, restarted on every rotation. An application in weekly
#: use never sees the end of it; one abandoned for a month has to be authorized
#: again, which is the right outcome.
REFRESH_LIFETIME = timedelta(days=30)

#: How long a device has to be authorized before its codes stop working. Ten
#: minutes is RFC 8628's own example and about as long as somebody will hold a
#: code in their head while they walk to another machine.
DEVICE_CODE_LIFETIME = timedelta(minutes=10)

#: How often a device may ask whether it has been authorized yet, in seconds.
#: RFC 8628 §3.5's default, reported in the response so a device need not
#: assume it.
DEVICE_POLL_INTERVAL = 5

#: What a user code is spelled with: twenty consonants, so no code is a word
#: anybody would rather not read out, and none of ``0/O``, ``1/I`` or ``5/S``
#: can be mistyped for another. Eight characters of it is about 34 bits, which
#: is what RFC 8628 §5.1 asks for from a code that lives ten minutes.
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"
USER_CODE_LENGTH = 8

#: The prefix an access token carries. Not security -- the token is random
#: either way -- but it makes one recognisable in a log or a bug report, and it
#: lets :func:`altero.services.auth.authenticate` tell a token from an API key
#: without a database lookup for each.
ACCESS_PREFIX = "alt_at_"
REFRESH_PREFIX = "alt_rt_"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issuer(public_url: str) -> str:
    """Return the ``iss`` this server claims, or refuse to guess it.

    ``public_url`` decides it and nothing else does. There is deliberately no
    fallback to the address the request arrived on, for the reason
    :func:`altero.services.passkeys.relying_party` gives and one more: ``iss`` is
    what a client pins to notice that a token minted by one provider has been
    replayed into a conversation with another. A value the caller can set with a
    ``Host`` header is not a value anybody can pin.
    """
    if not public_url:
        raise InvalidInputError(
            "Set ALTERO_PUBLIC_URL before using the authorization server: an "
            "issuer taken from the request is one a caller can choose"
        )
    parsed = urlparse(public_url)
    if not parsed.scheme or not parsed.hostname:
        raise InvalidInputError(f"{public_url} is not an address this server can claim as issuer")
    return public_url.rstrip("/")


# --------------------------------------------------------------------------
# The signing key
# --------------------------------------------------------------------------


async def signing_key(session: AsyncSession) -> OAuthSigningKey:
    """Return the key ID tokens are signed with, making one if there is none.

    Made on first use rather than at start-up, so an instance that never issues
    a token never generates one, and generating it is not something a
    deployment has to remember to do.
    """
    key = await session.scalar(
        select(OAuthSigningKey)
        .where(OAuthSigningKey.retired_at.is_(None))
        .order_by(OAuthSigningKey.created.desc())
    )
    if key is not None:
        return key

    pem = jws.generate_private_key()
    key = OAuthSigningKey(kid=jws.thumbprint(pem), private_pem=pem)
    session.add(key)
    await session.commit()
    return key


async def public_keys(session: AsyncSession) -> list[dict[str, str]]:
    """Return every key a client might have to verify against, newest first.

    Retired keys stay in the set until nothing they signed can still be in
    hand. Publishing only the current one would break every ID token issued
    before a rotation, which is the failure that makes people avoid rotating.
    """
    await signing_key(session)
    rows = await session.scalars(select(OAuthSigningKey).order_by(OAuthSigningKey.created.desc()))
    return [jws.public_jwk(row.private_pem, row.kid) for row in rows]


async def rotate_signing_key(session: AsyncSession) -> OAuthSigningKey:
    """Retire the current signing key and start using a new one."""
    current = await signing_key(session)
    current.retired_at = _now()
    pem = jws.generate_private_key()
    fresh = OAuthSigningKey(kid=jws.thumbprint(pem), private_pem=pem)
    session.add(fresh)
    await session.commit()
    return fresh


# --------------------------------------------------------------------------
# Starting an authorization
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Redirect:
    """An address to hand the browser back to, belonging to the application.

    Named rather than a bare string because of what it is *not* allowed to be.
    RFC 6749 §4.1.2.1 is explicit: an error about *which* client or *which*
    redirect URI must never be reported by redirecting, since the only address
    available to bounce it off is the unverified one the request just supplied.
    Those failures are raised instead, and this type is only ever built from an
    address that has already been matched against a registration.
    """

    url: str


def _redirect_with(base: str, **params: str) -> str:
    separator = "&" if urlparse(base).query else "?"
    return f"{base}{separator}{urlencode({k: v for k, v in params.items() if v})}"


def error_redirect(redirect_uri: str, state: str, error: OAuthError) -> Redirect:
    """Return where to send an application that asked for something impossible.

    Only ever called once the redirect URI has been matched against the
    registration. RFC 6749 §4.1.2.1 draws that line: an error about the client
    or the address itself is shown on this server, because the only address in
    hand is the unverified one; everything after that check is delivered to the
    application where it can be acted on.
    """
    return Redirect(
        _redirect_with(redirect_uri, error=error.code, error_description=error.message, state=state)
    )


async def begin(
    session: AsyncSession,
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    scope: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    nonce: str,
) -> OAuthAuthorizationRequest:
    """Check an incoming authorization and store what was asked for.

    Raises rather than redirecting for anything about the client or the
    redirect URI; :class:`OAuthError` for everything the application should be
    told about at its own address. The caller decides which of the two it is by
    catching, which keeps the rule in one place.
    """
    client = await oauthclients.require(session, client_id)
    if not oauthclients.redirect_uri_permitted(client, redirect_uri):
        # Deliberately not redirected. The address in hand is the unverified
        # one; bouncing an error off it is how an open redirector is built.
        raise ForbiddenError(
            f"{redirect_uri} is not a redirect URI registered for {client_id}. "
            "Ask whoever runs this server to add it."
        )

    if response_type != "code":
        raise OAuthError("unsupported_response_type", "This server issues authorization codes only")
    if code_challenge_method != "S256":
        raise OAuthError(
            "invalid_request",
            "PKCE with S256 is required. 'plain' makes the challenge equal to the "
            "verifier, which is the interception this exists to prevent.",
        )
    if not code_challenge:
        raise OAuthError("invalid_request", "code_challenge is required")

    try:
        requested = oauthscopes.validate(scope)
    except InvalidInputError as exc:
        raise OAuthError("invalid_scope", exc.message) from exc

    permitted = set(client.scopes.split())
    beyond = [item for item in requested if item not in permitted]
    if beyond:
        raise OAuthError(
            "invalid_scope",
            f"{client_id} is not registered for {' '.join(beyond)}",
        )

    await session.execute(
        delete(OAuthAuthorizationRequest).where(OAuthAuthorizationRequest.expires < _now())
    )
    pending = OAuthAuthorizationRequest(
        handle=secrets.token_urlsafe(32),
        client_id=client.id,
        redirect_uri=redirect_uri,
        scopes=" ".join(requested),
        state=state[:255],
        code_challenge=code_challenge[:128],
        nonce=nonce[:255],
        expires=_now() + REQUEST_LIFETIME,
    )
    session.add(pending)
    await session.commit()
    return pending


@dataclass(frozen=True, slots=True)
class PendingAuthorization:
    """An authorization waiting on a decision, as the consent screen sees it."""

    handle: str
    client_name: str
    client_id: str
    description: str
    scopes: list[str]
    #: Scopes this person has not already granted this application. What the
    #: screen highlights: coming back to an application you use every day
    #: should not read like granting it everything afresh.
    new_scopes: list[str]
    already_granted: bool


async def pending(session: AsyncSession, handle: str, user: User) -> PendingAuthorization:
    """Return what ``handle`` is asking ``user`` to approve.

    Everything shown comes from the stored row, never from the request that is
    asking to see it. That is the whole reason the handle is opaque: a consent
    screen whose text came from its own query string describes whatever the
    link says it describes.
    """
    request = await session.get(OAuthAuthorizationRequest, handle)
    if request is None or request.expires < _now():
        raise NotFoundError("This authorization has expired or was never started")

    client = await session.get(OAuthClient, request.client_id)
    if client is None or client.disabled_at is not None:
        raise NotFoundError("No such client")

    grant = await _grant_for(session, user.id, client.id)
    granted = grant.scopes if grant else ""
    requested = request.scopes.split()
    return PendingAuthorization(
        handle=handle,
        client_name=client.name,
        client_id=client.client_id,
        description=client.description,
        scopes=requested,
        new_scopes=[scope for scope in requested if scope not in set(granted.split())],
        already_granted=bool(grant) and oauthscopes.covers(granted, request.scopes),
    )


async def _grant_for(session: AsyncSession, user_id: int, client_id: int) -> OAuthGrant | None:
    return await session.scalar(
        select(OAuthGrant).where(OAuthGrant.user_id == user_id, OAuthGrant.client_id == client_id)
    )


async def approve(session: AsyncSession, handle: str, user: User) -> Redirect:
    """Record consent and hand the browser back to the application with a code."""
    request = await session.get(OAuthAuthorizationRequest, handle)
    if request is None or request.expires < _now():
        raise NotFoundError("This authorization has expired or was never started")

    client = await session.get(OAuthClient, request.client_id)
    if client is None or client.disabled_at is not None:
        raise NotFoundError("No such client")

    grant = await _grant_for(session, user.id, client.id)
    if grant is None:
        grant = OAuthGrant(user_id=user.id, client_id=client.id, scopes=request.scopes)
        session.add(grant)
        await session.flush()
    else:
        grant.scopes = oauthscopes.union(grant.scopes, request.scopes)
        grant.approved_at = _now()

    if request.device_code_id is not None:
        return await _approve_device(session, request, grant)

    # Read out before the row goes, since the redirect is built from it.
    redirect_uri, state = request.redirect_uri, request.state

    raw_code = secrets.token_urlsafe(32)
    await session.execute(delete(OAuthCode).where(OAuthCode.expires < _now()))
    session.add(
        OAuthCode(
            code_hash=_hash(raw_code),
            grant_id=grant.id,
            redirect_uri=redirect_uri,
            scopes=request.scopes,
            code_challenge=request.code_challenge,
            nonce=request.nonce,
            family=secrets.token_urlsafe(16),
            authenticated_at=_now(),
            expires=_now() + CODE_LIFETIME,
        )
    )
    # The request is spent whether or not the exchange succeeds, so a handle
    # cannot be approved twice.
    await session.delete(request)
    await session.commit()

    return Redirect(_redirect_with(redirect_uri, code=raw_code, state=state))


async def _approve_device(
    session: AsyncSession, request: OAuthAuthorizationRequest, grant: OAuthGrant
) -> Redirect:
    """Record consent for a device, which has nowhere to be sent back to.

    An empty :class:`Redirect`, because there is no application address here at
    all -- the device is waiting on its own poll. Where the *browser* goes next
    is a question about the interface, and the route answers it.
    """
    device = await session.get(OAuthDeviceCode, request.device_code_id)
    if device is None or device.expires < _now():
        raise NotFoundError("That device has stopped waiting")

    now = _now()
    device.grant_id = grant.id
    device.approved_at = now
    device.authenticated_at = now
    await session.delete(request)
    await session.commit()
    return Redirect("")


async def deny(session: AsyncSession, handle: str) -> Redirect:
    """Refuse an authorization and tell the application so, as RFC 6749 §4.1.2.1 asks."""
    request = await session.get(OAuthAuthorizationRequest, handle)
    if request is None or request.expires < _now():
        raise NotFoundError("This authorization has expired or was never started")

    if request.device_code_id is not None:
        device = await session.get(OAuthDeviceCode, request.device_code_id)
        if device is not None:
            device.denied_at = _now()
        await session.delete(request)
        await session.commit()
        return Redirect("")

    target = _redirect_with(
        request.redirect_uri,
        error="access_denied",
        error_description="The account holder refused this authorization",
        state=request.state,
    )
    await session.delete(request)
    await session.commit()
    return Redirect(target)


# --------------------------------------------------------------------------
# A device with no browser
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeviceAuthorization:
    """What a device is handed to show and to poll with.

    The URIs are not in here. Building them means knowing where the interface
    is mounted, and that is the web framework's business rather than this
    module's -- see the layering rule in ``CLAUDE.md``.
    """

    device_code: str
    user_code: str
    expires_in: int
    interval: int


def normalise_user_code(raw: str) -> str:
    """Return ``raw`` as it is stored: upper case, with the decoration dropped.

    The dash and the case are there to be read, not to be typed. Somebody
    copying a code off a screen should not have to know which of the two the
    server cares about, so neither survives to the comparison.
    """
    return "".join(character for character in raw.upper() if character in USER_CODE_ALPHABET)


def _user_code() -> str:
    body = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LENGTH))
    return f"{body[: USER_CODE_LENGTH // 2]}-{body[USER_CODE_LENGTH // 2 :]}"


async def begin_device(session: AsyncSession, *, client_id: str, scope: str) -> DeviceAuthorization:
    """Start an authorization for a device that cannot show a browser.

    No redirect URI and no PKCE, because neither has anything to bind to: there
    is no authorization code travelling through a browser to intercept. What
    takes their place is the device code itself, which is long, random, and
    known only to the device that asked for it.
    """
    client = await oauthclients.by_client_id(session, client_id)
    if client is None or client.disabled_at is not None:
        raise OAuthError("invalid_client", "No such client")

    try:
        requested = oauthscopes.validate(scope)
    except InvalidInputError as exc:
        raise OAuthError("invalid_scope", exc.message) from exc

    beyond = [item for item in requested if item not in set(client.scopes.split())]
    if beyond:
        raise OAuthError("invalid_scope", f"{client_id} is not registered for {' '.join(beyond)}")

    await session.execute(delete(OAuthDeviceCode).where(OAuthDeviceCode.expires < _now()))

    raw_device = secrets.token_urlsafe(32)
    raw_user = _user_code()
    session.add(
        OAuthDeviceCode(
            device_code_hash=_hash(raw_device),
            user_code_hash=_hash(normalise_user_code(raw_user)),
            client_id=client.id,
            scopes=" ".join(requested),
            expires=_now() + DEVICE_CODE_LIFETIME,
        )
    )
    await session.commit()
    return DeviceAuthorization(
        device_code=raw_device,
        user_code=raw_user,
        expires_in=int(DEVICE_CODE_LIFETIME.total_seconds()),
        interval=DEVICE_POLL_INTERVAL,
    )


async def claim_user_code(session: AsyncSession, code: str) -> str:
    """Turn a typed user code into an authorization waiting for a decision.

    Returns the handle of an ordinary :class:`~altero.models.oauth.OAuthAuthorizationRequest`,
    so that what happens next is the consent screen every other application
    gets. A second screen written for devices would be a second place for the
    two to disagree about what is being granted.

    A code that has expired, been answered already or been spent is not found,
    in those words: which of them it was is nothing the person typing needs to
    be told, and saying would let somebody sweep for live codes.
    """
    row = await session.scalar(
        select(OAuthDeviceCode).where(
            OAuthDeviceCode.user_code_hash == _hash(normalise_user_code(code))
        )
    )
    if row is None or row.expires < _now():
        raise NotFoundError("No device is waiting for that code")
    if row.approved_at is not None or row.denied_at is not None or row.consumed_at is not None:
        raise NotFoundError("No device is waiting for that code")

    client = await session.get(OAuthClient, row.client_id)
    if client is None or client.disabled_at is not None:
        raise NotFoundError("No device is waiting for that code")

    pending_request = OAuthAuthorizationRequest(
        handle=secrets.token_urlsafe(32),
        client_id=row.client_id,
        # A device has no address to be sent back to, which is the point of the
        # flow. Empty rather than absent so the column keeps its shape.
        redirect_uri="",
        scopes=row.scopes,
        device_code_id=row.id,
        expires=_now() + REQUEST_LIFETIME,
    )
    session.add(pending_request)
    await session.commit()
    return pending_request.handle


async def exchange_device(
    session: AsyncSession,
    *,
    client_id: str,
    client_secret: str | None,
    device_code: str,
    public_url: str,
) -> dict[str, object]:
    """Answer a device asking whether it has been authorized yet.

    Four of the five answers are errors, and they are different errors on
    purpose: ``authorization_pending`` means keep asking, ``slow_down`` means
    keep asking less often, and ``expired_token`` and ``access_denied`` both
    mean stop. A device that cannot tell those apart either gives up on a
    person who is still walking to their laptop or polls forever.
    """
    client = await _authenticated_client(session, client_id, client_secret)

    row = await session.scalar(
        select(OAuthDeviceCode).where(OAuthDeviceCode.device_code_hash == _hash(device_code))
    )
    if row is None or row.client_id != client.id:
        raise OAuthError("invalid_grant", "No such device code")
    if row.consumed_at is not None:
        raise OAuthError("invalid_grant", "This device code has already been exchanged")
    if row.expires < _now():
        raise OAuthError("expired_token", "This device code has expired; ask for another")

    asked_before, asking_now = row.last_polled, _now()
    row.last_polled = asking_now
    if asked_before is not None and (asking_now - asked_before).total_seconds() < (
        DEVICE_POLL_INTERVAL
    ):
        # Committed before raising, or the note of this attempt is rolled back
        # with the request and the next one looks like the first again.
        await session.commit()
        raise OAuthError("slow_down", f"Ask at most every {DEVICE_POLL_INTERVAL} seconds")

    if row.denied_at is not None:
        await session.commit()
        raise OAuthError("access_denied", "The account holder refused this authorization")
    if row.approved_at is None or row.grant_id is None:
        await session.commit()
        raise OAuthError("authorization_pending", "Nobody has answered yet")

    grant = await session.get(OAuthGrant, row.grant_id)
    if grant is None:
        raise OAuthError("invalid_grant", "That authorization has been withdrawn")
    user = await session.get(User, grant.user_id)
    if user is None or user.disabled_at is not None:
        raise OAuthError("invalid_grant", "This account is not active")

    row.consumed_at = _now()
    raw_access, raw_refresh = await _issue_pair(
        session, grant, row.scopes, secrets.token_urlsafe(16)
    )
    payload: dict[str, object] = {
        "access_token": raw_access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_LIFETIME.total_seconds()),
        "refresh_token": raw_refresh,
        "scope": row.scopes,
    }
    if oauthscopes.OPENID in row.scopes.split():
        payload["id_token"] = await _id_token(
            session,
            user=user,
            client=client,
            scopes=row.scopes,
            nonce="",
            authenticated_at=row.authenticated_at or row.approved_at or _now(),
            access_token=raw_access,
            public_url=public_url,
        )
    await session.commit()
    return payload


# --------------------------------------------------------------------------
# Signing out because an application asked
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Logout:
    """A logout an application has asked for, once it has been believed."""

    #: The account the hint was issued for. The session is ended only if it is
    #: this one's -- OpenID Connect RP-Initiated Logout 1.0 §2 is explicit that
    #: somebody else's must not be, and an application holding a stale token
    #: for one account should not sign out whoever is at the browser now.
    user_id: int
    #: Where to send the browser afterwards, already matched against the
    #: client's registration.
    redirect: Redirect | None


async def end_session(
    session: AsyncSession,
    *,
    id_token_hint: str,
    client_id: str,
    post_logout_redirect_uri: str,
    state: str,
    public_url: str,
) -> Logout:
    """Check a logout request, or refuse it. Ends nothing itself.

    **The hint is required**, which OpenID Connect RP-Initiated Logout 1.0 §3
    only recommends. This endpoint is a navigation, so any page on the internet
    can send a browser to it, and without something the caller could only have
    got from this server it would be a way of signing strangers out of their
    library from a hidden image. An ID token is exactly that thing: it was
    issued to an application, over TLS, at the token endpoint.

    Its signature is verified against this server's own keys and its issuer
    against this server's own name. Expiry is *not* checked, per §2: an ID
    token lives an hour and somebody signs out whenever they decide to.
    """
    issued_by = issuer(public_url)
    keys = {row.kid: row.private_pem for row in await _all_signing_keys(session)}
    if not id_token_hint:
        raise InvalidInputError(
            "id_token_hint is required to sign out here. Without it this address "
            "would sign people out on any page's say-so."
        )
    try:
        claims = jws.verify(id_token_hint, keys)
    except ValueError as exc:
        raise InvalidInputError(f"That is not an ID token this server issued: {exc}") from exc

    if claims.get("iss") != issued_by:
        raise InvalidInputError("That ID token was issued somewhere else")

    audience = claims.get("aud")
    named = client_id or (audience if isinstance(audience, str) else "")
    if not isinstance(audience, str) or named != audience:
        raise InvalidInputError("That ID token was issued for a different application")
    client = await oauthclients.by_client_id(session, audience)
    if client is None:
        raise InvalidInputError(
            "That ID token was issued for an application that is not registered"
        )

    try:
        user_id = int(str(claims.get("sub", "")))
    except ValueError as exc:
        raise InvalidInputError("That ID token names nobody") from exc

    if not post_logout_redirect_uri:
        return Logout(user_id=user_id, redirect=None)
    if not oauthclients.post_logout_uri_permitted(client, post_logout_redirect_uri):
        # Refused here rather than obeyed, and deliberately not bounced off the
        # address that was refused -- the same rule the authorization endpoint
        # follows, and for the same reason.
        raise InvalidInputError(
            f"{post_logout_redirect_uri} is not a post-logout address registered for "
            f"{client.client_id}. Ask whoever runs this server to add it."
        )
    return Logout(
        user_id=user_id, redirect=Redirect(_redirect_with(post_logout_redirect_uri, state=state))
    )


async def _all_signing_keys(session: AsyncSession) -> list[OAuthSigningKey]:
    """Return every key, retired included: a hint may outlive a rotation."""
    return list(await session.scalars(select(OAuthSigningKey)))


# --------------------------------------------------------------------------
# Issuing tokens
# --------------------------------------------------------------------------


def verify_challenge(verifier: str, challenge: str) -> bool:
    """Return whether ``verifier`` is the pre-image of ``challenge`` under S256.

    RFC 7636 §4.6. Compared with :func:`secrets.compare_digest` because the
    challenge is public and the verifier is not, so the comparison is between a
    secret and something an attacker can vary.
    """
    if not verifier or not challenge:
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return secrets.compare_digest(jws.b64url(digest), challenge.rstrip("="))


async def _issue_pair(
    session: AsyncSession, grant: OAuthGrant, scopes: str, family: str
) -> tuple[str, str]:
    raw_access = ACCESS_PREFIX + secrets.token_urlsafe(32)
    raw_refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
    now = _now()
    session.add(
        OAuthToken(
            kind="access",
            token_hash=_hash(raw_access),
            grant_id=grant.id,
            family=family,
            scopes=scopes,
            expires=now + ACCESS_LIFETIME,
        )
    )
    session.add(
        OAuthToken(
            kind="refresh",
            token_hash=_hash(raw_refresh),
            grant_id=grant.id,
            family=family,
            scopes=scopes,
            expires=now + REFRESH_LIFETIME,
        )
    )
    return raw_access, raw_refresh


async def _burn_family(session: AsyncSession, family: str) -> None:
    """Revoke every token descended from one authorization.

    Called when a credential is presented that should have been spent. There is
    no telling whether the replay came from the application or from whoever took
    a copy, so the only safe answer is that neither of them keeps working.
    """
    tokens = await session.scalars(
        select(OAuthToken).where(OAuthToken.family == family, OAuthToken.revoked_at.is_(None))
    )
    now = _now()
    for token in tokens:
        token.revoked_at = now


async def group_names(session: AsyncSession, user_id: int) -> list[str]:
    """Return the names of the groups ``user_id`` belongs to.

    Names rather than identifiers, because the only thing this claim is for is
    a relying party's role mapping, and those are written by somebody in a
    configuration file: ``altero_groups = Reading Group`` is a rule that can be
    checked by reading it, where a list of integers is one that cannot. Group
    names are not unique on an instance -- ``docs/oauth.md`` says so, since a
    deployment mapping roles from them has to keep them distinct.

    Membership and nothing else. A public group somebody has never joined is
    not in the list, the same way it is not in ``GET /users/<id>/groups``.
    """
    return [group.name for _, group, _ in await groups.list_groups_for_user(session, user_id)]


async def _id_token(
    session: AsyncSession,
    *,
    user: User,
    client: OAuthClient,
    scopes: str,
    nonce: str,
    authenticated_at: datetime,
    access_token: str,
    public_url: str,
) -> str:
    key = await signing_key(session)
    now = _now()
    granted = set(scopes.split())
    claims: dict[str, object] = {
        "iss": issuer(public_url),
        "sub": str(user.id),
        "aud": client.client_id,
        "iat": int(now.replace(tzinfo=UTC).timestamp()),
        "exp": int((now + ACCESS_LIFETIME).replace(tzinfo=UTC).timestamp()),
        "auth_time": int(authenticated_at.replace(tzinfo=UTC).timestamp()),
        "at_hash": jws.access_token_hash(access_token),
    }
    if nonce:
        claims["nonce"] = nonce
    if oauthscopes.PROFILE in granted:
        claims["preferred_username"] = user.username
        claims["name"] = user.display_name or user.username
    if oauthscopes.EMAIL in granted and user.email:
        claims["email"] = user.email
        # Stated rather than assumed. An unverified address is exactly the claim
        # that must not be treated as an identity -- services/federation.py says
        # why at length from the other side of this protocol.
        claims["email_verified"] = user.email_verified is not None
    if oauthscopes.GROUPS in granted:
        # Present and empty rather than omitted for an account in no group: a
        # relying party mapping roles has to tell "belongs to nothing" from
        # "this server did not say", and an absent claim is the second one.
        claims["groups"] = await group_names(session, user.id)
    return jws.sign(claims, key.private_pem, key.kid)


async def exchange(
    session: AsyncSession,
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    public_url: str,
) -> dict[str, object]:
    """Exchange an authorization code for tokens."""
    client = await _authenticated_client(session, client_id, client_secret)

    row = await session.scalar(select(OAuthCode).where(OAuthCode.code_hash == _hash(code)))
    if row is None:
        raise OAuthError("invalid_grant", "No such authorization code")

    grant = await session.get(OAuthGrant, row.grant_id)
    if grant is None or grant.client_id != client.id:
        # A code minted for one application, presented by another. Refused with
        # the same words as an unknown code: which of the two it was is not
        # something the caller has any business learning.
        raise OAuthError("invalid_grant", "No such authorization code")

    if row.consumed_at is not None:
        await _burn_family(session, row.family)
        await session.commit()
        raise OAuthError(
            "invalid_grant",
            "This authorization code has already been used. Everything issued "
            "from it has been revoked.",
        )

    if row.expires < _now():
        raise OAuthError("invalid_grant", "This authorization code has expired")
    if row.redirect_uri != redirect_uri:
        raise OAuthError("invalid_grant", "redirect_uri does not match the one the code was for")
    if not verify_challenge(code_verifier, row.code_challenge):
        raise OAuthError("invalid_grant", "code_verifier does not match the challenge")

    user = await session.get(User, grant.user_id)
    if user is None or user.disabled_at is not None:
        raise OAuthError("invalid_grant", "This account is not active")

    row.consumed_at = _now()
    raw_access, raw_refresh = await _issue_pair(session, grant, row.scopes, row.family)

    payload: dict[str, object] = {
        "access_token": raw_access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_LIFETIME.total_seconds()),
        "refresh_token": raw_refresh,
        "scope": row.scopes,
    }
    if oauthscopes.OPENID in row.scopes.split():
        payload["id_token"] = await _id_token(
            session,
            user=user,
            client=client,
            scopes=row.scopes,
            nonce=row.nonce,
            authenticated_at=row.authenticated_at,
            access_token=raw_access,
            public_url=public_url,
        )
    await session.commit()
    return payload


async def refresh(
    session: AsyncSession,
    *,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
    public_url: str,
) -> dict[str, object]:
    """Rotate a refresh token, issuing a fresh pair in the same family."""
    client = await _authenticated_client(session, client_id, client_secret)

    row = await session.scalar(
        select(OAuthToken).where(
            OAuthToken.token_hash == _hash(refresh_token), OAuthToken.kind == "refresh"
        )
    )
    if row is None:
        raise OAuthError("invalid_grant", "No such refresh token")

    grant = await session.get(OAuthGrant, row.grant_id)
    if grant is None or grant.client_id != client.id:
        raise OAuthError("invalid_grant", "No such refresh token")

    if row.revoked_at is not None:
        # Presented after it was rotated away: somebody has a copy. Which of the
        # two callers is the thief is unknowable, so the family goes and both
        # have to start again.
        await _burn_family(session, row.family)
        await session.commit()
        raise OAuthError(
            "invalid_grant",
            "This refresh token was already used. Everything in its family has been revoked.",
        )
    if row.expires < _now():
        raise OAuthError("invalid_grant", "This refresh token has expired")

    user = await session.get(User, grant.user_id)
    if user is None or user.disabled_at is not None:
        raise OAuthError("invalid_grant", "This account is not active")

    row.revoked_at = _now()
    # The scopes come from the token, never from the request: RFC 6749 §6 allows
    # a refresh to narrow and never to widen, and narrowing is not worth the
    # surface here.
    raw_access, raw_refresh = await _issue_pair(session, grant, row.scopes, row.family)
    await session.commit()
    return {
        "access_token": raw_access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_LIFETIME.total_seconds()),
        "refresh_token": raw_refresh,
        "scope": row.scopes,
    }


async def _authenticated_client(
    session: AsyncSession, client_id: str, client_secret: str | None
) -> OAuthClient:
    client = await oauthclients.by_client_id(session, client_id)
    if client is None or client.disabled_at is not None:
        raise OAuthError("invalid_client", "No such client")
    if not oauthclients.verify_secret(client, client_secret):
        raise OAuthError("invalid_client", "The client secret is wrong")
    return client


async def revoke(session: AsyncSession, *, client_id: str, token: str) -> None:
    """Revoke a token, as RFC 7009 asks.

    Presenting the token is the authorization to revoke it, so a token that
    does not resolve is not an error: §2.2 requires 200 either way, because
    telling a caller that a token it holds is unknown here is telling it
    something about somebody else's token.
    """
    client = await oauthclients.by_client_id(session, client_id)
    if client is None:
        return

    row = await session.scalar(select(OAuthToken).where(OAuthToken.token_hash == _hash(token)))
    if row is None:
        return

    grant = await session.get(OAuthGrant, row.grant_id)
    if grant is None or grant.client_id != client.id:
        return

    if row.kind == "refresh":
        await _burn_family(session, row.family)
    else:
        row.revoked_at = _now()
    await session.commit()


@dataclass(frozen=True, slots=True)
class TokenIdentity:
    """A resolved access token: who it speaks for and what it may do."""

    user_id: int
    scopes: str
    grant_id: int


async def resolve_access_token(session: AsyncSession, raw: str) -> TokenIdentity | None:
    """Return who ``raw`` speaks for, or ``None`` if it is not a live access token.

    ``None`` rather than an error, because the caller
    (:func:`altero.services.auth.authenticate`) has an API key to try as well
    and only it knows whether anything is left to try.
    """
    if not raw.startswith(ACCESS_PREFIX):
        return None

    row = await session.scalar(
        select(OAuthToken).where(
            OAuthToken.token_hash == _hash(raw),
            OAuthToken.kind == "access",
            OAuthToken.revoked_at.is_(None),
            OAuthToken.expires > _now(),
        )
    )
    if row is None:
        return None

    grant = await session.get(OAuthGrant, row.grant_id)
    if grant is None:
        return None
    return TokenIdentity(user_id=grant.user_id, scopes=row.scopes, grant_id=grant.id)


# --------------------------------------------------------------------------
# What a person can see and take back
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Authorization:
    """One application a person has connected, as the interface lists it."""

    id: int
    client_id: str
    name: str
    description: str
    scopes: list[str]
    approved: datetime
    #: Live access tokens, so "this is in use" can be told from "this was
    #: authorized once and forgotten".
    active_tokens: int


async def authorizations(session: AsyncSession, user: User) -> list[Authorization]:
    """Return every application ``user`` has authorized, most recent first."""
    rows = await session.execute(
        select(OAuthGrant, OAuthClient)
        .join(OAuthClient, OAuthClient.id == OAuthGrant.client_id)
        .where(OAuthGrant.user_id == user.id)
        .order_by(OAuthGrant.approved_at.desc())
    )
    listed = []
    for grant, client in rows:
        live = await session.scalars(
            select(OAuthToken).where(
                OAuthToken.grant_id == grant.id,
                OAuthToken.kind == "access",
                OAuthToken.revoked_at.is_(None),
                OAuthToken.expires > _now(),
            )
        )
        listed.append(
            Authorization(
                id=grant.id,
                client_id=client.client_id,
                name=client.name,
                description=client.description,
                scopes=grant.scopes.split(),
                approved=grant.approved_at,
                active_tokens=len(list(live)),
            )
        )
    return listed


async def withdraw(session: AsyncSession, user: User, grant_id: int) -> None:
    """Disconnect an application.

    The grant goes and the codes and tokens go with it, by the cascade on the
    foreign key: a person who has decided an application should stop working
    means now, not when its access token happens to expire.
    """
    grant = await session.get(OAuthGrant, grant_id)
    if grant is None or grant.user_id != user.id:
        raise NotFoundError("No such authorization")
    await session.delete(grant)
    await session.commit()


async def prune(session: AsyncSession) -> int:
    """Delete spent and expired codes and tokens, returning how many rows went.

    Called by the retention sweep. Nothing here is load-bearing once it has
    expired, and a table that only grows is a table somebody eventually finds
    the hard way.
    """
    now = _now()
    removed = 0
    for statement in (
        delete(OAuthAuthorizationRequest).where(OAuthAuthorizationRequest.expires < now),
        delete(OAuthCode).where(OAuthCode.expires < now),
        delete(OAuthDeviceCode).where(OAuthDeviceCode.expires < now),
        delete(OAuthToken).where(OAuthToken.expires < now),
    ):
        result = await session.execute(statement)
        removed += getattr(result, "rowcount", 0) or 0
    await session.commit()
    return removed
