"""Behavioural tests for the wrangling CLI: check, fix, edit, apply, history, undo."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from bepress_importer.cli import cli

AS_OF = "2026-07-28"


def run(*args, input=None):
    return CliRunner().invoke(cli, [str(a) for a in args], input=input)


def make_records():
    """Record 10 has two fixable problems; record 20 is clean."""
    return [
        {
            "metadata": {
                "identifiers": [{"identifier": "10", "scheme": "import-recid"}],
                "title": "Problem Record",
                "publication_date": "Spring 2015",
                "resource_type": {"id": "masters_thesis"},
                "creators": [
                    {
                        "person_or_org": {
                            "type": "personal", "name": "Smith, Jane",
                            "given_name": "Jane", "family_name": "Smith",
                        },
                        "role": {"id": "author"},
                    }
                ],
            },
            "files": {"enabled": False},
        },
        {
            "metadata": {
                "identifiers": [{"identifier": "20", "scheme": "import-recid"}],
                "title": "Clean Record",
                "publication_date": "2016",
                "resource_type": {"id": "textDocument-journalArticle"},
                "creators": [
                    {
                        "person_or_org": {
                            "type": "personal", "name": "Doe, Jo",
                            "given_name": "Jo", "family_name": "Doe",
                        },
                        "role": {"id": "author"},
                    }
                ],
            },
            "files": {"enabled": False},
        },
    ]


@pytest.fixture
def data_dir(tmp_path):
    directory = tmp_path / "converted"
    directory.mkdir()
    (directory / "coll.json").write_text(json.dumps(make_records()))
    return directory


def load_out(out_dir):
    return json.loads((Path(out_dir) / "coll.json").read_text())


class TestCheck:
    def test_subdirectories_named_like_json_are_ignored(self, data_dir):
        (data_dir / "nested.json").mkdir()  # a directory, not a file
        result = run("check", data_dir, "--as-of", AS_OF)
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert result.exit_code == 1  # findings from coll.json still reported

    def test_findings_exit_one_and_are_printed(self, data_dir):
        result = run("check", data_dir, "--as-of", AS_OF)
        assert result.exit_code == 1
        assert "resource-type-vocab" in result.output
        assert "edtf-date" in result.output
        assert "masters_thesis" in result.output

    def test_clean_data_exits_zero(self, data_dir, tmp_path):
        clean = tmp_path / "clean"
        clean.mkdir()
        (clean / "coll.json").write_text(json.dumps([make_records()[1]]))
        result = run("check", clean, "--as-of", AS_OF)
        assert result.exit_code == 0

    def test_rule_filter(self, data_dir):
        result = run("check", data_dir, "--as-of", AS_OF, "--rule", "edtf-date")
        assert "edtf-date" in result.output
        assert "resource-type-vocab" not in result.output


class TestFix:
    def test_yes_accepts_all_and_regenerates_output(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        result = run("fix", data_dir, "--log", log, "-o", out, "--yes", "--as-of", AS_OF)
        assert result.exit_code == 0, result.output
        records = load_out(out)
        assert records[0]["metadata"]["resource_type"]["id"] == "textDocument-thesis"
        assert records[0]["metadata"]["publication_date"] == "2015-21"
        saved = json.loads(log.read_text())
        assert len(saved["changes"]) == 2
        summary = (tmp_path / "wrangling.log").read_text()
        assert "[Change 1]" in summary
        assert 'Record 10 ("Problem Record")' in summary

    def test_interactive_accept_then_reject(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        result = run(
            "fix", data_dir, "--log", log, "-o", out, "--as-of", AS_OF, input="y\nn\n"
        )
        assert result.exit_code == 0, result.output
        saved = json.loads(log.read_text())
        assert len(saved["changes"]) == 1

    def test_quit_stops_prompting(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        result = run(
            "fix", data_dir, "--log", log, "-o", tmp_path / "w", "--as-of", AS_OF, input="q\n"
        )
        assert result.exit_code == 0, result.output
        assert json.loads(log.read_text())["changes"] == []

    def test_second_fix_run_chains_on_existing_log(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        run("fix", data_dir, "--log", log, "-o", out, "--yes", "--as-of", AS_OF)
        # manually break the date again via edit, then fix again: chain must link
        run("edit", data_dir, "--log", log, "-o", out, "--record", "10",
            "--field", "/metadata/publication_date", "--set", "Fall 2016")
        run("fix", data_dir, "--log", log, "-o", out, "--yes", "--as-of", AS_OF)
        changes = json.loads(log.read_text())["changes"]
        date_changes = [
            c for c in changes if c["field"] == "/metadata/publication_date"
        ]
        assert [c["parent"] for c in date_changes] == [None, date_changes[0]["id"],
                                                       date_changes[1]["id"]]


class TestEdit:
    def test_set_and_log(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        result = run(
            "edit", data_dir, "--log", log, "-o", out, "--record", "20",
            "--field", "/metadata/title", "--set", "Renamed", "--note", "client request",
        )
        assert result.exit_code == 0, result.output
        assert load_out(out)[1]["metadata"]["title"] == "Renamed"
        change = json.loads(log.read_text())["changes"][0]
        assert change["rule"] == "manual"
        assert change["before"] == "Clean Record"
        assert change["note"] == "client request"

    def test_unset_removes_field(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        result = run(
            "edit", data_dir, "--log", log, "-o", out, "--record", "20",
            "--field", "/metadata/publication_date", "--unset",
        )
        assert result.exit_code == 0, result.output
        assert "publication_date" not in load_out(out)[1]["metadata"]

    def test_set_json_structured_value(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        result = run(
            "edit", data_dir, "--log", log, "-o", out, "--record", "20",
            "--field", "/metadata/rights", "--set-json", '[{"id": "cc-by-4.0"}]',
        )
        assert result.exit_code == 0, result.output
        assert load_out(out)[1]["metadata"]["rights"] == [{"id": "cc-by-4.0"}]

    def test_unknown_record_errors(self, data_dir, tmp_path):
        result = run(
            "edit", data_dir, "--log", tmp_path / "l.json", "-o", tmp_path / "w",
            "--record", "999", "--field", "/metadata/title", "--set", "X",
        )
        assert result.exit_code != 0


class TestApply:
    def test_regenerates_output_files(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out1, out2 = tmp_path / "w1", tmp_path / "w2"
        run("fix", data_dir, "--log", log, "-o", out1, "--yes", "--as-of", AS_OF)
        result = run("apply", data_dir, "--log", log, "-o", out2)
        assert result.exit_code == 0, result.output
        assert (out1 / "coll.json").read_bytes() == (out2 / "coll.json").read_bytes()

    def test_conflict_exits_one_and_names_change(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        log.write_text(json.dumps({
            "schema_version": 1,
            "changes": [{
                "id": 1, "op": "change", "record_id": "10", "field": "/metadata/title",
                "before": "Stale", "after": "New", "at": "2026-07-28T10:00:00Z",
                "parent": None, "target": None, "rule": None, "note": None,
            }],
        }))
        result = run("apply", data_dir, "--log", log, "-o", tmp_path / "w")
        assert result.exit_code == 1
        assert "conflict" in result.output.lower()
        assert "Change 1" in result.output


class TestHistoryAndUndo:
    def test_history_lists_changes_and_filters_by_record(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        run("fix", data_dir, "--log", log, "-o", out, "--yes", "--as-of", AS_OF)
        run("edit", data_dir, "--log", log, "-o", out, "--record", "20",
            "--field", "/metadata/title", "--set", "Renamed")
        full = run("history", "--log", log)
        assert "Record 10" in full.output
        assert "Record 20" in full.output
        filtered = run("history", "--log", log, "--record", "20")
        assert "Record 20" in filtered.output
        assert "Record 10" not in filtered.output

    def test_undo_change_then_apply_restores_value(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        run("fix", data_dir, "--log", log, "-o", out, "--yes", "--as-of", AS_OF)
        changes = json.loads(log.read_text())["changes"]
        date_change = next(c for c in changes if c["field"] == "/metadata/publication_date")
        result = run("undo", "--log", log, "--change", date_change["id"])
        assert result.exit_code == 0, result.output
        run("apply", data_dir, "--log", log, "-o", out)
        assert load_out(out)[0]["metadata"]["publication_date"] == "Spring 2015"

    def test_undo_non_head_requires_cascade(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        run("fix", data_dir, "--log", log, "-o", out, "--yes", "--as-of", AS_OF)
        run("edit", data_dir, "--log", log, "-o", out, "--record", "10",
            "--field", "/metadata/publication_date", "--set", "2015")
        changes = json.loads(log.read_text())["changes"]
        first_date = next(c for c in changes if c["field"] == "/metadata/publication_date")
        blocked = run("undo", "--log", log, "--change", first_date["id"])
        assert blocked.exit_code != 0
        cascaded = run("undo", "--log", log, "--change", first_date["id"], "--cascade")
        assert cascaded.exit_code == 0, cascaded.output

    def test_undo_record_restores_original_state(self, data_dir, tmp_path):
        log = tmp_path / "wrangling.json"
        out = tmp_path / "wrangled"
        run("fix", data_dir, "--log", log, "-o", out, "--yes", "--as-of", AS_OF)
        result = run("undo", "--log", log, "--record", "10")
        assert result.exit_code == 0, result.output
        run("apply", data_dir, "--log", log, "-o", out)
        assert load_out(out) == make_records()


class TestVocabSyncCommand:
    def test_sync_writes_to_dest(self, tmp_path, monkeypatch):
        from bepress_importer import vocab_sync as vs

        def fake_fetch(url):
            return {"hits": {"hits": [{"id": "x"}], "total": 1}}

        monkeypatch.setattr(vs, "_http_fetch", fake_fetch)
        result = run("vocab", "sync", "--dest", tmp_path / "vocab")
        assert result.exit_code == 0, result.output
        assert (tmp_path / "vocab" / "resource_types.json").exists()
