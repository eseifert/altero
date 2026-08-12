"""Talking OpenID Connect to somebody else's directory.

The second place altero makes outbound requests, after
:mod:`altero.services.zoteroapi`, and it gets the same treatment: one module,
one client, and nothing else in the codebase reaching the network.

**Authorization code with PKCE, confidential client.** No implicit flow and no
hybrid flow: both put tokens in the browser, where this application has no need
of them, and both are the ones the specification's own security guidance now
advises against.

**The ID token's signature is not verified, and that is deliberate.** The token
is fetched by altero directly from the token endpoint over TLS, which is the
case OpenID Connect Core §3.1.3.7 item 6 permits to be validated by the
connection rather than by the signature -- "If the ID Token is received via
direct communication between the Client and the Token Endpoint, the TLS server
validation MAY be used to validate the issuer in place of checking the token
signature." Taking that path means altero carries no JWS implementation and
therefore none of the ways one goes wrong: no ``alg: none``, no HMAC-versus-RSA
confusion, no key selected by an attacker-supplied ``kid``.

What it *does* rest on is the two conditions that make the exemption sound, and
they are checked rather than assumed: the client is confidential (there is a
secret) and the token came from the token endpoint on this connection. Every
*claim* check is still made, and that is where the security actually lives --
see :func:`validate_claims`. If a public client is ever wanted here, this
decision has to be revisited and a signature verifier written first;
``docs/compatibility.md`` records that.
"""

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import IdentityProvider

logger = logging.getLogger("altero.oidc")

#: How long a cached discovery document stands before it is fetched again.
DISCOVERY_MAX_AGE = timedelta(hours=24)

#: How long a sign-in may take between leaving here and coming back. Long
#: enough to type a password and answer a push notification, short enough that
#: a state left in a browser history is not usable tomorrow.
REQUEST_LIFETIME = timedelta(minutes=15)

#: Clock skew allowed on ``exp`` and ``iat``. Directories and servers disagree
#: by seconds, and refusing a token for that would be an outage nobody can
#: diagnose from this side.
CLOCK_SKEW = timedelta(minutes=5)

#: How long to wait on a directory. A person is watching a redirect.
TIMEOUT_SECONDS = 15

#: Always requested; the rest is the provider's ``scopes``.
BASE_SCOPE = "openid"


@dataclass(frozen=True, slots=True)
class Discovery:
    """The endpoints a provider publishes."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str = ""


@dataclass(frozen=True, slots=True)
class Assertion:
    """What a completed sign-in established about somebody.

    ``claims`` is everything the directory said, kept whole because the
    required-claim check is configured by name and cannot know in advance which
    ones matter.
    """

    subject: str
    username: str
    display_name: str
    email: str
    claims: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def discovery_url(issuer: str) -> str:
    """Return where a provider's configuration hangs off its issuer."""
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def needs_discovery(provider: IdentityProvider, *, now: datetime | None = None) -> bool:
    """Return whether this provider's endpoints should be fetched again.

    Refetched on an interval rather than once, so a directory that moves an
    endpoint is followed without anybody having to notice and re-save the
    configuration.
    """
    if not provider.authorization_endpoint or not provider.token_endpoint:
        return True
    if provider.discovered is None:
        return True
    return (now or _now()) - provider.discovered > DISCOVERY_MAX_AGE


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    return secrets.token_urlsafe(24)


def generate_verifier() -> str:
    """Return a PKCE code verifier, within RFC 7636's 43-128 characters."""
    return secrets.token_urlsafe(64)[:128]


def challenge_for(verifier: str) -> str:
    """Return the S256 challenge for ``verifier``.

    S256 and never ``plain``: a ``plain`` challenge is the verifier, so an
    attacker who can read the authorization request can complete the exchange,
    which is the whole thing PKCE exists to stop.
    """
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _decode_segment(segment: str) -> dict[str, Any]:
    """Return the JSON in one base64url JWT segment."""
    import json

    padded = segment + "=" * (-len(segment) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError) as broken:
        raise ForbiddenError("The identity provider returned a token we cannot read") from broken


def read_id_token(token: str) -> dict[str, Any]:
    """Return the claims in an ID token, without checking its signature.

    See this module's docstring for why that is sound here and what it rests
    on. The parsing is deliberately minimal: nothing in the header is read, so
    there is no ``alg`` for anybody to lie about.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ForbiddenError("The identity provider returned a token we cannot read")
    return _decode_segment(parts[1])


def validate_claims(
    claims: dict[str, Any],
    provider: IdentityProvider,
    *,
    nonce: str,
    now: datetime | None = None,
) -> None:
    """Raise unless these claims belong to this request and this client.

    This is where the security of the whole exchange sits, given that the
    signature is not checked. Each of these has a job:

    ``iss``
        The token came from the directory we configured, not another one.
    ``aud`` and ``azp``
        It was minted for *this* client. Without it, a token any other client
        of the same directory obtained would sign its holder in here.
    ``nonce``
        It answers *this* request. Without it, a token captured from an earlier
        sign-in could be replayed.
    ``exp`` and ``iat``
        It is current.
    ``sub``
        There is somebody to be.
    """
    moment = now or _now()

    if claims.get("iss") != provider.issuer:
        raise ForbiddenError("That sign-in came from a different identity provider")

    audience = claims.get("aud")
    allowed = audience if isinstance(audience, list) else [audience]
    if provider.client_id not in allowed:
        raise ForbiddenError("That sign-in was not issued for this server")

    # Required by the specification only when there are several audiences, but
    # checked whenever it is present: a token that names another party as the
    # authorized one is not ours to accept.
    party = claims.get("azp")
    if party is not None and party != provider.client_id:
        raise ForbiddenError("That sign-in was not issued for this server")

    if not nonce or claims.get("nonce") != nonce:
        raise ForbiddenError("That sign-in does not answer this request")

    expires = claims.get("exp")
    if not isinstance(expires, int | float):
        raise ForbiddenError("That sign-in has no expiry")
    if datetime.fromtimestamp(expires, UTC).replace(tzinfo=None) < moment - CLOCK_SKEW:
        raise ForbiddenError("That sign-in has expired")

    issued = claims.get("iat")
    if isinstance(issued, int | float):
        when = datetime.fromtimestamp(issued, UTC).replace(tzinfo=None)
        if when > moment + CLOCK_SKEW:
            raise ForbiddenError("That sign-in is dated in the future")

    if not claims.get("sub"):
        raise ForbiddenError("That sign-in names nobody")


def _text(claims: dict[str, Any], name: str) -> str:
    """Return a claim as a string, or empty. Never raises on an odd shape."""
    value = claims.get(name)
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return ""


def assertion_from(claims: dict[str, Any], provider: IdentityProvider) -> Assertion:
    """Read the configured claims out, falling back where a directory omits one."""
    subject = _text(claims, "sub")
    username = _text(claims, provider.username_claim) or subject
    return Assertion(
        subject=subject,
        username=username,
        display_name=_text(claims, provider.name_claim) or username,
        email=_text(claims, provider.email_claim).lower(),
        claims=claims,
    )


def satisfies_requirement(claims: dict[str, Any], provider: IdentityProvider) -> bool:
    """Return whether these claims carry what the provider insists on.

    The claim may be a string or a list, because directories send group
    membership both ways -- one string when there is one group, a list when
    there are several -- and an instance that handled only one would suspend
    everybody the day somebody joined a second group.

    A provider naming no claim requires nothing, which is the default.
    """
    if not provider.required_claim:
        return True

    value = claims.get(provider.required_claim)
    if value is None:
        return False

    wanted = provider.required_value
    if not wanted:
        # The claim merely has to be there and non-empty.
        return bool(value)

    if isinstance(value, list):
        return wanted in [str(entry) for entry in value]
    return str(value) == wanted


class Client:
    """The one thing here that makes network calls."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def discover(self, issuer: str) -> Discovery:
        """Fetch a provider's published configuration."""
        try:
            response = await self.client.get(discovery_url(issuer), timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as failure:
            logger.warning("Could not read the configuration at %s: %s", issuer, failure)
            raise InvalidInputError(
                f"Could not read an OpenID configuration from {issuer}"
            ) from failure

        missing = [
            name
            for name in ("issuer", "authorization_endpoint", "token_endpoint")
            if not document.get(name)
        ]
        if missing:
            raise InvalidInputError(
                f"The configuration at {issuer} is missing {', '.join(missing)}"
            )

        # Checked here rather than at every sign-in: a document whose issuer
        # disagrees with where it was fetched from is the shape of a mix-up
        # attack, and refusing it once at configuration time is kinder than
        # refusing every sign-in later.
        if document["issuer"].rstrip("/") != issuer.rstrip("/"):
            raise InvalidInputError(
                f"The configuration at {issuer} claims to be for {document['issuer']}"
            )

        return Discovery(
            issuer=document["issuer"],
            authorization_endpoint=document["authorization_endpoint"],
            token_endpoint=document["token_endpoint"],
            userinfo_endpoint=document.get("userinfo_endpoint", ""),
        )

    async def exchange(
        self,
        provider: IdentityProvider,
        *,
        code: str,
        verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Trade an authorization code for tokens, on the back channel.

        The secret goes in the body rather than in a Basic header because more
        directories accept it there than accept either alone, and both are
        permitted. It never leaves this call.
        """
        try:
            response = await self.client.post(
                provider.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": provider.client_id,
                    "client_secret": provider.client_secret,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as failure:
            logger.warning("Could not reach %s: %s", provider.token_endpoint, failure)
            raise ForbiddenError("Could not reach the identity provider") from failure

        if response.status_code >= 400:
            # The body carries the directory's own reason and is logged, but is
            # not passed on: it is written for whoever configured the client,
            # not for whoever is trying to sign in.
            logger.warning(
                "%s refused the code exchange: %s %s",
                provider.slug,
                response.status_code,
                response.text[:500],
            )
            raise ForbiddenError("The identity provider refused that sign-in")

        try:
            return response.json()
        except ValueError as broken:
            raise ForbiddenError("The identity provider answered with something unreadable") from (
                broken
            )

    async def userinfo(self, provider: IdentityProvider, access_token: str) -> dict[str, Any]:
        """Fetch the UserInfo claims, or return nothing.

        Best effort on purpose. The ID token already carries what is needed to
        sign somebody in, and a directory that omits an optional endpoint, or
        one that is briefly down, should not turn a valid sign-in into a
        failure. Where it answers, its claims fill gaps the token left.
        """
        if not provider.userinfo_endpoint:
            return {}
        try:
            response = await self.client.get(
                provider.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            claims = response.json()
        except (httpx.HTTPError, ValueError) as failure:
            logger.info("UserInfo at %s did not answer: %s", provider.slug, failure)
            return {}
        return claims if isinstance(claims, dict) else {}


def authorization_url(
    provider: IdentityProvider,
    *,
    redirect_uri: str,
    state: str,
    nonce: str,
    verifier: str,
    prompt: str | None = None,
) -> str:
    """Return where to send the browser to sign in.

    ``prompt="login"`` is what re-authentication asks for: an account with no
    password here has nothing to type into a "current password" field, and
    making the directory ask again is the equivalent proof.
    """
    scope = " ".join(dict.fromkeys([BASE_SCOPE, *provider.scopes.split()]))
    parameters = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge_for(verifier),
        "code_challenge_method": "S256",
    }
    if prompt:
        parameters["prompt"] = prompt
    return f"{provider.authorization_endpoint}?{urlencode(parameters)}"
