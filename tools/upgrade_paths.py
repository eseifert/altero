"""Replay upgrades from local beta tags with disposable databases and live HTTP.

Run with ``python -m tools.upgrade_paths --state-dir /tmp/altero-upgrades``.
The installed Python dependencies are shared; historical application code and
migrations come from each tag, without altering the checkout. PostgreSQL URLs
are used only to CREATE new databases; generated names and all state survive.
"""

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tarfile
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx2
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
KEY = "UpgradeCheckKey23456789abc"
READER_KEY = "UpgradeReaderKey23456789a"


def beta_tags(root: Path) -> list[str]:
    tags = subprocess.check_output(["git", "tag", "--list", "v1.0.0-beta.*"], cwd=root, text=True)
    return sorted(
        (tag for tag in tags.splitlines() if re.fullmatch(r"v1\.0\.0-beta\.\d+", tag)),
        key=lambda tag: int(tag.rsplit(".", 1)[1]),
    )


def environment(source: Path, state: Path, database_url: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ALTERO_")}
    return env | {
        "PYTHONPATH": str(source / "src"),
        "ALTERO_CONFIG": str(state / "no-config.py"),
        "ALTERO_DATABASE_URL": database_url,
        "ALTERO_STORAGE_PATH": str(state / "storage"),
    }


def extract(root: Path, tag: str, destination: Path) -> str:
    """Pin to the resolved commit before archiving, retaining the exact source."""
    commit = subprocess.check_output(
        ["git", "rev-parse", f"{tag}^{{commit}}"], cwd=root, text=True
    ).strip()
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination.parent / "source.tar"
    with archive.open("wb") as handle:
        subprocess.run(
            ["git", "archive", commit, "src", "migrations", "alembic.ini"],
            cwd=root,
            stdout=handle,
            check=True,
        )
    with tarfile.open(archive) as handle:
        handle.extractall(destination, filter="data")
    return commit


async def fresh_postgres(state: Path, admin_url: str) -> str:
    url = make_url(admin_url)
    if url.drivername != "postgresql+asyncpg":
        raise ValueError("--postgres-url requires a postgresql+asyncpg URL")
    name = f"altero_upgrade_{uuid4().hex}"
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()
    (state / "database.json").write_text(json.dumps({"backend": "postgresql", "name": name}) + "\n")
    return url.set(database=name).render_as_string(hide_password=False)


async def migrate(source: Path, env: dict[str, str], state: Path, label: str) -> None:
    for operation in (("upgrade", "head"), ("check",)):
        with (state / f"{label}-{operation[0]}.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "alembic",
                *operation,
                cwd=source,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                async with asyncio.timeout(120):
                    code = await process.wait()
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if code:
                raise RuntimeError(f"{label} Alembic {operation[0]} failed; see {state}")


@asynccontextmanager
async def live_server(source: Path, env: dict[str, str], state: Path, label: str, *, seed=False):
    """Bind once in the parent so another process cannot steal a reserved port."""
    with socket.socket() as listener, (state / f"{label}-server.log").open("wb") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            str(listener.fileno()),
            *(["--seed"] if seed else []),
            cwd=source,
            env=env,
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=log,
        )
        try:
            url = f"http://127.0.0.1:{listener.getsockname()[1]}"
            async with httpx2.AsyncClient(
                base_url=url, headers={"Zotero-API-Key": KEY}, timeout=10, trust_env=False
            ) as client:
                async with asyncio.timeout(30):
                    while True:
                        if process.returncode is not None:
                            raise RuntimeError(f"{label} server exited; see {state}")
                        try:
                            response = await client.get("/health")
                            if response.status_code == 200:
                                break
                        except httpx2.TransportError:
                            pass
                        await asyncio.sleep(0.05)
                yield client
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    async with asyncio.timeout(15):
                        await process.wait()
                except TimeoutError:
                    process.kill()
                    await process.wait()


async def worker(fd: int, seed: bool) -> None:
    # These imports must resolve through the worker's PYTHONPATH, including
    # when running an old tag. Never import altero in the parent process.
    import uvicorn

    from altero.app import create_app
    from altero.services import admin

    app = create_app()
    if seed:
        async with app.state.database.session_factory() as session:
            await admin.create_user(session, username="upgrade", user_id=1)
            key = await admin.create_api_key(
                session,
                username="upgrade",
                name="Disposable upgrade check",
                all_groups_read=True,
                all_groups_write=True,
            )
            key.key = KEY
            await session.commit()
            group = await admin.create_group(
                session, name="Upgrade group", owner_username="upgrade", group_id=2
            )
            await admin.create_user(session, username="reader", user_id=2)
            reader_key = await admin.create_api_key(
                session,
                username="reader",
                name="Disposable read-only membership",
                all_groups_read=True,
                all_groups_write=True,
            )
            reader_key.key = READER_KEY
            await session.commit()
            await admin.add_group_member(session, group, username="reader", permission="read")
    await uvicorn.Server(uvicorn.Config(app, fd=fd, log_level="warning", access_log=False)).serve()


async def matrix(state: Path, tags: list[str], postgres_url: str | None) -> None:
    from tools.upgrade_corpus import check_new_writes, check_preserved, populate, snapshot

    state.mkdir(parents=True, exist_ok=False)
    report: dict = {
        "target": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "results": [],
    }
    try:
        for tag in tags:
            for backend in ["sqlite", "postgresql"] if postgres_url else ["sqlite"]:
                cell = state / f"{tag}-{backend}"
                cell.mkdir()
                result = {"tag": tag, "backend": backend, "status": "running"}
                report["results"].append(result)
                try:
                    result["source"] = extract(ROOT, tag, cell / "source")
                    if backend == "postgresql":
                        assert postgres_url is not None
                        url = await fresh_postgres(cell, postgres_url)
                    else:
                        url = f"sqlite+aiosqlite:///{cell / 'library.sqlite'}"
                    old_env = environment(cell / "source", cell, url)
                    current_env = environment(ROOT, cell, url)
                    await migrate(cell / "source", old_env, cell, "before")
                    async with live_server(
                        cell / "source", old_env, cell, "before", seed=True
                    ) as client:
                        result["before"] = (await client.get("/health")).json()
                        assert result["before"]["version"] == tag.replace("v", "").replace(
                            "-beta.", "b"
                        )
                        await populate(client)
                        before = await snapshot(client)
                        (cell / "before.json").write_text(json.dumps(before, indent=2) + "\n")
                    await migrate(ROOT, current_env, cell, "after")
                    async with live_server(ROOT, current_env, cell, "after") as client:
                        result["after"] = (await client.get("/health")).json()
                        after = await snapshot(client)
                        (cell / "after.json").write_text(json.dumps(after, indent=2) + "\n")
                        check_preserved(before, after)
                        await check_new_writes(client, after)
                        written = await snapshot(client)
                    await migrate(ROOT, current_env, cell, "restart")
                    async with live_server(ROOT, current_env, cell, "restart") as client:
                        assert await snapshot(client) == written, (
                            "Repeat startup changed library data"
                        )
                    result["status"] = "passed"
                    print(f"{tag} {backend}: passed", flush=True)
                except BaseException:
                    result["status"] = "failed"
                    raise
    finally:
        (state / "report.json").write_text(json.dumps(report, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument(
        "--postgres-url", help="Create disposable databases using this admin connection"
    )
    parser.add_argument("--tag", action="append", help="Limit to a beta tag (repeatable)")
    parser.add_argument("--worker", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--seed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker is not None:
        asyncio.run(worker(args.worker, args.seed))
        return
    if args.state_dir is None:
        parser.error("--state-dir is required and must not exist")
    tags = beta_tags(ROOT)
    if not tags or (args.tag and not set(args.tag) <= set(tags)):
        parser.error("Fetch the beta tags first; --tag must name a local beta release")
    asyncio.run(matrix(args.state_dir.resolve(), args.tag or tags, args.postgres_url))


if __name__ == "__main__":
    main()
