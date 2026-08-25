"""Behavioural tests for dumping a single record straight from an export."""

import json

import pytest

from bepress_importer.profiles import load_profile
from bepress_importer.readers import Table, Workbook
from bepress_importer.show import MISSING, annotate_missing, explain_record, render

AS_OF = "2026-08-25"

PROFILE_TOML = """
[profile]
name = "mini"
schema_version = 1

[defaults]
record_id.column = "context_key"

[[sheet]]
match = "*"
collection = "theses"
require_columns = ["context_key", "state"]
select = { column = "publication", values = ["masters_theses"] }

  [sheet.filter]
  column = "state"
  keep = ["published"]

  [sheet.resource_type]
  constant = "textDocument-thesis"

  [[sheet.field]]
  source = "title"
  target = "/metadata/title"
  required = true

  [[sheet.field]]
  source = "publication_date"
  target = "/metadata/publication_date"
  transform = "edtf_date"
  required = true

[[sheet]]
match = "*"
collection = "everything_else"
require_columns = ["context_key", "state"]

  [sheet.filter]
  column = "state"
  keep = ["published"]

  [[sheet.field]]
  source = "title"
  target = "/metadata/title"
  required = true
"""

COLUMNS = ("context_key", "state", "publication", "title", "publication_date")


def row(context_key, title="A title", state="published", publication="masters_theses",
        publication_date="2020-01-01"):
    return dict(zip(COLUMNS, (context_key, state, publication, title, publication_date)))


@pytest.fixture(scope="module")
def profile(tmp_path_factory):
    path = tmp_path_factory.mktemp("profiles") / "mini.toml"
    path.write_text(PROFILE_TOML)
    return load_profile(path)


def workbook(*rows):
    return Workbook(
        tables=(
            Table(name="Content Inventory", columns=COLUMNS, rows=tuple(rows)),
            Table(name="Field Names", columns=("Fields included",), rows=()),
        )
    )


class TestExplainRecord:
    def test_converts_the_requested_row(self, profile):
        view = explain_record(workbook(row("1"), row("2", title="Wanted")), profile,
                              "2", as_of=AS_OF)
        assert view.record["metadata"]["title"] == "Wanted"
        assert view.collection == "theses"
        assert view.sheet == "Content Inventory"
        assert view.excluded is None

    def test_reports_required_fields_left_empty(self, profile):
        view = explain_record(workbook(row("1", publication_date="")), profile,
                              "1", as_of=AS_OF)
        assert view.missing == ("/metadata/publication_date",)

    def test_a_complete_record_has_no_missing_fields(self, profile):
        view = explain_record(workbook(row("1")), profile, "1", as_of=AS_OF)
        assert view.missing == ()

    def test_returns_none_for_an_unknown_record_id(self, profile):
        assert explain_record(workbook(row("1")), profile, "999", as_of=AS_OF) is None

    def test_filtered_rows_are_still_shown_with_the_exclusion_reason(self, profile):
        view = explain_record(workbook(row("1", state="withdrawn")), profile,
                              "1", as_of=AS_OF)
        assert view.record["metadata"]["title"] == "A title"
        assert "withdrawn" in view.excluded
        assert "state" in view.excluded

    def test_rows_are_routed_by_the_profile_select(self, profile):
        view = explain_record(workbook(row("1", publication="other_coll")), profile,
                              "1", as_of=AS_OF)
        assert view.collection == "everything_else"


class TestAnnotateMissing:
    def test_places_the_sentinel_at_each_missing_pointer(self):
        record = {"metadata": {"title": "T"}}
        annotated = annotate_missing(record, ("/metadata/publication_date",))
        assert annotated["metadata"]["publication_date"] == MISSING

    def test_does_not_mutate_the_original_record(self):
        record = {"metadata": {"title": "T"}}
        annotate_missing(record, ("/metadata/publication_date",))
        assert "publication_date" not in record["metadata"]


def sample_record():
    return {"metadata": {"title": "T", "publication_date": MISSING}}


class TestRender:

    def test_default_output_is_pretty_printed(self):
        text = render(sample_record())
        assert "\n" in text
        assert json.loads(_strip_ansi(text)) == sample_record()

    def test_missing_lines_are_highlighted_red(self):
        text = render(sample_record())
        red_lines = [l for l in text.splitlines() if "\x1b[31m" in l]
        assert len(red_lines) == 1
        assert "publication_date" in red_lines[0]

    def test_plain_output_is_one_line_of_unstyled_json(self):
        text = render(sample_record(), plain=True)
        assert "\n" not in text
        assert "\x1b[" not in text
        assert json.loads(text) == sample_record()


def _strip_ansi(text):
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)
