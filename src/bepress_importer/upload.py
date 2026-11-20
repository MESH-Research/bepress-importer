"""Upload finished KC Works JSON to the Import API (POST /api/import/<collection-id>).

Mirrors MESH's kcworks_api_importer.py request shape: multipart form with a
`metadata` part holding the JSON array. The bearer token is never logged.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

DEFAULT_API_URL = "https://works.hcommons.org"
API_KEY_ENV = "KCWORKS_IMPORT_API_KEY"
API_URL_ENV = "KCWORKS_IMPORT_API_URL"

@dataclass
class PostResponse:
    """Everything we got back from one POST, for receipts and debug output."""

    status_code: int
    payload: dict
    headers: dict = field(default_factory=dict)
    text: str = ""


# poster(url, headers, form_data) -> PostResponse
Poster = Callable[[str, dict, dict], "PostResponse"]


@dataclass
class UploadResult:
    status_code: int
    success: bool
    message: str
    receipts: dict[str, dict] = field(default_factory=dict)


def upload_collection(
    records: list[dict],
    collection_id: str,
    api_key: str,
    api_url: str = DEFAULT_API_URL,
    notify_record_owners: bool = False,
    review_required: bool | None = None,
    strict_validation: bool | None = None,
    post: Poster | None = None,
    debug=None,
) -> UploadResult:
    """POST one collection's records; returns per-record receipts keyed by import-recid.

    With a DebugReporter in `debug`, narrates the exchange and dumps the
    full request and response.
    """
    post = post or _http_post
    url = f"{api_url.rstrip('/')}/api/import/{collection_id}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    data = build_form(
        records,
        notify_record_owners=notify_record_owners,
        review_required=review_required,
        strict_validation=strict_validation,
    )

    if debug:
        debug.say(f"Submitting {len(records)} record(s) to the streamlined Import API "
                  f"for collection {collection_id!r}")
        debug.say("Full request about to be sent:")
        debug.show_request("POST", url, headers, data)
        debug.say("POSTing now; large imports can take a while (timeout 600s)...")
    response = post(url, headers, data)
    if debug:
        debug.say("Server replied; full response follows:")
        debug.show_response(response)

    payload = response.payload
    receipts: dict[str, dict] = {}
    for item in list(payload.get("data", [])) + list(payload.get("errors", [])):
        source_id = item.get("source_id")
        if source_id:
            receipts[source_id] = {
                "record_id": item.get("record_id"),
                "record_url": item.get("record_url"),
                "errors": item.get("errors", []),
            }
    if debug:
        debug.say(f"Parsed {len(receipts)} per-record receipt(s) from the response's "
                  "data/errors arrays")
    return UploadResult(
        status_code=response.status_code,
        success=response.status_code == 201,
        message=payload.get("message", ""),
        receipts=receipts,
    )


def build_form(
    records: list[dict],
    notify_record_owners: bool = False,
    review_required: bool | None = None,
    strict_validation: bool | None = None,
) -> dict[str, str]:
    """The multipart form fields the Import API expects, metadata as a JSON array."""
    data: dict[str, str] = {
        "metadata": json.dumps(records, ensure_ascii=False),
        "notify_record_owners": str(notify_record_owners).lower(),
    }
    if review_required is not None:
        data["review_required"] = str(review_required).lower()
    if strict_validation is not None:
        data["strict_validation"] = str(strict_validation).lower()
    return data


def _http_post(url: str, headers: dict, data: dict) -> PostResponse:
    import requests

    # The Import API requires multipart/form-data; requests only produces it
    # via `files=`, so every form field travels as an explicit part.
    files = {
        name: (None, value, "application/json") if name == "metadata" else (None, value)
        for name, value in data.items()
    }
    response = requests.post(url, headers=headers, files=files, timeout=600)
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:500]}
    return PostResponse(
        status_code=response.status_code,
        payload=payload,
        headers=dict(response.headers),
        text=response.text,
    )
