"""Validation rules: find KC Works schema problems and propose safe fixes.

Each rule inspects records and returns findings. A finding may carry a
Proposal (the concrete corrected value — value=None means "remove the
field"); findings without a proposal are flag-only and need `edit`.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass

from bepress_importer import vocab
from bepress_importer.edtf import SEASONS, is_valid


@dataclass(frozen=True)
class Proposal:
    value: object  # None means: remove the field


@dataclass(frozen=True)
class Finding:
    rule: str
    record_id: str
    field: str
    current: object
    proposal: Proposal | None = None
    note: str | None = None


RuleFn = Callable[[list[dict], str | None], list[Finding]]

_RULES: dict[str, RuleFn] = {}


def _rule(name: str) -> Callable[[RuleFn], RuleFn]:
    def register(fn: RuleFn) -> RuleFn:
        _RULES[name] = fn
        return fn

    return register


def available_rules() -> list[str]:
    """Names of all registered rules, in run order."""
    return list(_RULES)


def run_rules(
    records: list[dict],
    names: list[str] | None = None,
    as_of: str | None = None,
) -> list[Finding]:
    """Run rules (all by default) over records and return their findings."""
    findings: list[Finding] = []
    for name, fn in _RULES.items():
        if names is not None and name not in names:
            continue
        findings.extend(fn(records, as_of))
    return findings


def record_id_of(record: dict) -> str:
    for ident in record.get("metadata", {}).get("identifiers", []):
        if ident.get("scheme") == "import-recid":
            return ident["identifier"]
    return ""


@_rule("required-fields")
def required_fields(records: list[dict], as_of: str | None) -> list[Finding]:
    findings = []
    for record in records:
        rid = record_id_of(record)
        metadata = record.get("metadata", {})
        checks = [
            ("/metadata/title", metadata.get("title")),
            ("/metadata/resource_type/id", metadata.get("resource_type", {}).get("id")),
            ("/metadata/publication_date", metadata.get("publication_date")),
            ("/metadata/creators", metadata.get("creators")),
        ]
        for pointer, value in checks:
            if not value:
                findings.append(
                    Finding("required-fields", rid, pointer, value, note="required field missing")
                )
    return findings


@_rule("resource-type-vocab")
def resource_type_vocab(records: list[dict], as_of: str | None) -> list[Finding]:
    data = vocab.load("resource_types")
    valid, aliases = set(data["ids"]), data["aliases"]
    findings = []
    for record in records:
        current = record.get("metadata", {}).get("resource_type", {}).get("id")
        if not current or current in valid:
            continue
        proposal = None
        if current in aliases:
            proposal = Proposal(aliases[current])
        else:
            close = difflib.get_close_matches(current, data["ids"], n=1, cutoff=0.8)
            if close:
                proposal = Proposal(close[0])
        findings.append(
            Finding(
                "resource-type-vocab",
                record_id_of(record),
                "/metadata/resource_type/id",
                current,
                proposal,
                note=f"{current!r} is not in the KC Works resource_type vocabulary",
            )
        )
    return findings


_MONTHS = {
    name: f"{num:02d}"
    for num, name in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"],
        start=1,
    )
}


def _reparse_date(value: str) -> str | None:
    text = value.strip().lower()
    match = re.match(r"^([a-z]+),?\s+(\d{4})$", text)
    if match:
        word, year = match.groups()
        if word in SEASONS:
            return f"{year}-{SEASONS[word]}"
        if word in _MONTHS:
            return f"{year}-{_MONTHS[word]}"
    match = re.match(r"^(\d{4})[/.](\d{1,2})(?:[/.](\d{1,2}))?$", text)
    if match:
        year, month, day = match.groups()
        candidate = f"{year}-{int(month):02d}" + (f"-{int(day):02d}" if day else "")
        return candidate if is_valid(candidate) else None
    return None


@_rule("edtf-date")
def edtf_date(records: list[dict], as_of: str | None) -> list[Finding]:
    findings = []
    for record in records:
        current = record.get("metadata", {}).get("publication_date")
        if not current or is_valid(current):
            continue
        proposed = _reparse_date(current)
        findings.append(
            Finding(
                "edtf-date",
                record_id_of(record),
                "/metadata/publication_date",
                current,
                Proposal(proposed) if proposed else None,
                note=f"{current!r} is not valid EDTF",
            )
        )
    return findings


_DOI_OK = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_EXTRACT = re.compile(r"(10\.\d{4,9}/\S+)", re.IGNORECASE)
_PMID = re.compile(r"^\s*pmid:?\s*(\d+)\s*$", re.IGNORECASE)


@_rule("doi-format")
def doi_format(records: list[dict], as_of: str | None) -> list[Finding]:
    findings = []
    for record in records:
        for index, ident in enumerate(record.get("metadata", {}).get("identifiers", [])):
            value = ident.get("identifier", "")
            if ident.get("scheme") != "doi" or _DOI_OK.match(value):
                continue
            pmid = _PMID.match(value)
            if pmid:
                findings.append(
                    Finding(
                        "doi-format",
                        record_id_of(record),
                        f"/metadata/identifiers/{index}",
                        dict(ident),
                        Proposal(
                            {
                                "identifier": f"https://pubmed.ncbi.nlm.nih.gov/{pmid.group(1)}/",
                                "scheme": "url",
                            }
                        ),
                        note="this is a PubMed ID, not a DOI; KC Works has no pmid "
                        "scheme, so link it as a PubMed URL instead",
                    )
                )
                continue
            match = _DOI_EXTRACT.search(value)
            findings.append(
                Finding(
                    "doi-format",
                    record_id_of(record),
                    f"/metadata/identifiers/{index}/identifier",
                    value,
                    Proposal(match.group(1)) if match else None,
                    note="DOI should be the bare 10.xxxx/... form"
                    if match
                    else "value in the doi field does not look like a DOI",
                )
            )
    return findings


@_rule("rights-vocab")
def rights_vocab(records: list[dict], as_of: str | None) -> list[Finding]:
    valid = set(vocab.load("rights")["ids"])
    findings = []
    for record in records:
        for index, right in enumerate(record.get("metadata", {}).get("rights", [])):
            current = right.get("id")
            if current and current not in valid:
                findings.append(
                    Finding(
                        "rights-vocab",
                        record_id_of(record),
                        f"/metadata/rights/{index}/id",
                        current,
                        note=f"{current!r} is not in the rights vocabulary",
                    )
                )
    return findings


@_rule("language-code")
def language_code(records: list[dict], as_of: str | None) -> list[Finding]:
    valid = set(vocab.load("languages")["ids"])
    findings = []
    for record in records:
        for index, language in enumerate(record.get("metadata", {}).get("languages", [])):
            current = language.get("id")
            if current and current not in valid:
                findings.append(
                    Finding(
                        "language-code",
                        record_id_of(record),
                        f"/metadata/languages/{index}/id",
                        current,
                        note=f"{current!r} is not an ISO 639-3 code in the vocabulary",
                    )
                )
    return findings


# commas/semicolons only: trailing periods are legitimate (initials, "Jr.")
_TRAILING_PUNCT = re.compile(r"[\s,;]+$")


@_rule("name-sanity")
def name_sanity(records: list[dict], as_of: str | None) -> list[Finding]:
    findings = []
    for record in records:
        rid = record_id_of(record)
        for index, creator in enumerate(record.get("metadata", {}).get("creators", [])):
            person = creator.get("person_or_org", {})
            base = f"/metadata/creators/{index}/person_or_org"
            for key in ("name", "given_name", "family_name"):
                value = person.get(key)
                if value and _TRAILING_PUNCT.search(value):
                    findings.append(
                        Finding(
                            "name-sanity",
                            rid,
                            f"{base}/{key}",
                            value,
                            Proposal(_TRAILING_PUNCT.sub("", value)),
                            note="trailing punctuation",
                        )
                    )
            if person.get("type") == "personal" and not person.get("family_name"):
                findings.append(
                    Finding(
                        "name-sanity",
                        rid,
                        f"{base}/family_name",
                        None,
                        note="personal creator has no family name",
                    )
                )
    return findings


@_rule("duplicate-recid")
def duplicate_recid(records: list[dict], as_of: str | None) -> list[Finding]:
    counts: dict[str, int] = {}
    for record in records:
        rid = record_id_of(record)
        counts[rid] = counts.get(rid, 0) + 1
    findings = []
    for record in records:
        rid = record_id_of(record)
        if rid and counts[rid] > 1:
            findings.append(
                Finding(
                    "duplicate-recid",
                    rid,
                    "/metadata/identifiers",
                    rid,
                    note=f"import-recid {rid!r} appears {counts[rid]} times",
                )
            )
    return findings


@_rule("embargo-past")
def embargo_past(records: list[dict], as_of: str | None) -> list[Finding]:
    if as_of is None:
        return []
    findings = []
    for record in records:
        embargo = record.get("access", {}).get("embargo", {})
        until = embargo.get("until")
        if embargo.get("active") and until and until <= as_of:
            findings.append(
                Finding(
                    "embargo-past",
                    record_id_of(record),
                    "/access/embargo",
                    embargo,
                    Proposal(None),
                    note=f"embargo expired on {until}",
                )
            )
    return findings
