"""All schema item types, fields and creator roles survive the wire round trip."""

from tools.compatibility.corpus import schema_corpus


async def test_every_schema_type_field_and_creator_round_trips(desktop):
    corpus = schema_corpus()
    # The annotation needs its attachment parent saved first.
    ordered = sorted(corpus, key=lambda item: item["itemType"] == "annotation")
    uploaded = await desktop.upload(ordered)
    assert len(uploaded["results"]["successful"]) == len(corpus)
    batches = await desktop.value("downloadObjects", "item", [item["key"] for item in corpus])
    objects = {item["key"]: item["data"] for batch in batches for item in batch["json"]}
    assert set(objects) == {item["key"] for item in corpus}
    for expected in corpus:
        stored = objects[expected["key"]]
        for field, value in expected.items():
            assert stored[field] == value, (expected["itemType"], field)
        assert stored["version"] > 0
