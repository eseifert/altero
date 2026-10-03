"""Independent expected state and validity rules for protocol sequences."""

import base64
import copy
import hashlib
import re


class ProtocolModel:
    def __init__(self):
        self.version = 0
        self.objects = {kind: {} for kind in ("item", "collection", "search")}
        self.settings, self.fulltext, self.files = {}, {}, {}
        self.deleted = {kind: set() for kind in ("items", "collections", "searches", "settings")}
        self.pending = {"A": [], "B": []}
        self.access = {"A": True, "B": True}

    def apply(self, operation: dict) -> None:
        """Apply only effective, valid operations; reject candidates during shrinking."""
        trial = copy.deepcopy(self)
        trial._apply(operation)
        self.__dict__.update(trial.__dict__)

    def _apply(self, op):
        action, client = op.get("action"), op.get("client", "A")
        if client not in self.pending:
            raise ValueError("Unknown client")
        key = op.get("key")
        if action in {"item", "collection", "search", "file", "fulltext", "delete", "offline"} and (
            not isinstance(key, str)
            or not re.fullmatch(r"[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}", key)
        ):
            raise ValueError("Invalid key")
        if action == "access":
            value = op.get("value")
            if type(value) is not bool or value == self.access[client]:
                raise ValueError("Access change must be effective")
            self.access[client] = value
            return
        if action == "offline":
            if key not in self.objects["item"] or not op.get("data"):
                raise ValueError("Offline work needs an existing item")
            if any(self.objects["item"][key].get(k) == v for k, v in op["data"].items()):
                raise ValueError("Offline edit must be effective")
            if any(p["key"] == key for p in self.pending[client]):
                raise ValueError("Only one pending edit per object")
            self.pending[client].append(
                op | {"base": self.version, "version": self.objects["item"][key]["version"]}
            )
            return
        if action == "flush":
            if not self.access[client] or not self.pending[client]:
                raise ValueError("Flush needs accessible, pending work")
            next_version = self.version + 1
            for pending in self.pending[client]:
                self._save("item", pending["key"], pending["data"], next_version)
            self.version = next_version
            self.pending[client].clear()
            return
        if not self.access[client]:
            raise ValueError("Writes need credential access")
        next_version = self.version + 1
        if action in self.objects:
            self._save(action, key, op.get("data", {}), next_version)
        elif action == "setting":
            name, value = op["name"], op["value"]
            if value is None:
                if name not in self.settings:
                    raise ValueError("Setting deletion must be effective")
                del self.settings[name]
                self.deleted["settings"].add(name)
            else:
                if self.settings.get(name, {}).get("value") == value:
                    raise ValueError("Setting change must be effective")
                self.settings[name] = dict(value=value, version=next_version)
                self.deleted["settings"].discard(name)
        elif action in {"file", "fulltext"}:
            item = self.objects["item"].get(key)
            if not item or item.get("itemType") != "attachment":
                raise ValueError("File and full text need an attachment parent")
            if action == "fulltext":
                content = op["content"]
                if self.fulltext.get(key, {}).get("content") == content:
                    raise ValueError("Full text must change")
                self.fulltext[key] = dict(
                    content=content,
                    indexedChars=len(content),
                    totalChars=len(content),
                    version=next_version,
                )
            else:
                content = base64.b64decode(op["content"], validate=True)
                if self.files.get(key, {}).get("content") == op["content"]:
                    raise ValueError("File change must be effective")
                self.files[key] = dict(content=op["content"], mtime=op["mtime"])
                item.update(
                    md5=hashlib.md5(content, usedforsecurity=False).hexdigest(),
                    mtime=op["mtime"],
                    contentType="application/pdf",
                    filename="research.pdf",
                    version=next_version,
                )
        elif action == "delete":
            kind = op.get("kind", "item")
            values = self.objects[kind]
            if key not in values:
                raise ValueError("Deletion must be effective")
            doomed = {key}
            if kind == "item":
                while (
                    children := {k for k, v in values.items() if v.get("parentItem") in doomed}
                    - doomed
                ):
                    doomed.update(children)
                if any(p["key"] in doomed for queue in self.pending.values() for p in queue):
                    raise ValueError("Deletion strands pending work")
                for removed in doomed:
                    self.files.pop(removed, None)
                    self.fulltext.pop(removed, None)
            elif kind == "collection":
                for value in values.values():
                    if value.get("parentCollection") == key:
                        value.update(
                            parentCollection=values[key].get("parentCollection", False),
                            version=next_version,
                        )
                for value in self.objects["item"].values():
                    if key in value.get("collections", []):
                        value["collections"].remove(key)
            for removed in doomed:
                del values[removed]
            plural = {"item": "items", "collection": "collections", "search": "searches"}[kind]
            self.deleted[plural].update(doomed)
        else:
            raise ValueError("Unknown protocol operation")
        self.version = next_version

    def _save(self, kind, key, data, version):
        previous = self.objects[kind].get(key, {})
        if not data or (previous and all(previous.get(k) == v for k, v in data.items())):
            raise ValueError("Object change must be effective")
        value = previous | copy.deepcopy(data)
        if "relations" in value:
            value["relations"] = {
                predicate: targets[0]
                if isinstance(targets, list) and len(targets) == 1
                else targets
                for predicate, targets in value["relations"].items()
            }
        if kind == "item":
            if "itemType" not in value:
                raise ValueError("New item needs a type")
            parent = value.get("parentItem")
            if parent and parent not in self.objects["item"]:
                raise ValueError("Missing item parent")
            if (
                parent
                and (
                    value["itemType"] == "note"
                    or (
                        value["itemType"] == "attachment"
                        and value.get("linkMode") != "embedded_image"
                    )
                )
                and self.objects["item"][parent].get("itemType")
                in {"note", "attachment", "annotation"}
            ):
                raise ValueError("Note/attachment parent must be a regular item")
            if parent and value.get("collections"):
                raise ValueError("Child items cannot be assigned to collections")
            if value["itemType"] == "annotation" and (
                not parent or self.objects["item"][parent].get("itemType") != "attachment"
            ):
                raise ValueError("Annotation parent must be an attachment")
            if any(c not in self.objects["collection"] for c in value.get("collections", [])):
                raise ValueError("Missing collection")
        elif kind == "collection":
            parent = value.get("parentCollection")
            seen = {key}
            while parent:
                if parent in seen or parent not in self.objects["collection"]:
                    raise ValueError("Invalid collection parent")
                seen.add(parent)
                parent = self.objects["collection"][parent].get("parentCollection")
        value.update(key=key, version=version)
        self.objects[kind][key] = value


def valid_protocol_sequence(operations):
    if not isinstance(operations, list) or not operations:
        return False
    model = ProtocolModel()
    try:
        for operation in operations:
            if not isinstance(operation, dict):
                return False
            model.apply(operation)
    except ValueError, KeyError, TypeError:
        return False
    return True
