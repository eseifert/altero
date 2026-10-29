"""A headless desktop cannot escape onto an inherited Wayland display."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tools.compatibility.acceptance import display

VARIABLES = ("DISPLAY", "GDK_BACKEND", "MOZ_ENABLE_WAYLAND", "WAYLAND_DISPLAY")


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("failure", [False, True])
async def test_xvfb_isolates_and_restores_the_display(tmp_path, monkeypatch, inherited, failure):
    before = dict(zip(VARIABLES, (":host", "wayland", "1", "wayland-0"), strict=True))
    for name in VARIABLES:
        if inherited:
            monkeypatch.setenv(name, before[name])
        else:
            monkeypatch.delenv(name, raising=False)
    process = SimpleNamespace(
        stdout=SimpleNamespace(readline=AsyncMock(return_value=b"99\n")),
        returncode=None,
        terminate=Mock(),
        wait=AsyncMock(return_value=0),
    )
    monkeypatch.setattr("asyncio.create_subprocess_exec", AsyncMock(return_value=process))

    class ProbeFailure(Exception):
        pass

    try:
        async with display(tmp_path, True):
            assert os.environ["DISPLAY"] == ":99"
            assert os.environ.get("GDK_BACKEND") == "x11"
            assert os.environ.get("MOZ_ENABLE_WAYLAND") == "0"
            assert "WAYLAND_DISPLAY" not in os.environ
            if failure:
                raise ProbeFailure
    except ProbeFailure:
        assert failure
    assert {name: os.environ.get(name) for name in VARIABLES} == (
        before if inherited else dict.fromkeys(VARIABLES)
    )
    process.terminate.assert_called_once()
    process.wait.assert_awaited_once()
