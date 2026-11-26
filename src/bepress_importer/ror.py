"""ROR ids for affiliations: ids fixed by the profile, and free-text lookups
in the ROR API with an on-disk cache so no text is ever looked up twice."""

from __future__ import annotations

import datetime
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import requests

API_URL = "https://api.ror.org/v2/organizations"
_ATTEMPTS = 5
_TIMEOUT = 30
_MAX_WAIT = 300
# consecutive failed lookups after which the API is left alone for the run
_GIVE_UP_AFTER = 3


class RorUnavailable(Exception):
    """The ROR API could not be reached or kept refusing the request."""


@dataclass(frozen=True)
class RorLookup:
    """What the ROR API said about one affiliation text.

    ror_id/name/score describe the organisation the API itself marked as its
    chosen match (all None when it chose none); contested is true when some
    other organisation scored at least as high.
    """

    ror_id: str | None = None
    name: str | None = None
    score: float | None = None
    contested: bool = False


@dataclass(frozen=True)
class RorMatch:
    """A ROR id settled on for an affiliation text, and on what evidence
    ("profile" for an id the profile fixes, "api" for a ROR API match)."""

    ror_id: str
    name: str | None
    evidence: str
    score: float | None = None


def read_response(payload: dict) -> RorLookup:
    """The API's answer to an affiliation query, reduced to its chosen match."""
    items = payload.get("items") or []
    chosen = [entry for entry in items if entry.get("chosen") is True]
    if len(chosen) != 1:
        return RorLookup()
    organization = chosen[0].get("organization") or {}
    ror_id = str(organization.get("id", "")).rstrip("/").rsplit("/", 1)[-1]
    if not ror_id or organization.get("status", "active") != "active":
        return RorLookup()
    score = chosen[0].get("score")
    names = organization.get("names") or []
    name = next(
        (n.get("value") for n in names if "ror_display" in (n.get("types") or [])), None
    )
    contested = any(
        entry is not chosen[0] and (entry.get("score") or 0) >= (score or 0) for entry in items
    )
    return RorLookup(ror_id=ror_id, name=name, score=score, contested=contested)


def is_certain(lookup: RorLookup, min_score: float = 1.0) -> bool:
    """Whether the API's answer is safe to use without a person checking it:
    it chose an organisation, at full score, and nothing else scored as high."""
    return (
        lookup.ror_id is not None
        and lookup.score is not None
        and lookup.score >= min_score
        and not lookup.contested
    )


def _key(text: str) -> str:
    """Texts differing only in case or spacing are the same affiliation."""
    return " ".join(text.split()).casefold()


class RorCache:
    """Affiliation text → RorLookup, kept in a SQLite file.

    Answers without a match are kept too, so those texts are not asked again.
    Texts differing only in case or spacing share an entry.
    """

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS affiliation_lookup ("
            " query TEXT PRIMARY KEY,"  # the affiliation text, case and spacing folded
            " asked TEXT NOT NULL,"  # the text as it was put to the API
            " ror_id TEXT,"  # NULL: the API chose no organisation
            " name TEXT,"
            " score REAL,"
            " contested INTEGER NOT NULL,"
            " fetched_at TEXT NOT NULL)"
        )
        self._db.commit()

    def get(self, text: str) -> RorLookup | None:
        row = self._db.execute(
            "SELECT ror_id, name, score, contested FROM affiliation_lookup WHERE query = ?",
            (_key(text),),
        ).fetchone()
        if row is None:
            return None
        return RorLookup(ror_id=row[0], name=row[1], score=row[2], contested=bool(row[3]))

    def put(self, text: str, lookup: RorLookup) -> None:
        fetched_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        self._db.execute(
            "INSERT OR REPLACE INTO affiliation_lookup VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _key(text), " ".join(text.split()), lookup.ror_id, lookup.name,
                lookup.score, int(lookup.contested), fetched_at,
            ),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()


def fetch_affiliation(
    text: str, *, session=None, sleep: Callable[[float], None] = time.sleep
) -> dict:
    """Ask the ROR API which organisation an affiliation text names.

    Waits and retries when rate-limited; raises RorUnavailable when the API
    cannot be reached or keeps failing.
    """
    session = session or requests.Session()
    problem = "no answer"
    for attempt in range(_ATTEMPTS):
        try:
            answer = session.get(API_URL, params={"affiliation": text}, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            problem = f"request failed ({exc.__class__.__name__})"
            sleep(2**attempt)
            continue
        if answer.status_code == 200:
            try:
                return answer.json()
            except ValueError as exc:
                raise RorUnavailable("the ROR API answer was not JSON") from exc
        problem = f"HTTP {answer.status_code}"
        if answer.status_code == 429:
            sleep(_retry_after(answer.headers.get("Retry-After")))
        elif answer.status_code >= 500:
            sleep(2**attempt)
        else:
            break  # the request itself is refused; asking again will not help
    raise RorUnavailable(f"the ROR API did not answer: {problem}")


def _retry_after(header: str | None) -> float:
    try:
        return min(max(float(header), 1), _MAX_WAIT)
    except (TypeError, ValueError):
        return 60


@dataclass
class RorResolver:
    """Decides the ROR id, if any, for an affiliation text.

    known: {ror_id: names} fixed by the profile — a text naming one of them
    (on its own or after a department, "Biology Department, X University")
    gets that id without any lookup.
    fetch: asks the ROR API; None keeps the resolver offline (known ids and
    cached answers only).
    """

    known: Mapping[str, Sequence[str]] = field(default_factory=dict)
    cache: RorCache | None = None
    fetch: Callable[[str], dict] | None = None
    min_score: float = 1.0
    failures: list[str] = field(default_factory=list)
    _failed_in_a_row: int = field(default=0, repr=False)

    def resolve(self, text: str) -> RorMatch | None:
        text = " ".join(text.split())
        if not text:
            return None
        known = self._known(text)
        if known is not None:
            return known
        lookup = self.cache.get(text) if self.cache else None
        if lookup is None:
            lookup = self._ask(text)
        if lookup is None or not is_certain(lookup, self.min_score):
            return None
        return RorMatch(
            ror_id=lookup.ror_id, name=lookup.name, evidence="api", score=lookup.score
        )

    def _known(self, text: str) -> RorMatch | None:
        """The id of a profile-fixed institution the text names: as the whole
        text, or as one comma-separated part of it (department, institution)."""
        parts = {_name_key(text), *(_name_key(part) for part in text.split(","))}
        for ror_id, names in self.known.items():
            if parts & {_name_key(name) for name in names}:
                return RorMatch(ror_id=ror_id, name=next(iter(names), None), evidence="profile")
        return None

    def _ask(self, text: str) -> RorLookup | None:
        if self.fetch is None:
            return None
        if self._failed_in_a_row >= _GIVE_UP_AFTER:
            self.failures.append(text)
            return None
        try:
            lookup = read_response(self.fetch(text))
        except RorUnavailable:
            self._failed_in_a_row += 1
            self.failures.append(text)
            return None
        self._failed_in_a_row = 0
        if self.cache:
            self.cache.put(text, lookup)
        return lookup


def _name_key(name: str) -> str:
    return _key(name).rstrip(".").strip()
