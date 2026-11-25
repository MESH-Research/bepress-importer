"""Permanently remove every record in a KC Works collection (REST hard-delete).

Lists the collection's records through the communities REST API, then sends
them in batches to POST /api/records/hard-delete. The bearer token is never
logged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import requests

HARD_DELETE_KEY_ENV = "KCWORKS_HARD_DELETE_API_KEY"
PRODUCTION_HOSTS = frozenset({"works.hcommons.org"})
BATCH_MAX = 100
DEFAULT_BATCH_SIZE = 25
PAGE_SIZE = 100
READ_TIMEOUT_SECONDS = 60
# One request deletes files, DOIs and index entries for a whole batch.
DELETE_TIMEOUT_SECONDS = 600


class HardDeleteError(Exception):
    """The hard delete could not be carried out (or had to stop part-way)."""


@dataclass
class DeleteOutcome:
    """What happened to one record."""

    recid: str
    title: str
    ok: bool
    message: str = ""


@dataclass
class HardDeleteResult:
    slug: str
    cascade: bool
    subcollections: list[str] = field(default_factory=list)
    outcomes: list[DeleteOutcome] = field(default_factory=list)
    # Records left alone because they also belong to a sub-collection.
    skipped: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.ok)

    @property
    def failed(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.ok)

    @property
    def success(self) -> bool:
        return self.failed == 0


def is_production(api_url: str) -> bool:
    """Whether this base URL points at the production KC Works instance."""
    host = urlsplit(_with_scheme(api_url)).hostname or ""
    return host.rstrip(".").lower() in PRODUCTION_HOSTS


def _with_scheme(api_url: str) -> str:
    api_url = api_url.strip()
    return api_url if "://" in api_url else f"https://{api_url}"


def make_session() -> requests.Session:
    """The HTTP session used for every request."""
    return requests.Session()


def hard_delete_collection(
    slug: str,
    api_key: str,
    api_url: str,
    cascade: bool = False,
    note: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    session: requests.Session | None = None,
    log: Callable[[str], None] | None = None,
) -> HardDeleteResult:
    """Hard-delete every record in the collection `slug`; returns per-record outcomes.

    Records that also belong to one of the collection's sub-collections are
    left alone unless `cascade` is set, in which case the records of every
    sub-collection (at any depth) go too. Every step is narrated through
    `log`. Raises HardDeleteError when the collection cannot be listed or
    the server refuses the key.
    """
    log = log or (lambda line: None)
    batch_size = max(1, min(batch_size, BATCH_MAX))
    api = _Api(session or make_session(), api_url, api_key, log)
    note = note or f"bepress-importer hard-delete of collection {slug}"
    result = HardDeleteResult(slug=slug, cascade=cascade)

    log(f"Hard delete on {api.instance}: collection {slug!r}, "
        f"sub-collections {'included' if cascade else 'not included'}")
    descendants = _descendants(api, slug)
    result.subcollections = [child_slug for _, child_slug in descendants]
    if descendants:
        log(f"Sub-collections of {slug!r}: {', '.join(result.subcollections)} "
            f"({'their records will be deleted too' if cascade else 'left alone'})")

    attempted: set[str] = set()
    skipped: set[str] = set()
    while True:
        records, in_subcollections, cut_off = _gather(api, slug, descendants, cascade)
        for recid, title in in_subcollections.items():
            if recid not in skipped:
                skipped.add(recid)
                result.skipped.append(recid)
                log(f"SKIPPED {recid}  {title}  (also in a sub-collection)")
        fresh = [(recid, title) for recid, title in records.items() if recid not in attempted]
        if not fresh:
            break
        log(f"Deleting {len(fresh)} record(s) in batches of up to {batch_size}")
        for start in range(0, len(fresh), batch_size):
            batch = fresh[start:start + batch_size]
            attempted.update(recid for recid, _ in batch)
            for outcome in _delete_batch(api, batch, note):
                result.outcomes.append(outcome)
                if outcome.ok:
                    log(f"DELETED {outcome.recid}  {outcome.title}")
                else:
                    log(f"FAILED  {outcome.recid}  {outcome.title}: {outcome.message}")
        if not cut_off:
            break
    if cut_off:
        log("NOTE the server stopped listing before the end of the collection; "
            "records may remain, so run this again to check")
    log(f"Summary: total={len(result.outcomes)} succeeded={result.succeeded} "
        f"failed={result.failed} skipped={len(result.skipped)}")
    return result


class _Api:
    """The handful of REST calls needed, against one instance with one key."""

    def __init__(self, session: requests.Session, api_url: str, api_key: str,
                 log: Callable[[str], None]) -> None:
        self.session = session
        self.instance = _with_scheme(api_url).rstrip("/")
        self.api_key = api_key
        self.log = log
        self.anonymous_reads = False

    def get(self, path: str, params: dict) -> requests.Response:
        """A listing request, as the key's owner so restricted records are seen.

        The key may be scoped so narrowly that the server will not take it
        for reads; public listings are then read without it.
        """
        headers = {"Accept": "application/json"}
        if not self.anonymous_reads:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = self._send("GET", path, headers, READ_TIMEOUT_SECONDS, params=params)
        if response.status_code in (401, 403) and not self.anonymous_reads:
            self.anonymous_reads = True
            self.log(f"NOTE the server would not accept the key for listing "
                     f"(HTTP {response.status_code}); listing without it, so "
                     "restricted records will not be seen")
            return self.get(path, params)
        return response

    def post(self, path: str, body: dict) -> requests.Response:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        return self._send("POST", path, headers, DELETE_TIMEOUT_SECONDS, json=body)

    def _send(self, method: str, path: str, headers: dict, timeout: int,
              **kwargs) -> requests.Response:
        try:
            return self.session.request(
                method, f"{self.instance}/api{path}", headers=headers, timeout=timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise HardDeleteError(f"Could not reach {self.instance}: {exc}") from exc


def _payload(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {"message": response.text[:500]}
    return payload if isinstance(payload, dict) else {}


def _list_all(api: _Api, slug: str, kind: str, params: dict) -> tuple[list[dict], bool]:
    """Every hit of one collection listing, and whether the server cut it short.

    Search will not page past a fixed window (10,000 results), answering
    HTTP 400 beyond it; that is reported rather than treated as an error.
    """
    hits: list[dict] = []
    page = 1
    while True:
        response = api.get(
            f"/communities/{quote(slug, safe='')}/{kind}",
            {**params, "size": PAGE_SIZE, "page": page},
        )
        if response.status_code == 400 and page > 1:
            return hits, True
        payload = _payload(response)
        if response.status_code == 404:
            raise HardDeleteError(f"No collection {slug!r} was found on {api.instance}")
        if response.status_code != 200:
            raise HardDeleteError(
                f"Could not list the {kind} of collection {slug!r} "
                f"(HTTP {response.status_code}): {payload.get('message', '')}"
            )
        found = payload.get("hits", {})
        batch = found.get("hits", [])
        hits.extend(batch)
        total = found.get("total")
        if not batch or (total is not None and len(hits) >= total):
            return hits, False
        page += 1


def _descendants(api: _Api, slug: str) -> list[tuple[str, str]]:
    """(id, slug) of every sub-collection below `slug`, at any depth."""
    found: dict[str, str] = {}
    queue = [slug]
    while queue:
        children, _ = _list_all(api, queue.pop(0), "subcommunities", {})
        for child in children:
            if child["id"] not in found and child["slug"] != slug:
                found[child["id"]] = child["slug"]
                queue.append(child["slug"])
    return list(found.items())


def _gather(api: _Api, slug: str, descendants: list[tuple[str, str]],
            cascade: bool) -> tuple[dict[str, str], dict[str, str], bool]:
    """{recid: title} to delete, {recid: title} to leave alone, and whether cut short."""
    descendant_ids = {collection_id for collection_id, _ in descendants}
    targets = [slug] + ([child_slug for _, child_slug in descendants] if cascade else [])
    records: dict[str, str] = {}
    in_subcollections: dict[str, str] = {}
    cut_off = False
    for target in targets:
        # allversions: superseded versions are records in their own right.
        hits, target_cut_off = _list_all(
            api, target, "records", {"sort": "oldest", "allversions": "true"}
        )
        cut_off = cut_off or target_cut_off
        for hit in hits:
            title = hit.get("metadata", {}).get("title", "")
            member_of = set(hit.get("parent", {}).get("communities", {}).get("ids", []))
            if not cascade and member_of & descendant_ids:
                in_subcollections[hit["id"]] = title
            else:
                records[hit["id"]] = title
    return records, in_subcollections, cut_off


def _delete_batch(api: _Api, batch: list[tuple[str, str]], note: str) -> list[DeleteOutcome]:
    """One bulk hard-delete request; an outcome for every record sent."""
    response = api.post(
        "/records/hard-delete",
        {"ids": [recid for recid, _ in batch], "id_type": "recid", "note": note},
    )
    payload = _payload(response)
    status = response.status_code
    if status in (401, 403):
        raise HardDeleteError(
            f"The server refused the hard-delete key (HTTP {status}: "
            f"{payload.get('message', '')}). The key needs the records:delete scope "
            "and must belong to an account with the administration role."
        )
    if status not in (200, 207):
        message = f"HTTP {status}: {payload.get('message', '')}"
        return [DeleteOutcome(recid, title, ok=False, message=message) for recid, title in batch]
    results: dict[str, dict] = {}
    for item in payload.get("results", []):
        for key in (item.get("recid"), item.get("id")):
            if key:
                results[key] = item
    outcomes = []
    for recid, title in batch:
        item = results.get(recid)
        if item is None:
            outcomes.append(DeleteOutcome(recid, title, ok=False,
                                          message="the server reported no result for it"))
        elif item.get("ok"):
            outcomes.append(DeleteOutcome(recid, title, ok=True))
        else:
            message = item.get("message") or item.get("error") or "the server gave no reason"
            outcomes.append(DeleteOutcome(recid, title, ok=False, message=message))
    return outcomes
