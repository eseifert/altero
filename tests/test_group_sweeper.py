"""The periodic task that runs the digest sweep.

The one piece of machinery this feature adds. `docs/email.md` says altero has
no queue and no retry, and this does not change that: nothing is queued and
nothing is retried. What runs on a timer is the decision that a burst has
finished, which cannot be made at the moment of a write because the write does
not know whether another is coming.

Like the streaming broker, it lives in one process. Unlike the broker, running
several is safe rather than merely partial -- the claim in
:mod:`altero.services.groupdigest` means two sweeps cannot send the same
digest.
"""

import asyncio
from datetime import timedelta

import pytest

from altero.services.groupsweeper import Sweeper


class Recorder:
    """Counts sweeps and can be told to fail or to block."""

    def __init__(self) -> None:
        self.runs = 0
        #: Sweeps that ran all the way through, for telling "started" from
        #: "was allowed to finish".
        self.finished = 0
        self.fail_next = False
        self.gate: asyncio.Event | None = None

    async def sweep(self) -> int:
        self.runs += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("the database went away")
        if self.gate is not None:
            await self.gate.wait()
        self.finished += 1
        return 0


async def until(predicate, timeout: float = 2.0) -> None:  # type: ignore[no-untyped-def]
    """Wait for ``predicate`` rather than sleeping for a fixed time."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class TestRunning:
    async def test_it_sweeps_on_a_timer(self) -> None:
        recorder = Recorder()
        sweeper = Sweeper(recorder.sweep, interval=timedelta(seconds=0.01))

        async with sweeper:
            await until(lambda: recorder.runs >= 3)

        assert recorder.runs >= 3

    async def test_it_stops_when_the_application_does(self) -> None:
        recorder = Recorder()
        sweeper = Sweeper(recorder.sweep, interval=timedelta(seconds=0.01))

        async with sweeper:
            await until(lambda: recorder.runs >= 1)
        after = recorder.runs

        await asyncio.sleep(0.05)
        assert recorder.runs == after

    async def test_a_sweep_in_progress_is_awaited_on_shutdown(self) -> None:
        # Cancelling between the claim and the sending would leave rows stamped
        # as delivered that nobody was told about, which is the one state
        # nothing else recovers from: the next sweep skips them.
        recorder = Recorder()
        recorder.gate = asyncio.Event()
        sweeper = Sweeper(recorder.sweep, interval=timedelta(seconds=0.01))

        await sweeper.__aenter__()
        await until(lambda: recorder.runs >= 1)

        # Shut down while the sweep is stuck inside its send.
        closing = asyncio.create_task(sweeper.aclose())
        await asyncio.sleep(0.05)
        assert not closing.done(), "shutdown abandoned a sweep that was still sending"

        recorder.gate.set()
        async with asyncio.timeout(2):
            await closing
        assert recorder.finished == recorder.runs


class TestSurvivingFailure:
    async def test_a_failing_sweep_does_not_stop_the_next_one(self) -> None:
        # A database blip must not silently end notifications for the lifetime
        # of the process -- there is nothing to notice it by.
        recorder = Recorder()
        recorder.fail_next = True
        sweeper = Sweeper(recorder.sweep, interval=timedelta(seconds=0.01))

        async with sweeper:
            await until(lambda: recorder.runs >= 3)

        assert recorder.runs >= 3

    async def test_the_failure_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        recorder = Recorder()
        recorder.fail_next = True
        sweeper = Sweeper(recorder.sweep, interval=timedelta(seconds=0.01))

        with caplog.at_level("ERROR", logger="altero.groupsweeper"):
            async with sweeper:
                await until(lambda: recorder.runs >= 2)

        assert "the database went away" in caplog.text


class TestBeingTurnedOff:
    async def test_a_zero_interval_never_runs(self) -> None:
        # The off switch, for an instance that wants none of this.
        recorder = Recorder()
        sweeper = Sweeper(recorder.sweep, interval=timedelta(0))

        async with sweeper:
            await asyncio.sleep(0.05)

        assert recorder.runs == 0

    async def test_it_reports_whether_it_is_running(self) -> None:
        recorder = Recorder()

        off = Sweeper(recorder.sweep, interval=timedelta(0))
        async with off:
            assert not off.running

        on = Sweeper(recorder.sweep, interval=timedelta(seconds=0.01))
        async with on:
            assert on.running
