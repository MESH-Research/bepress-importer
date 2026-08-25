"""Behavioural tests for the `show` command: dump one record from an export."""

import json

from click.testing import CliRunner

from bepress_importer.cli import cli
from test_cli_convert import INVENTORY_PROFILE, write_inventory_xlsx


def run(*args, color=False):
    return CliRunner().invoke(cli, [str(a) for a in args], color=color)


def setup_export(tmp_path):
    xlsx = tmp_path / "inventory.xlsx"
    write_inventory_xlsx(xlsx)
    profile = tmp_path / "inventory.toml"
    profile.write_text(INVENTORY_PROFILE)
    return xlsx, profile


class TestShow:
    def test_dumps_the_record_as_pretty_json(self, tmp_path):
        xlsx, profile = setup_export(tmp_path)
        result = run("show", xlsx, "--profile", profile, "--record", "12345")
        assert result.exit_code == 0, result.output
        record = json.loads(result.output)
        assert record["metadata"]["title"] == "A Study of Things"
        assert "\n" in result.output.strip()  # pretty-printed by default

    def test_missing_required_fields_are_marked(self, tmp_path):
        xlsx, profile = setup_export(tmp_path)
        profile.write_text(
            INVENTORY_PROFILE + """
  [[sheet.field]]
  source = "publication_date"
  target = "/metadata/publication_date"
  required = true

  [[sheet.field]]
  source = "nonexistent_column"
  target = "/metadata/description"
  required = true
"""
        )
        result = run("show", xlsx, "--profile", profile, "--record", "12345")
        assert result.exit_code == 0, result.output
        record = json.loads(result.output)
        assert record["metadata"]["description"] == "MISSING"
        assert record["metadata"]["publication_date"] == "2020-01-01"

    def test_missing_lines_are_red_in_color_mode(self, tmp_path):
        xlsx, profile = setup_export(tmp_path)
        profile.write_text(
            INVENTORY_PROFILE + """
  [[sheet.field]]
  source = "nonexistent_column"
  target = "/metadata/description"
  required = true
"""
        )
        result = run("show", xlsx, "--profile", profile, "--record", "12345", color=True)
        assert result.exit_code == 0, result.output
        assert "\x1b[31m" in result.output

    def test_plain_is_one_line_without_color(self, tmp_path):
        xlsx, profile = setup_export(tmp_path)
        result = run(
            "show", xlsx, "--profile", profile, "--record", "12345", "--plain",
            color=True,
        )
        assert result.exit_code == 0, result.output
        assert "\x1b[" not in result.output
        assert result.output.strip().count("\n") == 0
        assert json.loads(result.output)["metadata"]["title"] == "A Study of Things"

    def test_filtered_records_are_shown_with_a_note(self, tmp_path):
        xlsx, profile = setup_export(tmp_path)
        result = run("show", xlsx, "--profile", profile, "--record", "12346")
        assert result.exit_code == 0, result.output
        record = json.loads(result.stdout)  # the note goes to stderr only
        assert record["metadata"]["title"] == "Withdrawn Item"
        assert "withdrawn" in result.stderr

    def test_unknown_record_id_errors(self, tmp_path):
        xlsx, profile = setup_export(tmp_path)
        result = run("show", xlsx, "--profile", profile, "--record", "99999")
        assert result.exit_code != 0
        assert "99999" in result.output + result.stderr
