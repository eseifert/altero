"""Record and verify the PostgreSQL container used by CI, without dependencies."""

import argparse
import json
import subprocess
import sys


def output(*arguments: str) -> str:
    return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout.strip()


def check_postgres(container: str) -> None:
    image_id = output("docker", "inspect", "--format", "{{.Image}}", container)
    digests = json.loads(
        output("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image_id)
    )
    version = json.loads(
        output(
            "docker",
            "exec",
            container,
            "psql",
            "-X",
            "-U",
            "altero",
            "-d",
            "altero",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT json_build_object('version', current_setting('server_version'), "
            "'version_num', current_setting('server_version_num')::integer);",
        )
    )
    number = int(version["version_num"])
    print(f"PostgreSQL server: {version['version']} (server_version_num={number})")
    print(f"PostgreSQL image ID: {image_id}")
    print(f"PostgreSQL registry digests: {', '.join(digests or []) or '(unavailable)'}")
    if not 180007 <= number < 190000:
        raise ValueError("expected PostgreSQL 18.7 or newer within major 18")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container", help="Running CI PostgreSQL service container ID or name")
    args = parser.parse_args(argv)
    try:
        check_postgres(args.container)
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"PostgreSQL CI check failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
