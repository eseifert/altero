"""Running the digest sweep on a timer.

The only machinery this feature adds, and deliberately the smallest that will
do. `docs/email.md` says altero has no queue and no retry; that stands. Nothing
is queued here and nothing is retried. What runs on a timer is the *decision*
that a burst of writes has finished, which cannot be made at the moment of a
write because a write does not know whether another is coming.

Running more than one of these is safe, unlike the streaming broker: the claim
in :mod:`altero.services.groupdigest` means two sweeps cannot deliver the same
activity, so an instance behind several workers sends one digest, not one per
worker.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from types import TracebackType

logger = logging.getLogger("altero.groupsweeper")

#: Runs one sweep and returns how many digests it sent.
Sweep = Callable[[], Awaitable[int]]


class Sweeper:
    """Calls ``sweep`` every ``interval`` until it is closed.

    An async context manager, so the application's lifespan starts and stops it
    without knowing anything about tasks. An interval of zero is the off
    switch, and produces an object that starts nothing.
    """

    def __init__(self, sweep: Sweep, *, interval: timedelta) -> None:
        self._sweep = sweep
        self._interval = interval.total_seconds()
        self._task: asyncio.Task[None] | None = None
        #: The sweep currently running, if one is. Held separately from the
        #: loop so that shutting the loop down can still wait for it.
        self._current: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def __aenter__(self) -> Sweeper:
        if self._interval > 0:
            self._task = asyncio.create_task(self._run(), name="altero.groupsweeper")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Stop sweeping, waiting for one in progress to finish.

        Cancelled between the claim and the sending, a sweep would leave rows
        stamped as delivered that nobody was told about -- the one state
        nothing else recovers from, since the next sweep skips them. So the
        loop is cancelled but the sweep it was running is awaited: the
        cancellation lands while waiting for the next tick, never mid-sweep.
        """
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Cancelling the loop only unblocks the shield; the sweep behind it is
        # still running, and abandoning it here is exactly what shielding was
        # meant to prevent.
        current, self._current = self._current, None
        if current is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await current

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            # Shielded so that a shutdown arriving mid-sweep leaves it running
            # rather than tearing it in half. `aclose` then waits for it.
            self._current = asyncio.create_task(self._guarded_sweep())
            try:
                await asyncio.shield(self._current)
            finally:
                if self._current is not None and self._current.done():
                    self._current = None

    async def _guarded_sweep(self) -> None:
        """Sweep, swallowing anything it raises.

        A database blip must not quietly end notifications for the lifetime of
        the process: there is nothing to notice that by, short of somebody
        eventually asking why they stopped hearing about their group.
        """
        try:
            sent = await self._sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Group digest sweep failed; will try again")
        else:
            if sent:
                logger.info("Sent %d group digest(s)", sent)
