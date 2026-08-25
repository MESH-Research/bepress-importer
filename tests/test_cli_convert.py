"""Behavioural tests for the inspect and convert CLI commands."""

import json
from pathlib import Path

from click.testing import CliRunner

from bepress_importer.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"


def run(*args):
    return CliRunner().invoke(cli, [str(a) for a in args])


class TestConvert:
    def test_writes_per_collection_json_and_report(self, tmp_path):
        out = tmp_path / "out"
        result = run(
            "convert", FIXTURES / "journal.csv",
            "--profile", FIXTURES / "golden_profile.toml",
            "-o", out, "--as-of", "2026-07-28",
        )
        assert result.exit_code == 0, result.output
        records = json.loads((out / "fac_journ.json").read_text())
        expected = json.loads((FIXTURES / "golden" / "fac_journ.expected.json").read_text())
        assert records == expected
        report = json.loads((out / "report.json").read_text())
        assert report["as_of"] == "2026-07-28"
        assert report["issues"] == []

    def test_output_is_byte_identical_across_runs(self, tmp_path):
        out1, out2 = tmp_path / "a", tmp_path / "b"
        for out in (out1, out2):
            result = run(
                "convert", FIXTURES / "journal.csv",
                "--profile", FIXTURES / "golden_profile.toml",
                "-o", out, "--as-of", "2026-07-28",
            )
            assert result.exit_code == 0, result.output
        assert (out1 / "fac_journ.json").read_bytes() == (out2 / "fac_journ.json").read_bytes()

    def test_sheet_filter_excludes_other_sheets(self, tmp_path):
        out = tmp_path / "out"
        result = run(
            "convert", FIXTURES / "journal.csv",
            "--profile", FIXTURES / "golden_profile.toml",
            "-o", out, "--as-of", "2026-07-28", "--sheet", "nope",
        )
        assert result.exit_code != 0

    def test_missing_profile_errors(self, tmp_path):
        result = run(
            "convert", FIXTURES / "journal.csv",
            "--profile", tmp_path / "absent.toml", "-o", tmp_path / "out",
        )
        assert result.exit_code != 0

    def test_summary_names_collections_and_counts(self, tmp_path):
        result = run(
            "convert", FIXTURES / "journal.csv",
            "--profile", FIXTURES / "golden_profile.toml",
            "-o", tmp_path / "out", "--as-of", "2026-07-28",
        )
        assert "fac_journ" in result.output
        assert "2" in result.output


def write_inventory_xlsx(path):
    """A miniature Content Inventory export: data sheet plus 'Field Names' legend."""
    import openpyxl

    book = openpyxl.Workbook()
    data = book.active
    data.title = "Content Inventory"
    data.append([
        "title", "state", "publication", "document_type", "abstract",
        "publication_date", "author1_fname", "author1_lname", "context_key",
    ])
    data.append([
        "A Study of Things", "published", "fac_journ", "article", "An abstract.",
        "2020-01-01", "Ada", "Lovelace", 12345,
    ])
    data.append([
        "Withdrawn Item", "withdrawn", "fac_journ", "article", "Gone.",
        "2020-01-01", "Ada", "Lovelace", 12346,
    ])
    legend = book.create_sheet("Field Names")
    legend.append(["Fields included"])
    legend.append(["title"])
    book.save(path)


INVENTORY_PROFILE = """
[profile]
name = "mini-inventory"
schema_version = 1
signature_columns = ["context_key", "state", "document_type"]

[defaults]
record_id.column = "context_key"

[[sheet]]
match = "*"
collection = "inventory"
require_columns = ["context_key", "state", "document_type"]

  [sheet.filter]
  column = "state"
  keep = ["published"]

  [[sheet.field]]
  source = "title"
  target = "/metadata/title"
  required = true
"""


class TestConvertProfileValidation:
    def test_convert_requires_a_profile(self, tmp_path):
        result = run("convert", FIXTURES / "journal.csv", "-o", tmp_path / "out")
        assert result.exit_code != 0
        assert "--profile" in result.output

    def test_a_matching_inventory_profile_converts_the_inventory(self, tmp_path):
        xlsx = tmp_path / "inventory.xlsx"
        write_inventory_xlsx(xlsx)
        profile = tmp_path / "inventory.toml"
        profile.write_text(INVENTORY_PROFILE)
        out = tmp_path / "out"
        result = run("convert", xlsx, "--profile", profile, "-o", out, "--as-of", "2026-08-25")
        assert result.exit_code == 0, result.output
        records = json.loads((out / "inventory.json").read_text())
        assert len(records) == 1  # withdrawn row filtered out
        assert records[0]["metadata"]["title"] == "A Study of Things"

    def test_an_inventory_profile_rejects_a_collection_export(self, tmp_path):
        profile = tmp_path / "inventory.toml"
        profile.write_text(INVENTORY_PROFILE)
        result = run(
            "convert", FIXTURES / "journal.csv",
            "--profile", profile, "-o", tmp_path / "out",
        )
        assert result.exit_code != 0
        assert "mini-inventory" in result.output
        assert "state" in result.output  # names the missing signature columns

    def test_a_non_matching_profile_fails_instead_of_writing_nothing(self, tmp_path):
        xlsx = tmp_path / "inventory.xlsx"
        write_inventory_xlsx(xlsx)
        result = run(
            "convert", xlsx, "--profile", FIXTURES / "golden_profile.toml",
            "-o", tmp_path / "out", "--as-of", "2026-08-25",
        )
        assert result.exit_code != 0
        assert "golden" in result.output

    def test_the_error_hints_at_a_sibling_profile_that_does_match(self, tmp_path):
        xlsx = tmp_path / "inventory.xlsx"
        write_inventory_xlsx(xlsx)
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "inventory.toml").write_text(INVENTORY_PROFILE)
        wrong = profile_dir / "collection.toml"
        wrong.write_text(
            (FIXTURES / "golden_profile.toml").read_text()
        )
        result = run(
            "convert", xlsx, "--profile", wrong, "-o", tmp_path / "out",
            "--as-of", "2026-08-25",
        )
        assert result.exit_code != 0
        assert str(profile_dir / "inventory.toml") in result.output


class TestIssuesSurfaceFirst:
    def convert_with_issue(self, tmp_path):
        csv = tmp_path / "journal.csv"
        csv.write_text(
            "title,context_key,document_type,publication_date\n"
            ",900,article,2020-01-01\n"
        )
        out = tmp_path / "out"
        result = run(
            "convert", csv, "--profile", FIXTURES / "golden_profile.toml",
            "-o", out, "--as-of", "2026-08-25",
        )
        assert result.exit_code == 0, result.output
        return out

    def test_report_json_puts_issues_before_everything_else(self, tmp_path):
        out = self.convert_with_issue(tmp_path)
        raw = (out / "report.json").read_text()
        assert raw.index('"issues"') < raw.index('"as_of"')
        report = json.loads(raw)
        assert report["issues"][0]["record_id"] == "900"

    def test_conversion_log_lists_issues_before_the_mapping_documentation(self, tmp_path):
        out = self.convert_with_issue(tmp_path)
        text = (out / "conversion-log.txt").read_text()
        assert "required field 'title' is missing" in text
        assert text.index("required field 'title' is missing") < text.index("=== Sheet")


class TestInspect:
    def test_lists_sheets_rows_and_columns(self):
        result = run("inspect", FIXTURES / "journal.csv")
        assert result.exit_code == 0, result.output
        assert "journal" in result.output
        assert "2" in result.output  # row count
        assert "context_key" in result.output

    def test_profile_coverage_lists_unmapped_columns(self, tmp_path):
        csv = tmp_path / "journal.csv"
        csv.write_text("title,context_key,mystery_column\nT,1,x\n")
        result = run("inspect", csv, "--profile", FIXTURES / "golden_profile.toml")
        assert result.exit_code == 0, result.output
        assert "mystery_column" in result.output

    def test_scaffold_prints_starter_profile(self):
        result = run("inspect", FIXTURES / "journal.csv", "--scaffold")
        assert result.exit_code == 0, result.output
        assert "[[sheet]]" in result.output
        assert 'match = "journal"' in result.output
        assert "src_journal" in result.output
