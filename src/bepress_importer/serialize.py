"""Canonical JSON serialization: same data in → same bytes out, always."""

from __future__ import annotations

import json
from pathlib import Path


def canonical_dumps(obj: object) -> str:
    """Serialize with sorted keys, 2-space indent, unescaped unicode, trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_json(path: str | Path, obj: object) -> None:
    Path(path).write_text(canonical_dumps(obj), encoding="utf-8")
