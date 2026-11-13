"""Bind a federated request to its initiating browser, including anonymous ones.

PKCE and a stored nonce correlate the provider's answer with our request, but
do not stop someone transferring their own callback URL to another browser.
The state is therefore authenticated with a separate HttpOnly browser secret.
It starts with an underscore so SAML can also use it as an XML ID.
"""

import base64
import hmac
import re
import secrets

from starlette.requests import Request
from starlette.responses import Response

from altero.services import oidc

_SECRET = re.compile(r"[A-Za-z0-9_-]{43}")


def _cookie_name(request: Request) -> str:
    # HTTPS forbids a sibling subdomain from planting this cookie via Domain.
    return "__Host-altero_sso" if request.url.scheme == "https" else "altero_sso"


def _signature(secret: str, nonce: str) -> str:
    digest = hmac.digest(secret.encode(), nonce.encode(), "sha256")
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def create(request: Request) -> tuple[str, str]:
    """Return a fresh state and the browser secret that authenticates it."""
    secret = request.cookies.get(_cookie_name(request), "")
    if not _SECRET.fullmatch(secret):
        secret = secrets.token_urlsafe(32)
    # 61 characters including the full HMAC: fits the existing varchar(64)
    # state column on PostgreSQL as well as SQLite.
    nonce = "_" + secrets.token_urlsafe(12)
    return f"{nonce}.{_signature(secret, nonce)}", secret


def matches(request: Request, state: str) -> bool:
    """Whether this browser started the request, without spending the state."""
    secret = request.cookies.get(_cookie_name(request), "")
    if not _SECRET.fullmatch(secret) or not re.fullmatch(
        r"_[A-Za-z0-9_-]{16}\.[A-Za-z0-9_-]{43}", state
    ):
        return False
    nonce, signature = state.split(".")
    return hmac.compare_digest(signature, _signature(secret, nonce))


def set_cookie(response: Response, request: Request, secret: str) -> Response:
    """Retain the secret across the provider trip and parallel sign-in tabs."""
    response.set_cookie(
        _cookie_name(request),
        secret,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
        max_age=int(oidc.REQUEST_LIFETIME.total_seconds()),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
