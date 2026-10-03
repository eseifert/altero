"""Independent graph validity and seeded generation."""

import pytest

from tools.compatibility.protocol_generate import generate_protocol_sequence
from tools.compatibility.protocol_model import ProtocolModel, valid_protocol_sequence


def test_protocol_generation_is_reproducible_and_covers_all_families():
    operations = generate_protocol_sequence(14, 60)
    assert operations == generate_protocol_sequence(14, 60)
    model = ProtocolModel()
    for operation in operations:
        model.apply(operation)
    assert {op["action"] for op in operations} >= {
        "item",
        "collection",
        "search",
        "setting",
        "fulltext",
        "file",
        "access",
        "offline",
        "flush",
        "delete",
    }
    assert {op.get("client") for op in operations} >= {"A", "B"}


@pytest.mark.parametrize("seed", range(100))
def test_generated_sequences_finish_with_access_and_no_stranded_offline_work(seed):
    model = ProtocolModel()
    for operation in generate_protocol_sequence(seed, 60):
        model.apply(operation)
    assert all(model.access.values())
    assert not any(model.pending.values())


def test_shrinking_cannot_leave_an_orphan_or_an_ineffective_operation():
    model = ProtocolModel()
    with pytest.raises(ValueError, match="parent"):
        model.apply(
            dict(
                action="item",
                key="CHILD234",
                data=dict(itemType="note", parentItem="MISSING2", note="x"),
            )
        )
    model.apply(dict(action="item", key="PARENT23", data=dict(itemType="book", title="x")))
    with pytest.raises(ValueError, match="effective"):
        model.apply(dict(action="item", key="PARENT23", data=dict(title="x")))


def test_shrinking_rejects_non_regular_note_parents_and_child_filing():
    model = ProtocolModel()
    model.apply(dict(action="item", key="PARENT23", data=dict(itemType="book", title="Parent")))
    model.apply(
        dict(
            action="item",
            key="CHILD234",
            data=dict(itemType="note", parentItem="PARENT23", note="x"),
        )
    )
    with pytest.raises(ValueError, match="regular"):
        model.apply(
            dict(
                action="item",
                key="ANTHR234",
                data=dict(itemType="note", parentItem="CHILD234", note="x"),
            )
        )
    model.apply(dict(action="collection", key="BASE2345", data=dict(name="Root")))
    with pytest.raises(ValueError, match="collection"):
        model.apply(
            dict(
                action="item",
                key="CHILD234",
                data=dict(parentItem="PARENT23", collections=["BASE2345"]),
            )
        )


@pytest.mark.parametrize("operation", [None, [], "invalid"])
def test_non_mapping_operations_are_rejected_before_replay(operation):
    assert not valid_protocol_sequence([operation])
