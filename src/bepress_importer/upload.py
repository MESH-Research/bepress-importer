"""Upload finished KC Works JSON to the Import API (POST /api/import/<collection-id>).

Mirrors MESH's kcworks_api_importer.py request shape: multipart form with a
`metadata` part holding the JSON array. The bearer token is never logged.
"""

from __future__ import annotations

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
    raise NotImplementedError
