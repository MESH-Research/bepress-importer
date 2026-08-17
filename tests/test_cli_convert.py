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
        "title", "state", "submission_date", "document_type", "abstract",
        "publication_date", "author1_fname", "author1_lname", "context_key",
    ])
    data.append([
        "A Study of Things", "published", "2019-05-01", "article", "An abstract.",
        "2020-01-01", "Ada", "Lovelace", 12345,
    ])
    data.append([
        "Withdrawn Item", "withdrawn", "2019-05-01", "article", "Gone.",
        "2020-01-01", "Ada", "Lovelace", 12346,
    ])
    legend = book.create_sheet("Field Names")
    legend.append(["Fields included"])
    legend.append(["title"])
    book.save(path)


class TestConvertAutodetect:
    def test_convert_detects_content_inventory_without_profile(self, tmp_path):
        xlsx = tmp_path / "inventory.xlsx"
        write_inventory_xlsx(xlsx)
        out = tmp_path / "out"
        result = run("convert", xlsx, "-o", out, "--as-of", "2026-08-17")
        assert result.exit_code == 0, result.output
        assert "inventory" in result.output
        records = json.loads((out / "inventory.json").read_text())
        assert len(records) == 1  # withdrawn row filtered out
        assert records[0]["metadata"]["title"] == "A Study of Things"
        report = json.loads((out / "report.json").read_text())
        assert report["unmatched_sheets"] == ["Field Names"]

    def test_convert_without_profile_on_unknown_format_errors(self, tmp_path):
        result = run(
            "convert", FIXTURES / "journal.csv", "-o", tmp_path / "out",
            "--as-of", "2026-08-17",
        )
        assert result.exit_code != 0
        assert "--profile" in result.output

    def test_explicit_profile_overrides_detection(self, tmp_path):
        xlsx = tmp_path / "inventory.xlsx"
        write_inventory_xlsx(xlsx)
        out = tmp_path / "out"
        result = run(
            "convert", xlsx, "--profile", FIXTURES / "golden_profile.toml",
            "-o", out, "--as-of", "2026-08-17",
        )
        assert result.exit_code == 0, result.output
        report = json.loads((out / "report.json").read_text())
        # the golden profile matches neither sheet, proving detection was not used
        assert set(report["unmatched_sheets"]) == {"Content Inventory", "Field Names"}


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
