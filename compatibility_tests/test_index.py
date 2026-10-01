"""Source inventories retain the conditions behind a protocol expectation."""

from tools.compatibility.client import run_node
from tools.compatibility.index_server import response_shape, routes


def test_client_reads_are_traced_through_a_simple_alias() -> None:
    source = """
    this.permissions = function(json, id) {
      const data = json;
      let editable = false;
      if (data.members && data.members.indexOf(id) !== -1) editable = true;
      return editable;
    };
    """
    entry = run_node({"operation": "index", "source": source})[0]

    assert {read["field"] for read in entry["reads"] if read["root"] == "json"} == {"members"}
    assert entry["defaults"][0]["value"] is False
    assert "data.members.indexOf(id)" in entry["conditions"][0]["expression"]


def test_client_inventory_keeps_headers_and_request_construction() -> None:
    source = """
    this.getGroup = async function(userID) {
      const uri = this.baseURL + 'users/' + userID + '/groups';
      const response = await this.makeRequest('GET', uri);
      if (response.status === 304) return false;
      return response.getResponseHeader('Last-Modified-Version');
    };
    """
    entry = run_node({"operation": "index", "source": source})[0]

    assert entry["headers"][0]["name"] == "Last-Modified-Version"
    assert entry["requests"][0]["method"] == "GET"
    assert entry["requests"][0]["uri"] == "{this.baseURL}users/{userID}/groups"
    assert "response.status === 304" in entry["conditions"][0]["expression"]


def test_conditional_server_fields_are_possible_fields() -> None:
    source = """
def group(roster):
    data = {"owner": 1}
    if roster:
        data["members"] = roster
    return {"data": data}
"""
    shape = response_shape(source, "group", "data")

    assert set(shape["fields"]) == {"owner", "members"}
    assert not shape["dynamic"]


def test_an_inline_server_object_has_the_same_shape_as_an_alias() -> None:
    shape = response_shape('def group():\n    return {"data": {"owner": 1}}\n', "group", "data")

    assert set(shape["fields"]) == {"owner"}
    assert not shape["dynamic"]


def test_unknown_updates_make_missing_field_analysis_uncertain() -> None:
    source = """
def group(fields):
    data = {"owner": 1}
    data.update(fields)
    return {"data": data}
"""
    shape = response_shape(source, "group", "data")

    assert set(shape["fields"]) == {"owner"}
    assert shape["dynamic"]


def test_dictionary_expansion_keeps_known_fields_and_uncertainty() -> None:
    source = 'def group(fields):\n    return {"data": {"owner": 1, **fields}}\n'

    assert response_shape(source, "group", "data")["dynamic"]


def test_a_keyword_update_is_not_mistaken_for_an_absent_field() -> None:
    source = (
        'def group():\n    data = {}\n    data.update(members=[2])\n    return {"data": data}\n'
    )

    assert "members" in response_shape(source, "group", "data")["fields"]


def test_an_unknown_union_update_is_reported_as_dynamic() -> None:
    source = 'def group(fields):\n    data = {}\n    data |= fields\n    return {"data": data}\n'

    assert response_shape(source, "group", "data")["dynamic"]


def test_routes_are_indexed_without_importing_the_application() -> None:
    source = """
@router.get('/groups/{group_id}')
async def get_group():
    pass
"""

    assert routes(source)[0] == {
        "method": "GET",
        "path": "/groups/{group_id}",
        "function": "get_group",
        "line": 3,
    }
