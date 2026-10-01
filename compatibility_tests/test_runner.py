"""The harness must execute the upstream function, not a translation of it."""

import hashlib
from pathlib import Path

import pytest

from tools.compatibility.client import CompatibilityError, ZoteroClient


@pytest.fixture
def source(tmp_path: Path) -> Path:
    (tmp_path / "groups.js").write_text(
        "this.permissions = function (json, id) {\n"
        "  // Braces in strings must not fool extraction: }\n"
        "  const ignored = '}';\n"
        "  return {editable: json.members?.indexOf(id) !== -1 && !!json.members};\n"
        "};\n"
    )
    return tmp_path


def manifest(source: Path, tmp_path: Path, *, selector: str = "this.permissions") -> Path:
    path = tmp_path / "contracts.toml"
    digest = hashlib.sha256((source / "groups.js").read_bytes()).hexdigest()
    path.write_text(
        '[zotero]\nrevision = "' + "0" * 40 + '"\n'
        '[contracts.permissions]\nsource = "groups.js"\n'
        f'selector = "{selector}"\nsha256 = "{digest}"\n'
    )
    return path


def test_javascript_membership_keeps_its_strict_type_check(source: Path, tmp_path: Path) -> None:
    client = ZoteroClient(source, manifest(source, tmp_path))

    assert client.call("permissions", [{"members": [2]}, 2]) == {"editable": True}
    assert client.call("permissions", [{"members": ["2"]}, 2]) == {"editable": False}


def test_a_changed_source_requires_review(source: Path, tmp_path: Path) -> None:
    client = ZoteroClient(source, manifest(source, tmp_path))
    (source / "groups.js").write_text("this.permissions = function () { return true; };")

    with pytest.raises(CompatibilityError, match="fingerprint"):
        client.call("permissions", [])


def test_a_missing_function_is_an_error(source: Path, tmp_path: Path) -> None:
    client = ZoteroClient(source, manifest(source, tmp_path, selector="this.missing"))

    with pytest.raises(CompatibilityError, match="exactly one"):
        client.call("permissions", [])


def test_duplicate_functions_are_not_chosen_arbitrarily(source: Path, tmp_path: Path) -> None:
    with (source / "groups.js").open("a") as file:
        file.write("this.permissions = function () { return false; };\n")
    client = ZoteroClient(source, manifest(source, tmp_path))

    with pytest.raises(CompatibilityError, match="exactly one"):
        client.call("permissions", [])


def test_source_paths_cannot_escape_the_checkout(source: Path, tmp_path: Path) -> None:
    path = manifest(source, tmp_path)
    path.write_text(path.read_text().replace('source = "groups.js"', 'source = "../groups.js"'))

    with pytest.raises(CompatibilityError, match="inside"):
        ZoteroClient(source, path).call("permissions", [])


def test_a_client_exception_reports_its_message(source: Path, tmp_path: Path) -> None:
    (source / "groups.js").write_text(
        "this.permissions = function () { throw new Error('Invalid group'); };"
    )
    client = ZoteroClient(source, manifest(source, tmp_path))

    with pytest.raises(CompatibilityError, match="Invalid group"):
        client.call("permissions", [])


def test_a_loop_cannot_hang_the_test_run(source: Path, tmp_path: Path) -> None:
    (source / "groups.js").write_text("this.permissions = function () { while (true) {} };")
    client = ZoteroClient(source, manifest(source, tmp_path))

    with pytest.raises(CompatibilityError, match="timed out"):
        client.call("permissions", [])


def test_async_method_shorthand_is_extracted_as_a_function(source: Path, tmp_path: Path) -> None:
    (source / "groups.js").write_text(
        "const object = {async permissions(json) {return json.members.map(id => id + 1);}};"
    )
    client = ZoteroClient(source, manifest(source, tmp_path, selector="permissions"))

    assert client.call("permissions", [{"members": [2]}]) == [3]
