# `upload-client` command design

Date: 2026-11-21

## Goal

Offer a second way to send a finished collection file to KC Works:
`bepress-importer upload-client`, which goes through MESH's
`kcworks-import-client` library instead of our own request code. Both
commands hit the same streamlined Import API route
(`POST /api/import/<collection-id>`). `upload` stays exactly as it is, so
the two can be compared against the same instance.

## Decisions

- **Dependency.** `kcworks-import-client` is not on PyPI. It is a normal
  dependency installed from GitHub, pinned to commit `e6ceaa1`, the commit
  KC Works `staging` pins as a submodule.
- **Metadata-only uploads.** Our records carry no files. With an empty file
  list the library sends `application/x-www-form-urlencoded`, and the server
  registers a parser for `multipart/form-data` only. We hand the library a
  `requests.Session` subclass (`MultipartSession`) that sends the library's
  own form fields as multipart parts when there are no files. The library
  still chooses the fields and parses the response.
- **`all_or_none`.** Always sent as `true`, matching `upload`. The library's
  own default is `false`.
- **Options.** Same as `upload`, minus `--review-required` and
  `--strict-validation`: the library has no way to send either, so the
  server defaults (both true) apply.
- **Timeout.** The library sets none; `MultipartSession` applies the same
  600 s that `upload` uses.

## Differences on the wire from `upload`

The library always adds `id_scheme=import-recid` and `no_updates=false`.
`upload` sends neither and gets the server defaults.

## Components

### `bepress_importer/upload_client.py` (new)

- `MultipartSession(requests.Session)`: forces multipart when no files are
  attached, applies the timeout, and remembers the last form and response
  for the debug transcript.
- `make_session() -> MultipartSession`: the single place a session is
  created, so tests can substitute one with a fake transport mounted.
- `upload_collection_via_client(records, collection_id, api_key, api_url,
  notify_record_owners, all_or_none=True, session=None, debug=None)
  -> UploadResult`: builds `ImportClient(base_url=<api_url>/api/import)`,
  calls `import_works(..., files=[])`, and returns the same `UploadResult`
  shape as `upload_collection` (success means HTTP 201; receipts keyed by
  `import-recid`).

The library's `KCWORKS_IMPORT_API_URL` handling (full import base, TLS
verification off) is bypassed: we always pass `base_url`, so the variable
keeps the meaning it has for `upload` (instance base URL) and TLS
verification stays on.

### `bepress_importer/upload.py`

Receipt building moves into a shared `build_receipts(data, errors)` used by
both paths.

### `bepress_importer/cli.py`

`upload` and `upload-client` share option definitions and the helpers that
load records, resolve the API URL and key, and write receipts. `--dry-run`
and `--debug` work on both; under `--debug` the transcript shows the form
fields the library actually sent and the server's full response, with the
token redacted.

## Testing

`tests/test_upload_client.py` runs the real library and the real session
against a fake transport adapter (no network) and asserts on the request
that would go on the wire and on the returned receipts. CLI tests mirror
those for `upload`.

## Success criteria

- A metadata-only upload through `upload-client` goes out as
  `multipart/form-data` with `all_or_none=true`.
- Receipts and exit codes match `upload` for the same server response.
- The bearer token never appears in any output.
- `upload` behaves as before; its tests pass unchanged.
