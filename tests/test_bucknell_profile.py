"""Behavioural tests for the shipped Bucknell profile."""

from pathlib import Path

import pytest

from bepress_importer.profiles import load_profile
from bepress_importer.transforms import known_transforms

PROFILE = Path(__file__).parent.parent / "profiles" / "bucknell.toml"

SHEETS = [
    "Fac Journal Articles",
    "Masters Theses",
    "Honors Theses",
    "BU Authored Books",
    "Bu Press",
    "BU Digital Scholarship",
    "Student Digital Projects (DSSRF",
    "BU Podcasts",
]


@pytest.fixture(scope="module")
def profile():
    return load_profile(PROFILE, known_transforms=known_transforms())


def test_profile_loads_and_validates(profile):
    assert profile.name == "bucknell"


@pytest.mark.parametrize("sheet_name", SHEETS)
def test_every_export_sheet_is_matched(profile, sheet_name):
    assert profile.match_sheet(sheet_name) is not None


def test_journal_articles_map_core_fields(profile):
    sheet = profile.match_sheet("Fac Journal Articles")
    targets = {f.target for f in sheet.fields}
    assert "/metadata/title" in targets
    assert "/metadata/publication_date" in targets
    assert "/custom_fields/kcr:user_defined_tags" in targets
    assert sheet.journal is not None
    assert sheet.resource_type.map["article"] == "textDocument-journalArticle"


def test_theses_have_advisor_contributors_and_degree(profile):
    for name in ("Masters Theses", "Honors Theses"):
        sheet = profile.match_sheet(name)
        assert sheet.contributors.prefix == "advisor"
        assert sheet.contributors.role == "committeeMember"
        targets = {f.target for f in sheet.fields}
        assert "/custom_fields/kcr:degree" in targets
    masters = profile.match_sheet("Masters Theses")
    assert masters.resource_type.map["masters_thesis"] == "textDocument-thesis"


def test_books_are_constant_book_type(profile):
    assert profile.match_sheet("BU Authored Books").resource_type.constant == "textDocument-book"
    assert profile.match_sheet("Bu Press").resource_type.constant == "textDocument-book"


def test_podcasts_map_to_podcast_episode(profile):
    sheet = profile.match_sheet("BU Podcasts")
    assert sheet.resource_type.map["interview"] == "audiovisual-podcastEpisode"


def test_dssrf_license_urls_become_rights(profile):
    sheet = profile.match_sheet("Student Digital Projects (DSSRF")
    license_fields = [f for f in sheet.fields if f.transform == "license_url"]
    assert license_fields and license_fields[0].target == "/metadata/rights"
