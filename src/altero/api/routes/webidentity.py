"""Signing in against a directory, and the screens that configure one.

Under ``/web`` like everything cookie-authenticated, and no part of it reaches
the v3 API: what a completed sign-in produces is a browser session, exactly the
one a password produces. A desktop client still holds an API key and still gets
it the way it always did, from a signed-in browser under **Settings → API
keys**. That is the boundary rule doing its job rather than a gap -- the v3 API
takes keys and nothing else, and no amount of federation changes it.

Two routes here answer with **no session and no CSRF token**, and both are
navigations rather than fetches:

``/auth/sso/{slug}/start``
    A browser being sent to the directory. It creates an
    :class:`~altero.models.AuthRequest` row and redirects; it grants nothing,
    and the state it mints is what the callback will insist on.

``/auth/sso/{slug}/callback``
    The browser coming back. It arrives as a top-level ``GET``, so
    ``SameSite=Lax`` cookies *are* sent -- but nothing here reads them for
    authority. The state parameter resolving to a row this server wrote is what
    makes the request genuine, and the row is spent on use.
"""

from typing import Annotated
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Body, Form, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from altero.api.deps import SessionDep
from altero.api.routes.web import (
    AuthenticatedDep,
    CsrfDep,
    CurrentUserDep,
    _set_session_cookies,
)
from altero.api.routes.webadmin import AdministratorDep
from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import AuthRequest, FederatedIdentity, IdentityProvider, User
from altero.services import (
    account,
    authrequests,
    federation,
    identityproviders,
    oidc,
    saml,
    samlreplay,
    websessions,
)

router = APIRouter(prefix="/web", tags=["web"])


class ProviderInput(BaseModel):
    """What the administration screen may set.

    ``clientSecret`` absent leaves the stored one alone, which is what lets the
    screen save every other field without ever being able to read it back.
    """

    slug: str | None = None
    kind: str = "oidc"
    idp_entity_id: str | None = Field(default=None, alias="idpEntityId")
    sso_url: str | None = Field(default=None, alias="ssoUrl")
    certificates: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    enabled: bool | None = None
    issuer: str | None = None
    client_id: str | None = Field(default=None, alias="clientId")
    client_secret: str | None = Field(default=None, alias="clientSecret")
    scopes: str | None = None
    username_claim: str | None = Field(default=None, alias="usernameClaim")
    name_claim: str | None = Field(default=None, alias="nameClaim")
    email_claim: str | None = Field(default=None, alias="emailClaim")
    create_accounts: bool | None = Field(default=None, alias="createAccounts")
    required_claim: str | None = Field(default=None, alias="requiredClaim")
    required_value: str | None = Field(default=None, alias="requiredValue")
    revoke_keys_on_loss: bool | None = Field(default=None, alias="revokeKeysOnLoss")
    current_password: str | None = Field(default=None, alias="currentPassword")

    def values(self) -> dict:
        """Return the fields that were actually sent, by model attribute name."""
        return {
            name: value
            for name, value in self.model_dump(exclude_none=True).items()
            if name in identityproviders.WRITABLE
        }


def redirect_uri(request: Request, slug: str) -> str:
    """Return the absolute callback the directory must be configured with.

    From ``public_url`` where it is set, because behind a proxy the address a
    request arrived on is the proxy's idea of it -- and a redirect URI that
    does not match the one registered at the directory is refused outright,
    with an error page nobody can act on. This is the single most likely thing
    to be misconfigured, which is why the administration screen shows it.
    """
    configured = request.app.state.settings.public_url.rstrip("/")
    base = configured or str(request.base_url).rstrip("/")
    return f"{base}/web/auth/sso/{quote(slug)}/callback"


def acs_url(request: Request, slug: str) -> str:
    """Return where a SAML assertion is to be posted back to.

    Checked against the assertion's own ``Recipient``, so it has to be the
    address the directory was actually configured with -- which is what
    ``public_url`` is for.
    """
    configured = request.app.state.settings.public_url.rstrip("/")
    base = configured or str(request.base_url).rstrip("/")
    return f"{base}/web/auth/saml/{quote(slug)}/acs"


def entity_id(request: Request) -> str:
    """Return this instance's SAML entity id.

    Its own public URL, which is what a service provider's entity id
    conventionally is and is one less thing for an operator to invent and get
    wrong in two places.
    """
    configured = request.app.state.settings.public_url.rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _app_url(request: Request, path: str, **query: str) -> str:
    """Return a URL into the interface, for a redirect out of a route."""
    configured = request.app.state.settings.public_url.rstrip("/")
    base = configured or str(request.base_url).rstrip("/")
    suffix = f"?{urlencode(query)}" if query else ""
    return f"{base}/app{path}{suffix}"


async def _client(request: Request) -> oidc.Client:
    """Return the outbound client, built once per application."""
    existing = getattr(request.app.state, "http_client", None)
    if existing is None:
        existing = httpx.AsyncClient(follow_redirects=False)
        request.app.state.http_client = existing
    return oidc.Client(existing)


async def _ready(request: Request, session: SessionDep, provider: IdentityProvider) -> None:
    """Make sure the provider's endpoints are known and current."""
    if not oidc.needs_discovery(provider):
        return
    found = await (await _client(request)).discover(provider.issuer)
    await identityproviders.record_discovery(
        session,
        provider,
        authorization_endpoint=found.authorization_endpoint,
        token_endpoint=found.token_endpoint,
        userinfo_endpoint=found.userinfo_endpoint,
    )


# --------------------------------------------------------------------------
# Signing in
# --------------------------------------------------------------------------


@router.get("/auth/sso/{slug}/start")
async def start_sign_in(
    request: Request,
    session: SessionDep,
    slug: str,
    next: str = "/library",
    purpose: str = "login",
) -> Response:
    """Send the browser to the directory.

    A redirect rather than JSON, so the interface can use a plain link and the
    browser's own navigation carries it. No CSRF token: there is nothing to
    forge, since completing this grants exactly what signing in grants and the
    person doing it has to authenticate at the directory either way.
    """
    if purpose not in ("login", "link", "reauth"):
        raise InvalidInputError("Unknown purpose")

    try:
        provider = await identityproviders.by_slug(session, slug)
    except NotFoundError:
        return RedirectResponse(_app_url(request, "/sign-in", error="unknown-provider"), 303)
    if not provider.enabled:
        return RedirectResponse(_app_url(request, "/sign-in", error="provider-disabled"), 303)

    # Only a signed-in browser may attach an identity to an account or prove
    # itself again; a stranger asking for either gets an ordinary sign-in.
    user: User | None = None
    if purpose in ("link", "reauth"):
        record = await websessions.lookup(session, request.cookies.get("altero_session"))
        if record is None or not websessions.is_authenticated(record):
            return RedirectResponse(_app_url(request, "/sign-in", error="not-signed-in"), 303)
        user = await session.get(User, record.user_id)

    if provider.kind == "saml":
        if not provider.sso_url or not provider.certificates:
            return RedirectResponse(
                _app_url(request, "/sign-in", error="provider-unreachable"), 303
            )
        pending = await authrequests.create(
            session,
            provider,
            next_path=next if next.startswith("/") else "/library",
            purpose=purpose,
            user_id=user.id if user else None,
            # An xsd:ID rather than a URL-safe token: the value goes into the
            # AuthnRequest's ID attribute, which may not begin with a digit.
            state=saml.generate_request_id(),
        )
        return RedirectResponse(
            saml.authn_request_url(
                provider,
                acs_url=acs_url(request, provider.slug),
                entity_id=entity_id(request),
                request_id=pending.state,
            ),
            status_code=303,
        )

    try:
        await _ready(request, session, provider)
    except InvalidInputError:
        return RedirectResponse(_app_url(request, "/sign-in", error="provider-unreachable"), 303)

    pending = await authrequests.create(
        session,
        provider,
        next_path=next if next.startswith("/") else "/library",
        purpose=purpose,
        user_id=user.id if user else None,
    )
    return RedirectResponse(
        oidc.authorization_url(
            provider,
            redirect_uri=redirect_uri(request, provider.slug),
            state=pending.state,
            nonce=pending.nonce,
            verifier=pending.code_verifier,
            # Re-authentication is asking the directory to establish presence
            # again, so a session it still holds must not answer for it.
            prompt="login" if purpose == "reauth" else None,
        ),
        status_code=303,
    )


@router.get("/auth/sso/{slug}/callback")
async def complete_sign_in(
    request: Request,
    session: SessionDep,
    slug: str,
    code: str = "",
    state: str = "",
    error: str = "",
) -> Response:
    """Take the directory's answer and open a session.

    Every failure ends at a page in the interface rather than as JSON, because
    the browser got here by navigation and there is nobody to read a status
    code. What is *not* passed on is the directory's own error text: it is
    written for whoever configured the client.
    """
    if error:
        return RedirectResponse(_app_url(request, "/sign-in", error="refused"), 303)

    pending = await authrequests.consume(session, state)
    if pending is None:
        return RedirectResponse(_app_url(request, "/sign-in", error="expired"), 303)

    provider = await session.get(IdentityProvider, pending.provider_id)
    if provider is None or provider.slug != slug or not provider.enabled:
        return RedirectResponse(_app_url(request, "/sign-in", error="unknown-provider"), 303)

    if not code:
        return RedirectResponse(_app_url(request, "/sign-in", error="refused"), 303)

    try:
        assertion = await _assert(request, session, provider, pending, code)
    except ForbiddenError:
        return RedirectResponse(_app_url(request, "/sign-in", error="refused"), 303)

    if pending.purpose in ("link", "reauth"):
        return await _finish_for_signed_in(request, session, provider, pending, assertion)

    try:
        outcome = await federation.sign_in(
            session, provider, assertion, notify=request.app.state.mailer.send
        )
    except ForbiddenError:
        return RedirectResponse(_app_url(request, "/sign-in", error="not-permitted"), 303)

    token, _ = await websessions.create(
        session, outcome.user, user_agent=request.headers.get("user-agent", "")
    )
    response = RedirectResponse(_app_url(request, pending.next_path), status_code=303)
    _set_session_cookies(response, request, token)
    return response


@router.post("/auth/saml/{slug}/acs")
async def consume_assertion(
    request: Request,
    session: SessionDep,
    slug: str,
    SAMLResponse: Annotated[str, Form()] = "",
) -> Response:
    """Take a SAML assertion posted back by the directory.

    **No session and no CSRF token, and neither is an oversight.** The
    HTTP-POST binding delivers this as a cross-site form submission, and
    ``SameSite=Lax`` means the browser sends *no* cookies with it -- not the
    session, not the CSRF token. There is nothing to read and nothing to
    compare. What makes the request genuine instead is the signature on the
    assertion plus its ``InResponseTo`` matching a request row this server
    wrote, and this is the route that *sets* the cookies rather than one that
    reads them.

    It is also why altero is SP-initiated only: without a request row to match,
    there is nothing left holding this up.
    """
    if not SAMLResponse:
        return RedirectResponse(_app_url(request, "/sign-in", error="refused"), 303)

    provider = await session.scalar(
        select(IdentityProvider).where(IdentityProvider.slug == slug.strip().lower())
    )
    if provider is None or provider.kind != "saml" or not provider.enabled:
        return RedirectResponse(_app_url(request, "/sign-in", error="unknown-provider"), 303)

    # Read out of the assertion before the request row is spent, because the
    # row is what says which request this answers.
    try:
        request_id = saml.in_response_to(SAMLResponse)
    except ForbiddenError:
        return RedirectResponse(_app_url(request, "/sign-in", error="refused"), 303)

    pending = await authrequests.consume(session, request_id)
    if pending is None or pending.provider_id != provider.id:
        return RedirectResponse(_app_url(request, "/sign-in", error="expired"), 303)

    try:
        verified = saml.verify_response(
            SAMLResponse,
            provider,
            acs_url=acs_url(request, provider.slug),
            entity_id=entity_id(request),
            in_response_to=request_id,
        )
        await samlreplay.consume(
            session,
            provider,
            assertion_id=verified.assertion_id,
            expires=verified.expires,
        )
    except ForbiddenError, InvalidInputError:
        return RedirectResponse(_app_url(request, "/sign-in", error="refused"), 303)

    if pending.purpose in ("link", "reauth"):
        return await _finish_for_signed_in(request, session, provider, pending, verified.assertion)

    try:
        outcome = await federation.sign_in(
            session, provider, verified.assertion, notify=request.app.state.mailer.send
        )
    except ForbiddenError:
        return RedirectResponse(_app_url(request, "/sign-in", error="not-permitted"), 303)

    token, _ = await websessions.create(
        session, outcome.user, user_agent=request.headers.get("user-agent", "")
    )
    response = RedirectResponse(_app_url(request, pending.next_path), status_code=303)
    _set_session_cookies(response, request, token)
    return response


async def _assert(
    request: Request,
    session: SessionDep,
    provider: IdentityProvider,
    pending: AuthRequest,
    code: str,
) -> oidc.Assertion:
    """Exchange the code and establish what the directory said."""
    client = await _client(request)
    tokens = await client.exchange(
        provider,
        code=code,
        verifier=pending.code_verifier,
        redirect_uri=redirect_uri(request, provider.slug),
    )

    identity_token = tokens.get("id_token")
    if not isinstance(identity_token, str):
        raise ForbiddenError("The identity provider returned no identity")

    claims = oidc.read_id_token(identity_token)
    oidc.validate_claims(claims, provider, nonce=pending.nonce)

    # UserInfo fills what the token left out -- many directories keep the token
    # small and put the rest here, and the required claim is frequently there.
    access = tokens.get("access_token")
    if isinstance(access, str) and access:
        extra = await client.userinfo(provider, access)
        # The token wins on `sub`: UserInfo naming a different subject is a
        # mix-up, and the specification says to refuse it.
        if extra.get("sub") and extra["sub"] != claims.get("sub"):
            raise ForbiddenError("The identity provider contradicted itself")
        claims = {**extra, **claims} if extra else claims

    return oidc.assertion_from(claims, provider)


async def _finish_for_signed_in(
    request: Request,
    session: SessionDep,
    provider: IdentityProvider,
    pending: AuthRequest,
    assertion: oidc.Assertion,
) -> Response:
    """Attach the identity, or stamp the session as freshly proved."""
    user = await session.get(User, pending.user_id) if pending.user_id else None
    if user is None:
        return RedirectResponse(_app_url(request, "/sign-in", error="not-signed-in"), 303)

    record = await websessions.lookup(session, request.cookies.get("altero_session"))
    if record is None or record.user_id != user.id:
        # The browser that started this is not the one that came back.
        return RedirectResponse(_app_url(request, "/sign-in", error="not-signed-in"), 303)

    if pending.purpose == "link":
        try:
            await federation.link(session, user, provider, assertion)
        except ForbiddenError:
            return RedirectResponse(
                _app_url(request, "/settings/security", error="already-linked"), 303
            )
    else:
        identity = await federation.find(session, provider, assertion.subject)
        if identity is None or identity.user_id != user.id:
            return RedirectResponse(_app_url(request, "/settings/security", error="not-yours"), 303)

    # Either way this browser has just proved itself at the directory, which is
    # what re-authentication wanted -- see services/reauth.py.
    await account.stamp_proof(session, record)
    return RedirectResponse(_app_url(request, pending.next_path), status_code=303)


# --------------------------------------------------------------------------
# An account's own links
# --------------------------------------------------------------------------


@router.get("/account/identities")
async def list_identities(session: SessionDep, user: CurrentUserDep) -> Response:
    """The directories this account can sign in through."""
    identities = await federation.identities_for(session, user)
    providers = {entry.id: entry for entry in await identityproviders.list_all(session)}
    return JSONResponse(
        {
            "identities": [
                {
                    "id": entry.id,
                    "provider": providers[entry.provider_id].slug
                    if entry.provider_id in providers
                    else "",
                    "displayName": providers[entry.provider_id].display_name
                    if entry.provider_id in providers
                    else "",
                    "assertedName": entry.asserted_name,
                    "linked": entry.linked.isoformat() + "Z",
                    "lastSeen": entry.last_seen.isoformat() + "Z" if entry.last_seen else None,
                }
                for entry in identities
            ]
        }
    )


@router.delete("/account/identities/{identity_id}", status_code=204)
async def remove_identity(
    session: SessionDep,
    user: CurrentUserDep,
    record: AuthenticatedDep,
    identity_id: int,
    _csrf: CsrfDep,
) -> Response:
    """Detach a directory from this account.

    Takes proof, because it changes how the account is got into. Refused when
    it is the only way in -- an account with no password removing its last link
    would lock itself out of a library nobody else can reach.
    """
    await account.require_proof(session, user, record)

    identity = await session.get(FederatedIdentity, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="No such connection")
    await federation.unlink(session, user, identity)
    return Response(status_code=204)


# --------------------------------------------------------------------------
# The operator's screens
# --------------------------------------------------------------------------


@router.get("/admin/providers")
async def list_providers(
    request: Request, session: SessionDep, _admin: AdministratorDep
) -> Response:
    """Every configured provider, with the callback each has to be given."""
    providers = await identityproviders.list_all(session)
    return JSONResponse(
        {
            "providers": [
                {
                    **identityproviders.serialise(entry),
                    # The single most likely thing to be misconfigured, so it
                    # is shown rather than left to be worked out.
                    "redirectUri": redirect_uri(request, entry.slug),
                }
                for entry in providers
            ],
            # Without this every redirect URI is built from the request, which
            # is the proxy's idea of the address behind one.
            "publicUrlConfigured": bool(request.app.state.settings.public_url),
        }
    )


@router.post("/admin/providers", status_code=201)
async def create_provider(
    request: Request,
    session: SessionDep,
    admin_user: AdministratorDep,
    browser: AuthenticatedDep,
    body: Annotated[ProviderInput, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Add a provider, and try its discovery document straight away."""
    await account.require_proof(session, admin_user, browser, password=body.current_password)

    if not body.slug:
        raise InvalidInputError("A provider needs a name")

    provider = await identityproviders.create(
        session, slug=body.slug, kind=body.kind, **body.values()
    )
    warning = await _try_discovery(request, session, provider)
    return JSONResponse(
        {
            "provider": {
                **identityproviders.serialise(provider),
                "redirectUri": redirect_uri(request, provider.slug),
            },
            "warning": warning,
        },
        status_code=201,
    )


@router.patch("/admin/providers/{slug}")
async def change_provider(
    request: Request,
    session: SessionDep,
    admin_user: AdministratorDep,
    browser: AuthenticatedDep,
    slug: str,
    body: Annotated[ProviderInput, Body()],
    _csrf: CsrfDep,
) -> Response:
    await account.require_proof(session, admin_user, browser, password=body.current_password)

    provider = await identityproviders.by_slug(session, slug)
    await identityproviders.update(session, provider, body.values())
    warning = await _try_discovery(request, session, provider)
    return JSONResponse(
        {
            "provider": {
                **identityproviders.serialise(provider),
                "redirectUri": redirect_uri(request, provider.slug),
            },
            "warning": warning,
        }
    )


@router.delete("/admin/providers/{slug}", status_code=204)
async def remove_provider(
    session: SessionDep,
    admin_user: AdministratorDep,
    browser: AuthenticatedDep,
    slug: str,
    body: Annotated[ProviderInput, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Remove a provider, and with it every account's link to it."""
    await account.require_proof(session, admin_user, browser, password=body.current_password)

    provider = await identityproviders.by_slug(session, slug)
    await identityproviders.delete(session, provider)
    return Response(status_code=204)


async def _try_discovery(
    request: Request, session: SessionDep, provider: IdentityProvider
) -> str | None:
    """Fetch the provider's configuration, returning why not rather than raising.

    A directory that is unreachable at the moment it is configured must not
    lose what was typed: the row is saved either way and the screen says the
    endpoints are not known yet.
    """
    if provider.kind != "oidc" or not provider.issuer:
        return None
    try:
        found = await (await _client(request)).discover(provider.issuer)
    except InvalidInputError as failure:
        return failure.message

    await identityproviders.record_discovery(
        session,
        provider,
        authorization_endpoint=found.authorization_endpoint,
        token_endpoint=found.token_endpoint,
        userinfo_endpoint=found.userinfo_endpoint,
    )
    return None
