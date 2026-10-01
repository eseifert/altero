"""Run with ``python -m tools.compatibility`` from the repository root."""

import argparse
import json
import shlex
import sys
from pathlib import Path

from tools.compatibility.analyze import analyze
from tools.compatibility.client import DEFAULT_MANIFEST, CompatibilityError, ZoteroClient
from tools.compatibility.report import markdown
from tools.compatibility.review import evidence, review
from tools.compatibility.surface import inventory
from tools.compatibility.surface import markdown as surface_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify", "analyze", "coverage"])
    parser.add_argument("--zotero-source", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--server-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--allow-source-drift", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--evidence", type=Path, help="Write the bounded automated-review input")
    parser.add_argument(
        "--review-command", help="Program reading evidence JSON and writing findings JSON"
    )
    args = parser.parse_args()
    try:
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
        if args.command == "verify":
            client.verify_revision()
            for name in client.manifest["contracts"]:
                client.extract(name)
            print(f"Verified {len(client.manifest['contracts'])} client functions")
            return 0
        result = analyze(client, args.server_root, allow_drift=args.allow_source_drift)
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
    except (CompatibilityError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
