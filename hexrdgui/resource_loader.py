from __future__ import annotations

import types
from importlib import import_module
from typing import Any

try:
    import importlib.resources as importlib_resources
except ImportError:
    # Try backported to PY<37 `importlib_resources`.
    import importlib_resources  # type: ignore[no-redef]


def load_resource(
    module: types.ModuleType, name: str, binary: bool = False
) -> str | bytes:
    """This will return a string of a resource's contents"""
    resource = importlib_resources.files(module) / name
    if binary:
        return resource.read_bytes()

    return resource.read_text()


def resource_path(module: types.ModuleType, name: str) -> Any:
    return path(module, name)


def module_contents(module: types.ModuleType) -> Any:
    return [r.name for r in importlib_resources.files(module).iterdir()]


def import_dynamic_module(name: str) -> types.ModuleType:
    return import_module(name)


def path(module: types.ModuleType, name: str) -> Any:
    return importlib_resources.as_file(importlib_resources.files(module) / name)
