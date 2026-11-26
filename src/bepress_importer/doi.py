"""Recognising DOIs in messy spreadsheet cells.

Bepress DOI and link columns hold DOIs in every imaginable form: bare, as
resolver URLs (with or without a scheme), behind a "doi:" label, glued to
citation text or with landing-page suffixes. KC Works wants the bare
`10.xxxx/suffix` form, so everything here reduces a cell to that — or to
None when no trustworthy DOI can be read from it.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

# a DOI: registrant prefix, slash, then a suffix running to whitespace or a quote
_CANDIDATE = re.compile(r'(?<![\d.])10\.\d{4,9}/[^\s"]+')
_PREFIX_GAP = re.compile(r"((?<![\d.])10\.\d{4,9}/)\s+(?=\S)")
_LANDING_SUFFIX = re.compile(
    r"/(?:abstract|full|fulltext\.html|pdf|epdf|pdfplus|meta|summary)$", re.IGNORECASE
)
_BRACKETS = {")": "(", "]": "[", ">": "<"}
_REFERENCE = re.compile(
    r"(?:^|\s|://)(?:(?:www\.)?(?:dx[./])?doi[./]org/+|doi\s*:)\s*(?=10\.\d{4,9}/)",
    re.IGNORECASE,
)
_BARE = re.compile(r"^\s*(?:https?://)?(?=10\.\d{4,9}/)", re.IGNORECASE)


def _clean(candidate: str) -> str | None:
    """Strip everything a landing page or a sentence adds around a DOI."""
    doi = re.split(r"[?#]", candidate, maxsplit=1)[0]
    if "%" in doi:
        doi = unquote(doi)
    while True:
        trimmed = _LANDING_SUFFIX.sub("", doi).rstrip(".,;:")
        closer = trimmed[-1:]
        if closer in _BRACKETS and trimmed.count(closer) > trimmed.count(_BRACKETS[closer]):
            trimmed = trimmed[:-1]
        if trimmed == doi:
            break
        doi = trimmed
    return doi if doi.split("/", 1)[-1] else None


def extract_doi(text: str) -> str | None:
    """The bare DOI found anywhere in `text`, or None if there is no usable one.

    For cells that are *meant* to hold a DOI (a `doi` column): the DOI may be
    wrapped in a resolver URL, a label or a publisher landing-page URL.
    """
    text = _PREFIX_GAP.sub(r"\1", text)
    matches = list(_CANDIDATE.finditer(text))
    if not matches:
        return None
    first = matches[0]
    # "10.1371/journal. pone.0247579": the DOI was broken by a space, and
    # what is left would be somebody else's DOI — refuse rather than guess
    if first.group().endswith(".") and re.match(r"\s+\w", text[first.end():]):
        return None
    cleaned = [doi for m in matches if (doi := _clean(m.group()))]
    if not cleaned:
        return None
    doi = cleaned[0]
    for other in cleaned[1:]:
        # the same DOI repeated cleanly: the first had citation text glued on
        if len(other) < len(doi) and doi.lower().startswith(other.lower()):
            doi = other
    return doi


def doi_reference(text: str) -> str | None:
    """The bare DOI when `text` as a whole *is* a reference to a DOI, else None.

    For link cells, where most values are ordinary URLs: a DOI resolver
    address (doi.org / dx.doi.org, with or without http(s)://), a "doi:" label
    or a bare DOI counts; a publisher landing page that merely has a DOI in
    its path does not.
    """
    marker = _REFERENCE.search(text) or _BARE.match(text)
    if not marker:
        return None
    return extract_doi(text[marker.end():])
