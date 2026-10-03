"""An actual killable server process, with file controls outside its HTTP surface."""

import argparse
import asyncio
import json
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn

from altero.app import create_app
from altero.settings import Settings
from tools.compatibility.barriers import HTTPBarrier
from tools.compatibility.runtime import disposable_server


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


class ParentBarrier(HTTPBarrier):
    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.tasks: list[asyncio.Task] = []

    def arm(
        self, method, path, point="before", *, prefix=False, query=None, fault=None, status=503
    ):
        super().arm(method, path, point, prefix=prefix, query=query, fault=fault, status=status)
        token = uuid4().hex
        write_json(
            self.root / "arm.json",
            dict(
                token=token,
                method=method,
                path=path,
                point=point,
                prefix=prefix,
                query=query,
                fault=fault,
                status=status,
            ),
        )

        async def relay():
            marker = self.root / f"reached-{token}.json"
            while not marker.exists():
                await asyncio.sleep(0.01)
            self.trace.append(json.loads(marker.read_text()))
            self.active = False
            self.reached.set()
            await self.release.wait()
            self.root.joinpath(f"release-{token}").touch()

        self.tasks.append(asyncio.create_task(relay()))


class ChildBarrier(HTTPBarrier):
    token: str

    def __init__(self, root: Path):
        super().__init__()
        self.root = root

    async def pause(self, status=None):
        self.trace.append(
            dict(
                method=self.method,
                path=self.path,
                point=self.point,
                status=status,
                fault=self.fault,
            )
        )
        self.root.joinpath("arm.json").unlink()
        marker = self.root / f"reached-{self.token}.json"
        write_json(marker, self.trace[-1])
        while not self.root.joinpath(f"release-{self.token}").exists():
            await asyncio.sleep(0.01)

    def wrap(self, app):
        wrapped = super().wrap(app)

        async def controlled(scope, receive, send):
            marker = self.root / "arm.json"
            if not self.active and marker.exists():
                configuration = json.loads(marker.read_text())
                self.token = configuration.pop("token")
                self.arm(**configuration)
            await wrapped(scope, receive, send)

        return controlled


@asynccontextmanager
async def process_server(root: Path, *, accounts=1, postgres_url=None):
    root.mkdir(parents=True, exist_ok=False)
    # The seed application supplies the same real services for administrative
    # operations. Every desktop request goes to the independent worker below.
    async with disposable_server(
        root / "seed", accounts=accounts, postgres_url=postgres_url
    ) as server:
        assert server.storage_path is not None
        configuration = root / "worker.json"
        configuration.write_text(
            json.dumps(
                dict(
                    database_url=server.database_url,
                    storage_path=str(server.storage_path.resolve()),
                    control=str(root.resolve()),
                )
            )
        )
        control = ParentBarrier(root)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.set_inheritable(True)
        server.url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server.barrier = control
        process = None
        logs = []

        async def start():
            nonlocal process
            if process is not None and process.returncode is None:
                raise ValueError("Server process is already running")
            log = (root / f"worker-{len(logs) + 1}.log").open("wb")
            logs.append(log)
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "tools.compatibility.process_server",
                str(configuration),
                str(listener.fileno()),
                pass_fds=(listener.fileno(),),
                stdout=log,
                stderr=log,
            )
            async with httpx.AsyncClient(base_url=server.url, timeout=1) as client:
                async with asyncio.timeout(15):
                    while True:
                        if process.returncode is not None:
                            raise RuntimeError("Server worker exited before becoming healthy")
                        try:
                            response = await client.get("/health")
                            response.raise_for_status()
                            break
                        except httpx.TransportError:
                            await asyncio.sleep(0.05)
            return process.pid

        async def crash():
            assert process is not None
            assert process.returncode is None
            process.kill()
            assert await process.wait() == -9, "Server was not killed by SIGKILL"
            return process.pid

        server.crash, server.restart = crash, start
        try:
            await start()
            yield server
        finally:
            control.release.set()
            for task in control.tasks:
                task.cancel()
            await asyncio.gather(*control.tasks, return_exceptions=True)
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
            listener.close()
            for log in logs:
                log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("fd", type=int)
    args = parser.parse_args()
    configuration = json.loads(args.configuration.read_text())
    app = create_app(
        Settings(
            database_url=configuration["database_url"],
            storage_path=Path(configuration["storage_path"]),
        )
    )
    uvicorn.run(
        ChildBarrier(Path(configuration["control"])).wrap(app),
        fd=args.fd,
        log_level="error",
        access_log=False,
    )


if __name__ == "__main__":
    main()
