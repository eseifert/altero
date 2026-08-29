"""Applications an administrator has registered, and the addresses they may use.

This module is the answer to the one question an authorization server must not
get wrong: *where may the authorization code be sent?* The code travels through
the browser, and the only thing that keeps it from travelling to somebody else
is that its destination was written down here before the request arrived.
Nothing self-registers, and nothing is accepted because it was presented.

Registration is an administrator's act, from the command line, for the same
reason a group's policy is: it is a decision about the instance rather than a
use of it. An instance with no clients registered has an authorization server
that will not issue anything, which is the correct resting state.
"""

import secrets
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models.oauth import OAuthClient
from altero.services import oauthscopes, passwords

#: Hosts for which RFC 8252 §7.3 requires the port to be ignored when matching.
#: A native application listens on whatever port the operating system gave it,
#: so it cannot register one; everything else about the address still has to
#: match exactly. ``localhost`` is in the list because clients use it despite
#: the RFC preferring the literal, and refusing it produces a puzzling failure
#: rather than a secure one -- it resolves to the loopback interface either way.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _split(uris: str) -> list[str]:
    return [line.strip() for line in uris.splitlines() if line.strip()]


def validate_redirect_uri(uri: str) -> str:
    """Return ``uri`` if it is one an authorization code may be sent to.

    Three refusals, and each is a way the flow is broken in the wild:

    A URI with a fragment, because the fragment is where an implicit-flow
    response would go and this server has no implicit flow; one arriving here
    means the application is confused about which flow it is in.

    A relative URI, because "the browser will work it out" is exactly the
    ambiguity that lets a mistake resolve somewhere unintended.

    Plain ``http`` to anywhere but the loopback interface, because the code is
    the credential and a network that can read it can spend it. Loopback is the
    documented exception: a native application has no certificate and the
    traffic never leaves the machine.
    """
    parsed = urlparse(uri)
    if parsed.fragment:
        raise InvalidInputError(f"{uri} has a fragment; a redirect URI may not")
    if not parsed.scheme or not parsed.netloc:
        if not parsed.scheme:
            raise InvalidInputError(f"{uri} is not absolute; a redirect URI must be")
        # A private-use scheme -- com.example.app:/callback -- is how a mobile
        # application is reached, and RFC 8252 §7.1 endorses it. It has no
        # authority component by design.
        if ":" not in uri:
            raise InvalidInputError(f"{uri} is not a redirect URI")
        return uri
    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
        raise InvalidInputError(
            f"{uri} is plain http; an authorization code may only be sent over https, "
            "or to the loopback interface"
        )
    return uri


def _without_port(uri: str) -> str:
    parsed = urlparse(uri)
    host = f"[{parsed.hostname}]" if parsed.hostname and ":" in parsed.hostname else parsed.hostname
    return urlunparse(parsed._replace(netloc=host or ""))


def _matches(registered: list[str], uri: str) -> bool:
    """Return whether ``uri`` is one of ``registered``.

    Exact string comparison, with one exception: where the registered address is
    on the loopback interface, the port is ignored on both sides. RFC 8252 §7.3
    requires that, because a native application is given an ephemeral port by
    the operating system and cannot have registered it. Everything else --
    scheme, host, path, query -- still has to match exactly, so the exception
    widens the loopback interface and nothing beyond it.
    """
    if uri in registered:
        return True

    presented = urlparse(uri)
    if presented.scheme != "http" or presented.hostname not in LOOPBACK_HOSTS:
        return False

    stripped = _without_port(uri)
    return any(
        urlparse(candidate).scheme == "http"
        and urlparse(candidate).hostname in LOOPBACK_HOSTS
        and _without_port(candidate) == stripped
        for candidate in registered
    )


def post_logout_uri_permitted(client: OAuthClient, uri: str) -> bool:
    """Return whether ``uri`` is somewhere ``client`` may send a person after signing out.

    Matched the same way a redirect URI is, loopback exception included, and
    against its own list. A landing page receives no credential, so the stakes
    are lower -- but an address accepted because it was presented is an open
    redirector on this server's origin whatever it receives, and that is the
    thing being refused.
    """
    registered = _split(client.post_logout_redirect_uris)
    if not registered:
        return False
    return _matches(registered, uri)


def redirect_uri_permitted(client: OAuthClient, uri: str) -> bool:
    """Return whether ``uri`` is one of ``client``'s registered addresses."""
    return _matches(_split(client.redirect_uris), uri)


async def by_client_id(session: AsyncSession, client_id: str) -> OAuthClient | None:
    """Return the registration ``client_id`` names, or ``None``."""
    return await session.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))


async def require(session: AsyncSession, client_id: str) -> OAuthClient:
    """Return the registration ``client_id`` names, or refuse.

    A disabled client is refused here rather than further in, so that turning
    one off stops every part of the flow at once -- an application already
    holding a refresh token cannot rotate it either.
    """
    client = await by_client_id(session, client_id)
    if client is None or client.disabled_at is not None:
        raise NotFoundError("No such client")
    return client


async def create(
    session: AsyncSession,
    *,
    client_id: str,
    name: str,
    redirect_uris: list[str],
    scopes: str,
    description: str = "",
    confidential: bool = False,
    post_logout_redirect_uris: list[str] | None = None,
) -> tuple[OAuthClient, str | None]:
    """Register an application, returning it and its secret if it has one.

    The secret is returned once and stored only as a hash, the same bargain
    ``altero key add`` makes. A public client -- a browser or desktop
    application, which cannot keep a secret whatever it claims -- gets none and
    is held up by PKCE, which is required of every client here regardless.
    """
    if await by_client_id(session, client_id) is not None:
        raise InvalidInputError(f"A client called {client_id} is already registered")
    if not redirect_uris:
        raise InvalidInputError("A client needs at least one redirect URI")

    for uri in redirect_uris:
        validate_redirect_uri(uri)
    for uri in post_logout_redirect_uris or []:
        validate_redirect_uri(uri)
    permitted = " ".join(oauthscopes.validate(scopes))

    raw_secret: str | None = None
    secret_hash: str | None = None
    if confidential:
        raw_secret = secrets.token_urlsafe(32)
        secret_hash = passwords.hash_password(raw_secret)

    client = OAuthClient(
        client_id=client_id,
        name=name or client_id,
        secret_hash=secret_hash,
        redirect_uris="\n".join(redirect_uris),
        post_logout_redirect_uris="\n".join(post_logout_redirect_uris or []),
        scopes=permitted,
        description=description,
    )
    session.add(client)
    await session.commit()
    return client, raw_secret


def verify_secret(client: OAuthClient, secret: str | None) -> bool:
    """Return whether ``secret`` authenticates ``client``.

    A public client has no secret and authenticates by nothing at all, which is
    what PKCE is for. A confidential one must present its own; a *missing*
    secret for a confidential client is checked against a dummy hash rather than
    short-circuited, so the answer takes the same time either way.
    """
    if client.secret_hash is None:
        return True
    return passwords.verify_password(client.secret_hash, secret or "")


async def all_clients(session: AsyncSession) -> list[OAuthClient]:
    """Return every registration, newest last, for the command line to print."""
    result = await session.scalars(select(OAuthClient).order_by(OAuthClient.created))
    return list(result)
