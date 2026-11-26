"""ROR ids for affiliations: ids fixed by the profile, and free-text lookups
in the ROR API with an on-disk cache so no text is ever looked up twice."""

from __future__ import annotations

import datetime
import json
import re
import sqlite3
import time
import unicodedata
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
_CACHE_LAYOUT = 3


class RorUnavailable(Exception):
    """The ROR API could not be reached or kept refusing the request."""


@dataclass(frozen=True)
class RorLookup:
    """What the ROR API said about one affiliation text.

    ror_id/name/score describe the organisation the API itself marked as its
    chosen match (all None when it chose none).
    """

    ror_id: str | None = None
    name: str | None = None
    score: float | None = None
    # the chosen organisation's official names (display name and labels in
    # other languages — not aliases or acronyms) and where it is
    names: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    # official names of other organisations that scored as high as the chosen one
    rivals: tuple[str, ...] = ()


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
    rivals = tuple(
        rival_name
        for entry in items
        if entry is not chosen[0] and (entry.get("score") or 0) >= (score or 0)
        for rival_name in _official_names(entry.get("organization") or {})
    )
    official = _official_names(organization)
    places = []
    for location in organization.get("locations") or []:
        details = location.get("geonames_details") or {}
        for key in (
            "name", "country_subdivision_name", "country_subdivision_code",
            "country_name", "country_code",
        ):
            if details.get(key) and details[key] not in places:
                places.append(details[key])
    return RorLookup(
        ror_id=ror_id, name=name, score=score,
        names=official, places=tuple(places), rivals=rivals,
    )


def _official_names(organization: dict) -> tuple[str, ...]:
    """An organisation's display name and its labels in other languages —
    not its aliases or acronyms, which other organisations may share."""
    return tuple(
        n["value"]
        for n in organization.get("names") or []
        if n.get("value") and {"ror_display", "label"} & set(n.get("types") or [])
    )


def is_certain(lookup: RorLookup, text: str, min_score: float = 1.0) -> bool:
    """Whether the API's answer for `text` is safe to use without a person
    checking it.

    The API must have chosen an organisation, at full score — and the text
    must be that organisation's own official name, a name no equally scored
    organisation shares (see names_the_organisation). The API's choice alone
    is not enough: it also chooses on aliases and shared words, which is how
    "NC State" comes back as North Central State College.
    """
    return (
        lookup.ror_id is not None
        and lookup.score is not None
        and lookup.score >= min_score
        and names_the_organisation(text, lookup)
    )


# words that may follow an organisation's name without changing which
# organisation is meant
_FILLERS = {"at", "in", "the", "main", "campus"}
_PLACE_SYNONYMS = {
    "US": ("USA", "U.S.A.", "U.S.", "United States of America"),
    "GB": ("UK", "U.K.", "Great Britain", "England", "Scotland", "Wales"),
}


def _words(text: str) -> list[str]:
    """A name as comparable words: no case, accents, punctuation or leading article."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).casefold()
    plain = plain.replace("&", " and ")
    words = re.sub(r"[^a-z0-9]+", " ", plain).split()
    return words[1:] if words[:1] == ["the"] else words


def names_the_organisation(text: str, lookup: RorLookup) -> bool:
    """Whether the text is one of the organisation's official names — alone,
    or followed only by where the organisation is ("X University - Fort
    Collins", "X University, Japan") — rather than something that resembles it.
    A name that an equally scored rival also bears identifies neither.
    """
    words = _words(text)
    shared = [_words(rival) for rival in lookup.rivals]
    places = [*lookup.places]
    for code, synonyms in _PLACE_SYNONYMS.items():
        if code in lookup.places:
            places.extend(synonyms)
    place_words = [_words(place) for place in places]
    for name in lookup.names:
        name_words = _words(name)
        if not name_words or words[: len(name_words)] != name_words:
            continue
        if name_words in shared:
            continue
        rest = [word for word in words[len(name_words):] if word not in _FILLERS]
        if _only_places(rest, place_words):
            return True
    return False


def _only_places(words: list[str], places: list[list[str]]) -> bool:
    """Whether the words are nothing but a run of the given place names."""
    if not words:
        return True
    return any(
        place and words[: len(place)] == place and _only_places(words[len(place):], places)
        for place in places
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
        if self._db.execute("PRAGMA user_version").fetchone()[0] != _CACHE_LAYOUT:
            # a cache in another layout: its answers can simply be asked for again
            self._db.execute("DROP TABLE IF EXISTS affiliation_lookup")
            self._db.execute(f"PRAGMA user_version = {_CACHE_LAYOUT}")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS affiliation_lookup ("
            " query TEXT PRIMARY KEY,"  # the affiliation text, case and spacing folded
            " asked TEXT NOT NULL,"  # the text as it was put to the API
            " ror_id TEXT,"  # NULL: the API chose no organisation
            " name TEXT,"  # its display name
            " score REAL,"
            " names TEXT NOT NULL,"  # JSON list: its official names
            " places TEXT NOT NULL,"  # JSON list: its city, region and country
            " rivals TEXT NOT NULL,"  # JSON list: names of organisations scoring as high
            " fetched_at TEXT NOT NULL)"
        )
        self._db.commit()

    def get(self, text: str) -> RorLookup | None:
        row = self._db.execute(
            "SELECT ror_id, name, score, names, places, rivals "
            "FROM affiliation_lookup WHERE query = ?",
            (_key(text),),
        ).fetchone()
        if row is None:
            return None
        return RorLookup(
            ror_id=row[0], name=row[1], score=row[2], names=tuple(json.loads(row[3])),
            places=tuple(json.loads(row[4])), rivals=tuple(json.loads(row[5])),
        )

    def put(self, text: str, lookup: RorLookup) -> None:
        fetched_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        self._db.execute(
            "INSERT OR REPLACE INTO affiliation_lookup VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _key(text), " ".join(text.split()), lookup.ror_id, lookup.name,
                lookup.score,
                json.dumps(list(lookup.names), ensure_ascii=False),
                json.dumps(list(lookup.places), ensure_ascii=False),
                json.dumps(list(lookup.rivals), ensure_ascii=False), fetched_at,
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
        if lookup is None or not is_certain(lookup, text, self.min_score):
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
