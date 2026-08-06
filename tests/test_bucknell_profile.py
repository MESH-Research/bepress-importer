"""Behavioural tests for the shipped Bucknell profile (post client-remapping)."""

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


def mapping(sheet, source):
    matches = [f for f in sheet.fields if f.source == source]
    assert matches, f"no mapping for {source!r}"
    return matches[0]


def targets(sheet):
    return {f.target for f in sheet.fields}


def test_profile_loads_and_validates(profile):
    assert profile.name == "bucknell"


@pytest.mark.parametrize("sheet_name", SHEETS)
def test_every_export_sheet_is_matched(profile, sheet_name):
    assert profile.match_sheet(sheet_name) is not None


def test_kcr_publication_url_is_not_used_for_work_level_links(profile):
    # reserved for the larger publication (journal/series as a whole)
    for name in SHEETS:
        assert "/custom_fields/kcr:publication_url" not in targets(profile.match_sheet(name))


class TestJournalArticles:
    def test_pub_link_is_a_work_identifier(self, profile):
        sheet = profile.match_sheet("Fac Journal Articles")
        m = mapping(sheet, "pub_link")
        assert m.target == "/metadata/identifiers"
        assert m.transform == "identifier"
        assert m.args["scheme"] == "url"

    def test_pub_statement_becomes_copyright(self, profile):
        sheet = profile.match_sheet("Fac Journal Articles")
        assert mapping(sheet, "pub_statement").target == "/metadata/copyright"

    def test_comments_and_custom_citation_become_additional_descriptions(self, profile):
        sheet = profile.match_sheet("Fac Journal Articles")
        for source in ("comments", "custom_citation"):
            m = mapping(sheet, source)
            assert m.target == "/metadata/additional_descriptions"
            assert m.append is True

    def test_journal_composite_still_present(self, profile):
        assert profile.match_sheet("Fac Journal Articles").journal is not None


class TestTheses:
    @pytest.mark.parametrize("name", ["Masters Theses", "Honors Theses"])
    def test_thesis_fields_use_thesis_thesis_namespace(self, profile, name):
        sheet = profile.match_sheet(name)
        assert mapping(sheet, "department").target == "/custom_fields/thesis:thesis/department"
        assert mapping(sheet, "degree_name").target == "/custom_fields/thesis:thesis/type"
        assert mapping(sheet, "department2").target == "/custom_fields/kcr:institution_department"

    @pytest.mark.parametrize("name", ["Masters Theses", "Honors Theses"])
    def test_university_comes_from_author_institutions_with_default(self, profile, name):
        sheet = profile.match_sheet(name)
        m = mapping(sheet, "author1_institution")
        assert m.target == "/custom_fields/thesis:thesis/university"
        assert m.transform == "author_institution"
        assert m.args.get("default") == "Bucknell University"
        assert sheet.constants == {}

    @pytest.mark.parametrize("name", ["Masters Theses", "Honors Theses"])
    def test_concentration_merges_into_disciplines(self, profile, name):
        sheet = profile.match_sheet(name)
        m = mapping(sheet, "disciplines")
        assert m.target == "/custom_fields/kcr:discipline"
        assert m.args.get("also_columns") == ["concentration"]

    @pytest.mark.parametrize("name", ["Masters Theses", "Honors Theses"])
    def test_multimedia_format_becomes_media(self, profile, name):
        sheet = profile.match_sheet(name)
        assert mapping(sheet, "multimedia_format").target == "/custom_fields/kcr:media"


class TestBooksAndPress:
    @pytest.mark.parametrize("name", ["BU Authored Books", "Bu Press"])
    def test_buy_link_is_a_related_identifier(self, profile, name):
        m = mapping(profile.match_sheet(name), "buy_link")
        assert m.target == "/metadata/related_identifiers"
        assert m.transform == "related_identifier"
        assert m.args["scheme"] == "url"

    def test_press_rights_text_becomes_copyright_and_arr_license(self, profile):
        sheet = profile.match_sheet("Bu Press")
        rights_mappings = [f for f in sheet.fields if f.source == "rights"]
        by_target = {f.target: f for f in rights_mappings}
        assert "/metadata/copyright" in by_target
        arr = by_target["/metadata/rights"]
        assert arr.transform == "constant_if_present"
        assert arr.args["value"] == [{"id": "arr"}]

    def test_press_bu_type_is_a_namespaced_tag(self, profile):
        m = mapping(profile.match_sheet("Bu Press"), "bu_type")
        assert m.target == "/custom_fields/kcr:user_defined_tags"
        assert m.transform == "prefixed_tag"
        assert m.append is True


class TestDigitalAndPodcasts:
    def test_dssrf_multimedia_url_is_a_work_identifier(self, profile):
        m = mapping(profile.match_sheet("Student Digital Projects (DSSRF"), "multimedia_url")
        assert m.target == "/metadata/identifiers"
        assert m.args["scheme"] == "url"

    def test_podcast_multimedia_url_is_a_work_identifier(self, profile):
        m = mapping(profile.match_sheet("BU Podcasts"), "multimedia_url")
        assert m.target == "/metadata/identifiers"

    def test_podcast_duration_becomes_sizes(self, profile):
        m = mapping(profile.match_sheet("BU Podcasts"), "duration")
        assert m.target == "/metadata/sizes"

    def test_digital_scholarship_fulltext_url_is_a_work_identifier(self, profile):
        m = mapping(profile.match_sheet("BU Digital Scholarship"), "fulltext_url")
        assert m.target == "/metadata/identifiers"

    def test_digital_scholarship_copyright_note_maps_to_copyright(self, profile):
        m = mapping(profile.match_sheet("BU Digital Scholarship"), "copyright_note")
        assert m.target == "/metadata/copyright"

    @pytest.mark.parametrize(
        "name", ["Student Digital Projects (DSSRF", "BU Podcasts"]
    )
    def test_rights_text_becomes_copyright(self, profile, name):
        m = mapping(profile.match_sheet(name), "rights")
        assert m.target == "/metadata/copyright"
