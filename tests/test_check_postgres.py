"""CI checks the running server and the image it actually uses."""

import json
import subprocess

import pytest

from tools import check_postgres

IMAGE_ID = "sha256:" + "a" * 64
REGISTRY_DIGEST = "postgres@sha256:" + "b" * 64


@pytest.mark.parametrize(
    ("number", "accepted"),
    [
        (180007, True),
        (180008, True),
        (180010, True),
        (180006, False),
        (180000, False),
        (170012, False),
        (190000, False),
        (190001, False),
    ],
)
def test_ci_accepts_only_patched_postgresql_18(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], number: int, accepted: bool
) -> None:
    def docker(arguments: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if arguments[:2] == ("docker", "inspect"):
            assert arguments[-1] == "postgres-service"
            result = IMAGE_ID
        elif arguments[:3] == ("docker", "image", "inspect"):
            # Inspect the container's immutable image, not the moving tag.
            assert arguments[-1] == IMAGE_ID
            result = json.dumps([REGISTRY_DIGEST])
        else:
            assert arguments[:4] == ("docker", "exec", "postgres-service", "psql")
            assert "current_setting('server_version_num')" in arguments[-1]
            # A reassuring display string cannot override the numeric version.
            result = json.dumps({"version": "18.7 (fixture)", "version_num": number})
        return subprocess.CompletedProcess(arguments, 0, stdout=result)

    monkeypatch.setattr(check_postgres.subprocess, "run", docker)
    assert check_postgres.main(["postgres-service"]) == (0 if accepted else 1)
    captured = capsys.readouterr()
    assert f"server_version_num={number}" in captured.out
    assert IMAGE_ID in captured.out
    assert REGISTRY_DIGEST in captured.out
    if not accepted:
        assert "18.7 or newer within major 18" in captured.err


@pytest.mark.parametrize("operation", ["inspect", "exec"])
def test_ci_fails_when_the_service_cannot_be_inspected_or_queried(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], operation: str
) -> None:
    def unavailable(
        arguments: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if arguments[1] == operation:
            raise subprocess.CalledProcessError(1, arguments, stderr="service unavailable")
        result = IMAGE_ID if arguments[1] == "inspect" else json.dumps([REGISTRY_DIGEST])
        return subprocess.CompletedProcess(arguments, 0, stdout=result)

    monkeypatch.setattr(check_postgres.subprocess, "run", unavailable)
    assert check_postgres.main(["postgres-service"]) == 1
    assert "service unavailable" in capsys.readouterr().err
