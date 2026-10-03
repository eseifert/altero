"""Every network call site stays visible, including callbacks and dynamic URLs."""

import pytest

from tools.compatibility.client import CompatibilityError, run_node
from tools.compatibility.interactions import require_reviewed


def test_network_inventory_includes_unassigned_callbacks_and_transports():
    source = """
    const uri = base + '/items';
    Zotero.HTTP.request('GET', uri, {headers: {'Accept': 'application/json'}});
    setTimeout(async () => {await Zotero.HTTP.download(url, file);});
    new WebSocket(streamURL);
    fetch(`${base}/extra`);
    """
    result = run_node({"operation": "network", "files": [{"file": "client.js", "source": source}]})
    assert not result["errors"]
    calls = result["calls"]
    assert len(calls) == 4
    assert {call["transport"] for call in calls} == {"request", "download", "WebSocket", "fetch"}
    assert calls[0]["uri"] == "{base}/items"
    assert "Accept" in calls[0]["expression"]
    assert calls[1]["method"] == "GET"
    assert calls[-1]["uri"] == "{base}/extra"


def test_network_inventory_reports_parse_errors_and_keeps_other_files():
    result = run_node(
        {
            "operation": "network",
            "files": [
                {"file": "broken.js", "source": "this.invalid = ;"},
                {"file": "valid.js", "source": "this.send = () => this.makeRequest(method, uri);"},
            ],
        }
    )
    assert result["errors"][0]["file"] == "broken.js"
    assert result["calls"][0]["method"] == "{method}"
    assert result["calls"][0]["selector"] == "this.send"


def test_nested_network_calls_are_counted_once():
    result = run_node(
        {
            "operation": "network",
            "files": [
                {
                    "file": "client.js",
                    "source": "this.outer = function() {"
                    "this.inner = () => Zotero.HTTP.request('GET', url);};",
                }
            ],
        }
    )
    assert len(result["calls"]) == 1
    assert result["calls"][0]["selector"] == "this.inner"


@pytest.mark.parametrize(
    ("field", "value"),
    [("errors", [{"file": "bad.js"}]), ("stale", ["removed"]), ("counts", {"unreviewed": 1})],
)
def test_unreviewed_or_broken_source_cannot_pass_the_review_gate(field, value):
    report = dict(errors=[], stale=[], counts={}) | {field: value}
    with pytest.raises(CompatibilityError):
        require_reviewed(report)


def test_alias_resolution_does_not_cross_parameter_or_block_shadowing():
    result = run_node(
        {
            "operation": "network",
            "files": [
                {
                    "file": "client.js",
                    "source": """
    const uri = 'https://example.org';
    this.send = function(uri) {Zotero.HTTP.request('GET', uri);};
    {const uri = base + '/local'; Zotero.HTTP.request('POST', uri);}
    """,
                }
            ],
        }
    )
    assert [call["uri"] for call in result["calls"]] == ["{uri}", "{base}/local"]


def test_jsx_does_not_hide_network_requests():
    result = run_node(
        {
            "operation": "network",
            "files": [
                {
                    "file": "ui.js",
                    "source": "const view = <Panel "
                    "onClick={() => Zotero.HTTP.request('POST', url)}/>;",
                }
            ],
        }
    )
    assert not result["errors"]
    assert result["calls"][0]["method"] == "POST"
