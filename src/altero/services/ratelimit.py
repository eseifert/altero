"""Counting requests per caller, so a server can refuse one that asks too often.

Off unless configured: a personal instance with one client has nothing to
throttle, and a limit nobody asked for turns a working sync into a stuck one.

The count is held in this process. Behind several workers each keeps its own,
so the effective allowance is the configured one times the number of workers --
enough to stop a runaway client, not a defence against a determined one. That
belongs in front of the application, in whatever terminates TLS.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic


@dataclass
class RateLimiter:
    """A fixed window per caller.

    Args:
        limit: Requests allowed per window. Zero disables the limiter.
        window: Length of the window in seconds.
        now: Source of the current time, so tests need not sleep.
    """

    limit: int
    window: int
    now: Callable[[], float] = monotonic
    _windows: dict[str, tuple[float, int]] = field(default_factory=dict, repr=False)
    #: Credentials that authenticated, and when they last did.
    _vouched: dict[str, float] = field(default_factory=dict, repr=False)
    _pruned: float = field(default=float("-inf"), repr=False)

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    def check(self, caller: str, *also: str) -> int | None:
        """Count one request, returning the seconds to wait if it is refused.

        ``None`` means the request may proceed. The wait is a whole number of
        seconds and never zero: the client multiplies it by 1000 and pauses, so
        rounding 0.4 down would send it straight back into another refusal.

        A request counted against several callers -- ``also`` -- is refused when
        any of them has used up its window, and then counted against none.
        """
        if not self.enabled:
            return None

        moment = self.now()
        counted: dict[str, tuple[float, int]] = {}
        waits: list[int] = []
        for name in (caller, *also):
            started, count = self._windows.get(name, (moment, 0))
            if moment - started >= self.window:
                started, count = moment, 0
            if count >= self.limit:
                waits.append(max(1, math.ceil(self.window - (moment - started))))
            counted[name] = (started, count + 1)
        if waits:
            return max(waits)

        self._windows.update(counted)
        self._forget_lapsed(moment)
        return None

    def vouch(self, credential: str) -> None:
        """Note that ``credential`` authenticated, so it may be counted on its own."""
        if self.enabled:
            self._vouched[credential] = self.now()

    def vouched(self, credential: str) -> bool:
        """Whether ``credential`` authenticated within the last window."""
        seen = self._vouched.get(credential)
        return seen is not None and self.now() - seen < self.window

    def _forget_lapsed(self, moment: float) -> None:
        """Drop callers whose window has passed, so the table stays bounded.

        At most once a window: rebuilding the table on every request cost
        milliseconds once it held tens of thousands of callers, and nothing in
        it can lapse sooner than that.
        """
        if moment - self._pruned < self.window:
            return
        self._pruned = moment
        self._windows = {
            caller: entry
            for caller, entry in self._windows.items()
            if moment - entry[0] < self.window
        }
        self._vouched = {
            credential: seen
            for credential, seen in self._vouched.items()
            if moment - seen < self.window
        }

    def tracked(self) -> int:
        """Return how many callers are currently counted. For tests."""
        return len(self._windows)
