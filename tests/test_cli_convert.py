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
