"""Debug reporting for the KC Works Import API upload.

Everything a maintainer needs to diagnose an import: the full request
(headers redacted, metadata JSON pretty-printed), the full response, a
curl replay command, and human narrative of each step. The bearer token
never appears in any output.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path


def redact_headers(headers: dict) -> dict:
    """Return a copy with the Authorization credential replaced."""
    redacted = dict(headers)
    auth = redacted.get("Authorization")
    if auth:
        scheme, _, credential = auth.partition(" ")
        redacted["Authorization"] = f"{scheme} ***redacted ({len(credential)} chars)***"
    return redacted


def _pretty_json(text: str) -> str:
    """Pretty-print if the text parses as JSON; otherwise return it verbatim."""
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return text


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


class DebugReporter:
    """Emits debug lines through one injected callable."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit = emit

    def say(self, text: str) -> None:
        """One human narrative line describing what we are attempting."""
        self.emit(f"-- {text}")

    def show_request(self, method: str, url: str, headers: dict, form: dict) -> None:
        """Dump the full outgoing request: headers (redacted) and form fields."""
        self.emit(f"{method} {url}")
        self.emit("request headers:")
        for name, value in redact_headers(headers).items():
            self.emit(f"  {name}: {value}")
        self.emit("request form fields (sent as multipart/form-data):")
        for name, value in form.items():
            if name == "metadata":
                self.emit("  metadata (application/json), the records being submitted:")
                self.emit(_indent(_pretty_json(value)))
            else:
                self.emit(f"  {name}: {value}")

    def show_response(self, response) -> None:
        """Dump the full response: status, headers, body."""
        self.emit(f"response status: HTTP {response.status_code}")
        self.emit("response headers:")
        for name, value in dict(response.headers).items():
            self.emit(f"  {name}: {value}")
        self.emit("response body:")
        self.emit(_indent(_pretty_json(response.text)))

    def show_replay(self, url: str, form: dict, metadata_file: str) -> None:
        """Save the exact metadata bytes sent, and print a curl command that replays them.

        curl sends a file verbatim, and the source file is formatted differently
        from what we transmit (so it is a different size), so the replay reads a
        byte-identical copy written next to it as `<name>.payload.json`.
        """
        payload = form.get("metadata", "").encode("utf-8")
        payload_file = Path(metadata_file).with_suffix(".payload.json")
        payload_file.write_bytes(payload)
        self.say(f"Wrote the metadata exactly as transmitted ({len(payload)} bytes) to "
                 f"{payload_file}; {metadata_file} is formatted differently, so replaying "
                 "it directly would send a different request")
        self.show_curl(url, form, metadata_file=str(payload_file))

    def show_curl(self, url: str, form: dict, metadata_file: str = "metadata.json") -> None:
        """Print an equivalent curl command for replaying the request by hand."""
        self.say("equivalent curl command to replay this request by hand "
                 "(expects the token in $KCWORKS_IMPORT_API_KEY):")
        lines = [
            f"curl -X POST '{url}' \\",
            "  -H 'Accept: application/json' \\",
            '  -H "Authorization: Bearer $KCWORKS_IMPORT_API_KEY" \\',
        ]
        for name, value in form.items():
            if name == "metadata":
                lines.append(
                    f"  -F 'metadata=<{metadata_file};type=application/json' \\"
                )
            else:
                lines.append(f"  -F '{name}={value}' \\")
        lines[-1] = lines[-1].rstrip(" \\")
        self.emit("\n".join(lines))
