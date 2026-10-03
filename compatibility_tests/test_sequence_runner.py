"""A failed invariant produces a valid, independently confirmed reproducer."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from tools.compatibility import sequence_runner
from tools.compatibility.client import ZoteroClient


def test_protocol_failure_identity_preserves_family_key_and_field():
    identity = sequence_runner.invariant_identity
    original = identity((8, "item", "CHILD234", "note", "object-state"), "protocol")
    assert original == identity((2, "item", "CHILD234", "note", "object-state"), "protocol")
    assert original != identity((2, "item", "CHILD234", "parentItem", "object-state"), "protocol")
    assert original != identity((2, "item", "OTHER234", "note", "object-state"), "protocol")


async def test_runner_shrinks_only_the_original_invariant(monkeypatch, tmp_path):
    @asynccontextmanager
    async def server(_root):
        yield SimpleNamespace(url="http://127.0.0.1:1", key="disposable")

    async def check(_desktop, operations):
        if any(step.get("title") == "trigger" for step in operations):
            assert any(step["action"] == "create" for step in operations)
            raise AssertionError((len(operations), "title"))

    monkeypatch.setattr(sequence_runner, "disposable_server", server)
    monkeypatch.setattr(sequence_runner, "DesktopAPI", lambda *args: None)
    monkeypatch.setattr(sequence_runner, "check_sequence", check)
    steps = [
        {"action": "collection", "key": "CNLLECT2"},
        {"action": "create", "key": "ABCD2345", "title": "old"},
        {"action": "edit", "key": "ABCD2345", "title": "trigger"},
    ]
    report = await sequence_runner.run_sequence(ZoteroClient(tmp_path), steps, tmp_path / "run")
    assert report["passed"] is False
    assert report["failure"]["invariant"] == "title"
    assert report["minimized"] == steps[1:]
    assert report["trials"] > 2
