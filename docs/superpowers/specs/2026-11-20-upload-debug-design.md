# Upload `--debug` mode design

Date: 2026-11-20

## Goal

Make `bepress-importer upload` fully debuggable against a live KC Works
instance (first target: works.hcommons-staging.org over VPN) using the
streamlined Import API (`POST /api/import/<collection-id>`), per
https://mesh-research.github.io/kcworks-import-client/import_api.html.
With `--debug`, the operator must see everything needed to hand a
transcript to the KCWorks maintainer: every request made, all JSON
submitted, all server responses, plus human narrative of what the tool is
attempting at each step. The bearer token must never appear in output.

## Components

### `bepress_importer/debug.py` (new)

- `redact_headers(headers) -> dict`: copy with `Authorization` replaced by
  `Bearer ***redacted (N chars)***`; other headers untouched.
- `DebugReporter(emit)`: all output through one injected `emit(str)`.
  - `say(text)`: narrative line, `-- ` prefix.
  - `show_request(method, url, headers, form)`: method + URL, redacted
    headers, each multipart form field; the `metadata` field is parsed and
    pretty-printed as JSON.
  - `show_response(response)`: status code, response headers, body
    pretty-printed when JSON, raw text otherwise.
  - `show_curl(url, form)`: equivalent `curl` command with
    `$KCWORKS_IMPORT_API_KEY` placeholder for replay by hand.

### `bepress_importer/upload.py` (changed)

- `PostResponse` dataclass: `status_code`, `payload` (parsed JSON dict),
  `headers` (response headers), `text` (raw body). Posters return this
  instead of `(status, dict)`.
- `upload_collection(..., debug: DebugReporter | None)`: narrates URL
  construction, shows the full request before POSTing and the full
  response after, then narrates receipt parsing.
- `_http_post` sends true `multipart/form-data` (requests `files=` with
  `(None, value)` parts; `metadata` typed `application/json`) as the API
  docs require, and captures response headers + raw text.

### `cli.py` upload command (changed)

- New `--debug` flag. Debug output goes to stderr (stdout keeps the
  existing summary; `2> debug.log` yields a shareable transcript).
- Narrates: metadata file load (path, record count, import-recids), API
  URL resolution (flag/env/default), token source (env var name or file
  path — never the value), request construction, response handling,
  receipt writing.
- `--debug --dry-run`: dumps the complete request (including metadata
  JSON and curl replay) without a token and POSTs nothing.

## Error handling

- Non-JSON response bodies are shown raw (truncated only in the parsed
  payload fallback, as now), never swallowed.
- Existing behaviour unchanged without `--debug`; non-201 still exits 1
  after writing receipts.

## Testing

Red/green: formatting units (redaction, request/response rendering),
`upload_collection` debug flow (capturing emit + poster fakes, token
never in output), CLI wiring (`--debug`, `--debug --dry-run`) via
CliRunner. Existing poster-tuple tests updated to `PostResponse` —
required by the interface change.
