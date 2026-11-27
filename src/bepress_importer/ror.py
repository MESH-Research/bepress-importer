"""ROR ids for affiliations: ids fixed by the profile, and free-text lookups
in the ROR API with an on-disk cache so no text is ever looked up twice."""

from __future__ import annotations

import dataclasses
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
_CACHE_LAYOUT = 4


class RorUnavailable(Exception):
    """The ROR API could not be reached or kept refusing the request."""


@dataclass(frozen=True)
class RorCandidate:
    """One organisation the ROR API returned for an affiliation text.

    names are its official names (display name and labels in other
    languages); aliases are its aliases and acronyms, which other
    organisations may share; places are its city, region and country.
    """

    ror_id: str
    name: str | None = None
    names: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    score: float | None = None
    chosen: bool = False


@dataclass(frozen=True)
class RorLookup:
    """Everything the ROR API returned for one affiliation text, in its order."""

    candidates: tuple[RorCandidate, ...] = ()


@dataclass(frozen=True)
class RorMatch:
    """A ROR id settled on for an affiliation text, and on what evidence:
    "profile" for an id the profile fixes, "api" for a ROR API result, with
    detail saying where the text's words were found ("name", "name and place")."""

    ror_id: str
    name: str | None
    evidence: str
    detail: str | None = None


def _words(text: str) -> list[str]:
    """A text as comparable words: no case, accents or punctuation."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("&", " and ")).split()


#: Words that say nothing about which organisation is meant: a text or a
#: name may have them or lack them ("The Pennsylvania State University",
#: "University of Pittsburgh - Main Campus").
_PASSED_OVER = frozenset({"the", "at", "main", "campus"})


def _telling_words(text: str) -> set[str]:
    return set(_words(text)) - _PASSED_OVER


def best_match(text: str, lookup: RorLookup) -> tuple[RorCandidate, str] | None:
    """The returned organisation that the text names, and how ("name" or
    "name and place"); None when no result has all of the text's words.

    A result is taken when every word of the text is in one of its official
    names, or when the text is that whole name plus words from its place
    ("X University - Fort Collins"). A place may not stand in for part of the
    name: "NC State" is not Appalachian State University, though "State" is
    in its name and NC is where it is. Aliases and acronyms do not count:
    several organisations can share one ("NC State"). Words that say nothing
    about which organisation is meant ("the", "at", "main", "campus") are
    passed over on both sides.

    Among results that qualify, a name holding every word beats one helped by
    its place, and then the name with the fewest words the text lacks wins,
    so "Miami University" is not taken for the University of Miami. Two
    results that qualify equally well are left alone. A single word is too
    little to pick a longer name by ("Exeter" is not Phillips Exeter
    Academy): it is taken only when it is the whole name.
    """
    wanted = _telling_words(text)
    if not wanted:
        return None
    fits = []
    for order, candidate in enumerate(lookup.candidates):
        place_words = {word for place in candidate.places for word in _words(place)}
        best = None
        for name in candidate.names:
            name_words = _telling_words(name)
            if wanted == name_words or (wanted < name_words and len(wanted) > 1):
                fit = (0, len(name_words - wanted))
            elif name_words and name_words <= wanted <= name_words | place_words:
                fit = (1, 0)  # the whole name, followed by where it is
            else:
                continue
            best = fit if best is None else min(best, fit)
        if best is not None:
            fits.append((best, order, candidate))
    if not fits:
        return None
    fits.sort(key=lambda entry: entry[:2])
    if len(fits) > 1 and fits[0][0] == fits[1][0]:
        return None
    (needs_place, _), _, candidate = fits[0]
    return candidate, "name and place" if needs_place else "name"


def read_response(payload: dict) -> RorLookup:
    """The organisations the API returned for an affiliation query, in its order."""
    candidates = []
    for entry in payload.get("items") or []:
        organization = entry.get("organization") or {}
        ror_id = str(organization.get("id", "")).rstrip("/").rsplit("/", 1)[-1]
        if not ror_id or organization.get("status", "active") != "active":
            continue
        names = [n for n in organization.get("names") or [] if n.get("value")]
        official = [n for n in names if {"ror_display", "label"} & set(n.get("types") or [])]
        places = []
        for location in organization.get("locations") or []:
            details = location.get("geonames_details") or {}
            for key in (
                "name", "country_subdivision_name", "country_subdivision_code",
                "country_name", "country_code",
            ):
                if details.get(key) and details[key] not in places:
                    places.append(details[key])
        candidates.append(
            RorCandidate(
                ror_id=ror_id,
                name=next(
                    (n["value"] for n in names if "ror_display" in (n.get("types") or [])), None
                ),
                names=tuple(n["value"] for n in official),
                aliases=tuple(n["value"] for n in names if n not in official),
                places=tuple(places),
                score=entry.get("score"),
                chosen=entry.get("chosen") is True,
            )
        )
    return RorLookup(candidates=tuple(candidates))


def _key(text: str) -> str:
    """Texts differing only in case or spacing are the same affiliation."""
    return " ".join(text.split()).casefold()


class RorCache:
    """Affiliation text → RorLookup, kept in a SQLite file.

    The whole answer is kept (every organisation returned, with its names and
    place), so the rule that picks among them can change without asking
    again. Answers without any organisation are kept too. Texts differing
    only in case or spacing share an entry.
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
            " candidates TEXT NOT NULL,"  # JSON list: the organisations returned
            " fetched_at TEXT NOT NULL)"
        )
        self._db.commit()

    def get(self, text: str) -> RorLookup | None:
        row = self._db.execute(
            "SELECT candidates FROM affiliation_lookup WHERE query = ?", (_key(text),)
        ).fetchone()
        if row is None:
            return None
        return RorLookup(
            candidates=tuple(
                RorCandidate(
                    ror_id=entry["ror_id"],
                    name=entry["name"],
                    names=tuple(entry["names"]),
                    aliases=tuple(entry["aliases"]),
                    places=tuple(entry["places"]),
                    score=entry["score"],
                    chosen=entry["chosen"],
                )
                for entry in json.loads(row[0])
            )
        )

    def put(self, text: str, lookup: RorLookup) -> None:
        fetched_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        candidates = json.dumps(
            [dataclasses.asdict(candidate) for candidate in lookup.candidates],
            ensure_ascii=False,
        )
        self._db.execute(
            "INSERT OR REPLACE INTO affiliation_lookup VALUES (?, ?, ?, ?)",
            (_key(text), " ".join(text.split()), candidates, fetched_at),
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
        found = best_match(text, lookup) if lookup is not None else None
        if found is None:
            return None
        candidate, how = found
        return RorMatch(
            ror_id=candidate.ror_id, name=candidate.name, evidence="api", detail=how
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
