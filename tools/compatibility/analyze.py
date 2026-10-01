"""Compare mapped contracts and report consumers that have no mapping yet."""

import hashlib
from pathlib import Path
from typing import Any

from tools.compatibility.client import CompatibilityError, ZoteroClient, read_inside, run_node
from tools.compatibility.index_server import response_shape, routes


def source_files(root: Path, patterns: list[str], declared: list[str]) -> list[str]:
    result = set(declared)
    for pattern in patterns:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise CompatibilityError(f"Discovery pattern must be inside its checkout: {pattern}")
        result.update(str(path.relative_to(root)) for path in root.glob(pattern) if path.is_file())
    return sorted(result)


def analyze(client: ZoteroClient, server: Path, *, allow_drift: bool = False) -> dict[str, Any]:
    pinned = True
    revision_error = None
    try:
        client.verify_revision()
    except CompatibilityError as error:
        if not allow_drift:
            raise
        pinned, revision_error = False, str(error)
    if not allow_drift:
        for name in client.manifest["contracts"]:
            client.source(name)
    report: dict[str, Any] = dict(
        schema=1,
        expected_revision=client.manifest["zotero"]["revision"],
        pinned=pinned,
        revision_error=revision_error,
        contracts=[],
        findings=[],
        inventory=[],
        unmapped=[],
        routes=[],
        errors=[],
    )
    declarations = client.manifest["contracts"]
    discovery = client.manifest.get("discovery", {})
    inventory = {}
    for file in source_files(
        client.root, discovery.get("client_globs", []), [c["source"] for c in declarations.values()]
    ):
        try:
            source = read_inside(client.root, file)
            entries = run_node({"operation": "index", "source": source})
            for entry in entries:
                entry["file"] = file
            inventory[file] = entries
            report["inventory"].extend(entries)
        except CompatibilityError as error:
            report["errors"].append(dict(file=file, error=str(error)))

    for name, declaration in declarations.items():
        entry: dict[str, Any] = dict(
            name=name, status="execution-only", tests=declaration.get("tests", [])
        )
        report["contracts"].append(entry)
        try:
            contract, source = client.source(name, allow_drift=allow_drift)
            entry["fingerprint_matches"] = (
                hashlib.sha256(source.encode()).hexdigest() == contract["sha256"]
            )
            if not entry["fingerprint_matches"]:
                report["pinned"] = False
            matches = [
                e
                for e in inventory.get(contract["source"], [])
                if e["selector"] == contract["selector"]
            ]
            if len(matches) != 1:
                raise CompatibilityError(f"Expected exactly one consumer for {name}")
            consumer = matches[0]
            entry["client"] = dict(
                file=contract["source"],
                line=consumer["line"],
                end_line=consumer["end_line"],
                code="\n".join(source.splitlines()[consumer["line"] - 1 : consumer["end_line"]]),
                **{
                    key: consumer[key]
                    for key in ("reads", "headers", "requests", "conditions", "defaults")
                },
            )
            entry["server_evidence"] = []
            bindings = contract.get("evidence", [])
            if "server" in contract:
                bindings = [contract["server"], *bindings]
            for binding in bindings:
                shape = response_shape(
                    read_inside(server, binding["source"]),
                    binding["function"],
                    binding.get("object", ""),
                )
                entry["server_evidence"].append(dict(file=binding["source"], **shape))
            if "server" not in contract or "input" not in contract["server"]:
                continue
            binding = contract["server"]
            shape = entry["server_evidence"][0]
            if shape["dynamic"]:
                entry["status"] = "unresolved"
                continue
            exceptions = contract.get("exceptions", {})
            if any(
                not isinstance(reason, str) or not reason.strip() for reason in exceptions.values()
            ):
                raise CompatibilityError(f"Exceptions in {name} need an explanation")
            entry["exceptions"] = exceptions
            consumed = {
                read["field"]: read["line"]
                for read in consumer["reads"]
                if read["root"] == binding["input"]
            }
            missing = consumed.keys() - shape["fields"].keys() - exceptions.keys()
            entry["status"] = "candidate" if missing else "no-static-gap"
            for field in sorted(missing):
                report["findings"].append(
                    dict(
                        contract=name,
                        field=field,
                        status="unverified",
                        client=dict(file=contract["source"], line=consumed[field]),
                        server=dict(
                            file=binding["source"], line=shape["line"], function=binding["function"]
                        ),
                    )
                )
        except (CompatibilityError, SyntaxError) as error:
            entry["status"] = "unresolved"
            entry["error"] = str(error)
            report["errors"].append(dict(contract=name, error=str(error)))

    mapped = {(c["source"], c["selector"]) for c in declarations.values()}
    report["unmapped"] = [
        dict(file=e["file"], selector=e["selector"], line=e["line"])
        for e in report["inventory"]
        if (e["file"], e["selector"]) not in mapped
        and (e["requests"] or e["headers"] or any(r["root"] == "json" for r in e["reads"]))
    ]
    for file in source_files(server, discovery.get("server_globs", []), []):
        try:
            report["routes"].extend(
                dict(file=file, **route) for route in routes(read_inside(server, file))
            )
        except (CompatibilityError, SyntaxError) as error:
            report["errors"].append(dict(file=file, error=str(error)))
    return report
