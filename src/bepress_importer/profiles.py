"""TOML sheet-mapping profiles: which columns map to which KC Works fields.

Profiles are pure data — column names, JSON-pointer targets, transform names
and value maps. All conversion logic lives in the transform registry; a new
client export means a new profile file, not new code.
"""

from __future__ import annotations

import fnmatch
import tomllib
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
class RowFilter:
    """Keep only rows whose column value is in `keep` (e.g. state = published)."""

    column: str
    keep: tuple[str, ...]


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
    filter: RowFilter | None = None


@dataclass(frozen=True)
class Profile:
    name: str
    defaults: Defaults
    sheets: tuple[SheetProfile, ...]

    def match_sheet(self, sheet_name: str) -> SheetProfile | None:
        """Return the first sheet profile whose match pattern fits, else None."""
        for sheet in self.sheets:
            if fnmatch.fnmatchcase(sheet_name, sheet.match):
                return sheet
        return None


def load_profile(path: str | Path, known_transforms: set[str] | None = None) -> Profile:
    """Load and validate a TOML profile. Raises ProfileError with context."""
    path = Path(path)
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path}: invalid TOML: {exc}") from exc

    head = data.get("profile", {})
    name = head.get("name")
    if not name:
        raise ProfileError(f"{path}: [profile] section with a 'name' key is required")

    defaults = _parse_defaults(data.get("defaults", {}))
    sheets = tuple(
        _parse_sheet(path, i, raw, known_transforms)
        for i, raw in enumerate(data.get("sheet", []))
    )
    return Profile(name=name, defaults=defaults, sheets=sheets)


def _parse_defaults(raw: dict) -> Defaults:
    authors_raw = raw.get("author_columns", {})
    return Defaults(
        record_id_column=raw.get("record_id", {}).get("column", "context_key"),
        url_column=raw.get("url_identifier", {}).get("column"),
        files_enabled=raw.get("files_enabled", False),
        season_style=raw.get("season_style", "edtf-season"),
        authors=AuthorColumns(
            prefix=authors_raw.get("prefix", "author"),
            max=authors_raw.get("max", 32),
        ),
    )


def _parse_sheet(
    path: Path, index: int, raw: dict, known_transforms: set[str] | None
) -> SheetProfile:
    where = f"{path}: [[sheet]] #{index + 1}"
    match = raw.get("match")
    if not match:
        raise ProfileError(f"{where}: 'match' is required")

    fields = []
    seen_targets: set[str] = set()
    for f_raw in raw.get("field", []):
        source, target = f_raw.get("source"), f_raw.get("target")
        if not source or not target:
            raise ProfileError(f"{where}: every field needs 'source' and 'target'")
        if not target.startswith("/"):
            raise ProfileError(f"{where}: target {target!r} must be a JSON pointer starting with '/'")
        if target in seen_targets:
            raise ProfileError(f"{where}: duplicate target {target!r}")
        seen_targets.add(target)
        transform = f_raw.get("transform")
        if transform and known_transforms is not None and transform not in known_transforms:
            raise ProfileError(f"{where}: unknown transform {transform!r} for source {source!r}")
        fields.append(
            FieldMapping(
                source=source,
                target=target,
                transform=transform,
                args=dict(f_raw.get("args", {})),
                required=f_raw.get("required", False),
            )
        )

    resource_type = None
    if "resource_type" in raw:
        rt_raw = raw["resource_type"]
        resource_type = ResourceTypeMapping(
            column=rt_raw.get("column"),
            map=dict(rt_raw.get("map", {})),
            default=rt_raw.get("default"),
            constant=rt_raw.get("constant"),
        )
        if not resource_type.column and not resource_type.constant:
            raise ProfileError(f"{where}: resource_type needs a 'column' or a 'constant'")

    journal = None
    if "journal" in raw:
        j_raw = raw["journal"]
        pages = j_raw.get("pages", {})
        journal = JournalMapping(
            title=j_raw.get("title"),
            volume=j_raw.get("volume"),
            issue=j_raw.get("issue"),
            issn=j_raw.get("issn"),
            pages_first=pages.get("first"),
            pages_last=pages.get("last"),
        )

    imprint = None
    if "imprint" in raw:
        i_raw = raw["imprint"]
        imprint = ImprintMapping(
            title=i_raw.get("title"),
            isbn=i_raw.get("isbn"),
            place=i_raw.get("place"),
            pages=i_raw.get("pages"),
        )

    contributors = None
    if "contributors" in raw:
        c_raw = raw["contributors"]
        if not c_raw.get("prefix") or not c_raw.get("role"):
            raise ProfileError(f"{where}: contributors needs 'prefix' and 'role'")
        contributors = ContributorColumns(
            prefix=c_raw["prefix"],
            max=c_raw.get("max", 5),
            role=c_raw["role"],
        )

    row_filter = None
    if "filter" in raw:
        f_raw = raw["filter"]
        if not f_raw.get("column") or not f_raw.get("keep"):
            raise ProfileError(f"{where}: filter needs 'column' and a 'keep' list")
        row_filter = RowFilter(column=f_raw["column"], keep=tuple(f_raw["keep"]))

    constants = dict(raw.get("constants", {}))
    for pointer in constants:
        if not pointer.startswith("/"):
            raise ProfileError(
                f"{where}: constant key {pointer!r} must be a JSON pointer starting with '/'"
            )

    return SheetProfile(
        match=match,
        resource_type=resource_type,
        fields=tuple(fields),
        journal=journal,
        imprint=imprint,
        contributors=contributors,
        constants=constants,
        collection=raw.get("collection"),
        filter=row_filter,
    )
