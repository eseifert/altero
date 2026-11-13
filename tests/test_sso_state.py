"""Browser correlation works before authentication and across parallel tabs."""

import pytest
from starlette.requests import Request
from starlette.responses import Response

from altero.api import ssostate


def browser(*, secret: str = "", secure: bool = False) -> Request:
    name = "__Host-altero_sso" if secure else "altero_sso"
    return Request(
        {
            "type": "http",
            "path": "/",
            "server": ("example.org", 443 if secure else 80),
            "scheme": "https" if secure else "http",
            "headers": [(b"cookie", f"{name}={secret}".encode())] if secret else [],
        }
    )


def test_parallel_requests_share_only_the_browser_binding() -> None:
    first, secret = ssostate.create(browser())
    request = browser(secret=secret)
    second, retained = ssostate.create(request)
    assert retained == secret
    assert first != second
    # Fits auth_requests.state on PostgreSQL; starts as a valid SAML XML ID.
    assert first.startswith("_")
    assert len(first) <= 64
    assert ssostate.matches(request, first)
    assert ssostate.matches(request, second)
    assert not ssostate.matches(browser(), first)
    _, stranger = ssostate.create(browser())
    assert not ssostate.matches(browser(secret=stranger), first)


def test_tampering_with_a_request_breaks_its_binding() -> None:
    state, secret = ssostate.create(browser())
    forged = state[:-1] + ("A" if state[-1] != "A" else "B")
    assert not ssostate.matches(browser(secret=secret), forged)


@pytest.mark.parametrize("secure", [False, True])
def test_the_binding_cookie_is_private_and_host_bound(secure: bool) -> None:
    request = browser(secure=secure)
    _, secret = ssostate.create(request)
    response = ssostate.set_cookie(Response(), request, secret)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie
    assert ("Secure" in cookie) is secure
    assert cookie.startswith("__Host-altero_sso=" if secure else "altero_sso=")
