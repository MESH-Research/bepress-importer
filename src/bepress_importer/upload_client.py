"""Upload finished KC Works JSON through MESH's kcworks-import-client library.

An alternative to `upload.py`, which builds the request itself. Both reach
the same streamlined Import API route (POST /api/import/<collection-id>).
The bearer token is never logged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import requests
from kcworks_import_client import ImportClient, ImportRequestError

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


@dataclass
class BatchReport:
    """What happened to one batch of a batched upload."""

    number: int
    total: int
    # 1-based positions of the batch's first and last record in the input file.
    first: int
    last: int
    # None when no response was received at all.
    status_code: int | None
    message: str

    @property
    def success(self) -> bool:
        return self.status_code == 201

    @property
    def outcome(self) -> str:
        if self.status_code is None:
            return f"no response: {self.message}"
        return f"HTTP {self.status_code}: {self.message}"

    def describe(self) -> str:
        """One line for the progress log."""
        span = f"records {self.first}-{self.last}" if self.last >= self.first else "no records"
        return f"batch {self.number}/{self.total} ({span}): {self.outcome}"


def split_batches(records: list[dict], batch_size: int) -> list[list[dict]]:
    """The records in file order, `batch_size` to a batch; the last may be smaller.

    An empty list is still one (empty) batch, so the server answers for it as
    it would for an unbatched upload.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    return [
        records[start:start + batch_size] for start in range(0, len(records), batch_size)
    ] or [records]


def upload_batches_via_client(
    records: list[dict],
    collection_id: str,
    api_key: str,
    batch_size: int,
    api_url: str = DEFAULT_API_URL,
    notify_record_owners: bool = False,
    all_or_none: bool = True,
    session: requests.Session | None = None,
    debug=None,
    metadata_file: str | None = None,
    on_batch: Callable[[BatchReport], None] | None = None,
) -> UploadResult:
    """POST one collection's records `batch_size` at a time, in file order.

    Each batch is its own request, so `all_or_none` holds within a batch, not
    across the file. Every batch is sent whatever happened to the ones before
    it, so one run collects the errors of every batch that fails.

    Returns one result for the whole run: receipts merged from every batch
    that got a response, success only if every batch returned 201, a message
    summarising the run, and the status of the first batch that was not a
    plain success (0 if that batch got no response). `on_batch` is called
    with a BatchReport as each batch finishes. With `debug` and
    `metadata_file`, each batch saves its own curl replay payload.
    """
    session = session or make_session()
    batches = split_batches(records, batch_size)
    width = len(str(len(batches)))
    receipts: dict[str, dict] = {}
    reports: list[BatchReport] = []
    sent = 0
    for number, batch in enumerate(batches, start=1):
        first, sent = sent + 1, sent + len(batch)
        if debug:
            debug.say(f"Batch {number} of {len(batches)}: {len(batch)} record(s), "
                      f"up to record {sent} of {len(records)}")
        payload_file = None
        if metadata_file:
            payload_file = str(
                Path(metadata_file).with_suffix(f".batch-{number:0{width}d}.payload.json")
            )
        try:
            result = upload_collection_via_client(
                batch,
                collection_id,
                api_key=api_key,
                api_url=api_url,
                notify_record_owners=notify_record_owners,
                all_or_none=all_or_none,
                session=session,
                debug=debug,
                metadata_file=metadata_file,
                payload_file=payload_file,
            )
        except ImportRequestError as exc:
            report = BatchReport(number, len(batches), first, sent, None, str(exc))
        else:
            receipts.update(result.receipts)
            report = BatchReport(
                number, len(batches), first, sent, result.status_code, result.message
            )
        reports.append(report)
        if on_batch:
            on_batch(report)

    troubled = next((report for report in reports if not report.success), None)
    return UploadResult(
        status_code=201 if troubled is None else troubled.status_code or 0,
        success=troubled is None,
        message=_summarise(reports, len(records)),
        receipts=receipts,
    )


def _summarise(reports: list[BatchReport], record_count: int) -> str:
    imported = sum(1 for report in reports if report.success)
    parts = [f"{imported} of {len(reports)} batch(es) imported"]
    partly = [report for report in reports if report.status_code == 207]
    if partly:
        parts.append(f"{len(partly)} partly imported "
                     f"(batch {_ranges(report.number for report in partly)})")
    failed = [report for report in reports if report.status_code not in (201, 207)]
    if failed:
        records = sum(report.last - report.first + 1 for report in failed)
        parts.append(f"{len(failed)} failed (batch {_ranges(r.number for r in failed)}, "
                     f"{records} of {record_count} record(s); first: {failed[0].outcome})")
    return "; ".join(parts)


def _ranges(numbers) -> str:
    """Batch numbers with runs collapsed: 1, 2, 3, 7 -> "1-3, 7"."""
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def upload_collection_via_client(
    records: list[dict],
    collection_id: str,
    api_key: str,
    api_url: str = DEFAULT_API_URL,
    notify_record_owners: bool = False,
    all_or_none: bool = True,
    session: requests.Session | None = None,
    debug=None,
    metadata_file: str | None = None,
    payload_file: str | None = None,
) -> UploadResult:
    """POST one collection's records via kcworks-import-client.

    Returns the same result shape as `upload.upload_collection`. Raises the
    library's ImportRequestError when no response was received. With a
    DebugReporter in `debug`, dumps the request the library sent and the
    server's response; given `metadata_file` too, it also saves a curl replay
    payload next to that file (or at `payload_file`, when given).
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
        if metadata_file:
            debug.show_replay(
                response.request.url, getattr(session, "last_form", {}),
                metadata_file=metadata_file, payload_file=payload_file,
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
