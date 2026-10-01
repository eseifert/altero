"""Inventory declared routes and possible JSON keys without importing server code.

The shape is a union of fields across branches. It does not establish which
fields appear for a requester; that is the job of an executable contract.
Unknown dictionary expansion is retained instead of treated as an empty object.
"""

import ast
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from tools.compatibility.client import CompatibilityError

type Shape = tuple[dict[tuple[str, ...], int], set[tuple[str, ...]]]


def body_nodes(node: ast.AST) -> Iterator[ast.AST]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        yield child
        yield from body_nodes(child)


def response_shape(source: str, function: str, path: str) -> dict[str, Any]:
    tree = ast.parse(source)
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function
    ]
    if len(matches) != 1:
        raise CompatibilityError(f"Expected exactly one server function for {function}")
    definition = matches[0]
    nodes = list(body_nodes(definition))
    values: dict[str, list[ast.AST]] = defaultdict(list)
    additions: dict[str, dict[tuple[str, ...], int]] = defaultdict(dict)
    for node in nodes:
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    values[target.id].append(node.value)
                elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    if isinstance(target.slice, ast.Constant) and isinstance(
                        target.slice.value, str
                    ):
                        additions[target.value.id][(target.slice.value,)] = node.lineno
                    else:
                        values[target.value.id].append(target)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name)
        ):
            values[node.func.value.id].extend(node.args)
            if node.keywords:
                values[node.func.value.id].append(
                    ast.Dict(
                        keys=[
                            ast.Constant(value=kw.arg) if kw.arg else None for kw in node.keywords
                        ],
                        values=[kw.value for kw in node.keywords],
                        lineno=node.lineno,
                    )
                )
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            values[node.target.id].append(node.value)

    def merge(shapes: list[Shape]) -> Shape:
        fields: dict[tuple[str, ...], int] = {}
        dynamic: set[tuple[str, ...]] = set()
        for keys, unknown in shapes:
            fields.update(keys)
            dynamic.update(unknown)
        return fields, dynamic

    def shape(node: ast.AST, seen: frozenset[str] = frozenset()) -> Shape:
        if isinstance(node, ast.Name):
            if node.id in seen or node.id not in values:
                return {}, {()}
            fields, dynamic = merge([shape(value, seen | {node.id}) for value in values[node.id]])
            fields.update(additions[node.id])
            return fields, dynamic
        if isinstance(node, ast.IfExp):
            return merge([shape(node.body, seen), shape(node.orelse, seen)])
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return merge([shape(node.left, seen), shape(node.right, seen)])
        if isinstance(node, ast.Dict):
            pairs = list(zip(node.keys, node.values, strict=True))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "dict"
        ):
            pairs = [
                (ast.Constant(value=kw.arg), kw.value) if kw.arg else (None, kw.value)
                for kw in node.keywords
            ]
            pairs.extend((None, arg) for arg in node.args)
        elif isinstance(node, ast.Constant | ast.List | ast.Tuple | ast.ListComp):
            return {}, set()
        else:
            return {}, {()}
        fields, dynamic = {}, set()
        for key, value in pairs:
            child_fields, child_dynamic = shape(value, seen)
            if key is None:
                fields.update(child_fields)
                dynamic.update(child_dynamic)
            elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                prefix = (key.value,)
                fields[prefix] = getattr(key, "lineno", node.lineno)
                fields.update({prefix + name: line for name, line in child_fields.items()})
                dynamic.update(prefix + name for name in child_dynamic)
            else:
                dynamic.add(())
        return fields, dynamic

    fields, unknown = merge(
        [shape(node.value) for node in nodes if isinstance(node, ast.Return) and node.value]
    )
    prefix = tuple(path.split(".")) if path else ()
    if prefix and prefix not in fields and not any(prefix[: len(p)] == p for p in unknown):
        raise CompatibilityError(f"Server function {function} has no response object {path}")
    return {
        "function": function,
        "line": definition.lineno,
        "end_line": definition.end_lineno,
        "source": ast.get_source_segment(source, definition),
        "fields": {
            name[len(prefix)]: line
            for name, line in fields.items()
            if name[: len(prefix)] == prefix and len(name) == len(prefix) + 1
        },
        "dynamic": any(prefix[: len(p)] == p for p in unknown),
    }


def routes(source: str) -> list[dict[str, Any]]:
    result = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                continue
            if not decorator.args:
                continue
            path = decorator.args[0]
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                result.append(
                    dict(method=method, path=path.value, function=node.name, line=node.lineno)
                )
    return result
