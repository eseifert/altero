"""The authorization server's public endpoints.

Five of the six answer without a cookie and without a CSRF token, and none of
them is a hole in the boundary ``/web`` draws. ``/oauth/authorize`` is a
navigation that authenticates nobody -- it checks what an application asked for
and hands the browser to the interface, which is where signing in happens. The
token, revocation and userinfo endpoints are back channels an application calls
with credentials of its own. Discovery and the key set are public documents by
definition; a JWKS that needed authenticating would be a JWKS nobody could use.

**Where the consent screen is not.** There is no HTML in this module. The
authorization request is stored, the browser is sent to ``/app/authorize`` with
an opaque handle, and everything a person sees is the interface in
``web/src/views/AuthorizeView.vue`` -- translated like the rest of it, and
signing in through the same ``/web/auth/login`` as every other way into this
server. That is what makes a second factor, a passkey and single sign-on work
here: not code, but the absence of a second door.

**What this adds to the v3 API.** An OAuth access token authenticates the v3
endpoints alongside an API key -- the one place the rule in ``CLAUDE.md``
widens. It stays a bearer credential presented on the request, never a cookie,
so the reason that rule exists is untouched: a page on another origin still
cannot cause a browser to authenticate a sync request. ``docs/compatibility.md``
records the decision.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Form, Query
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from altero.api.deps import SessionDep, get_credential
from altero.api.routes.web import SESSION_COOKIE, clear_session_cookies
from altero.api.spa import MOUNT_PATH
from altero.errors import ForbiddenError, OAuthError
from altero.models.library import User
from altero.services import oauthscopes, oauthserver, websessions

router = APIRouter(tags=["oauth"])

#: RFC 8628's name for the device grant, which is a URN rather than a word
#: because it was defined after the registry that would have held a word.
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def _issuer(request: Request) -> str:
    return oauthserver.issuer(request.app.state.settings.public_url)


def _metadata(request: Request) -> dict[str, Any]:
    """Return the discovery document both well-known paths serve.

    One document, because RFC 8414's ``oauth-authorization-server`` and OpenID
    Connect Discovery's ``openid-configuration`` describe the same server and
    every field either asks for is in here. Clients look in one place or the
    other depending on what they think they are talking to.
    """
    base = _issuer(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "userinfo_endpoint": f"{base}/oauth/userinfo",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "device_authorization_endpoint": f"{base}/oauth/device_authorization",
        "end_session_endpoint": f"{base}/oauth/logout",
        "jwks_uri": f"{base}/oauth/jwks.json",
        "scopes_supported": list(oauthscopes.ALL),
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": [
            "authorization_code",
            "refresh_token",
            DEVICE_GRANT,
        ],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        # S256 alone. `plain` makes the challenge equal to the verifier, which
        # is the interception PKCE exists to prevent, so it is neither
        # advertised nor accepted.
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "claims_supported": [
            "sub",
            "iss",
            "aud",
            "exp",
            "iat",
            "auth_time",
            "nonce",
            "at_hash",
            "preferred_username",
            "name",
            "email",
            "email_verified",
            "groups",
        ],
        "service_documentation": "https://eseifert.github.io/altero/latest/oauth/",
    }


@router.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request) -> dict[str, Any]:
    """Serve the OpenID Connect discovery document."""
    return _metadata(request)


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata(request: Request) -> dict[str, Any]:
    """Serve the same document under the name RFC 8414 gives it."""
    return _metadata(request)


@router.get("/oauth/jwks.json")
async def jwks(request: Request, session: SessionDep) -> dict[str, Any]:
    """Serve the keys ID tokens are verified against.

    Every key, not only the one currently signing: a token issued before a
    rotation has to keep verifying until it expires, and a client that cannot
    find its ``kid`` here has no way to tell a rotation from a forgery.
    """
    _issuer(request)
    return {"keys": await oauthserver.public_keys(session)}


@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    session: SessionDep,
    client_id: Annotated[str, Query()],
    redirect_uri: Annotated[str, Query()],
    response_type: Annotated[str, Query()] = "code",
    scope: Annotated[str, Query()] = "openid",
    state: Annotated[str, Query()] = "",
    code_challenge: Annotated[str, Query()] = "",
    code_challenge_method: Annotated[str, Query()] = "S256",
    nonce: Annotated[str, Query()] = "",
) -> Response:
    """Check what an application is asking for and hand the browser to the interface.

    Nothing is authenticated here and no screen is drawn here. What comes back
    is a redirect into the single-page application carrying an opaque handle;
    the request itself stays in the database, where the interface cannot change
    it and the query string cannot contradict it.

    The split in how failures are reported is RFC 6749 §4.1.2.1 and it matters:
    a problem with the *client* or the *redirect URI* is shown on this server,
    because the only address available to bounce it off is the unverified one
    the request just supplied, and bouncing errors off unverified addresses is
    how an open redirector is built. Everything else is the application's own
    problem and is delivered to its registered address where it can act on it.
    """
    _issuer(request)
    try:
        pending = await oauthserver.begin(
            session,
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            nonce=nonce,
        )
    except OAuthError as error:
        # The redirect URI is known good by the time this can be raised, so the
        # application is told at its own address, as the RFC requires.
        return RedirectResponse(
            oauthserver.error_redirect(redirect_uri, state, error).url, status_code=303
        )

    return RedirectResponse(f"{MOUNT_PATH}/authorize?request={pending.handle}", status_code=303)


@router.post("/oauth/device_authorization")
async def device_authorization(
    request: Request,
    session: SessionDep,
    client_id: Annotated[str, Form()],
    scope: Annotated[str, Form()] = "openid",
) -> JSONResponse:
    """Start an authorization for a device that cannot show a browser.

    RFC 8628. The device is handed a long code it keeps and a short one it
    shows; a person types the short one into this server's interface at the
    address in the answer. Nothing is authenticated here -- like
    ``/oauth/authorize``, this only records what was asked for.
    """
    base = _issuer(request)
    started = await oauthserver.begin_device(session, client_id=client_id, scope=scope)
    return JSONResponse(
        {
            "device_code": started.device_code,
            "user_code": started.user_code,
            "verification_uri": f"{base}{MOUNT_PATH}/device",
            # RFC 8628 §3.2 calls this optional. It is the difference between
            # typing a code and following a link, wherever the device can show
            # one -- a QR code on a screen, a line in a terminal.
            "verification_uri_complete": f"{base}{MOUNT_PATH}/device?code={started.user_code}",
            "expires_in": started.expires_in,
            "interval": started.interval,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/oauth/logout")
async def logout(
    request: Request,
    session: SessionDep,
    id_token_hint: Annotated[str, Query()] = "",
    client_id: Annotated[str, Query()] = "",
    post_logout_redirect_uri: Annotated[str, Query()] = "",
    state: Annotated[str, Query()] = "",
) -> Response:
    """End the browser session an application asked to end, and send it onward.

    A navigation, like ``/oauth/authorize``, and it takes no CSRF token for the
    reason the passkey routes take none: the browser this is for may hold
    nothing at all. What stands in for one is the ``id_token_hint``, which
    :func:`altero.services.oauthserver.end_session` requires and verifies --
    a page on another origin cannot mint one, so it cannot provoke this.

    What ends is the *session*, and not the grant. The application keeps the
    tokens it was given, because signing out of a browser is not withdrawing
    consent; that is **Settings -> Connected applications**, and
    ``docs/oauth.md`` says so where somebody will read it.
    """
    return await _end_session(
        request,
        session,
        id_token_hint=id_token_hint,
        client_id=client_id,
        post_logout_redirect_uri=post_logout_redirect_uri,
        state=state,
    )


@router.post("/oauth/logout")
async def logout_posted(
    request: Request,
    session: SessionDep,
    id_token_hint: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    post_logout_redirect_uri: Annotated[str, Form()] = "",
    state: Annotated[str, Form()] = "",
) -> Response:
    """The same thing as a form post, which RP-Initiated Logout 1.0 §2 allows."""
    return await _end_session(
        request,
        session,
        id_token_hint=id_token_hint,
        client_id=client_id,
        post_logout_redirect_uri=post_logout_redirect_uri,
        state=state,
    )


async def _end_session(
    request: Request,
    session: SessionDep,
    *,
    id_token_hint: str,
    client_id: str,
    post_logout_redirect_uri: str,
    state: str,
) -> Response:
    asked = await oauthserver.end_session(
        session,
        id_token_hint=id_token_hint,
        client_id=client_id,
        post_logout_redirect_uri=post_logout_redirect_uri,
        state=state,
        public_url=request.app.state.settings.public_url,
    )

    record = await websessions.lookup(session, request.cookies.get(SESSION_COOKIE))
    ended = record is not None and record.user_id == asked.user_id
    if record is not None and ended:
        await websessions.revoke(session, record)

    target = asked.redirect.url if asked.redirect else f"{MOUNT_PATH}/"
    response = RedirectResponse(target, status_code=303)
    if ended:
        clear_session_cookies(response)
    return response


@router.post("/oauth/token")
async def token(
    request: Request,
    session: SessionDep,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()] = "",
    client_secret: Annotated[str | None, Form()] = None,
    code: Annotated[str, Form()] = "",
    code_verifier: Annotated[str, Form()] = "",
    redirect_uri: Annotated[str, Form()] = "",
    refresh_token: Annotated[str, Form()] = "",
    device_code: Annotated[str, Form()] = "",
) -> JSONResponse:
    """Exchange an authorization code, or rotate a refresh token.

    ``Cache-Control: no-store`` because the response holds bearer credentials
    and RFC 6749 §5.1 requires it.
    """
    public_url = request.app.state.settings.public_url
    oauthserver.issuer(public_url)

    if grant_type == "authorization_code":
        payload = await oauthserver.exchange(
            session,
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            public_url=public_url,
        )
    elif grant_type == DEVICE_GRANT:
        payload = await oauthserver.exchange_device(
            session,
            client_id=client_id,
            client_secret=client_secret,
            device_code=device_code,
            public_url=public_url,
        )
    elif grant_type == "refresh_token":
        payload = await oauthserver.refresh(
            session,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            public_url=public_url,
        )
    else:
        raise OAuthError(
            "unsupported_grant_type",
            "This server issues tokens for authorization_code, refresh_token and "
            f"{DEVICE_GRANT}, not {grant_type}",
        )

    return JSONResponse(payload, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/oauth/revoke")
async def revoke(
    session: SessionDep,
    token: Annotated[str, Form()],
    client_id: Annotated[str, Form()] = "",
    token_type_hint: Annotated[str | None, Form()] = None,
) -> Response:
    """Revoke a token, answering 200 whether or not it was one.

    RFC 7009 §2.2 requires that. A caller holding a token is entitled to revoke
    it; a caller holding something that is not a token learns nothing from the
    answer, which is the point -- an error here would turn this endpoint into a
    way of asking whether a given string is somebody's live credential.

    Revoking a *refresh* token takes its whole family, since the access tokens
    beside it were issued from the same authorization and stopping one while
    leaving the others is not what anybody means by revoking.
    """
    await oauthserver.revoke(session, client_id=client_id, token=token)
    return Response(status_code=200, headers={"Cache-Control": "no-store"})


@router.get("/oauth/userinfo")
async def userinfo(request: Request, session: SessionDep) -> JSONResponse:
    """Return the claims the token's scopes allow.

    Scope-gated one claim at a time, and that is the whole substance of this
    endpoint: a token holding ``openid`` alone gets a subject identifier and
    nothing else -- not a name, not an address, and no library anywhere.
    """
    credential = get_credential(request)
    if not credential:
        raise ForbiddenError("No access token")

    identity = await oauthserver.resolve_access_token(session, credential)
    if identity is None:
        raise ForbiddenError("Invalid access token")

    owner = await session.get(User, identity.user_id)
    if owner is None or owner.disabled_at is not None:
        raise ForbiddenError("This account is not active")

    granted = set(identity.scopes.split())
    claims: dict[str, Any] = {"sub": str(owner.id)}
    if oauthscopes.PROFILE in granted:
        claims["preferred_username"] = owner.username
        claims["name"] = owner.display_name or owner.username
    if oauthscopes.EMAIL in granted and owner.email:
        claims["email"] = owner.email
        claims["email_verified"] = owner.email_verified is not None
    if oauthscopes.GROUPS in granted:
        claims["groups"] = await oauthserver.group_names(session, owner.id)

    return JSONResponse(claims, headers={"Cache-Control": "no-store"})
