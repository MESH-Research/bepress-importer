"""Behavioural tests for upload debug output: everything shown, token never."""

import json

from bepress_importer.debug import DebugReporter, redact_headers
from bepress_importer.upload import PostResponse

RECORDS = [
    {
        "metadata": {
            "identifiers": [{"identifier": "10", "scheme": "import-recid"}],
            "title": "A Title",
        },
        "files": {"enabled": False},
    }
]

FORM = {
    "metadata": json.dumps(RECORDS, ensure_ascii=False),
    "notify_record_owners": "false",
}

HEADERS = {
    "Accept": "application/json",
    "Authorization": "Bearer sekrit123",
}


def make_reporter():
    lines = []
    return DebugReporter(lines.append), lines


class TestRedactHeaders:
    def test_authorization_is_redacted(self):
        redacted = redact_headers(HEADERS)
        assert "sekrit123" not in json.dumps(redacted)
        assert "redacted" in redacted["Authorization"]

    def test_other_headers_untouched_and_original_not_mutated(self):
        redacted = redact_headers(HEADERS)
        assert redacted["Accept"] == "application/json"
        assert HEADERS["Authorization"] == "Bearer sekrit123"


class TestDebugReporter:
    def test_say_emits_narrative_line(self):
        reporter, lines = make_reporter()
        reporter.say("Loading metadata")
        assert len(lines) == 1
        assert "Loading metadata" in lines[0]

    def test_show_request_dumps_everything_but_the_token(self):
        reporter, lines = make_reporter()
        reporter.show_request("POST", "https://x.example/api/import/c", HEADERS, FORM)
        text = "\n".join(lines)
        assert "POST" in text
        assert "https://x.example/api/import/c" in text
        assert "Accept" in text
        assert "notify_record_owners" in text and "false" in text
        # metadata part is pretty-printed JSON, not a one-line blob
        assert '"title": "A Title"' in text
        assert "sekrit123" not in text
        assert "redacted" in text

    def test_show_response_pretty_prints_json_body(self):
        payload = {"status": "success", "message": "ok", "data": []}
        response = PostResponse(
            status_code=201,
            payload=payload,
            headers={"Content-Type": "application/json"},
            text=json.dumps(payload),
        )
        reporter, lines = make_reporter()
        reporter.show_response(response)
        text = "\n".join(lines)
        assert "201" in text
        assert "Content-Type" in text
        assert '"status": "success"' in text

    def test_show_response_falls_back_to_raw_body(self):
        response = PostResponse(
            status_code=504, payload={}, headers={}, text="<html>Gateway Timeout</html>"
        )
        reporter, lines = make_reporter()
        reporter.show_response(response)
        text = "\n".join(lines)
        assert "504" in text
        assert "<html>Gateway Timeout</html>" in text

    def test_show_curl_replays_request_with_placeholder_token(self):
        reporter, lines = make_reporter()
        reporter.show_curl("https://x.example/api/import/c", FORM)
        text = "\n".join(lines)
        assert "curl" in text
        assert "https://x.example/api/import/c" in text
        assert "$KCWORKS_IMPORT_API_KEY" in text
        assert "sekrit123" not in text

    def test_show_replay_saves_the_exact_metadata_sent(self, tmp_path):
        source = tmp_path / "coll.json"
        source.write_text(json.dumps([{"title": "Caf\u00e9"}], indent=2))
        sent = json.dumps([{"title": "Caf\u00e9"}], ensure_ascii=False)
        lines = []
        DebugReporter(lines.append).show_replay(
            "https://x.example/api/import/c",
            {"metadata": sent, "all_or_none": "true"},
            metadata_file=str(source),
        )
        payload = tmp_path / "coll.payload.json"
        assert payload.read_bytes() == sent.encode("utf-8")
        assert source.read_text() != sent  # the source file itself is left alone

    def test_show_replay_curl_reads_the_saved_payload_not_the_source(self, tmp_path):
        source = tmp_path / "coll.json"
        source.write_text("[]")
        lines = []
        DebugReporter(lines.append).show_replay(
            "https://x.example/api/import/c",
            {"metadata": "[]", "all_or_none": "true"},
            metadata_file=str(source),
        )
        curl = next(line for line in lines if line.startswith("curl"))
        assert f"metadata=<{tmp_path / 'coll.payload.json'};" in curl
        assert f"metadata=<{source};" not in curl
        assert "-F 'all_or_none=true'" in curl
