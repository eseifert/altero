"""Interrupting a launcher must also stop its child desktop process."""

import asyncio
import os
import shlex
import signal
import sys
from pathlib import Path

from tools.compatibility.desktop import run_phase


def running(pid: int) -> bool:
    path = Path(f"/proc/{pid}/stat")
    return path.exists() and path.read_text().split(")", 1)[1].split()[0] != "Z"


async def test_interrupt_kills_the_launchers_child(tmp_path):
    root = tmp_path / "profile"
    root.mkdir()
    marker = tmp_path / "child.pid"
    child = (
        "import os,time; from pathlib import Path; "
        f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    launcher = tmp_path / "launcher.sh"
    launcher.write_text(
        f"#!/bin/sh\n{shlex.quote(sys.executable)} -c {shlex.quote(child)} &\nwait\n"
    )
    launcher.chmod(0o700)
    interrupt = asyncio.Event()
    pending = asyncio.create_task(
        run_phase(
            launcher,
            root,
            version="10.0.5",
            key=None,
            operations=[],
            interrupt=interrupt,
        )
    )
    pid = None
    try:
        async with asyncio.timeout(10):
            while not marker.exists():
                await asyncio.sleep(0.01)
        pid = int(marker.read_text())
        assert running(pid)
        interrupt.set()
        assert (await pending)["interrupted"]
        await asyncio.sleep(0.05)
        assert not running(pid), "The launcher died but its desktop kept running"
    finally:
        if pid is not None and running(pid):
            os.kill(pid, signal.SIGKILL)
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
