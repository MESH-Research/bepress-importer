"""Behavioural tests for keeping old receipts when a new run writes its own."""

import json

import pytest
from click.testing import CliRunner

from bepress_importer import upload as upload_module
from bepress_importer import upload_client
from bepress_importer.cli import cli
from bepress_importer.serialize import backup_existing
from test_upload import ERROR_RESPONSE, RECORDS, SUCCESS_RESPONSE, CapturingPoster
from test_upload_client import FakeTransport, session_with


class TestBackupExisting:
    def test_nothing_to_back_up_when_the_file_does_not_exist(self, tmp_path):
        assert backup_existing(tmp_path / "receipts.json") is None
        assert list(tmp_path.iterdir()) == []

    def test_the_old_contents_survive_in_another_file(self, tmp_path):
        path = tmp_path / "receipts.json"
        path.write_bytes(b'{"10": "first run"}\n')
        backup = backup_existing(path)
        assert backup is not None
        assert backup != path
        assert backup.read_bytes() == b'{"10": "first run"}\n'

    def test_the_backup_sits_next_to_the_original(self, tmp_path):
        path = tmp_path / "out" / "coll.receipts.json"
        path.parent.mkdir()
        path.write_text("{}")
        backup = backup_existing(path)
        assert backup.parent == path.parent
        assert backup.name.startswith("coll.receipts.")

    def test_accepts_a_plain_string_path(self, tmp_path):
        path = tmp_path / "receipts.json"
        path.write_text("old")
        backup = backup_existing(str(path))
        assert backup.read_text() == "old"

    def test_repeated_backups_never_overwrite_each_other(self, tmp_path):
        path = tmp_path / "receipts.json"
        backups = []
        for contents in ("first", "second", "third"):
            path.write_text(contents)
            backups.append(backup_existing(path))
        assert len(set(backups)) == 3
        assert [backup.read_text() for backup in backups] == ["first", "second", "third"]

    def test_a_file_without_an_extension_is_backed_up_too(self, tmp_path):
        path = tmp_path / "receipts"
        path.write_text("old")
        backup = backup_existing(path)
        assert backup != path
        assert backup.read_text() == "old"


def other_files(tmp_path):
    """Everything in the directory besides the metadata and the live receipts."""
    return sorted(
        path for path in tmp_path.iterdir()
        if path.name not in {"coll.json", "receipts.json"}
    )


def run_upload(tmp_path, monkeypatch, *extra, status=201, payload=SUCCESS_RESPONSE):
    metadata = tmp_path / "coll.json"
    metadata.write_text(json.dumps(RECORDS))
    monkeypatch.setattr(upload_module, "_http_post", CapturingPoster(status, payload))
    return CliRunner().invoke(
        cli,
        ["upload", str(metadata), "--collection-id", "coll-1",
         "--receipts", str(tmp_path / "receipts.json"), *extra],
        env={"KCWORKS_IMPORT_API_KEY": "k", "KCWORKS_IMPORT_API_URL": ""},
    )


def run_upload_client(tmp_path, monkeypatch, *extra, status=201, payload=SUCCESS_RESPONSE):
    metadata = tmp_path / "coll.json"
    metadata.write_text(json.dumps(RECORDS))
    transport = FakeTransport(status, payload)
    monkeypatch.setattr(upload_client, "make_session", lambda: session_with(transport))
    return CliRunner().invoke(
        cli,
        ["upload-client", str(metadata), "--collection-id", "coll-1",
         "--receipts", str(tmp_path / "receipts.json"), *extra],
        env={"KCWORKS_IMPORT_API_KEY": "k", "KCWORKS_IMPORT_API_URL": ""},
    )


def run_upload_client_batched(tmp_path, monkeypatch, *extra, **kwargs):
    return run_upload_client(tmp_path, monkeypatch, "--batch", "1", *extra, **kwargs)


@pytest.mark.parametrize("run", [run_upload, run_upload_client, run_upload_client_batched])
class TestReceiptsAreBackedUp:
    def test_a_first_run_leaves_no_backup(self, tmp_path, monkeypatch, run):
        result = run(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert other_files(tmp_path) == []

    def test_a_second_run_keeps_the_first_runs_receipts(self, tmp_path, monkeypatch, run):
        run(tmp_path, monkeypatch, status=400, payload=ERROR_RESPONSE)
        first = (tmp_path / "receipts.json").read_bytes()
        result = run(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        live = json.loads((tmp_path / "receipts.json").read_text())
        assert live["10"]["record_url"] == "https://works.example.org/records/abc123"
        backups = other_files(tmp_path)
        assert len(backups) == 1
        assert backups[0].read_bytes() == first
        assert json.loads(first)["10"]["errors"]

    def test_the_backup_is_named_in_the_output(self, tmp_path, monkeypatch, run):
        run(tmp_path, monkeypatch)
        result = run(tmp_path, monkeypatch)
        assert str(other_files(tmp_path)[0]) in result.output

    def test_a_failed_run_also_keeps_the_previous_receipts(self, tmp_path, monkeypatch, run):
        run(tmp_path, monkeypatch)
        first = (tmp_path / "receipts.json").read_bytes()
        result = run(tmp_path, monkeypatch, status=400, payload=ERROR_RESPONSE)
        assert result.exit_code != 0
        assert json.loads((tmp_path / "receipts.json").read_text())["10"]["errors"]
        assert [path.read_bytes() for path in other_files(tmp_path)] == [first]

    def test_every_earlier_run_is_kept(self, tmp_path, monkeypatch, run):
        kept = []
        for status, payload in [(201, SUCCESS_RESPONSE), (400, ERROR_RESPONSE),
                                (201, SUCCESS_RESPONSE)]:
            run(tmp_path, monkeypatch, status=status, payload=payload)
            kept.append((tmp_path / "receipts.json").read_bytes())
        run(tmp_path, monkeypatch)
        assert sorted(path.read_bytes() for path in other_files(tmp_path)) == sorted(kept)

    def test_a_dry_run_leaves_existing_receipts_alone(self, tmp_path, monkeypatch, run):
        run(tmp_path, monkeypatch)
        before = (tmp_path / "receipts.json").read_bytes()
        result = run(tmp_path, monkeypatch, "--dry-run")
        assert result.exit_code == 0, result.output
        assert (tmp_path / "receipts.json").read_bytes() == before
        assert other_files(tmp_path) == []


def test_default_receipts_file_is_backed_up_too(tmp_path, monkeypatch):
    metadata = tmp_path / "coll.json"
    metadata.write_text(json.dumps(RECORDS))
    (tmp_path / "coll.receipts.json").write_text("from an earlier run")
    monkeypatch.setattr(upload_module, "_http_post", CapturingPoster())
    result = CliRunner().invoke(
        cli, ["upload", str(metadata), "--collection-id", "c"],
        env={"KCWORKS_IMPORT_API_KEY": "k"},
    )
    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "coll.receipts.json").read_text())["10"]["record_id"]
    others = [path for path in tmp_path.iterdir()
              if path.name not in {"coll.json", "coll.receipts.json"}]
    assert [path.read_text() for path in others] == ["from an earlier run"]
