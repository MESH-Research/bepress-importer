"""Registering a work's existing DOI as its KC Works persistent identifier.

A record that already has a DOI (a published article, say) must carry it in
the top-level `pids` block, marked as externally registered, so KC Works uses
that DOI instead of minting a new one:

    "pids": {"doi": {"identifier": "10.1234/abc", "provider": "external"}}

The converter first gathers DOIs into `metadata.identifiers` (from DOI
columns and from links to a DOI resolver); the functions here move them from
there into `pids`.
"""

from __future__ import annotations

from dataclasses import dataclass

from bepress_importer.doi import doi_reference, extract_doi


@dataclass(frozen=True)
class DoiPromotion:
    """What happened to a record's DOI identifiers."""

    doi: str
    consumed: tuple[dict, ...] = ()  # identifier entries that named this DOI
    conflicting: tuple[str, ...] = ()  # other DOIs on the record, kept as links


def _named_doi(entry: dict) -> str | None:
    """The DOI an identifier entry names, if it names one."""
    value = entry.get("identifier", "")
    if entry.get("scheme") == "doi":
        return extract_doi(value)
    if entry.get("scheme") == "url":
        return doi_reference(value)
    return None


def _identifiers(record: dict) -> list[dict]:
    return record.get("metadata", {}).get("identifiers", [])


def _link(doi: str) -> dict:
    return {"identifier": f"https://doi.org/{doi}", "scheme": "url"}


def doi_claim(record: dict) -> str | None:
    """The DOI this record would register as its own, or None if it has none.

    A `doi`-scheme identifier takes precedence over a `url` identifier that
    points at a DOI resolver; a publisher landing page is never a claim.
    """
    named = [(entry, doi) for entry in _identifiers(record) if (doi := _named_doi(entry))]
    for scheme in ("doi", "url"):
        for entry, doi in named:
            if entry.get("scheme") == scheme:
                return doi
    return None


def _rewrite(record: dict, claim: str, keep_claim_as_link: bool) -> DoiPromotion:
    """Rebuild the identifier list around the claimed DOI.

    Entries naming the claimed DOI are dropped (or collapsed into a single
    resolver link); entries naming any other DOI become resolver links.
    """
    consumed, conflicting, rebuilt = [], [], []
    for entry in _identifiers(record):
        doi = _named_doi(entry)
        if doi is None:
            replacement = entry
        elif doi.lower() == claim.lower():
            consumed.append(dict(entry))
            replacement = _link(claim) if keep_claim_as_link else None
        else:
            if doi not in conflicting:
                conflicting.append(doi)
            replacement = _link(doi)
        if replacement is not None and replacement not in rebuilt:
            rebuilt.append(replacement)
    record["metadata"]["identifiers"] = rebuilt
    return DoiPromotion(doi=claim, consumed=tuple(consumed), conflicting=tuple(conflicting))


def promote_doi_pid(
    record: dict, provider: str = "external", keep_identifiers: bool = False
) -> DoiPromotion | None:
    """Move the record's DOI into `pids.doi`, in bare form; None if it has no DOI.

    Every identifier entry naming that DOI is removed from
    `metadata.identifiers` (unless keep_identifiers), since the DOI is now the
    record's own identifier. A second, different DOI stays behind as a
    `https://doi.org/` link.
    """
    claim = doi_claim(record)
    if claim is None:
        return None
    if keep_identifiers:
        result = DoiPromotion(
            doi=claim,
            consumed=tuple(
                dict(entry)
                for entry in _identifiers(record)
                if (_named_doi(entry) or "").lower() == claim.lower()
            ),
        )
    else:
        result = _rewrite(record, claim, keep_claim_as_link=False)
    record.setdefault("pids", {})["doi"] = {"identifier": claim, "provider": provider}
    return result


def keep_doi_as_link(record: dict) -> DoiPromotion | None:
    """Keep the record's DOI as a plain `https://doi.org/` link, with no `pids`.

    For a DOI that cannot be registered as this record's own — one that
    another record in the same import claims too.
    """
    claim = doi_claim(record)
    if claim is None:
        return None
    return _rewrite(record, claim, keep_claim_as_link=True)
