"""Deterministic conversion: normalized workbook + profile → KC Works records."""

from __future__ import annotations

from dataclasses import dataclass, field

from bepress_importer.profiles import Profile
from bepress_importer.readers import Workbook


@dataclass(frozen=True)
class Issue:
    """A conversion problem worth reporting; the record is still emitted."""

    sheet: str
    record_id: str
    message: str


@dataclass
class ConversionResult:
    collections: dict[str, list[dict]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    unmatched_sheets: list[str] = field(default_factory=list)


def convert_workbook(workbook: Workbook, profile: Profile, as_of: str) -> ConversionResult:
    """Convert every profile-matched sheet to a per-collection list of KC Works records.

    as_of: ISO date used for embargo-activity decisions; an explicit input so
    output is reproducible.
    """
    raise NotImplementedError
