"""Working out who published a work from the traces a publisher leaves.

Bepress journal-article rows rarely name their publisher, but KC Works needs
one (it is required to register a DOI). The publisher can usually be read off
the row all the same: a copyright or publication statement names it ("©
2019 IEEE", "published by Taylor & Francis"), a DOI carries the publisher's
registrant prefix, and a link points at the publisher's own platform.

The list of publishers and their traces is data, not code: see
`vocab/publishers.toml`.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_LIST = Path(__file__).parent / "vocab" / "publishers.toml"
_HOST_RE = re.compile(r"https?://([^/\s:?#]+)", re.IGNORECASE)
_BARE_HOST_RE = re.compile(r"^([\w-]+(?:\.[\w-]+)+)(?:[/:?#]|$)")


@dataclass(frozen=True)
class Publisher:
    """One publisher and the traces that identify it."""

    name: str
    statement: tuple[str, ...] = ()  # phrases found in copyright text, any case
    acronyms: tuple[str, ...] = ()  # whole words matched in exactly this case
    doi_prefixes: tuple[str, ...] = ()
    hosts: tuple[str, ...] = ()  # web domains of the publisher's own platform


@dataclass(frozen=True)
class PublisherMatch:
    """A publisher, and what gave it away."""

    name: str
    evidence: str  # "statement" | "doi" | "link"
    detail: str  # the phrase, DOI prefix or host that matched


@lru_cache(maxsize=1)
def known_publishers() -> tuple[Publisher, ...]:
    """Every publisher in the list, in file order."""
    with open(_LIST, "rb") as handle:
        entries = tomllib.load(handle)["publisher"]
    return tuple(
        Publisher(
            name=entry["name"],
            statement=tuple(entry.get("statement", ())),
            acronyms=tuple(entry.get("acronyms", ())),
            doi_prefixes=tuple(entry.get("doi_prefixes", ())),
            hosts=tuple(host.lower() for host in entry.get("hosts", ())),
        )
        for entry in entries
    )


def _whole_word(phrase: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", flags)


@lru_cache(maxsize=1)
def _statement_patterns() -> tuple[tuple[re.Pattern[str], str], ...]:
    patterns = []
    for publisher in known_publishers():
        for phrase in publisher.statement:
            patterns.append((_whole_word(phrase, re.IGNORECASE), publisher.name))
        for acronym in publisher.acronyms:
            patterns.append((_whole_word(acronym), publisher.name))
    return tuple(patterns)


@lru_cache(maxsize=1)
def _by_doi_prefix() -> dict[str, str]:
    return {prefix: p.name for p in known_publishers() for prefix in p.doi_prefixes}


@lru_cache(maxsize=1)
def _by_host() -> dict[str, str]:
    return {host: p.name for p in known_publishers() for host in p.hosts}


def publisher_from_statement(text: str) -> PublisherMatch | None:
    """The publisher named in a copyright/publication statement, if any.

    When several are named, the one mentioned first wins ("Published by
    Cambridge University Press on behalf of ..."), and the fuller name wins
    where two start at the same place ("Springer Nature", not "Springer").
    """
    text = " ".join(text.split())
    best: tuple[int, int, str, str] | None = None
    for pattern, name in _statement_patterns():
        found = pattern.search(text)
        if not found:
            continue
        candidate = (found.start(), -len(found.group()), name, found.group())
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    return PublisherMatch(name=best[2], evidence="statement", detail=best[3])


def publisher_from_doi(doi: str) -> PublisherMatch | None:
    """The publisher that registered a DOI, read from its prefix, if known."""
    prefix = doi.strip().split("/", 1)[0]
    name = _by_doi_prefix().get(prefix)
    return PublisherMatch(name=name, evidence="doi", detail=prefix) if name else None


def publisher_from_link(link: str) -> PublisherMatch | None:
    """The publisher whose platform a link points at, if it is one we know.

    Aggregators and indexes (JSTOR, Project MUSE, PubMed...) host many
    publishers' work and identify none.
    """
    found = _HOST_RE.search(link) or _BARE_HOST_RE.match(link.strip())
    if not found:
        return None
    host = found.group(1).lower()
    labels = host.split(".")
    for start in range(len(labels) - 1):
        name = _by_host().get(".".join(labels[start:]))
        if name:
            return PublisherMatch(name=name, evidence="link", detail=host)
    return None


def find_publisher(
    statements: Iterable[str] = (), dois: Iterable[str] = (), links: Iterable[str] = ()
) -> PublisherMatch | None:
    """The best-evidenced publisher: a statement naming it beats a DOI prefix,
    which beats a link."""
    for finder, values in (
        (publisher_from_statement, statements),
        (publisher_from_doi, dois),
        (publisher_from_link, links),
    ):
        for value in values:
            match = finder(value) if value else None
            if match:
                return match
    return None
