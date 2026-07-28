"""Behavioural test for help output form: command summaries must not be truncated."""

from click.testing import CliRunner

from bepress_importer.cli import cli


def test_command_summaries_fit_without_truncation():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    commands_section = lines[lines.index("Commands:") + 1 :]
    truncated = [line for line in commands_section if line.rstrip().endswith("...")]
    assert truncated == [], f"truncated help lines: {truncated}"
