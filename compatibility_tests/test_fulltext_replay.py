"""Full-text requests come from the original API client, including gzip."""

import pytest


@pytest.mark.parametrize("content", ["", "Über 東京 " * 200])
async def test_fulltext_content_versions_and_missing_items(desktop, content):
    await desktop.upload(
        [
            {
                "key": "ABCD2345",
                "itemType": "attachment",
                "linkMode": "imported_file",
                "contentType": "application/pdf",
                "filename": "research.pdf",
            }
        ]
    )
    assert await desktop.value("getFullTextForItem", "ABCD2345") is False
    result = await desktop.call(
        "setFullTextForItems",
        1,
        [
            {
                "key": "ABCD2345",
                "content": content,
                "indexedChars": len(content),
                "totalChars": len(content),
            }
        ],
    )
    assert result["error"] is None
    assert result["value"]["libraryVersion"] == "2"
    assert bool(result["requests"][0]["headers"].get("Content-Encoding")) is bool(content)
    read = await desktop.value("getFullTextForItem", "ABCD2345")
    assert read == {
        "version": "2",
        "data": {"content": content, "indexedChars": len(content), "totalChars": len(content)},
    }
    versions = await desktop.value("getFullTextVersions", 0)
    assert versions == {"libraryVersion": "2", "versions": {"ABCD2345": 2}}
    assert (await desktop.value("getFullTextVersions", 2))["versions"] == {}
    assert await desktop.value("getFullTextForItem", "ZZZZ9999") is False
    conflict = await desktop.call(
        "setFullTextForItems", 1, [{"key": "ABCD2345", "content": "lost"}]
    )
    assert conflict["error"]["status"] == 412
    assert (await desktop.value("getFullTextForItem", "ABCD2345"))["data"]["content"] == content
