"""Registry of pure transform functions applied by the converter.

A transform receives the raw cell value, the whole row (for sibling-column
lookups) and the profile-supplied args. It returns the normalized value to
place at the field's JSON-pointer target, or None to omit the field.
"""

from __future__ import annotations

from collections.abc import Callable

Transform = Callable[[str, dict[str, str], dict], object | None]

TRANSFORMS: dict[str, Transform] = {}


def transform(name: str) -> Callable[[Transform], Transform]:
    def register(fn: Transform) -> Transform:
        TRANSFORMS[name] = fn
        return fn

    return register


def known_transforms() -> set[str]:
    return set(TRANSFORMS)


def apply_transform(name: str, value: str, row: dict[str, str], args: dict) -> object | None:
    """Apply a registered transform. Empty input values are omitted (None)."""
    raise NotImplementedError


@transform("edtf_date")
def edtf_date(value: str, row: dict[str, str], args: dict) -> object | None:
    """ISO-ish date (+ optional season column) → EDTF; unparseable input passes through."""
    raise NotImplementedError


@transform("identifier")
def identifier(value: str, row: dict[str, str], args: dict) -> object | None:
    """Value → {"identifier": ..., "scheme": args["scheme"]}, normalizing DOIs."""
    raise NotImplementedError


@transform("split")
def split(value: str, row: dict[str, str], args: dict) -> object | None:
    """Delimited string → list of stripped non-empty items (or re-joined string)."""
    raise NotImplementedError


@transform("strip_html")
def strip_html(value: str, row: dict[str, str], args: dict) -> object | None:
    """Remove HTML tags, unescape entities, collapse whitespace."""
    raise NotImplementedError


@transform("url")
def url(value: str, row: dict[str, str], args: dict) -> object | None:
    """Pass through http(s) URLs; anything else is omitted."""
    raise NotImplementedError


@transform("embargo")
def embargo(value: str, row: dict[str, str], args: dict) -> object | None:
    """Embargo date → {"embargo": {...}} if still active at args["as_of"], else None."""
    raise NotImplementedError


@transform("language_list")
def language_list(value: str, row: dict[str, str], args: dict) -> object | None:
    """Comma-separated language codes → [{"id": code}, ...]."""
    raise NotImplementedError


@transform("license_url")
def license_url(value: str, row: dict[str, str], args: dict) -> object | None:
    """Creative Commons license URL → [{"id": "cc-..."}]; unknown URLs omitted."""
    raise NotImplementedError
