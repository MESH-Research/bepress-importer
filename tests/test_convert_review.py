"""Behavioural tests for what a conversion reports about values it had to
leave out or work out for itself."""

from bepress_importer import conversion_log
from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import load_profile
from bepress_importer.readers import Table, Workbook
from bepress_importer.transforms import known_transforms

COLUMNS = (
    "context_key", "title", "publication_date", "date_posted", "authors",
    "src_journal", "volnum", "issnum", "fpage", "lpage",
)
PROFILE = """
[profile]
name = "p"
[defaults.author_columns]
prefix = "author"
max = 3
json_column = "authors"
[[sheet]]
match = "*"
collection = "articles"
[sheet.resource_type]
constant = "textDocument-journalArticle"
[[sheet.field]]
source = "title"
target = "/metadata/title"
[[sheet.field]]
source = "publication_date"
target = "/metadata/publication_date"
transform = "edtf_date"
args = { fallback_columns = ["date_posted"] }
[sheet.journal]
title = "src_journal"
volume = "volnum"
issue = "issnum"
pages = { first = "fpage", last = "lpage" }
"""


def convert(tmp_path, **cells):
    path = tmp_path / "p.toml"
    path.write_text(PROFILE)
    row = {column: "" for column in COLUMNS} | {"context_key": "1", "title": "T"} | cells
    table = Table(name="Sheet", columns=COLUMNS, rows=(row,))
    profile = load_profile(path, known_transforms=known_transforms())
    return convert_workbook(Workbook(tables=(table,)), profile, as_of="2026-11-26")


def record(result):
    return result.collections["articles"][0]


class TestImplausibleJournalCells:
    def test_the_record_carries_only_the_plausible_parts(self, tmp_path):
        result = convert(
            tmp_path, src_journal="J", volnum="Online; print edition forthcoming",
            issnum="4", fpage="062105", lpage="not applicable",
        )
        assert record(result)["custom_fields"]["journal:journal"] == {
            "title": "J", "issue": "4", "pages": "062105",
        }

    def test_each_value_left_out_is_reported_and_logged(self, tmp_path):
        result = convert(
            tmp_path, src_journal="J", volnum="Online; print edition forthcoming",
            fpage="062105", lpage="not applicable",
        )
        assert sorted(i.message.split(" ")[0] for i in result.issues) == ["lpage", "volnum"]
        dropped = {c.source: c for c in result.value_changes if c.action == "dropped"}
        assert dropped["volnum"].raw == "Online; print edition forthcoming"
        assert dropped["lpage"].target == "/custom_fields/journal:journal"

    def test_a_clean_journal_reference_reports_nothing(self, tmp_path):
        result = convert(tmp_path, src_journal="J", volnum="3", fpage="1", lpage="9")
        assert result.issues == []


class TestCorporateAuthors:
    def test_the_profile_names_the_json_author_column(self, tmp_path):
        result = convert(
            tmp_path,
            authors='[{"CORPORATE_AUTHOR": "Bucknell Environmental Center", '
                    '"IS_CORPORATE_AUTHOR": "1"}]',
        )
        assert record(result)["metadata"]["creators"] == [
            {
                "person_or_org": {
                    "type": "organizational", "name": "Bucknell Environmental Center",
                },
                "role": {"id": "author"},
            }
        ]

    def test_the_json_author_column_counts_as_imported_in_the_log(self, tmp_path):
        result = convert(tmp_path, authors="[]")
        assert "authors" not in result.sheet_docs[0]["unmapped_columns"]


class TestFallbackDates:
    def test_a_date_taken_from_a_fallback_column_is_logged_as_such(self, tmp_path):
        result = convert(tmp_path, date_posted="2017-10-23 06:30:18")
        assert record(result)["metadata"]["publication_date"] == "2017-10-23"
        changes = [c for c in result.value_changes if c.target == "/metadata/publication_date"]
        assert len(changes) == 1
        assert changes[0].raw == ""
        assert "date_posted" in changes[0].reason

    def test_the_log_text_shows_where_the_date_came_from(self, tmp_path):
        result = convert(tmp_path, date_posted="2017-10-23 06:30:18")
        payload = conversion_log.build_payload(
            "in.xlsx", "p", "2026-11-26", result.sheet_docs, result.value_changes, result.issues
        )
        assert "date_posted" in conversion_log.render_text(payload).split("Per-record")[1]

    def test_a_date_given_in_the_export_is_not_reported_as_a_fallback(self, tmp_path):
        result = convert(tmp_path, publication_date="2019-04-25", date_posted="2020-01-01")
        assert record(result)["metadata"]["publication_date"] == "2019-04-25"
        assert [c for c in result.value_changes if "date_posted" in c.reason] == []
