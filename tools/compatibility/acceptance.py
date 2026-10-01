"""Convergence scenarios with two real desktop databases and local file storage."""

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from tools.compatibility.acceptance_runtime import AcceptanceRun
from tools.compatibility.client import CompatibilityError
from tools.compatibility.corpus import schema_corpus
from tools.compatibility.runtime import disposable_server


@asynccontextmanager
async def display(root: Path, xvfb: bool) -> AsyncIterator[None]:
    if not xvfb:
        yield
        return
    previous = os.environ.get("DISPLAY")
    with (root / "xvfb.log").open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            "Xvfb",
            "-displayfd",
            "1",
            "-screen",
            "0",
            "1280x800x24",
            "-nolisten",
            "tcp",
            stdout=asyncio.subprocess.PIPE,
            stderr=log,
        )
        try:
            assert process.stdout is not None
            async with asyncio.timeout(10):
                number = (await process.stdout.readline()).decode().strip()
            if not number.isdigit():
                raise CompatibilityError("Xvfb failed to allocate a display")
            os.environ["DISPLAY"] = ":" + number
            yield
        finally:
            if previous is None:
                os.environ.pop("DISPLAY", None)
            else:
                os.environ["DISPLAY"] = previous
            if process.returncode is None:
                process.terminate()
            await process.wait()


def item_state(snapshot: dict) -> dict:
    return {item["key"]: item for item in snapshot["items"]}


async def run_baseline(
    executable: Path, version: str, root: Path, *, xvfb=False, corpus=False
) -> dict:
    """Keep every phase result and profile for review; refuse existing state."""
    root.mkdir(parents=True, exist_ok=False)
    phases = []
    async with display(root, xvfb), disposable_server(root / "server") as server:
        runner = AcceptanceRun(executable, version, root, server)

        async def phase(name, operations=(), *, sync=True, files=True):
            snapshot = await runner.phase(
                name,
                operations,
                sync=sync,
                files=files,
            )
            number = len(phases) + 1
            path = root / f"phase-{number}-{name}.json"
            phases.append(
                {
                    "client": name,
                    "sync": sync,
                    "operations": list(operations),
                    "snapshot": path.name,
                }
            )
            return snapshot

        try:
            attachment = root / "research.pdf"
            content = b"%PDF-1.4\nDisposable compatibility bytes\n%%EOF\n"
            attachment.write_bytes(content)
            first = await phase(
                "A",
                [
                    {"action": "create", "key": "ABCD2345"},
                    {
                        "action": "create",
                        "key": "NNTE2345",
                        "data": {
                            "itemType": "note",
                            "parentItem": "ABCD2345",
                            "note": "<p>研究</p>",
                        },
                    },
                    {"action": "collection", "key": "CNLLECT2", "name": "研究"},
                    {"action": "file", "key": "ABCD2345", "collections": ["CNLLECT2"]},
                    {"action": "attach", "key": "ABCD2345", "path": str(attachment.resolve())},
                ],
            )
            second = await phase("B")
            assert item_state(first) == item_state(second), "Initial desktop states differ"
            await runner.converged(first, second)
            expected_file = base64.b64encode(content).decode()
            assert list(first["files"].values()) == [expected_file]
            assert second["files"] == first["files"], "Attachment bytes did not reach desktop B"
            await phase(
                "A",
                [{"action": "edit", "key": "ABCD2345", "fields": {"title": "Offline A 東京"}}],
                sync=False,
            )
            await phase(
                "B",
                [
                    {
                        "action": "edit",
                        "key": "ABCD2345",
                        "fields": {"abstractNote": "Offline B Über"},
                    }
                ],
                sync=False,
            )
            await phase("A")
            merged = await phase("B")
            converged = await phase("A")
            assert item_state(merged) == item_state(converged), "Offline clients did not converge"
            await runner.converged(merged, converged)
            item = item_state(converged)["ABCD2345"]
            assert item["title"] == "Offline A 東京"
            assert item["abstractNote"] == "Offline B Über"
            await phase("A", [{"action": "trash", "key": "ABCD2345"}])
            assert item_state(await phase("B"))["ABCD2345"]["deleted"] == 1
            await phase("B", [{"action": "restore", "key": "ABCD2345"}])
            assert not item_state(await phase("A"))["ABCD2345"].get("deleted")
            await phase("A", [{"action": "delete", "key": "ABCD2345"}])
            assert item_state(await phase("B")) == {}, "Parent deletion left orphaned children"
            if corpus:
                payloads = sorted(
                    schema_corpus(), key=lambda item: item["itemType"] == "annotation"
                )
                created = await phase(
                    "A",
                    [{"action": "create", "key": item["key"], "data": item} for item in payloads],
                    files=False,
                )
                downloaded = await phase("B", files=False)
                assert len(created["items"]) == len(payloads)
                assert item_state(created) == item_state(downloaded), (
                    "Schema corpus failed desktop convergence"
                )
            report = {
                "passed": True,
                "desktop_version": version,
                "schema_corpus": corpus,
                "phases": phases,
            }
        except Exception as error:
            report = {
                "passed": False,
                "desktop_version": version,
                "phases": phases,
                "error": str(error),
            }
            (root / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
            raise
    (root / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


SCENARIOS = ("baseline", "conflicts")


async def run_acceptance(
    executable: Path, version: str, root: Path, *, xvfb=False, corpus=False, scenarios=None
) -> dict:
    """Each scenario gets two profiles and its own server; retain failures."""
    from tools.compatibility.acceptance_conflicts import conflicts

    selected = tuple(scenarios or SCENARIOS)
    if not selected or any(name not in SCENARIOS for name in selected):
        raise CompatibilityError("Unknown or empty acceptance scenario selection")
    root.mkdir(parents=True, exist_ok=False)
    report: dict = dict(passed=False, desktop_version=version, scenarios={})
    try:
        async with display(root, xvfb):
            for name in selected:
                scenario_root = root / name
                if name == "baseline":
                    result = await run_baseline(executable, version, scenario_root, corpus=corpus)
                else:
                    scenario_root.mkdir()
                    async with disposable_server(scenario_root / "server") as server:
                        runner = AcceptanceRun(executable, version, scenario_root, server)
                        try:
                            await conflicts(runner)
                        finally:
                            report["scenarios"][name] = dict(phases=runner.phases)
                    result = dict(passed=True, phases=runner.phases)
                report["scenarios"][name] = result
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        (root / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
