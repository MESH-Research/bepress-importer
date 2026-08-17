"""Behavioural tests for the shipped Bepress site-inventory profile."""

from pathlib import Path

import pytest

from bepress_importer.profiles import load_profile
from bepress_importer.transforms import known_transforms

PROFILE = (
    Path(__file__).parent.parent / "src" / "bepress_importer" / "profiles" / "inventory.toml"
)


@pytest.fixture(scope="module")
def profile():
    return load_profile(PROFILE, known_transforms=known_transforms())


def test_profile_loads_and_matches_inventory_sheet(profile):
    assert profile.match_sheet("inventory") is not None


def test_only_published_rows_are_imported(profile):
    sheet = profile.match_sheet("inventory")
    assert sheet.filter.column == "state"
    assert sheet.filter.keep == ("published",)


def test_record_identity_is_context_key_with_no_url_column(profile):
    assert profile.defaults.record_id_column == "context_key"
    assert profile.defaults.url_column is None


def test_common_document_types_are_mapped(profile):
    rt = profile.match_sheet("inventory").resource_type
    assert rt.map["article"] == "textDocument-journalArticle"
    assert rt.map["honors_thesis"] == "textDocument-thesis"
    assert rt.map["poster"] == "presentation-conferencePoster"
    assert rt.map["conference_paper"] == "presentation-conferencePaper"
    assert rt.default == "textDocument-other"


def test_content_inventory_document_types_are_mapped(profile):
    rt = profile.match_sheet("inventory").resource_type
    assert rt.map["abstracts"] == "textDocument-abstract"
    assert rt.map["installation"] == "image-visualArt"
    assert rt.map["informationalworks"] == "textDocument-documentation"
    assert rt.map["webbasedmaterials"] == "other-interactiveResource"
    for front_matter in ("fullissue", "full_issue", "acknowledgements", "contributors",
                         "introductions", "newsletters", "printmaterials", "program",
                         "Program (Publication)", "response", "letter"):
        assert rt.map[front_matter] == "textDocument-other"


def test_every_mapped_resource_type_exists_in_the_vocabulary(profile):
    import json

    vocab_path = (
        Path(__file__).parent.parent / "src" / "bepress_importer" / "vocab"
        / "resource_types.json"
    )
    known_ids = set(json.loads(vocab_path.read_text())["ids"])
    rt = profile.match_sheet("inventory").resource_type
    assert set(rt.map.values()) <= known_ids
    assert rt.default in known_ids


def test_publication_date_falls_back_to_the_event_start_date(profile):
    mapping = next(
        f for f in profile.match_sheet("inventory").fields
        if f.target == "/metadata/publication_date"
    )
    assert mapping.args.get("fallback_columns") == ["start_date"]


def test_core_fields_and_builders_are_mapped(profile):
    sheet = profile.match_sheet("inventory")
    targets = {f.target for f in sheet.fields}
    assert "/metadata/title" in targets
    assert "/metadata/publication_date" in targets
    assert "/metadata/description" in targets
    assert "/custom_fields/kcr:user_defined_tags" in targets
    assert sheet.journal is not None
    assert sheet.journal.issn == "issn"
    assert sheet.contributors.prefix == "advisor"
