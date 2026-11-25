"""Behavioural tests for uploading through kcworks-import-client.

The real library and the real session run against a fake transport
adapter, so nothing touches the network and we assert on the request that
would have gone on the wire.
"""

import json
from email import message_from_bytes

import pytest
import requests
from click.testing import CliRunner
from requests.adapters import BaseAdapter

from bepress_importer import upload_client
from bepress_importer.cli import cli
from bepress_importer.upload_client import MultipartSession, upload_collection_via_client

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


class FakeTransport(BaseAdapter):
    """Stands in for the network: records requests, replies with canned JSON."""

    def __init__(self, status=201, payload=SUCCESS_RESPONSE, error=None):
        super().__init__()
        self.status = status
        self.payload = payload
        self.error = error
        self.requests = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        response = requests.Response()
        response.status_code = self.status
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(self.payload).encode("utf-8")
        response.request = request
        response.url = request.url
        return response

    def close(self):
        pass


def session_with(transport):
    session = MultipartSession()
    session.mount("https://", transport)
    session.mount("http://", transport)
    return session


def form_fields(request) -> dict[str, str]:
    """Decode a multipart/form-data request body into {field name: value}."""
    body = request.body if isinstance(request.body, bytes) else request.body.encode("utf-8")
    header = f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode()
    message = message_from_bytes(header + body)
    return {
        part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
        .decode("utf-8")
        for part in message.get_payload()
    }


class TestUploadCollectionViaClient:
    def upload(self, transport, **kwargs):
        return upload_collection_via_client(
            RECORDS, "coll-1", api_key="sekrit", session=session_with(transport), **kwargs
        )

    def test_posts_to_the_import_route_with_bearer_token(self):
        transport = FakeTransport()
        self.upload(transport)
        request = transport.requests[0]
        assert request.method == "POST"
        assert request.url == "https://works.hcommons.org/api/import/coll-1"
        assert request.headers["Authorization"] == "Bearer sekrit"
        assert request.headers["Accept"] == "application/json"

    def test_api_url_override_tolerates_trailing_slash(self):
        transport = FakeTransport()
        self.upload(transport, api_url="https://staging.example.org/")
        assert transport.requests[0].url == "https://staging.example.org/api/import/coll-1"

    def test_metadata_only_upload_is_multipart(self):
        transport = FakeTransport()
        self.upload(transport)
        content_type = transport.requests[0].headers["Content-Type"]
        assert content_type.startswith("multipart/form-data")

    def test_metadata_field_carries_the_records(self):
        transport = FakeTransport()
        self.upload(transport)
        assert json.loads(form_fields(transport.requests[0])["metadata"]) == RECORDS

    def test_all_or_none_sent_as_true_by_default(self):
        transport = FakeTransport()
        self.upload(transport)
        assert form_fields(transport.requests[0])["all_or_none"] == "true"

    def test_all_or_none_can_be_turned_off(self):
        transport = FakeTransport()
        self.upload(transport, all_or_none=False)
        assert form_fields(transport.requests[0])["all_or_none"] == "false"

    def test_notify_record_owners_off_unless_asked(self):
        quiet = FakeTransport()
        self.upload(quiet)
        assert form_fields(quiet.requests[0])["notify_record_owners"] == "false"
        loud = FakeTransport()
        self.upload(loud, notify_record_owners=True)
        assert form_fields(loud.requests[0])["notify_record_owners"] == "true"

    def test_success_receipts_keyed_by_import_recid(self):
        result = self.upload(FakeTransport())
        assert result.success
        assert result.status_code == 201
        assert result.message == "All records were successfully imported."
        assert result.receipts["10"]["record_id"] == "abc123"
        assert result.receipts["10"]["record_url"] == "https://works.example.org/records/abc123"

    def test_error_response_is_not_success_and_keeps_per_record_errors(self):
        result = self.upload(FakeTransport(status=400, payload=ERROR_RESPONSE))
        assert not result.success
        assert result.status_code == 400
        assert result.message == "Validation failed."
        assert result.receipts["10"]["errors"][0]["field"] == "title"

    def test_secret_never_reaches_the_debug_transcript(self):
        from bepress_importer.debug import DebugReporter

        lines = []
        self.upload(FakeTransport(), debug=DebugReporter(lines.append))
        transcript = "\n".join(lines)
        assert "sekrit" not in transcript
        assert "all_or_none: true" in transcript
        assert '"status": "success"' in transcript


class TestUploadClientCommand:
    def run(self, tmp_path, monkeypatch, *extra, env=None, transport=None):
        metadata = tmp_path / "coll.json"
        metadata.write_text(json.dumps(RECORDS))
        self.transport = transport or FakeTransport()
        monkeypatch.setattr(
            upload_client, "make_session", lambda: session_with(self.transport)
        )
        return CliRunner().invoke(
            cli,
            ["upload-client", str(metadata), "--collection-id", "coll-1",
             "--receipts", str(tmp_path / "receipts.json"), *map(str, extra)],
            env={"KCWORKS_IMPORT_API_URL": "", **(env or {})},
        )

    def test_missing_api_key_names_env_var(self, tmp_path, monkeypatch):
        result = self.run(tmp_path, monkeypatch, env={"KCWORKS_IMPORT_API_KEY": ""})
        assert result.exit_code != 0
        assert "KCWORKS_IMPORT_API_KEY" in result.output
        assert self.transport.requests == []

    def test_uploads_and_writes_receipts(self, tmp_path, monkeypatch):
        result = self.run(tmp_path, monkeypatch, env={"KCWORKS_IMPORT_API_KEY": "sekrit"})
        assert result.exit_code == 0, result.output
        receipts = json.loads((tmp_path / "receipts.json").read_text())
        assert receipts["10"]["record_url"] == "https://works.example.org/records/abc123"
        assert "sekrit" not in result.output

    def test_api_error_exits_nonzero_and_still_writes_receipts(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch, env={"KCWORKS_IMPORT_API_KEY": "k"},
            transport=FakeTransport(status=400, payload=ERROR_RESPONSE),
        )
        assert result.exit_code != 0
        receipts = json.loads((tmp_path / "receipts.json").read_text())
        assert receipts["10"]["errors"]

    def test_network_failure_exits_nonzero_with_a_message(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch, env={"KCWORKS_IMPORT_API_KEY": "k"},
            transport=FakeTransport(error=requests.exceptions.ConnectionError("no route")),
        )
        assert result.exit_code != 0
        assert isinstance(result.exception, SystemExit)
        assert "no route" in result.output

    def test_dry_run_needs_no_key_and_posts_nothing(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch, "--dry-run", env={"KCWORKS_IMPORT_API_KEY": ""}
        )
        assert result.exit_code == 0, result.output
        assert self.transport.requests == []
        assert "1 record" in result.output

    def test_api_key_file(self, tmp_path, monkeypatch):
        key_file = tmp_path / "key.txt"
        key_file.write_text("filekey\n")
        result = self.run(
            tmp_path, monkeypatch, "--api-key-file", key_file,
            env={"KCWORKS_IMPORT_API_KEY": ""},
        )
        assert result.exit_code == 0, result.output
        assert self.transport.requests[0].headers["Authorization"] == "Bearer filekey"

    def test_api_url_env_is_the_instance_base_url(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch,
            env={"KCWORKS_IMPORT_API_KEY": "k",
                 "KCWORKS_IMPORT_API_URL": "https://staging.example.org"},
        )
        assert result.exit_code == 0, result.output
        assert self.transport.requests[0].url == (
            "https://staging.example.org/api/import/coll-1"
        )

    def test_notify_record_owners_flag_reaches_the_request(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch, "--notify-record-owners",
            env={"KCWORKS_IMPORT_API_KEY": "k"},
        )
        assert result.exit_code == 0, result.output
        assert form_fields(self.transport.requests[0])["notify_record_owners"] == "true"

    def test_all_or_none_is_on_unless_turned_off(self, tmp_path, monkeypatch):
        result = self.run(tmp_path, monkeypatch, env={"KCWORKS_IMPORT_API_KEY": "k"})
        assert result.exit_code == 0, result.output
        assert form_fields(self.transport.requests[0])["all_or_none"] == "true"

    def test_all_or_none_flag_keeps_it_on(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch, "--all-or-none", env={"KCWORKS_IMPORT_API_KEY": "k"}
        )
        assert result.exit_code == 0, result.output
        assert form_fields(self.transport.requests[0])["all_or_none"] == "true"

    def test_no_all_or_none_flag_reaches_the_request(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch, "--no-all-or-none", env={"KCWORKS_IMPORT_API_KEY": "k"}
        )
        assert result.exit_code == 0, result.output
        assert form_fields(self.transport.requests[0])["all_or_none"] == "false"

    def test_debug_dry_run_reports_the_all_or_none_it_would_send(self, tmp_path, monkeypatch):
        on = self.run(
            tmp_path, monkeypatch, "--debug", "--dry-run",
            env={"KCWORKS_IMPORT_API_KEY": ""},
        )
        assert on.exit_code == 0, on.output
        assert "all_or_none=true" in on.stderr
        off = self.run(
            tmp_path, monkeypatch, "--debug", "--dry-run", "--no-all-or-none",
            env={"KCWORKS_IMPORT_API_KEY": ""},
        )
        assert off.exit_code == 0, off.output
        assert "all_or_none=false" in off.stderr
        assert self.transport.requests == []

    def test_debug_streams_transcript_to_stderr(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch, "--debug", env={"KCWORKS_IMPORT_API_KEY": "sekrit"}
        )
        assert result.exit_code == 0, result.output
        transcript = result.stderr
        assert "POST" in transcript
        assert "api/import/coll-1" in transcript
        assert '"title": "A"' in transcript  # the JSON we submitted
        assert '"status": "success"' in transcript  # the server's response
        assert "201" in transcript
        assert "curl" in transcript and "coll.json" in transcript
        assert "sekrit" not in transcript and "sekrit" not in result.output
        assert "receipts" in result.output

    def test_debug_replay_payload_is_byte_identical_to_what_was_sent(
        self, tmp_path, monkeypatch
    ):
        result = self.run(
            tmp_path, monkeypatch, "--debug", env={"KCWORKS_IMPORT_API_KEY": "k"}
        )
        assert result.exit_code == 0, result.output
        payload = tmp_path / "coll.payload.json"
        sent = form_fields(self.transport.requests[0])["metadata"]
        assert payload.read_bytes() == sent.encode("utf-8")
        assert f"metadata=<{payload};" in result.stderr

    def test_no_replay_payload_without_debug(self, tmp_path, monkeypatch):
        self.run(tmp_path, monkeypatch, env={"KCWORKS_IMPORT_API_KEY": "k"})
        assert not (tmp_path / "coll.payload.json").exists()

    def test_debug_dry_run_posts_nothing(self, tmp_path, monkeypatch):
        result = self.run(
            tmp_path, monkeypatch, "--debug", "--dry-run",
            env={"KCWORKS_IMPORT_API_KEY": ""},
        )
        assert result.exit_code == 0, result.output
        assert self.transport.requests == []
        assert "api/import/coll-1" in result.stderr

    def test_non_array_metadata_errors(self, tmp_path, monkeypatch):
        metadata = tmp_path / "bad.json"
        metadata.write_text(json.dumps({"not": "a list"}))
        result = CliRunner().invoke(
            cli, ["upload-client", str(metadata), "--collection-id", "c"],
            env={"KCWORKS_IMPORT_API_KEY": "k"},
        )
        assert result.exit_code != 0
        assert "JSON array" in result.output

    @pytest.mark.parametrize("flag", ["--review-required", "--strict-validation"])
    def test_flags_the_library_cannot_send_are_not_offered(self, tmp_path, monkeypatch, flag):
        result = self.run(tmp_path, monkeypatch, flag, env={"KCWORKS_IMPORT_API_KEY": "k"})
        assert result.exit_code != 0
        assert self.transport.requests == []
