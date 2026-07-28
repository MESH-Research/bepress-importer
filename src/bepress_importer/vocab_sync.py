"""Refresh vocabulary snapshots from a live KC Works / InvenioRDM instance.

Snapshots are committed files, so a sync shows up as a reviewable git diff
before it changes validation behaviour.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bepress_importer.vocab import VOCAB_DIR

# snapshot name → InvenioRDM vocabulary endpoint path
ENDPOINTS = {
    "resource_types": "/api/vocabularies/resourcetypes",
    "rights": "/api/vocabularies/licenses",
    "languages": "/api/vocabularies/languages",
}

Fetcher = Callable[[str], dict]


def sync_vocabularies(
    api_url: str,
    fetch: Fetcher | None = None,
    vocab_dir: str | Path = VOCAB_DIR,
) -> dict[str, int]:
    """Rewrite each snapshot from the live vocabulary endpoints.

    Existing resource-type aliases are preserved. Returns {snapshot: id count}.
    """
    raise NotImplementedError
