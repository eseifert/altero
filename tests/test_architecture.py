"""Guards on the layering.

The core of the application must stay independent of the web framework so that
it can be reused behind a different one. Only :mod:`altero.api`, the application
factory and the server entry point may import FastAPI, Starlette or uvicorn.
"""

import ast
from pathlib import Path

import pytest

import altero

SOURCE_ROOT = Path(altero.__file__).parent

#: Packages whose presence in an import makes a module framework-dependent.
WEB_FRAMEWORK_PACKAGES = {"fastapi", "starlette", "uvicorn"}

#: Modules allowed to reach for the web framework: the HTTP layer itself, the
#: application factory that assembles it, and the entry points that start it.
FRAMEWORK_MODULES = {"app.py", "__main__.py", "cli.py"}

#: Modules that make up the framework-independent core.
CORE_MODULES = sorted(
    path
    for path in SOURCE_ROOT.rglob("*.py")
    if "api" not in path.relative_to(SOURCE_ROOT).parts and path.name not in FRAMEWORK_MODULES
)


def imported_packages(path: Path) -> set[str]:
    """Return the top-level packages imported by the module at ``path``."""
    packages: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            packages.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            packages.add(node.module.split(".")[0])
    return packages


def test_the_core_modules_were_discovered() -> None:
    names = {path.name for path in CORE_MODULES}

    assert {"keys.py", "search.py", "pagination.py", "serializers.py", "errors.py"} <= names
    assert any(path.parent.name == "services" for path in CORE_MODULES)


@pytest.mark.parametrize("path", CORE_MODULES, ids=lambda path: path.name)
def test_core_modules_do_not_import_a_web_framework(path: Path) -> None:
    offenders = imported_packages(path) & WEB_FRAMEWORK_PACKAGES

    assert not offenders, f"{path.name} imports {', '.join(sorted(offenders))}"


@pytest.mark.parametrize("path", CORE_MODULES, ids=lambda path: path.name)
def test_core_modules_do_not_import_the_api_layer(path: Path) -> None:
    for node in ast.walk(ast.parse(path.read_text())):
        module = getattr(node, "module", None)
        if isinstance(node, ast.ImportFrom) and module:
            assert not module.startswith("altero.api"), f"{path.name} imports {module}"
