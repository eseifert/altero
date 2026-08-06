"""Reading a library out of api.zotero.org.

The only place altero makes a request of its own accord. Everywhere else it
answers them, so this module is deliberately narrow: one host, read-only, and
one credential that is handed in per call and never stored.

What it has to get right is not the requests but the *waiting*. api.zotero.org
throttles, and a migration is thousands of requests where a sync is a handful,
so it is the one caller most likely to be told to slow down:

- ``Backoff: <seconds>`` asks for a pause while the server is still answering.
  It is obeyed before the next request rather than after this one, so a burst
  already in flight is not abandoned.
- ``429`` with ``Retry-After: <seconds>`` is a refusal, and the same request is
  made again once the pause is over. Without the header the delay doubles from
  a second, which is what Zotero's own client does when it has to guess.

Both headers are read as whole seconds and ignored otherwise -- the same
strictness the desktop client applies to altero's own answers, and for the same
reason: a fractional or zero delay is a pause of no time followed by the same
refusal.

Requests are made one at a time. Zotero asks for no more than four at once, and
one is comfortably within that; a migration is not a thing anybody watches, and
being a well-behaved guest on somebody else's server matters more than
finishing a minute sooner.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from altero.errors import InvalidInputError

logger = logging.getLogger("altero.zoteroapi")

#: Where the Zotero Web API lives. Overridable so the tests can point this at
#: an altero of their own -- which is a real implementation of the same API,
#: and a better fixture than a hand-written one.
DEFAULT_BASE_URL = "https://api.zotero.org"

#: The API version this speaks. Pinned, because "latest" is a moving target and
#: the shapes below are version 3's.
API_VERSION = 3

#: How many objects to ask for at once. The documented maximum.
PAGE_SIZE = 100

#: How many times a request is repeated before the migration gives up on it.
MAX_ATTEMPTS = 5

#: Longest altero will wait when told to, however large the header. A server
#: asking for an hour is a server that should be come back to another day.
MAX_DELAY = 300.0


class ZoteroApiError(Exception):
    """api.zotero.org could not be read, and the migration cannot continue."""


def _seconds(headers: httpx.Headers, name: str) -> float | None:
    """Return a whole-second delay header, or ``None`` if it is unusable.

    Zotero's own client discards anything that is not a whole number, and zero
    with it. Both are treated the same way here: a delay that cannot be obeyed
    meaningfully is no delay at all.
    """
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return min(float(value), MAX_DELAY) if value > 0 else None


@dataclass
class ZoteroApi:
    """A read-only conversation with one Zotero account.

    Args:
        key: The API key. Created by its owner at zotero.org and used for the
            length of one migration; nothing here writes it anywhere.
        client: The HTTP client to speak through. Supplied so a caller can set
            timeouts, a proxy, or -- in the tests -- a transport that reaches
            another altero rather than the internet.
    """

    key: str
    client: httpx.AsyncClient
    base_url: str = DEFAULT_BASE_URL
    #: Called with the number of seconds whenever a pause is being observed, so
    #: that a long wait can be shown rather than looking like a hang.
    on_wait: Callable[[float], None] | None = None
    #: Left over from a `Backoff` header, to be observed before the next call.
    _pending: float = field(default=0.0, init=False)

    @property
    def headers(self) -> dict[str, str]:
        return {"Zotero-API-Key": self.key, "Zotero-API-Version": str(API_VERSION)}

    async def _pause(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self.on_wait is not None:
            self.on_wait(seconds)
        logger.info("waiting %.0fs before the next request to %s", seconds, self.base_url)
        await asyncio.sleep(seconds)

    async def get(self, path: str, **params: Any) -> httpx.Response:
        """Fetch one path, observing whatever the server asks for.

        Raises:
            ZoteroApiError: for a refusal that will not improve by being
                repeated, and for one that has been repeated enough.
        """
        url = f"{self.base_url.rstrip('/')}{path}"
        delay = 1.0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._pause(self._pending)
            self._pending = 0.0

            try:
                response = await self.client.get(
                    url, params=params, headers=self.headers, follow_redirects=True
                )
            except httpx.HTTPError as thrown:
                if attempt == MAX_ATTEMPTS:
                    raise ZoteroApiError(f"Could not reach {url}: {thrown}") from thrown
                await self._pause(delay)
                delay = min(delay * 2, MAX_DELAY)
                continue

            # Asked for while still being answered: kept for the next request
            # rather than served now, so a page that arrived is used.
            if (backoff := _seconds(response.headers, "Backoff")) is not None:
                self._pending = backoff

            if response.status_code == 429:
                if attempt == MAX_ATTEMPTS:
                    raise ZoteroApiError(f"{url} is still refusing requests; try again later")
                await self._pause(_seconds(response.headers, "Retry-After") or delay)
                delay = min(delay * 2, MAX_DELAY)
                continue

            if response.status_code in (401, 403):
                raise InvalidInputError(
                    "zotero.org refused that key. Check that it exists and may read your library."
                )
            if response.status_code >= 500:
                if attempt == MAX_ATTEMPTS:
                    raise ZoteroApiError(f"{url} answered {response.status_code}")
                await self._pause(delay)
                delay = min(delay * 2, MAX_DELAY)
                continue

            return response

        raise ZoteroApiError(f"Gave up on {url}")  # pragma: no cover - the loop always returns

    async def json(self, path: str, **params: Any) -> Any:
        response = await self.get(path, **params)
        if response.status_code == 404:
            raise ZoteroApiError(f"{path} is not there")
        response.raise_for_status()
        return response.json()

    async def paged(self, path: str, **params: Any) -> AsyncIterator[list[Any]]:
        """Yield every page of a multi-object listing.

        Walked with ``start`` rather than by following the ``Link`` header: the
        header names api.zotero.org, and a caller that has been pointed
        somewhere else -- the tests, a proxy -- would be sent back to the real
        thing halfway through.
        """
        start = 0
        while True:
            response = await self.get(path, **params, limit=PAGE_SIZE, start=start)
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, list):  # pragma: no cover - defensive
                raise ZoteroApiError(f"{path} did not answer with a list")
            if not page:
                return

            yield page
            start += len(page)

            total = response.headers.get("Total-Results")
            if total is not None and start >= int(total):
                return

    async def key_owner(self) -> dict[str, Any]:
        """Return what the key says about itself: whose it is and what it may do."""
        payload = await self.json("/keys/current")
        if not isinstance(payload, dict) or "userID" not in payload:
            raise ZoteroApiError("zotero.org did not say who that key belongs to")
        return payload

    async def library_version(self, prefix: str) -> int:
        """Return the library's current version, without fetching its contents."""
        response = await self.get(f"{prefix}/items", format="versions", limit=1)
        response.raise_for_status()
        return int(response.headers.get("Last-Modified-Version", 0))

    async def file(self, prefix: str, item_key: str) -> bytes | None:
        """Return an attachment's bytes, or ``None`` if the server has none.

        A ``404`` is the ordinary case rather than a failure: a linked file was
        never uploaded, and a stored one is only there if the account had the
        storage to keep it.
        """
        response = await self.get(f"{prefix}/items/{item_key}/file")
        if response.status_code in (403, 404):
            return None
        response.raise_for_status()
        return response.content
