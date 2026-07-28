"""Behavioural tests for TOML profile loading, validation and sheet matching."""

from pathlib import Path

import pytest

from bepress_importer.profiles import ProfileError, load_profile

FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "mini_profile.toml"


def write_profile(tmp_path, body: str) -> Path:
    path = tmp_path / "p.toml"
    path.write_text(body)
    return path


def test_loads_profile_name_and_defaults():
    profile = load_profile(MINI)
    assert profile.name == "mini"
    assert profile.defaults.record_id_column == "context_key"
    assert profile.defaults.url_column == "calc_url"
    assert profile.defaults.files_enabled is False
    assert profile.defaults.season_style == "edtf-season"
    assert profile.defaults.authors.prefix == "author"
    assert profile.defaults.authors.max == 5


def test_exact_sheet_matching():
    profile = load_profile(MINI)
    sheet = profile.match_sheet("mini")
    assert sheet is not None
    assert sheet.collection == "mini_collection"


def test_glob_sheet_matching():
    profile = load_profile(MINI)
    assert profile.match_sheet("Theses 2024") is not None
    assert profile.match_sheet("Theses 2024").resource_type.constant == "textDocument-thesis"


def test_unmatched_sheet_returns_none():
    profile = load_profile(MINI)
    assert profile.match_sheet("Unknown Sheet") is None


def test_field_mappings_parsed_in_order():
    sheet = load_profile(MINI).match_sheet("mini")
    assert [f.source for f in sheet.fields] == ["title", "abstract", "publication_date"]
    title = sheet.fields[0]
    assert title.target == "/metadata/title"
    assert title.required is True
    assert title.transform is None
    date = sheet.fields[2]
    assert date.transform == "edtf_date"
    assert date.args == {"season_column": "season"}


def test_resource_type_map_and_default():
    sheet = load_profile(MINI).match_sheet("mini")
    assert sheet.resource_type.column == "document_type"
    assert sheet.resource_type.map["article"] == "textDocument-journalArticle"
    assert sheet.resource_type.default == "textDocument-journalArticle"


def test_journal_composite_parsed():
    sheet = load_profile(MINI).match_sheet("mini")
    assert sheet.journal.title == "src_journal"
    assert sheet.journal.volume == "volnum"
    assert sheet.journal.pages_first == "fpage"
    assert sheet.journal.pages_last == "lpage"


def test_contributors_parsed():
    sheet = load_profile(MINI).match_sheet("Theses 2024")
    assert sheet.contributors.prefix == "advisor"
    assert sheet.contributors.max == 3
    assert sheet.contributors.role == "committeeMember"


def test_constants_parsed():
    sheet = load_profile(MINI).match_sheet("mini")
    assert sheet.constants == {"/custom_fields/kcr:sponsoring_institution": "Test University"}


def test_missing_profile_name_is_an_error(tmp_path):
    path = write_profile(tmp_path, '[[sheet]]\nmatch = "x"\n')
    with pytest.raises(ProfileError, match="name"):
        load_profile(path)


def test_target_without_leading_slash_is_an_error(tmp_path):
    path = write_profile(
        tmp_path,
        '[profile]\nname = "p"\n[[sheet]]\nmatch = "x"\n'
        '[[sheet.field]]\nsource = "title"\ntarget = "metadata/title"\n',
    )
    with pytest.raises(ProfileError, match="metadata/title"):
        load_profile(path)


def test_duplicate_targets_are_an_error(tmp_path):
    path = write_profile(
        tmp_path,
        '[profile]\nname = "p"\n[[sheet]]\nmatch = "x"\n'
        '[[sheet.field]]\nsource = "a"\ntarget = "/metadata/title"\n'
        '[[sheet.field]]\nsource = "b"\ntarget = "/metadata/title"\n',
    )
    with pytest.raises(ProfileError, match="/metadata/title"):
        load_profile(path)


def test_unknown_transform_is_an_error_when_registry_given(tmp_path):
    path = write_profile(
        tmp_path,
        '[profile]\nname = "p"\n[[sheet]]\nmatch = "x"\n'
        '[[sheet.field]]\nsource = "a"\ntarget = "/metadata/title"\ntransform = "no_such"\n',
    )
    with pytest.raises(ProfileError, match="no_such"):
        load_profile(path, known_transforms={"edtf_date", "split"})


def test_unknown_transform_allowed_without_registry(tmp_path):
    path = write_profile(
        tmp_path,
        '[profile]\nname = "p"\n[[sheet]]\nmatch = "x"\n'
        '[[sheet.field]]\nsource = "a"\ntarget = "/metadata/title"\ntransform = "no_such"\n',
    )
    profile = load_profile(path)
    assert profile.sheets[0].fields[0].transform == "no_such"


def test_resource_type_requires_column_or_constant(tmp_path):
    path = write_profile(
        tmp_path,
        '[profile]\nname = "p"\n[[sheet]]\nmatch = "x"\n[sheet.resource_type]\ndefault = "d"\n',
    )
    with pytest.raises(ProfileError, match="resource_type"):
        load_profile(path)
