"""Original HTTP scheduling and terminal errors with a virtual clock."""

import pytest


@pytest.mark.parametrize(("backoff", "pauses"), [("3", [3000]), ("bad", []), ("0", [0])])
async def test_backoff_on_success(desktop, backoff, pauses):
    response = await desktop.call(
        "getVersions",
        "item",
        {},
        faults=[
            {
                "status": 200,
                "text": "{}",
                "headers": {"Last-Modified-Version": "0", "Backoff": backoff},
            }
        ],
    )
    assert response["error"] is None
    assert response["pauses"] == pauses


async def test_429_without_retry_after_uses_increasing_delays(desktop):
    response = await desktop.call(
        "getVersions",
        "item",
        {},
        faults=[{"status": 429, "occurrence": 1}, {"status": 429, "occurrence": 2}],
    )
    assert response["error"] is None
    assert response["pauses"] == [30000, 60000]
    assert [r["status"] for r in response["requests"]] == [429, 429, 200]


@pytest.mark.parametrize("status", [400, 403, 412, 500, 503])
async def test_terminal_status_is_not_retried(desktop, status):
    response = await desktop.call("getVersions", "item", {}, faults=[{"status": status}])
    assert response["error"]["status"] == status
    assert len(response["requests"]) == 1
    assert response["pauses"] == []


async def test_invalid_retry_after_does_not_retry_503(desktop):
    response = await desktop.call(
        "getVersions", "item", {}, faults=[{"status": 503, "headers": {"Retry-After": "tomorrow"}}]
    )
    assert response["error"]["status"] == 503
    assert response["diagnostics"] == ["Invalid Retry-After delay tomorrow"]
    assert response["pauses"] == []
