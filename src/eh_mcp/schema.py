"""Type-skeleton helper for the developer schema probe.

Turns a parsed JSON response into a structure of the same shape where every
scalar value is replaced by its type name. Field names survive (they are
schema, not data); values never do. This lets a developer confirm the live API
shape during setup without any personal data reaching the model.
"""

from __future__ import annotations

from typing import Any

_MAX_DEPTH = 6


def type_skeleton(obj: Any, _depth: int = 0) -> Any:
    if _depth > _MAX_DEPTH:
        return "..."
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, int):
        return "int"
    if isinstance(obj, float):
        return "float"
    if isinstance(obj, str):
        return "str"
    if isinstance(obj, list):
        if not obj:
            return "list[empty]"
        # One element is enough to learn the item shape; its values are typed
        # away too, so nothing leaks even from the sample row.
        return [type_skeleton(obj[0], _depth + 1)]
    if isinstance(obj, dict):
        return {str(k): type_skeleton(v, _depth + 1) for k, v in obj.items()}
    return type(obj).__name__
