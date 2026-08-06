"""Behavioural tests for the shipped Bepress site-inventory profile."""

from pathlib import Path

import pytest

from bepress_importer.profiles import load_profile
from bepress_importer.transforms import known_transforms

PROFILE = Path(__file__).parent.parent / "profiles" / "inventory.toml"


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
