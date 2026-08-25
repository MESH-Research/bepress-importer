"""Canonical JSON serialization: same data in → same bytes out, always."""

from __future__ import annotations

import json
from pathlib import Path


def canonical_dumps(obj: object, sort_keys: bool = True) -> str:
    """Serialize with 2-space indent, unescaped unicode, trailing newline.

    sort_keys=False keeps the object's own (deterministic) key order — used
    where reading order matters, e.g. issues first in report.json.
    """
    return json.dumps(obj, sort_keys=sort_keys, indent=2, ensure_ascii=False) + "\n"


def write_json(path: str | Path, obj: object, sort_keys: bool = True) -> None:
    Path(path).write_text(canonical_dumps(obj, sort_keys=sort_keys), encoding="utf-8")
