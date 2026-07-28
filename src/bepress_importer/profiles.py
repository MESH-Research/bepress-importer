"""TOML sheet-mapping profiles: which columns map to which KC Works fields.

Profiles are pure data — column names, JSON-pointer targets, transform names
and value maps. All conversion logic lives in the transform registry; a new
client export means a new profile file, not new code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class ProfileError(ValueError):
    """Raised when a profile file is structurally invalid."""


@dataclass(frozen=True)
class FieldMapping:
    source: str
    target: str
    transform: str | None = None
    args: dict = field(default_factory=dict)
    required: bool = False


@dataclass(frozen=True)
class ResourceTypeMapping:
    """document_type column → resource_type id, or a constant id for the sheet."""

    column: str | None = None
    map: dict[str, str] = field(default_factory=dict)
    default: str | None = None
    constant: str | None = None


@dataclass(frozen=True)
class AuthorColumns:
    prefix: str = "author"
    max: int = 32


@dataclass(frozen=True)
class ContributorColumns:
    prefix: str
    max: int
    role: str


@dataclass(frozen=True)
class JournalMapping:
    title: str | None = None
    volume: str | None = None
    issue: str | None = None
    issn: str | None = None
    pages_first: str | None = None
    pages_last: str | None = None


@dataclass(frozen=True)
class ImprintMapping:
    title: str | None = None
    isbn: str | None = None
    place: str | None = None
    pages: str | None = None


@dataclass(frozen=True)
class Defaults:
    record_id_column: str = "context_key"
    url_column: str | None = None
    files_enabled: bool = False
    season_style: str = "edtf-season"
    authors: AuthorColumns = field(default_factory=AuthorColumns)


@dataclass(frozen=True)
class SheetProfile:
    match: str
    resource_type: ResourceTypeMapping | None = None
    fields: tuple[FieldMapping, ...] = ()
    journal: JournalMapping | None = None
    imprint: ImprintMapping | None = None
    contributors: ContributorColumns | None = None
    constants: dict[str, str] = field(default_factory=dict)
    collection: str | None = None


@dataclass(frozen=True)
class Profile:
    name: str
    defaults: Defaults
    sheets: tuple[SheetProfile, ...]

    def match_sheet(self, sheet_name: str) -> SheetProfile | None:
        """Return the first sheet profile whose match pattern fits, else None."""
        raise NotImplementedError


def load_profile(path: str | Path, known_transforms: set[str] | None = None) -> Profile:
    """Load and validate a TOML profile. Raises ProfileError with context."""
    raise NotImplementedError
