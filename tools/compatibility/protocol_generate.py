"""Seeded effective graph operations with recoverable offline work."""

import base64
import copy
import random

from tools.compatibility.protocol_model import ProtocolModel


def generate_protocol_sequence(seed: int, steps: int = 60) -> list[dict]:
    if steps < 32:
        raise ValueError("Protocol sequences need at least 32 steps")
    randomizer = random.Random(seed)
    operations = [
        dict(action="collection", key="BASE2345", data=dict(name="Root")),
        dict(
            action="collection",
            key="BRANCH23",
            data=dict(name="Branch", parentCollection="BASE2345"),
        ),
        dict(
            action="item",
            key="PARENT23",
            data=dict(itemType="book", title="Über 東京", collections=["BRANCH23"]),
        ),
        dict(action="item", key="NTHER234", data=dict(itemType="book", title="Other")),
        dict(
            action="item",
            key="CHILD234",
            data=dict(itemType="note", parentItem="PARENT23", note="<p>研究</p>"),
        ),
        dict(
            action="item",
            key="ATTACH23",
            data=dict(
                itemType="attachment",
                parentItem="PARENT23",
                linkMode="imported_file",
                filename="research.pdf",
                contentType="application/pdf",
            ),
        ),
        dict(
            action="item",
            key="ANN23456",
            data=dict(
                itemType="annotation",
                parentItem="ATTACH23",
                annotationType="highlight",
                annotationText="東京",
                annotationComment="Über",
                annotationColor="#ffd400",
                annotationPageLabel="1",
                annotationSortIndex="00000|000001|00000",
                annotationPosition='{"pageIndex":0,"rects":[[1,2,3,4]]}',
            ),
        ),
        dict(
            action="search",
            key="SEARCH23",
            data=dict(
                name="Research",
                conditions=[dict(condition="title", operator="contains", value="Über")],
            ),
        ),
        dict(action="setting", name="tagColors", value=[dict(name="研究", color="#123456")]),
        dict(
            action="file",
            key="ATTACH23",
            content=base64.b64encode(b"%PDF-1.4\ninitial\n").decode(),
            mtime=1785701798544,
        ),
        dict(action="fulltext", key="ATTACH23", content="Über 東京 研究"),
        dict(action="offline", key="PARENT23", data=dict(title="Offline A"), client="A"),
        dict(action="item", key="PARENT23", data=dict(abstractNote="Remote B"), client="B"),
        dict(action="flush", client="A"),
        dict(action="offline", key="NTHER234", data=dict(title="Queued B"), client="B"),
        dict(action="access", client="B", value=False),
        dict(action="access", client="B", value=True),
        dict(action="flush", client="B"),
        dict(action="item", key="CHILD234", data=dict(parentItem="NTHER234")),
        dict(
            action="item",
            key="ANN23456",
            data=dict(annotationComment="Changed 研究", annotationColor="#ff6666"),
        ),
        dict(action="collection", key="BRANCH23", data=dict(parentCollection=False)),
        dict(
            action="search",
            key="SEARCH23",
            data=dict(
                name="Changed", conditions=[dict(condition="tag", operator="is", value="研究")]
            ),
        ),
        dict(
            action="item",
            key="PARENT23",
            data=dict(
                tags=[dict(tag="研究")], relations={"dc:relation": ["https://example.org/related"]}
            ),
        ),
        dict(action="item", key="PARENT23", data=dict(deleted=True)),
        dict(action="item", key="PARENT23", data=dict(deleted=False)),
        dict(action="item", key="PARENT23", data=dict(tags=[], relations={}, collections=[])),
        dict(action="setting", name="tagColors", value=None),
        dict(action="setting", name="tagColors", value=[dict(name="recreated", color="#ff6666")]),
        dict(action="delete", kind="search", key="SEARCH23"),
        dict(action="delete", kind="collection", key="BASE2345"),
        dict(action="delete", key="PARENT23"),
        dict(action="delete", key="NTHER234"),
    ]
    model = ProtocolModel()
    for operation in operations:
        model.apply(operation)
    for index in range(steps - len(operations)):
        key = "GEN" + f"{index + 2:05d}".translate(str.maketrans("01", "AB"))
        actor = randomizer.choice(["A", "B"])
        title = f"Seed {seed}: {index} 東京"
        candidates = [
            dict(
                action="item",
                key=key,
                data=dict(
                    itemType=randomizer.choice(["book", "journalArticle", "report", "webpage"]),
                    title=title,
                ),
            ),
            dict(action="collection", key=key, data=dict(name=title)),
            dict(
                action="search",
                key=key,
                data=dict(
                    name=title,
                    conditions=[dict(condition="title", operator="contains", value=title)],
                ),
            ),
            dict(action="setting", name="tagColors", value=[dict(name=title, color="#123456")]),
        ]
        for existing, value in model.objects["item"].items():
            candidates.append(dict(action="delete", key=existing))
            if value["itemType"] not in {"annotation", "note", "attachment"}:
                candidates.extend(
                    [
                        dict(action="item", key=existing, data=dict(title=title)),
                        dict(
                            action="item",
                            key=existing,
                            data=dict(deleted=not value.get("deleted", False)),
                        ),
                        dict(action="item", key=existing, data=dict(tags=[dict(tag=title)])),
                        dict(
                            action="item",
                            key=key,
                            data=dict(itemType="note", parentItem=existing, note=f"<p>{title}</p>"),
                        ),
                        dict(
                            action="item",
                            key=key,
                            data=dict(
                                itemType="attachment",
                                parentItem=existing,
                                linkMode="imported_file",
                                filename="research.pdf",
                                contentType="application/pdf",
                            ),
                        ),
                        dict(action="offline", key=existing, data=dict(abstractNote=title)),
                    ]
                )
                for collection in model.objects["collection"]:
                    candidates.append(
                        dict(
                            action="item",
                            key=existing,
                            data=dict(
                                collections=[]
                                if collection in value.get("collections", [])
                                else [collection]
                            ),
                        )
                    )
            elif value["itemType"] == "attachment":
                candidates.extend(
                    [
                        dict(
                            action="file",
                            key=existing,
                            content=base64.b64encode(title.encode()).decode(),
                            mtime=1785701798544 + index + 1,
                        ),
                        dict(action="fulltext", key=existing, content=title),
                    ]
                )
        for kind in ("collection", "search"):
            for existing in model.objects[kind]:
                candidates.append(dict(action="delete", kind=kind, key=existing))
                if kind == "collection":
                    candidates.append(
                        dict(action="collection", key=existing, data=dict(name=title))
                    )
        if model.settings:
            candidates.append(dict(action="setting", name="tagColors", value=None))
        candidates.extend(
            [dict(action="access", value=not model.access[actor]), dict(action="flush")]
        )
        randomizer.shuffle(candidates)
        # End with accessible credentials and committed pending edits.
        recovery = [
            dict(action="access", client=c, value=True) for c in ("A", "B") if not model.access[c]
        ]
        recovery += [dict(action="flush", client=c) for c in ("A", "B") if model.pending[c]]
        remaining = steps - len(operations)
        if remaining <= len(recovery):
            candidates = recovery
        for candidate in candidates:
            operation = candidate | {"client": candidate.get("client", actor)}
            try:
                trial = copy.deepcopy(model)
                trial.apply(operation)
            except ValueError:
                continue
            recovery_cost = sum(not allowed for allowed in trial.access.values())
            recovery_cost += sum(bool(queue) for queue in trial.pending.values())
            if recovery_cost > remaining - 1:
                continue
            model = trial
            operations.append(operation)
            break
        else:
            raise AssertionError("Generator ran out of valid, effective operations")
    return operations
