"""Upload finished KC Works JSON through MESH's kcworks-import-client library.

An alternative to `upload.py`, which builds the request itself. Both reach
the same streamlined Import API route (POST /api/import/<collection-id>).
The bearer token is never logged.
"""

from __future__ import annotations

from collections.abc import Mapping

import requests
from kcworks_import_client import ImportClient

from bepress_importer.upload import DEFAULT_API_URL, UploadResult, build_receipts

TIMEOUT_SECONDS = 600


class MultipartSession(requests.Session):
    """A session that sends form fields as multipart even with no files.

    The Import API only parses multipart/form-data, but our records carry no
    files, and with an empty file list the client library's request goes out
    form-urlencoded. Here the library's own fields travel as multipart parts
    instead. The library sets no timeout, so one is applied too. The last
    form and response are kept for the debug transcript.
    """

    def __init__(self) -> None:
        super().__init__()
        self.last_form: dict[str, str] = {}
        self.last_response: requests.Response | None = None

    def post(self, url, data=None, json=None, **kwargs):
        if isinstance(data, Mapping):
            self.last_form = dict(data)
            if not kwargs.get("files"):
                kwargs["files"] = {
                    name: (None, value, "application/json")
                    if name == "metadata"
                    else (None, value)
                    for name, value in data.items()
                }
                data = None
        kwargs.setdefault("timeout", TIMEOUT_SECONDS)
        self.last_response = super().post(url, data=data, json=json, **kwargs)
        return self.last_response


def make_session() -> MultipartSession:
    """The session handed to the client library."""
    return MultipartSession()


def upload_collection_via_client(
    records: list[dict],
    collection_id: str,
    api_key: str,
    api_url: str = DEFAULT_API_URL,
    notify_record_owners: bool = False,
    all_or_none: bool = True,
    session: requests.Session | None = None,
    debug=None,
    metadata_file: str = "metadata.json",
) -> UploadResult:
    """POST one collection's records via kcworks-import-client.

    Returns the same result shape as `upload.upload_collection`. Raises the
    library's ImportRequestError when no response was received. With a
    DebugReporter in `debug`, dumps the request the library sent, a curl
    replay of it (naming `metadata_file`), and the server's response.
    """
    session = session or make_session()
    # base_url is always passed, so the library never applies its own reading
    # of KCWORKS_IMPORT_API_URL (which would also switch TLS verification off).
    client = ImportClient(
        api_key, base_url=f"{api_url.rstrip('/')}/api/import", session=session
    )
    if debug:
        debug.say(f"Submitting {len(records)} record(s) through kcworks-import-client "
                  f"to {client.import_url(collection_id)}")
        debug.say(f"POSTing now; large imports can take a while (timeout {TIMEOUT_SECONDS}s)...")
    result = client.import_works(
        collection_id,
        records,
        files=[],
        notify_owners=notify_record_owners,
        all_or_none=all_or_none,
    )
    response = getattr(session, "last_response", None)
    if debug and response is not None:
        debug.say("Request as the client library sent it:")
        debug.show_request(
            response.request.method,
            response.request.url,
            dict(response.request.headers),
            getattr(session, "last_form", {}),
        )
        debug.show_curl(
            response.request.url, getattr(session, "last_form", {}),
            metadata_file=metadata_file,
        )
        debug.say("Server replied; full response follows:")
        debug.show_response(response)

    receipts = build_receipts(result.data, result.errors)
    if debug:
        debug.say(f"Parsed {len(receipts)} per-record receipt(s) from the response's "
                  "data/errors arrays")
    message = result.message
    if not message and isinstance(result.body, str):
        message = result.body[:500]
    return UploadResult(
        status_code=result.status_code,
        success=result.status_code == 201,
        message=message,
        receipts=receipts,
    )
