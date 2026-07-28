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


def build_creators(row: dict[str, str], config: AuthorColumns) -> list[dict]:
    """authorN_{fname,mname,lname,suffix,institution,is_corporate} columns → creators list."""
    raise NotImplementedError


def build_contributors(row: dict[str, str], config: ContributorColumns) -> list[dict]:
    """Free-text name columns (e.g. advisor1..3) → contributors with the configured role."""
    raise NotImplementedError


def build_journal(row: dict[str, str], config: JournalMapping) -> dict | None:
    """Journal columns → the "journal:journal" custom field, or None if all empty."""
    raise NotImplementedError


def build_imprint(row: dict[str, str], config: ImprintMapping) -> dict | None:
    """Imprint columns → the "imprint:imprint" custom field, or None if all empty."""
    raise NotImplementedError
