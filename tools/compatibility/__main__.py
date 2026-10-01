"""Run with ``python -m tools.compatibility`` from the repository root."""

import argparse
import asyncio
import json
import shlex
import sys
from pathlib import Path

from tools.compatibility.analyze import analyze
from tools.compatibility.client import DEFAULT_MANIFEST, CompatibilityError, ZoteroClient
from tools.compatibility.reference import reference_evidence
from tools.compatibility.report import markdown
from tools.compatibility.review import evidence, review
from tools.compatibility.surface import inventory
from tools.compatibility.surface import markdown as surface_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["verify", "analyze", "coverage", "sequence", "acceptance"]
    )
    parser.add_argument("--zotero-source", type=Path)
    parser.add_argument(
        "--dataserver-source",
        type=Path,
        help="Cross-check the separately pinned reference checkout",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--server-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--allow-source-drift", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state-dir", type=Path, help="New disposable state directory")
    parser.add_argument("--seed", type=int, default=14)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--replay", type=Path, help="Replay operations from a sequence JSON report")
    parser.add_argument("--desktop-executable", type=Path)
    parser.add_argument("--desktop-version")
    parser.add_argument("--xvfb", action="store_true")
    parser.add_argument("--schema-corpus", action="store_true")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--evidence", type=Path, help="Write the bounded automated-review input")
    parser.add_argument(
        "--review-command", help="Program reading evidence JSON and writing findings JSON"
    )
    args = parser.parse_args()
    try:
        if args.command == "acceptance":
            from tools.compatibility.acceptance import run_acceptance

            if not args.desktop_executable or not args.desktop_version or not args.state_dir:
                raise CompatibilityError(
                    "acceptance requires --desktop-executable, --desktop-version and --state-dir"
                )
            asyncio.run(
                run_acceptance(
                    args.desktop_executable.resolve(),
                    args.desktop_version,
                    args.state_dir,
                    xvfb=args.xvfb,
                    corpus=args.schema_corpus,
                )
            )
            return 0
        if args.command == "coverage":
            result = inventory(root=args.server_root)
            serialized = json.dumps(result, indent=2) + "\n"
            if args.output:
                args.output.write_text(serialized)
            else:
                print(serialized, end="")
            if args.markdown:
                args.markdown.write_text(surface_markdown(result))
            return 0
        if args.zotero_source is None:
            raise CompatibilityError("--zotero-source is required for verify and analyze")
        client = ZoteroClient(args.zotero_source, args.manifest)
        if args.command == "sequence":
            from tools.compatibility.sequence_runner import run_sequence
            from tools.compatibility.sequences import generate_sequence

            if args.state_dir is None or args.output is None:
                raise CompatibilityError("sequence requires --state-dir and --output")
            client.verify_revision()
            if args.replay:
                previous = json.loads(args.replay.read_text())
                operations = previous.get("minimized", previous["operations"])
            else:
                operations = generate_sequence(args.seed, args.steps)
            result = asyncio.run(run_sequence(client, operations, args.state_dir))
            result["seed"] = args.seed if not args.replay else previous.get("seed")
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            return 0 if result["passed"] else 1
        reference = reference_evidence(args.dataserver_source) if args.dataserver_source else None
        if args.command == "verify":
            client.verify_revision()
            for name in client.manifest["contracts"]:
                client.extract(name)
            print(f"Verified {len(client.manifest['contracts'])} client functions")
            return 0
        result = analyze(client, args.server_root, allow_drift=args.allow_source_drift)
        if reference:
            result["reference"] = reference
        packet = evidence(result)
        if args.evidence:
            args.evidence.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
        if args.review_command:
            try:
                command = shlex.split(args.review_command)
            except ValueError as error:
                raise CompatibilityError(f"Invalid review command: {error}") from error
            result["review_findings"] = review(packet, command)
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(serialized)
        else:
            print(serialized, end="")
        if args.markdown:
            args.markdown.write_text(markdown(result))
        return 0
    except (CompatibilityError, OSError, TimeoutError, AssertionError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
