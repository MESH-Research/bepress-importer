"""Builders assembling KC Works sub-objects from multiple Bepress columns.

These consume whole rows (authorN_*, advisorN, journal columns) rather than
single cells, so they live outside the scalar transform registry.
"""

from __future__ import annotations

from bepress_importer.profiles import (
    AuthorColumns,
    ContributorColumns,
    ImprintMapping,
    JournalMapping,
)

_TRUTHY = {"true", "1", "yes", "y", "x"}


def _get(row: dict[str, str], column: str | None) -> str:
    return row.get(column, "").strip() if column else ""


def build_creators(row: dict[str, str], config: AuthorColumns) -> list[dict]:
    """authorN_{fname,mname,lname,suffix,institution,is_corporate} columns → creators list."""
    creators = []
    for n in range(1, config.max + 1):
        prefix = f"{config.prefix}{n}_"
        fname = _get(row, prefix + "fname")
        mname = _get(row, prefix + "mname")
        lname = _get(row, prefix + "lname")
        suffix = _get(row, prefix + "suffix")
        institution = _get(row, prefix + "institution")
        corporate = _get(row, prefix + "is_corporate").lower() in _TRUTHY

        if not (fname or lname):
            continue

        if corporate:
            person_or_org: dict = {"type": "organizational", "name": lname or fname}
        else:
            given = " ".join(part for part in (fname, mname) if part)
            name = ", ".join(part for part in (lname, given, suffix) if part)
            person_or_org = {"type": "personal", "name": name}
            if given:
                person_or_org["given_name"] = given
            if lname:
                person_or_org["family_name"] = lname

        creator: dict = {"person_or_org": person_or_org, "role": {"id": "author"}}
        if institution and not corporate:
            creator["affiliations"] = [{"name": institution}]
        creators.append(creator)
    return creators


def build_contributors(row: dict[str, str], config: ContributorColumns) -> list[dict]:
    """Free-text name columns (e.g. advisor1..3) → contributors with the configured role."""
    contributors = []
    for n in range(1, config.max + 1):
        raw = _get(row, f"{config.prefix}{n}")
        if not raw:
            continue
        if "," in raw:
            family, _, given = (part.strip() for part in raw.partition(","))
        else:
            tokens = raw.split()
            family = tokens[-1]
            given = " ".join(tokens[:-1])
        person: dict = {
            "type": "personal",
            "name": f"{family}, {given}" if given else family,
            "family_name": family,
        }
        if given:
            person["given_name"] = given
        contributors.append({"person_or_org": person, "role": {"id": config.role}})
    return contributors


def build_journal(row: dict[str, str], config: JournalMapping) -> dict | None:
    """Journal columns → the "journal:journal" custom field, or None if all empty."""
    result = {}
    for key, column in (
        ("title", config.title),
        ("volume", config.volume),
        ("issue", config.issue),
        ("issn", config.issn),
    ):
        value = _get(row, column)
        if value:
            result[key] = value
    first, last = _get(row, config.pages_first), _get(row, config.pages_last)
    if first:
        result["pages"] = f"{first}-{last}" if last else first
    return result or None


def build_imprint(row: dict[str, str], config: ImprintMapping) -> dict | None:
    """Imprint columns → the "imprint:imprint" custom field, or None if all empty."""
    result = {}
    for key, column in (
        ("title", config.title),
        ("isbn", config.isbn),
        ("place", config.place),
        ("pages", config.pages),
    ):
        value = _get(row, column)
        if value:
            result[key] = value
    return result or None
