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

# poster(url, headers, form_data) -> (status_code, parsed_json)
Poster = Callable[[str, dict, dict], tuple[int, dict]]


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
) -> UploadResult:
    """POST one collection's records; returns per-record receipts keyed by import-recid."""
    post = post or _http_post
    url = f"{api_url.rstrip('/')}/api/import/{collection_id}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    data: dict[str, str] = {
        "metadata": json.dumps(records, ensure_ascii=False),
        "notify_record_owners": str(notify_record_owners).lower(),
    }
    if review_required is not None:
        data["review_required"] = str(review_required).lower()
    if strict_validation is not None:
        data["strict_validation"] = str(strict_validation).lower()

    status_code, payload = post(url, headers, data)
    receipts: dict[str, dict] = {}
    for item in list(payload.get("data", [])) + list(payload.get("errors", [])):
        source_id = item.get("source_id")
        if source_id:
            receipts[source_id] = {
                "record_id": item.get("record_id"),
                "record_url": item.get("record_url"),
                "errors": item.get("errors", []),
            }
    return UploadResult(
        status_code=status_code,
        success=status_code == 201,
        message=payload.get("message", ""),
        receipts=receipts,
    )


def _http_post(url: str, headers: dict, data: dict) -> tuple[int, dict]:
    import requests

    response = requests.post(url, headers=headers, data=data, timeout=600)
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:500]}
    return response.status_code, payload
