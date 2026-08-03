"""Turning a refused request into the answer the client understands.

``Zotero.Sync.APIClient._check429`` reads ``Retry-After`` and pauses for that
many seconds, and discards the value unless ``parseInt(value) == value`` -- so
the header is whole seconds or it is worse than useless.
"""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp

from altero.api.deps import get_credential
from altero.services.ratelimit import RateLimiter

#: Paths that are never limited. An orchestrator polls the probe on a fixed
#: interval and would take the instance out of service for a 429.
EXEMPT = frozenset({"/health"})


class RateLimitMiddleware:
    """Refuse a caller that has used up its allowance for the window."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self.limiter.enabled or request.url.path in EXEMPT:
            return await call_next(request)

        if (wait := self.limiter.check(self._caller(request))) is not None:
            return PlainTextResponse(
                "Too many requests",
                status_code=429,
                # Whole seconds: the client throws away anything else.
                headers={"Retry-After": str(wait)},
            )

        return await call_next(request)

    @staticmethod
    def _caller(request: Request) -> str:
        """Identify who is asking.

        The API key when there is one, so two clients of the same person are
        counted apart; otherwise the address, which is all an anonymous
        publications reader offers.
        """
        if credential := get_credential(request):
            return f"key:{credential}"
        return f"host:{request.client.host if request.client else 'unknown'}"
