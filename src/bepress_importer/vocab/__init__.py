"""Bundled KC Works vocabulary snapshots (refresh with `bpress-importer vocab sync`)."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

VOCAB_DIR = Path(__file__).parent


@cache
def load(name: str) -> dict:
    """Load a vocabulary snapshot by name (e.g. "resource_types")."""
    return json.loads((VOCAB_DIR / f"{name}.json").read_text(encoding="utf-8"))
