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
    if binary:
        return importlib_resources.read_binary(module, name)

    return importlib_resources.read_text(module, name)


def resource_path(module: types.ModuleType, name: str) -> Any:
    return path(module, name)


def module_contents(module: types.ModuleType) -> Any:
    return importlib_resources.contents(module)


def import_dynamic_module(name: str) -> types.ModuleType:
    return import_module(name)


def path(module: types.ModuleType, name: str) -> Any:
    return importlib_resources.path(module, name)
