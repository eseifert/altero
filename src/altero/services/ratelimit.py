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

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    def check(self, caller: str) -> int | None:
        """Count one request, returning the seconds to wait if it is refused.

        ``None`` means the request may proceed. The wait is a whole number of
        seconds and never zero: the client multiplies it by 1000 and pauses, so
        rounding 0.4 down would send it straight back into another refusal.
        """
        if not self.enabled:
            return None

        moment = self.now()
        started, count = self._windows.get(caller, (moment, 0))

        if moment - started >= self.window:
            started, count = moment, 0

        if count >= self.limit:
            return max(1, math.ceil(self.window - (moment - started)))

        self._windows[caller] = (started, count + 1)
        self._forget_lapsed(moment)
        return None

    def _forget_lapsed(self, moment: float) -> None:
        """Drop callers whose window has passed, so the table stays bounded."""
        self._windows = {
            caller: entry
            for caller, entry in self._windows.items()
            if moment - entry[0] < self.window
        }

    def tracked(self) -> int:
        """Return how many callers are currently counted. For tests."""
        return len(self._windows)
