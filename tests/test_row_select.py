"""Behavioural tests for row-level select routing.

One flat table (e.g. a site-wide Content Inventory) can carry several mapping
groups: each `[[sheet]]` block may declare a `select` on a column, rows are
routed to the first block whose select matches, and a block without a select
is the catch-all. The selection is pure profile data — nothing is hardcoded.
"""

import pytest

from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import ProfileError, load_profile
from bepress_importer.readers import Table, Workbook

AS_OF = "2026-08-25"

PROFILE_TOML = """
[profile]
name = "routed"
schema_version = 1

[defaults]
record_id.column = "context_key"

[[sheet]]
match = "*"
collection = "journals"
require_columns = ["context_key", "publication"]
select = { column = "publication", values = ["fac_journ", "tnp_journ"] }

  [sheet.resource_type]
  constant = "textDocument-journalArticle"

  [[sheet.field]]
  source = "title"
  target = "/metadata/title"
  required = true

[[sheet]]
match = "*"
collection = "theses"
require_columns = ["context_key", "publication"]
select = { column = "publication", values = ["masters_theses"] }

  [sheet.resource_type]
  constant = "textDocument-thesis"

  [[sheet.field]]
  source = "title"
  target = "/metadata/title"
  required = true

  [[sheet.field]]
  source = "degree_name"
  target = "/custom_fields/thesis:thesis/type"

[[sheet]]
match = "*"
collection = "everything_else"
require_columns = ["context_key", "publication"]

  [sheet.resource_type]
  constant = "textDocument-other"

  [[sheet.field]]
  source = "title"
  target = "/metadata/title"
  required = true
"""

COLUMNS = ("context_key", "publication", "title", "degree_name", "state")


def row(context_key, publication, title, **overrides):
    base = {column: "" for column in COLUMNS}
    base.update(context_key=context_key, publication=publication, title=title)
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def profile(tmp_path_factory):
    path = tmp_path_factory.mktemp("profiles") / "routed.toml"
    path.write_text(PROFILE_TOML)
    return load_profile(path)


class TestSelectParsing:
    def test_select_is_parsed_into_column_and_values(self, profile):
        journals = profile.sheets[0]
        assert journals.select is not None
        assert journals.select.column == "publication"
        assert journals.select.values == ("fac_journ", "tnp_journ")

    def test_catch_all_block_has_no_select(self, profile):
        assert profile.sheets[2].select is None

    def test_select_without_values_is_a_profile_error(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text(
            PROFILE_TOML.replace(
                'select = { column = "publication", values = ["masters_theses"] }',
                'select = { column = "publication" }',
            )
        )
        with pytest.raises(ProfileError):
            load_profile(path)

    def test_select_without_column_is_a_profile_error(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text(
            PROFILE_TOML.replace(
                'select = { column = "publication", values = ["masters_theses"] }',
                'select = { values = ["masters_theses"] }',
            )
        )
        with pytest.raises(ProfileError):
            load_profile(path)


class TestMatchSheets:
    def test_returns_every_fitting_block_in_profile_order(self, profile):
        blocks = profile.match_sheets("Content Inventory", columns=COLUMNS)
        assert [b.collection for b in blocks] == ["journals", "theses", "everything_else"]

    def test_require_columns_still_exclude_legend_sheets(self, profile):
        assert profile.match_sheets("Field Names", columns=("Fields included",)) == ()

    def test_match_sheet_returns_the_first_fitting_block(self, profile):
        assert profile.match_sheet("anything", columns=COLUMNS).collection == "journals"


@pytest.fixture(scope="module")
def result(profile):
    table = Table(
        name="Content Inventory",
        columns=COLUMNS,
        rows=(
            row("1", "fac_journ", "A journal article"),
            row("2", "masters_theses", "A thesis", degree_name="MSc"),
            row("3", "susquehanna", "A symposium poster"),
            row("4", "tnp_journ", "Another journal article"),
        ),
    )
    return convert_workbook(Workbook(tables=(table,)), profile, as_of=AS_OF)


class TestRowRouting:
    def test_rows_are_routed_to_the_first_matching_block(self, result):
        titles = [r["metadata"]["title"] for r in result.collections["journals"]]
        assert titles == ["A journal article", "Another journal article"]

    def test_each_block_applies_its_own_mappings(self, result):
        thesis = result.collections["theses"][0]
        assert thesis["metadata"]["resource_type"] == {"id": "textDocument-thesis"}
        assert thesis["custom_fields"]["thesis:thesis"]["type"] == "MSc"

    def test_unselected_rows_fall_to_the_catch_all(self, result):
        titles = [r["metadata"]["title"] for r in result.collections["everything_else"]]
        assert titles == ["A symposium poster"]

    def test_every_row_is_converted_exactly_once(self, result):
        total = sum(len(records) for records in result.collections.values())
        assert total == 4

    def test_sheet_docs_describe_each_group_and_its_selection(self, result):
        docs = {doc["collection"]: doc for doc in result.sheet_docs}
        assert docs["journals"]["records"] == 2
        assert docs["journals"]["select"] == {
            "column": "publication",
            "values": ["fac_journ", "tnp_journ"],
        }
        assert "select" not in docs["everything_else"]

    def test_rows_matching_no_block_are_reported_as_issues(self, profile):
        # a profile whose blocks all have selects: unrouted rows must surface
        table = Table(
            name="Content Inventory",
            columns=COLUMNS,
            rows=(row("9", "unknown_pub", "Orphan row"),),
        )
        from dataclasses import replace

        selective_profile = replace(profile, sheets=profile.sheets[:2])
        result = convert_workbook(Workbook(tables=(table,)), selective_profile, as_of=AS_OF)
        assert result.collections == {}
        assert any(
            issue.record_id == "9" and "select" in issue.message for issue in result.issues
        )

    def test_per_block_row_filters_apply_after_routing(self, tmp_path):
        toml = PROFILE_TOML.replace(
            'select = { column = "publication", values = ["fac_journ", "tnp_journ"] }',
            'select = { column = "publication", values = ["fac_journ", "tnp_journ"] }\n'
            "\n  [sheet.filter]\n"
            '  column = "state"\n'
            '  keep = ["published"]\n',
        )
        path = tmp_path / "filtered.toml"
        path.write_text(toml)
        filtered_profile = load_profile(path)
        table = Table(
            name="Content Inventory",
            columns=COLUMNS,
            rows=(
                row("1", "fac_journ", "Published article", state="published"),
                row("2", "fac_journ", "Withdrawn article", state="withdrawn"),
            ),
        )
        result = convert_workbook(Workbook(tables=(table,)), filtered_profile, as_of=AS_OF)
        titles = [r["metadata"]["title"] for r in result.collections["journals"]]
        assert titles == ["Published article"]
