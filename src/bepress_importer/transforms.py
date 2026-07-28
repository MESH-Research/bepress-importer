"""Registry of pure transform functions applied by the converter.

A transform receives the raw cell value, the whole row (for sibling-column
lookups) and the profile-supplied args. It returns the normalized value to
place at the field's JSON-pointer target, or None to omit the field.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable

from bepress_importer import edtf as edtf_module

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
    value = value.strip()
    if not value:
        return None
    return TRANSFORMS[name](value, row, args)


@transform("edtf_date")
def edtf_date(value: str, row: dict[str, str], args: dict) -> object | None:
    """ISO-ish date (+ optional season column) → EDTF; unparseable input passes through."""
    season_column = args.get("season_column")
    season = row.get(season_column, "") if season_column else None
    style = args.get("style", "edtf-season")
    try:
        return edtf_module.to_edtf(value, season=season, style=style)
    except ValueError:
        return value  # left as-is for the wrangler's edtf-date rule to flag


_DOI_RE = re.compile(r"(10\.\d{4,9}/\S+)", re.IGNORECASE)


@transform("identifier")
def identifier(value: str, row: dict[str, str], args: dict) -> object | None:
    """Value → {"identifier": ..., "scheme": args["scheme"]}, normalizing DOIs."""
    if "split" in args:
        value = value.split(args["split"])[0].strip()
        if not value:
            return None
    if args.get("normalize") == "doi":
        match = _DOI_RE.search(value)
        if match:
            value = match.group(1)
    return {"identifier": value, "scheme": args["scheme"]}


@transform("split")
def split(value: str, row: dict[str, str], args: dict) -> object | None:
    """Delimited string → list of stripped non-empty items (or re-joined string)."""
    items = [item.strip() for item in value.split(args.get("sep", ","))]
    items = [item for item in items if item]
    if not items:
        return None
    if "join" in args:
        return args["join"].join(items)
    return items


_TAG_RE = re.compile(r"<[^>]+>")


@transform("strip_html")
def strip_html(value: str, row: dict[str, str], args: dict) -> object | None:
    """Remove HTML tags, unescape entities, collapse whitespace."""
    text = html.unescape(_TAG_RE.sub(" ", value))
    return " ".join(text.split()) or None


@transform("url")
def url(value: str, row: dict[str, str], args: dict) -> object | None:
    """Pass through http(s) URLs; anything else is omitted."""
    if re.match(r"^https?://\S+$", value):
        return value
    return None


@transform("embargo")
def embargo(value: str, row: dict[str, str], args: dict) -> object | None:
    """Embargo date → {"embargo": {...}} if still active at args["as_of"], else None."""
    until = value.split(" ")[0]
    if until <= args["as_of"]:  # ISO date strings compare chronologically
        return None
    return {"embargo": {"active": True, "until": until}}


@transform("language_list")
def language_list(value: str, row: dict[str, str], args: dict) -> object | None:
    """Comma-separated language codes → [{"id": code}, ...]."""
    codes = [code.strip().lower() for code in value.split(",")]
    return [{"id": code} for code in codes if code] or None


@transform("additional_description")
def additional_description(value: str, row: dict[str, str], args: dict) -> object | None:
    """HTML-ish note → InvenioRDM additional_descriptions entry list."""
    text = strip_html(value, row, {})
    if not text:
        return None
    return [{"description": text, "type": {"id": args.get("type", "other")}}]


_CC_LICENSE_RE = re.compile(
    r"https?://creativecommons\.org/licenses/(?P<code>[a-z-]+)/(?P<version>\d+\.\d+)"
)
_CC_ZERO_RE = re.compile(r"https?://creativecommons\.org/publicdomain/zero/(?P<version>\d+\.\d+)")


@transform("license_url")
def license_url(value: str, row: dict[str, str], args: dict) -> object | None:
    """Creative Commons license URL → [{"id": "cc-..."}]; unknown URLs omitted."""
    match = _CC_LICENSE_RE.match(value)
    if match:
        return [{"id": f"cc-{match.group('code')}-{match.group('version')}"}]
    match = _CC_ZERO_RE.match(value)
    if match:
        return [{"id": f"cc0-{match.group('version')}"}]
    return None
