from __future__ import annotations

import os
from importlib import import_module

from .base import CollectionAdapter
from ..config import settings


_FACTORIES = {
    "genesis": (".clothtwin", "ClothTwinAdapter"),
    "isaac_sim": (".isaac_sim", "IsaacSimAdapter"),
    "roboverse": (".roboverse", "RoboVerseAdapter"),
}
_enabled_ids = [item.strip() for item in os.environ.get(
    "ROBOT_DATA_STUDIO_ENABLED_ENGINES", "isaac_sim"
).split(",")]
if not all(_enabled_ids) or any(item not in _FACTORIES for item in _enabled_ids):
    raise ValueError("ROBOT_DATA_STUDIO_ENABLED_ENGINES must list known engine IDs: " + ", ".join(_FACTORIES))
_ENGINES: dict[str, CollectionAdapter] = {}
for _engine_id in _enabled_ids:
    if _engine_id != "isaac_sim":
        settings.require_extension(_engine_id)
    _module, _class = _FACTORIES[_engine_id]
    _ENGINES[_engine_id] = getattr(import_module(_module, __name__), _class)()


_ALIASES = {"clothtwin": "genesis"}


def canonical_engine_id(engine_id: str) -> str:
    return _ALIASES.get(engine_id, engine_id)


def get_engine(engine_id: str) -> CollectionAdapter:
    canonical = canonical_engine_id(engine_id)
    try:
        return _ENGINES[canonical]
    except KeyError:
        raise ValueError(f"unsupported engine: {engine_id}") from None


def engine_descriptors() -> list[dict]:
    return [adapter.descriptor() for adapter in _ENGINES.values()]


def __getattr__(name: str):
    # Preserve direct adapter-class imports without loading every optional
    # adapter when the core registry is imported.
    for module, class_name in _FACTORIES.values():
        if name == class_name:
            return getattr(import_module(module, __name__), class_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ClothTwinAdapter",
    "IsaacSimAdapter",
    "RoboVerseAdapter",
    "canonical_engine_id",
    "engine_descriptors",
    "get_engine",
]
