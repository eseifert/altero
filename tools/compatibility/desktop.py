"""Launch a real Zotero application in disposable profiles, with a test plugin."""

import asyncio
import json
import os
from pathlib import Path
from zipfile import ZipFile

from tools.compatibility.client import CompatibilityError

PLUGIN_ID = "acceptance@altero.invalid"
BOOTSTRAP = Path(__file__).with_name("desktop_bootstrap.js")


def prepare_profile(root: Path, server_url: str) -> Path:
    root.mkdir(parents=True, exist_ok=False)
    profile = root / "profile"
    profile.mkdir()
    data = root / "data"
    data.mkdir()
    extensions = profile / "extensions"
    extensions.mkdir()
    manifest = dict(
        manifest_version=2,
        name="Altero disposable acceptance runner",
        version="1.0",
        applications={
            "zotero": dict(
                id=PLUGIN_ID,
                strict_min_version="7.0",
                strict_max_version="10.*",
                update_url="https://altero.invalid/acceptance-updates.json",
            )
        },
    )
    with ZipFile(extensions / f"{PLUGIN_ID}.xpi", "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.write(BOOTSTRAP, "bootstrap.js")
    preferences = {
        "app.update.enabled": False,
        "extensions.update.enabled": False,
        "extensions.zoteroOpenOfficeIntegration.skipInstallation": True,
        "extensions.zoteroWinWordIntegration.skipInstallation": True,
        "extensions.zoteroMacWordIntegration.skipInstallation": True,
        "extensions.autoDisableScopes": 0,
        "extensions.zotero.dataDir": str(data.resolve()),
        "extensions.zotero.useDataDir": True,
        "extensions.zotero.api.url": server_url.rstrip("/") + "/",
        "extensions.zotero.streaming.enabled": False,
        "extensions.zotero.sync.autoSync": False,
        "extensions.zotero.automaticScraperUpdates": False,
        "extensions.zotero.firstRunGuidance": False,
        "extensions.zotero.firstRun2": False,
        "extensions.zotero.firstRun.skipFirefoxProfileAccessCheck": True,
        "extensions.altero.acceptance.config": str((root / "command.json").resolve()),
    }
    (profile / "user.js").write_text(
        "\n".join(
            f"user_pref({json.dumps(name)}, {json.dumps(value)});"
            for name, value in preferences.items()
        )
        + "\n"
    )
    return profile


async def run_phase(
    executable: Path,
    root: Path,
    *,
    version: str,
    key: str,
    operations: list[dict],
    sync: bool = True,
    timeout: float = 120,
) -> dict:
    result_path = root / "result.json"
    result_path.unlink(missing_ok=True)
    (root / "command.json").write_text(
        json.dumps(
            dict(
                version=version,
                key=key,
                operations=operations,
                sync=sync,
                result=str(result_path.resolve()),
            )
        )
    )
    environment = os.environ | {"MOZ_NO_REMOTE": "1"}
    log = (root / "desktop.log").open("ab")
    try:
        process = await asyncio.create_subprocess_exec(
            str(executable),
            "-ZoteroDebugText",
            "-no-remote",
            "-profile",
            str((root / "profile").resolve()),
            stdout=log,
            stderr=log,
            env=environment,
        )
        try:
            async with asyncio.timeout(timeout):
                await process.wait()
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
    finally:
        log.close()
    if not result_path.is_file():
        raise CompatibilityError(f"Desktop produced no result; inspect {root / 'desktop.log'}")
    result = json.loads(result_path.read_text())
    if result.get("error"):
        raise CompatibilityError(f"Desktop acceptance failed: {result['error']}")
    if process.returncode:
        raise CompatibilityError(f"Desktop exited with status {process.returncode}")
    return result
