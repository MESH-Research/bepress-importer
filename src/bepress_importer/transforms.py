"""Registry of pure transform functions applied by the converter.

A transform receives the raw cell value, the whole row (for sibling-column
lookups) and the profile-supplied args. It returns the normalized value to
place at the field's JSON-pointer target, or None to omit the field.
"""

from __future__ import annotations

import copy
import html
import re
from collections.abc import Callable

from bepress_importer import edtf as edtf_module
from bepress_importer.doi import doi_reference, extract_doi, is_resolver_address
from bepress_importer.publishers import PublisherMatch, find_publisher

Transform = Callable[[str, dict[str, str], dict], object | None]

TRANSFORMS: dict[str, Transform] = {}
_ACCEPTS_EMPTY: set[str] = set()
_DERIVES: set[str] = set()
_OPPORTUNISTIC: set[str] = set()


def transform(
    name: str, accepts_empty: bool = False, derives: bool = False, opportunistic: bool = False
) -> Callable[[Transform], Transform]:
    """Register a transform.

    accepts_empty: it runs even when its source cell is empty (it scans the row).
    derives: a value it produces from an empty cell was worked out from other
    columns, which is worth recording in the conversion log.
    opportunistic: it only picks up the occasional value another mapping of
    the same column passes over, so yielding nothing is not an omission.
    """

    def register(fn: Transform) -> Transform:
        TRANSFORMS[name] = fn
        if accepts_empty:
            _ACCEPTS_EMPTY.add(name)
        if derives:
            _DERIVES.add(name)
        if opportunistic:
            _OPPORTUNISTIC.add(name)
        return fn

    return register


def derives_value(name: str) -> bool:
    """True for transforms whose result from an empty cell should be logged."""
    return name in _DERIVES


def is_opportunistic(name: str) -> bool:
    """True for transforms whose empty result is not worth logging as dropped."""
    return name in _OPPORTUNISTIC


def known_transforms() -> set[str]:
    return set(TRANSFORMS)


def apply_transform(name: str, value: str, row: dict[str, str], args: dict) -> object | None:
    """Apply a registered transform. Empty input values are omitted (None),
    except for transforms that scan the whole row rather than one cell."""
    value = value.strip()
    if not value and name not in _ACCEPTS_EMPTY:
        return None
    return TRANSFORMS[name](value, row, args)


@transform("edtf_date", accepts_empty=True)
def edtf_date(value: str, row: dict[str, str], args: dict) -> object | None:
    """ISO-ish date (+ optional season column) → EDTF; unparseable input passes through.

    args.fallback_columns names sibling columns tried in order when the source
    cell is empty (e.g. an event's start_date standing in for publication_date).
    """
    if not value:
        value = next(
            (v for col in args.get("fallback_columns", []) if (v := row.get(col, "").strip())),
            "",
        )
        if not value:
            return None
    season_column = args.get("season_column")
    season = row.get(season_column, "") if season_column else None
    style = args.get("style", "edtf-season")
    try:
        return edtf_module.to_edtf(value, season=season, style=style)
    except ValueError:
        return value  # left as-is for the wrangler's edtf-date rule to flag


_URL_RE = re.compile(r"^https?://\S+$")
_PMID_RE = re.compile(r"^pmid:?\s*(\d+)$", re.IGNORECASE)
_FIRST_URL_RE = re.compile(r'https?://[^\s"<>]+', re.IGNORECASE)
_BARE_WWW_RE = re.compile(r"^www\.[\w.-]+\.[a-z]{2,}(?:/\S*)?$", re.IGNORECASE)
_INVISIBLE = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060"))


def _find_url(value: str) -> str | None:
    """The first web link in a messy cell, repairing the common typing slips."""
    text = value.translate(_INVISIBLE).strip()
    if text.lower().startswith("ttps://"):
        text = "h" + text
    if _BARE_WWW_RE.match(text):
        return "http://" + text
    match = _FIRST_URL_RE.search(text)
    return match.group().rstrip(".,;") if match else None


@transform("identifier")
def identifier(value: str, row: dict[str, str], args: dict) -> object | None:
    """Value → {"identifier": ..., "scheme": args["scheme"]}.

    args.normalize = "doi": the cell is meant to hold a DOI, which is reduced
    to its bare form. A cell with no readable DOI is not passed off as one: a
    PubMed id or a plain link is kept as a url identifier, anything else is
    omitted.
    args.scheme = "url": only real http(s) links are kept. With
    args.doi_references a link to a DOI resolver (or a "doi:" label) yields a
    doi identifier instead; with args.find_url the first link in a messy cell
    is recovered.
    """
    if "split" in args:
        value = value.split(args["split"])[0].strip()
        if not value:
            return None
    if args.get("normalize") == "doi":
        doi = extract_doi(value)
        if doi:
            return {"identifier": doi, "scheme": args["scheme"]}
        pmid = _PMID_RE.match(value)
        if pmid:
            return {
                "identifier": f"https://pubmed.ncbi.nlm.nih.gov/{pmid.group(1)}/",
                "scheme": "url",
            }
        if _URL_RE.match(value) and not is_resolver_address(value):
            return {"identifier": value, "scheme": "url"}
        return None
    if args.get("scheme") == "url":
        if args.get("doi_references"):
            doi = doi_reference(value)
            if doi:
                return {"identifier": doi, "scheme": "doi"}
            if is_resolver_address(value):
                return None  # a DOI link whose DOI cannot be read leads nowhere
        if args.get("find_url"):
            value = _find_url(value) or ""
        if not _URL_RE.match(value):
            return None
    return {"identifier": value, "scheme": args["scheme"]}


@transform("split")
def split(value: str, row: dict[str, str], args: dict) -> object | None:
    """Delimited string → list of stripped non-empty items (or re-joined string).

    args.also_columns merges values from sibling columns into the list.
    """
    sep = args.get("sep", ",")
    raw_parts = [value] + [row.get(col, "") for col in args.get("also_columns", [])]
    items = [item.strip() for part in raw_parts for item in part.split(sep)]
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


@transform("constant_if_present")
def constant_if_present(value: str, row: dict[str, str], args: dict) -> object | None:
    """Non-empty source → a fixed value from the profile (e.g. rights id 'arr')."""
    return copy.deepcopy(args["value"])


@transform("related_identifier")
def related_identifier(value: str, row: dict[str, str], args: dict) -> object | None:
    """Value → related_identifiers entry; url-scheme values must be real URLs."""
    if args.get("scheme") == "url" and not re.match(r"^https?://\S+$", value):
        return None
    return [
        {
            "identifier": value,
            "scheme": args["scheme"],
            "relation_type": {"id": args["relation"]},
        }
    ]


@transform("prefixed_tag")
def prefixed_tag(value: str, row: dict[str, str], args: dict) -> object | None:
    """Value → a single namespaced user-defined tag like 'bu_type: ...'."""
    return [f"{args['prefix']}: {value}"]


@transform("author_institution", accepts_empty=True)
def author_institution(value: str, row: dict[str, str], args: dict) -> object | None:
    """First non-empty {prefix}N_institution column in the row (thesis university)."""
    prefix = args.get("prefix", "author")
    for n in range(1, args.get("max", 32) + 1):
        institution = row.get(f"{prefix}{n}_institution", "").strip()
        if institution:
            return institution
    return args.get("default")


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


def publisher_evidence(row: dict[str, str], args: dict) -> PublisherMatch | None:
    """What the row's own columns say about who published it."""
    statements = [
        strip_html(row.get(column, ""), row, {}) or ""
        for column in args.get("statement_columns", [])
    ]
    links = [row.get(column, "") for column in args.get("link_columns", [])]
    doi_cells = [row.get(column, "") for column in args.get("doi_columns", [])] + links
    dois = [doi for cell in doi_cells if (doi := extract_doi(cell))]
    return find_publisher(statements, dois, links)


@transform("publisher", accepts_empty=True, derives=True)
def publisher(value: str, row: dict[str, str], args: dict) -> object | None:
    """The row's publisher: as given, or else inferred from the row's traces.

    args.statement_columns / doi_columns / link_columns name the columns to
    search for a copyright statement naming the publisher, a DOI carrying its
    prefix and a link to its platform (in that order of trust).
    """
    if value:
        return value
    match = publisher_evidence(row, args)
    return match.name if match else None


# words that only a rights statement uses, and words it shares with ordinary
# prose (which therefore only count in a short text)
_RIGHTS_WORDS = re.compile(
    r"copyright|©|ⓒ|\(c\)\s*(?:19|20)\d\d|licen[cs]e|permission|all rights reserved|"
    r"creative commons|\bcc[ -]by\b|\bcc0\b|public domain|open access|fair use|personal use",
    re.IGNORECASE,
)
_PUBLISHING_WORDS = re.compile(
    r"\bpublished\b|\bpublication\b|\bpublisher|\bversion\b|\bmanuscript\b|"
    r"\bpre-?print\b|\bpost-?print\b|\baccepted\b|\bembargo|\breprint|\bdeposit|"
    r"available (?:online )?at\b|first appeared|\bpeer[- ]review|\brights\b",
    re.IGNORECASE,
)
_STATEMENT_LENGTH = 400


def reads_as_rights_statement(text: str) -> bool:
    """True when `text` is the kind of thing a copyright field should hold:
    a copyright line, a licence, a permission or version note — as opposed to
    an abstract, a journal title or a stray remark."""
    if _RIGHTS_WORDS.search(text):
        return True
    return len(text) <= _STATEMENT_LENGTH and bool(_PUBLISHING_WORDS.search(text))


@transform("rights_statement")
def rights_statement(value: str, row: dict[str, str], args: dict) -> object | None:
    """Copyright/rights text with HTML removed — kept only if it reads as one."""
    text = strip_html(value, row, {})
    return text if text and reads_as_rights_statement(text) else None


@transform("misplaced_description", opportunistic=True)
def misplaced_description(value: str, row: dict[str, str], args: dict) -> object | None:
    """Descriptive prose typed into a rights column, rescued as a description.

    Yields the text only when it does not read as a rights statement, is
    long enough to be prose (args.min_length, default 80 characters) and none
    of args.unless_columns (the row's real abstract) has content.
    """
    text = strip_html(value, row, {})
    if not text or reads_as_rights_statement(text):
        return None
    if len(text) < args.get("min_length", 80):
        return None
    if any(row.get(column, "").strip() for column in args.get("unless_columns", [])):
        return None
    return text
