"""A full-text acceptance assertion must reject an absent or unfinished index."""

from copy import deepcopy

import pytest

from tools.compatibility.acceptance_fulltext import indexed


@pytest.mark.parametrize("defect", ["missing", "word", "pending", "version"])
def test_fulltext_assertion_requires_persisted_searchable_synced_content(defect):
    snapshot = {"fulltext": {"TEXT2345": dict(matches=["needle"], synced=1, version=2)}}
    indexed(snapshot, "TEXT2345", "needle")
    broken = deepcopy(snapshot)
    row = broken["fulltext"]["TEXT2345"]
    if defect == "missing":
        broken["fulltext"].clear()
    elif defect == "word":
        row["matches"] = []
    elif defect == "pending":
        row["synced"] = 2
    else:
        row["version"] = 0
    with pytest.raises(AssertionError):
        indexed(broken, "TEXT2345", "needle")
