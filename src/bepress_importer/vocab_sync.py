"""Refresh vocabulary snapshots from a live KC Works / InvenioRDM instance.

Snapshots are committed files, so a sync shows up as a reviewable git diff
before it changes validation behaviour.
"""

from __future__ import annotations

import json
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
    fetch = fetch or _http_fetch
    vocab_dir = Path(vocab_dir)
    vocab_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, endpoint in ENDPOINTS.items():
        url = f"{api_url.rstrip('/')}{endpoint}?size=10000"
        payload = fetch(url)
        ids = sorted(hit["id"] for hit in payload["hits"]["hits"])
        snapshot_path = vocab_dir / f"{name}.json"
        snapshot: dict = {}
        if snapshot_path.exists():
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["_comment"] = f"Synced from {api_url} via: bepress-importer vocab sync"
        snapshot["ids"] = ids
        if name == "resource_types":
            snapshot.setdefault("aliases", {})
        snapshot_path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        counts[name] = len(ids)
    return counts


def _http_fetch(url: str) -> dict:
    import requests

    response = requests.get(url, headers={"Accept": "application/json"}, timeout=60)
    response.raise_for_status()
    return response.json()
