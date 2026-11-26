"""Builders assembling KC Works sub-objects from multiple Bepress columns.

These consume whole rows (authorN_*, advisorN, journal columns) rather than
single cells, so they live outside the scalar transform registry.
"""

from __future__ import annotations

import json
import re

from bepress_importer.profiles import (
    AuthorColumns,
    ContributorColumns,
    ImprintMapping,
    JournalMapping,
)

_TRUTHY = {"true", "1", "yes", "y", "x"}


def _get(row: dict[str, str], column: str | None) -> str:
    return row.get(column, "").strip() if column else ""


_EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")


def _corporate_authors(row: dict[str, str], column: str | None) -> dict[int, str]:
    """{position: name} for the corporate authors in a JSON author-list cell."""
    try:
        entries = json.loads(_get(row, column)) if column else []
    except ValueError:
        return {}
    if not isinstance(entries, list):
        return {}
    return {
        position: name.strip()
        for position, entry in enumerate(entries, start=1)
        if isinstance(entry, dict)
        and isinstance(name := entry.get("CORPORATE_AUTHOR"), str)
        and name.strip()
    }


def build_creators(row: dict[str, str], config: AuthorColumns) -> list[dict]:
    """authorN_{fname,mname,lname,suffix,institution,is_corporate} columns → creators list.

    When config.json_column is set, corporate authors recorded only in that
    JSON author list (their numbered columns are blank) are slotted in at
    their position.
    """
    creators = []
    corporate_at = _corporate_authors(row, config.json_column)
    for n in range(1, max(config.max, *corporate_at, 0) + 1):
        prefix = f"{config.prefix}{n}_"
        fname = _get(row, prefix + "fname")
        mname = _get(row, prefix + "mname")
        lname = _get(row, prefix + "lname")
        suffix = _get(row, prefix + "suffix")
        institution = _get(row, prefix + "institution")
        corporate = _get(row, prefix + "is_corporate").lower() in _TRUTHY

        if not (fname or lname):
            if n in corporate_at:
                creators.append(
                    {
                        "person_or_org": {"type": "organizational", "name": corporate_at[n]},
                        "role": {"id": "author"},
                    }
                )
            continue
        if _EMAIL_RE.match(institution):
            institution = ""  # an address typed into the institution cell

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
    for key, column in (("title", config.title), ("issn", config.issn)):
        value = _get(row, column)
        if value:
            result[key] = value
    for key, column in (("volume", config.volume), ("issue", config.issue)):
        value = _get(row, column)
        if value and _plausible_number(value):
            result[key] = value
    first, last = (
        value if _plausible_page(value) else ""
        for value in (_get(row, config.pages_first), _get(row, config.pages_last))
    )
    if first:
        result["pages"] = f"{first}-{last}" if last else first
    return result or None


_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)


def _plausible_page(value: str) -> bool:
    """A page, a page range or an article number — not a link, a remark or a paragraph."""
    if len(value) > 30 or "://" in value:
        return False
    return any(ch.isdigit() for ch in value) or bool(_ROMAN_RE.match(value))


def _plausible_number(value: str) -> bool:
    """A volume or issue designation — not a note about online publication."""
    return len(value) <= 25 and "://" not in value and "doi" not in value.lower()


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


def implausible_journal_values(
    row: dict[str, str], config: JournalMapping
) -> list[tuple[str, str]]:
    """(column, value) for journal cells that cannot be what the column says:
    a paragraph or a link in a page cell, a note in place of a volume number.
    build_journal leaves these out."""
    found = []
    for column, plausible in (
        (config.volume, _plausible_number),
        (config.issue, _plausible_number),
        (config.pages_first, _plausible_page),
        (config.pages_last, _plausible_page),
    ):
        value = _get(row, column)
        if value and not plausible(value):
            found.append((column, value))
    return found
