"""Behavioural tests for vocabulary snapshot refresh (HTTP mocked out)."""

import json

from bepress_importer.vocab_sync import sync_vocabularies


def fake_fetch(url):
    catalog = {
        "resourcetypes": ["textDocument-journalArticle", "dataset", "textDocument-newType"],
        "licenses": ["cc-by-4.0", "cc0-1.0", "brand-new-license"],
        "languages": ["eng", "spa", "zzz"],
    }
    for key, ids in catalog.items():
        if key in url:
            return {"hits": {"hits": [{"id": i} for i in ids], "total": len(ids)}}
    raise AssertionError(f"unexpected url {url}")


def test_sync_writes_all_three_snapshots_with_sorted_ids(tmp_path):
    counts = sync_vocabularies("https://works.example.org", fetch=fake_fetch, vocab_dir=tmp_path)
    assert counts == {"resource_types": 3, "rights": 3, "languages": 3}
    for name in ("resource_types", "rights", "languages"):
        data = json.loads((tmp_path / f"{name}.json").read_text())
        assert data["ids"] == sorted(data["ids"])
    rights = json.loads((tmp_path / "rights.json").read_text())
    assert "brand-new-license" in rights["ids"]


def test_existing_aliases_are_preserved(tmp_path):
    (tmp_path / "resource_types.json").write_text(
        json.dumps({"ids": ["old"], "aliases": {"article": "textDocument-journalArticle"}})
    )
    sync_vocabularies("https://works.example.org", fetch=fake_fetch, vocab_dir=tmp_path)
    data = json.loads((tmp_path / "resource_types.json").read_text())
    assert data["aliases"] == {"article": "textDocument-journalArticle"}
    assert "old" not in data["ids"]
    assert "textDocument-newType" in data["ids"]
