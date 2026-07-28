"""Behavioural tests for the KC Works Import API upload (HTTP mocked out)."""

import json
from pathlib import Path

from click.testing import CliRunner

from bepress_importer.cli import cli
from bepress_importer.upload import upload_collection

RECORDS = [
    {
        "metadata": {
            "identifiers": [{"identifier": "10", "scheme": "import-recid"}],
            "title": "A",
        },
        "files": {"enabled": False},
    }
]

SUCCESS_RESPONSE = {
    "status": "success",
    "message": "All records were successfully imported.",
    "data": [
        {
            "item_index": 0,
            "record_id": "abc123",
            "source_id": "10",
            "record_url": "https://works.example.org/records/abc123",
            "errors": [],
        }
    ],
    "errors": [],
}

ERROR_RESPONSE = {
    "status": "error",
    "message": "Validation failed.",
    "data": [],
    "errors": [
        {
            "item_index": 0,
            "record_id": None,
            "source_id": "10",
            "record_url": None,
            "errors": [{"field": "title", "message": "Required field missing."}],
        }
    ],
}


class CapturingPoster:
    def __init__(self, status=201, payload=SUCCESS_RESPONSE):
        self.calls = []
        self.status = status
        self.payload = payload

    def __call__(self, url, headers, data):
        self.calls.append({"url": url, "headers": headers, "data": data})
        return self.status, self.payload


class TestUploadCollection:
    def test_request_shape(self):
        poster = CapturingPoster()
        upload_collection(RECORDS, "coll-1", api_key="sekrit", post=poster)
        call = poster.calls[0]
        assert call["url"] == "https://works.hcommons.org/api/import/coll-1"
        assert call["headers"]["Authorization"] == "Bearer sekrit"
        assert call["headers"]["Accept"] == "application/json"
        assert json.loads(call["data"]["metadata"]) == RECORDS
        assert call["data"]["notify_record_owners"] == "false"

    def test_optional_flags_sent_only_when_set(self):
        poster = CapturingPoster()
        upload_collection(RECORDS, "c", api_key="k", post=poster)
        assert "review_required" not in poster.calls[0]["data"]
        assert "strict_validation" not in poster.calls[0]["data"]
        poster2 = CapturingPoster()
        upload_collection(
            RECORDS, "c", api_key="k", review_required=False, strict_validation=False,
            post=poster2,
        )
        assert poster2.calls[0]["data"]["review_required"] == "false"
        assert poster2.calls[0]["data"]["strict_validation"] == "false"

    def test_success_receipts_keyed_by_import_recid(self):
        result = upload_collection(RECORDS, "c", api_key="k", post=CapturingPoster())
        assert result.success is True
        assert result.status_code == 201
        assert result.receipts["10"]["record_url"] == "https://works.example.org/records/abc123"
        assert result.receipts["10"]["errors"] == []

    def test_error_receipts_carry_field_errors(self):
        poster = CapturingPoster(status=400, payload=ERROR_RESPONSE)
        result = upload_collection(RECORDS, "c", api_key="k", post=poster)
        assert result.success is False
        assert result.receipts["10"]["errors"] == [
            {"field": "title", "message": "Required field missing."}
        ]

    def test_custom_api_url(self):
        poster = CapturingPoster()
        upload_collection(RECORDS, "c", api_key="k", api_url="https://staging.example.org/",
                          post=poster)
        assert poster.calls[0]["url"] == "https://staging.example.org/api/import/c"


class TestUploadCommand:
    def run(self, tmp_path, *extra, env=None, poster=None, monkeypatch=None):
        metadata = tmp_path / "coll.json"
        metadata.write_text(json.dumps(RECORDS))
        if poster is not None and monkeypatch is not None:
            from bepress_importer import upload as upload_module

            monkeypatch.setattr(upload_module, "_http_post", poster)
        return CliRunner().invoke(
            cli,
            ["upload", str(metadata), "--collection-id", "coll-1",
             "--receipts", str(tmp_path / "receipts.json"), *map(str, extra)],
            env=env or {},
        )

    def test_missing_api_key_names_env_var(self, tmp_path):
        result = self.run(tmp_path, env={"KCWORKS_IMPORT_API_KEY": ""})
        assert result.exit_code != 0
        assert "KCWORKS_IMPORT_API_KEY" in result.output

    def test_uploads_and_writes_receipts(self, tmp_path, monkeypatch):
        poster = CapturingPoster()
        result = self.run(
            tmp_path, env={"KCWORKS_IMPORT_API_KEY": "sekrit"},
            poster=poster, monkeypatch=monkeypatch,
        )
        assert result.exit_code == 0, result.output
        receipts = json.loads((tmp_path / "receipts.json").read_text())
        assert receipts["10"]["record_url"] == "https://works.example.org/records/abc123"
        assert "sekrit" not in result.output

    def test_api_error_exits_nonzero_and_still_writes_receipts(self, tmp_path, monkeypatch):
        poster = CapturingPoster(status=400, payload=ERROR_RESPONSE)
        result = self.run(
            tmp_path, env={"KCWORKS_IMPORT_API_KEY": "k"},
            poster=poster, monkeypatch=monkeypatch,
        )
        assert result.exit_code != 0
        receipts = json.loads((tmp_path / "receipts.json").read_text())
        assert receipts["10"]["errors"]

    def test_dry_run_needs_no_key_and_posts_nothing(self, tmp_path, monkeypatch):
        poster = CapturingPoster()
        result = self.run(
            tmp_path, "--dry-run", env={"KCWORKS_IMPORT_API_KEY": ""},
            poster=poster, monkeypatch=monkeypatch,
        )
        assert result.exit_code == 0, result.output
        assert poster.calls == []
        assert "1 record" in result.output

    def test_api_key_file(self, tmp_path, monkeypatch):
        key_file = tmp_path / "key.txt"
        key_file.write_text("filekey\n")
        poster = CapturingPoster()
        result = self.run(
            tmp_path, "--api-key-file", key_file,
            env={"KCWORKS_IMPORT_API_KEY": ""}, poster=poster, monkeypatch=monkeypatch,
        )
        assert result.exit_code == 0, result.output
        assert poster.calls[0]["headers"]["Authorization"] == "Bearer filekey"

    def test_non_array_metadata_errors(self, tmp_path):
        metadata = tmp_path / "bad.json"
        metadata.write_text(json.dumps({"not": "a list"}))
        result = CliRunner().invoke(
            cli, ["upload", str(metadata), "--collection-id", "c"],
            env={"KCWORKS_IMPORT_API_KEY": "k"},
        )
        assert result.exit_code != 0


def test_receipts_path_defaults_next_to_metadata(tmp_path, monkeypatch):
    from bepress_importer import upload as upload_module

    poster = CapturingPoster()
    monkeypatch.setattr(upload_module, "_http_post", poster)
    metadata = tmp_path / "coll.json"
    metadata.write_text(json.dumps(RECORDS))
    result = CliRunner().invoke(
        cli, ["upload", str(metadata), "--collection-id", "c"],
        env={"KCWORKS_IMPORT_API_KEY": "k"},
    )
    assert result.exit_code == 0, result.output
    assert Path(tmp_path / "coll.receipts.json").exists()
