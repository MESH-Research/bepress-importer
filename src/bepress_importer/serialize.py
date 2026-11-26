"""Canonical JSON serialization: same data in → same bytes out, always."""

from __future__ import annotations

import json
import time
from pathlib import Path


def canonical_dumps(obj: object, sort_keys: bool = True) -> str:
    """Serialize with 2-space indent, unescaped unicode, trailing newline.

    sort_keys=False keeps the object's own (deterministic) key order — used
    where reading order matters, e.g. issues first in report.json.
    """
    return json.dumps(obj, sort_keys=sort_keys, indent=2, ensure_ascii=False) + "\n"


def write_json(path: str | Path, obj: object, sort_keys: bool = True) -> None:
    Path(path).write_text(canonical_dumps(obj, sort_keys=sort_keys), encoding="utf-8")


def backup_existing(path: str | Path) -> Path | None:
    """Set an existing file aside before it is overwritten; returns where it went.

    The file is renamed next to itself with the time it was last written in
    its name (`coll.receipts.json` becomes `coll.receipts.20261126-143210.json`),
    and a counter is added rather than ever replacing an earlier backup.
    Returns None when there was no file to keep.
    """
    path = Path(path)
    if not path.is_file():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(path.stat().st_mtime))
    backup = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    counter = 1
    while backup.exists():
        counter += 1
        backup = path.with_name(f"{path.stem}.{stamp}-{counter}{path.suffix}")
    path.rename(backup)
    return backup
