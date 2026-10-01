"""Discovery is useful only if omissions and uncertainty are distinguishable."""

import hashlib
from pathlib import Path

import pytest

from tools.compatibility.analyze import analyze
from tools.compatibility.client import ZoteroClient


@pytest.fixture
def project(tmp_path: Path) -> tuple[ZoteroClient, Path]:
    root = tmp_path / "zotero"
    root.mkdir()
    source = "this.permissions = function(json, id) {return json.members?.includes(id) ?? false;};"
    (root / "groups.js").write_text(source)
    digest = hashlib.sha256(source.encode()).hexdigest()
    manifest = tmp_path / "contracts.toml"
    manifest.write_text(
        '[zotero]\nrevision = "' + "0" * 40 + '"\n'
        '[discovery]\nclient_globs = ["*.js"]\nserver_globs = ["routes.py"]\n'
        '[contracts.permissions]\nsource = "groups.js"\nselector = "this.permissions"\n'
        f'sha256 = "{digest}"\n'
        '[contracts.permissions.server]\nsource = "serializers.py"\n'
        'function = "group"\nobject = "data"\ninput = "json"\n'
    )
    server = tmp_path / "server"
    server.mkdir()
    (server / "serializers.py").write_text('def group():\n    return {"data": {"owner": 1}}\n')
    return ZoteroClient(root, manifest), server


def test_an_omitted_client_input_is_reported_with_source_evidence(project) -> None:
    client, server = project

    report = analyze(client, server, allow_drift=True)

    finding = report["findings"][0]
    assert finding["field"] == "members"
    assert finding["status"] == "unverified"
    assert finding["client"]["file"] == "groups.js"
    assert finding["server"]["file"] == "serializers.py"
    assert report["contracts"][0]["status"] == "candidate"


def test_an_unknown_server_object_is_unresolved_instead_of_missing(project) -> None:
    client, server = project
    (server / "serializers.py").write_text('def group(fields):\n    return {"data": fields}\n')

    report = analyze(client, server, allow_drift=True)

    assert report["findings"] == []
    assert report["contracts"][0]["status"] == "unresolved"


def test_an_unmapped_consumer_is_not_lost_from_the_inventory(project) -> None:
    client, server = project
    (client.root / "new.js").write_text(
        "this.newConsumer = function(json) {return json.newField;};"
    )

    report = analyze(client, server, allow_drift=True)

    assert report["unmapped"][0]["selector"] == "this.newConsumer"


def test_unparseable_client_files_are_reported(project) -> None:
    client, server = project
    (client.root / "broken.js").write_text("this.invalid = ;")

    report = analyze(client, server, allow_drift=True)

    assert report["errors"][0]["file"] == "broken.js"


def test_a_present_field_clears_the_static_candidate(project) -> None:
    client, server = project
    (server / "serializers.py").write_text('def group():\n    return {"data": {"members": [2]}}\n')

    report = analyze(client, server, allow_drift=True)

    assert report["findings"] == []
    assert report["contracts"][0]["status"] == "no-static-gap"
