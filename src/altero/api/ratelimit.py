"""Turning a refused request into the answer the client understands.

``Zotero.Sync.APIClient._check429`` reads ``Retry-After`` and pauses for that
many seconds, and discards the value unless ``parseInt(value) == value`` -- so
the header is whole seconds or it is worse than useless.
"""

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from altero.api.deps import get_credential
from altero.services.ratelimit import RateLimiter

#: Paths that are never limited. An orchestrator polls the probe on a fixed
#: interval and would take the instance out of service for a 429.
EXEMPT = frozenset({"/health"})


class RateLimitMiddleware:
    """Refuse a caller that has used up its allowance for the window.

    Plain ASGI, for the reason :mod:`altero.api.apiversion` gives, and a
    pass-through when no limit is configured -- which is the default.
    """

    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.limiter.enabled or scope["path"] in EXEMPT:
            await self.app(scope, receive, send)
            return

        if (wait := self.limiter.check(*self._callers(Request(scope)))) is not None:
            refusal = PlainTextResponse(
                "Too many requests",
                status_code=429,
                # Whole seconds: the client throws away anything else.
                headers={"Retry-After": str(wait)},
            )
            await refusal(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _callers(self, request: Request) -> list[str]:
        """Identify who is asking.

        The API key when there is one, so two clients of the same person are
        counted apart; otherwise the address, which is all an anonymous
        publications reader offers. A key that has not authenticated yet is
        counted against the address as well -- this runs before anybody is
        authenticated, and a made-up key per request would otherwise be a fresh
        allowance per request.
        """
        host = f"host:{request.client.host if request.client else 'unknown'}"
        credential = get_credential(request)
        if not credential:
            return [host]
        if self.limiter.vouched(credential):
            return [f"key:{credential}"]
        return [f"key:{credential}", host]
