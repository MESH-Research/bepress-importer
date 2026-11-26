"""Deterministic conversion: normalized workbook + profile → KC Works records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bepress_importer import conversion_log
from bepress_importer.builders import (
    build_contributors,
    build_creators,
    build_imprint,
    build_journal,
    creator_positions,
    implausible_journal_values,
)
from bepress_importer.doi import is_resolver_address
from bepress_importer.pids import doi_claim, keep_doi_as_link, promote_doi_pid
from bepress_importer.profiles import Defaults, DoiPid, Profile, SheetProfile
from bepress_importer.readers import Table, Workbook
from bepress_importer.ror import RorResolver
from bepress_importer.transforms import (
    apply_transform,
    derives_value,
    is_opportunistic,
    publisher_evidence,
)


@dataclass(frozen=True)
class Issue:
    """A conversion problem worth reporting; the record is still emitted."""

    sheet: str
    record_id: str
    message: str


@dataclass(frozen=True)
class ValueChange:
    """One value that left the spreadsheet altered (or omitted), and why."""

    collection: str
    record_id: str
    source: str
    target: str
    raw: str
    result: object
    action: str  # "transformed" | "dropped"
    reason: str


@dataclass
class ConversionResult:
    collections: dict[str, list[dict]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    unmatched_sheets: list[str] = field(default_factory=list)
    value_changes: list[ValueChange] = field(default_factory=list)
    sheet_docs: list[dict] = field(default_factory=list)


def set_pointer(obj: dict, pointer: str, value: object) -> None:
    """Set value at a JSON pointer, creating intermediate dicts.

    Lists at the target are extended/appended; dicts are shallow-merged.
    """
    parts = pointer.lstrip("/").split("/")
    node = obj
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    last = parts[-1]
    existing = node.get(last)
    if isinstance(existing, list):
        if isinstance(value, list):
            existing.extend(value)
        else:
            existing.append(value)
    elif isinstance(existing, dict) and isinstance(value, dict):
        existing.update(value)
    else:
        node[last] = value


def get_pointer(obj: dict, pointer: str) -> object | None:
    node: object = obj
    for part in pointer.lstrip("/").split("/"):
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(node, dict):
            if part not in node:
                return None
            node = node[part]
        else:
            return None
    return node


def _slugify(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", name.lower())).strip("_")


def _sort_key(record_id: str) -> tuple:
    return (0, int(record_id)) if record_id.isdigit() else (1, record_id)


def convert_workbook(
    workbook: Workbook, profile: Profile, as_of: str, ror: RorResolver | None = None
) -> ConversionResult:
    """Convert every profile-matched sheet to a per-collection list of KC Works records.

    as_of: ISO date used for embargo-activity decisions; an explicit input so
    output is reproducible.
    ror: resolves affiliation text to ROR ids when the profile asks for them;
    left out, only the ids the profile itself fixes are used (no lookups).
    """
    result = ConversionResult()
    origin: dict[int, str] = {}  # record → the sheet it came from, for late issues
    if profile.defaults.affiliations is None:
        ror = None
    elif ror is None:
        ror = offline_ror_resolver(profile.defaults)
    for table in workbook.tables:
        blocks = profile.match_sheets(table.name, columns=table.columns)
        if not blocks:
            result.unmatched_sheets.append(table.name)
            continue
        for block, block_table in _route_rows(table, blocks, profile.defaults, result.issues):
            slug = _collection_slug(block_table, block)
            block_table, filter_doc = _apply_row_filter(block_table, block, profile.defaults)
            records = _convert_sheet(
                block_table, block, profile.defaults, as_of, result.issues,
                slug, result.value_changes, ror=ror,
            )
            origin.update((id(record), table.name) for record in records)
            result.collections.setdefault(slug, []).extend(records)
            result.collections[slug].sort(key=lambda r: _sort_key(_record_id(r)))
            doc = conversion_log.describe_sheet(
                block_table, block, profile.defaults, slug
            )
            if filter_doc:
                doc["row_filter"] = filter_doc
            result.sheet_docs.append(doc)
    if profile.defaults.doi_pid is not None:
        _register_doi_pids(result, profile.defaults.doi_pid, origin)
    return result


def offline_ror_resolver(defaults: Defaults) -> RorResolver | None:
    """A resolver for the ROR ids the profile itself fixes: no cache, no lookups."""
    if defaults.affiliations is None:
        return None
    return RorResolver(
        known=defaults.affiliations.ror_ids, min_score=defaults.affiliations.min_score
    )


def _use_ror_ids(
    creators: list[dict], positions: list[int], prefix: str, ror: RorResolver,
    collection: str, record_id: str,
) -> list[ValueChange]:
    """Replace each affiliation the resolver is sure of by its ROR id, in
    place, and return one logged change per replacement."""
    changes = []
    for index, (creator, n) in enumerate(zip(creators, positions, strict=True)):
        for slot, affiliation in enumerate(creator.get("affiliations", [])):
            text = affiliation.get("name", "")
            match = ror.resolve(text)
            if match is None:
                continue
            creator["affiliations"][slot] = {"id": match.ror_id}
            if match.evidence == "profile":
                reason = (
                    f"affiliation replaced by its ROR id — {match.name or text} is fixed "
                    f"as {match.ror_id} in the profile"
                )
            else:
                reason = (
                    f"affiliation replaced by its ROR id — matched to "
                    f"{match.name or match.ror_id} by the ROR API (its chosen match, "
                    f"score {match.score:g})"
                )
            changes.append(
                ValueChange(
                    collection=collection,
                    record_id=record_id,
                    source=f"{prefix}{n}_institution",
                    target=f"/metadata/creators/{index}/affiliations/{slot}",
                    raw=text,
                    result={"id": match.ror_id},
                    action="transformed",
                    reason=reason,
                )
            )
    return changes


def _register_doi_pids(
    result: ConversionResult, settings: DoiPid, origin: dict[int, str]
) -> None:
    """Move each record's existing DOI into its `pids` block.

    A DOI identifies one work, and KC Works matches incoming records on it —
    so a DOI that several records in this conversion claim is registered for
    none of them (it stays as a link on each) and every claimant is reported.
    """
    claimants: dict[str, list[str]] = {}
    for records in result.collections.values():
        for record in records:
            claim = doi_claim(record)
            if claim:
                claimants.setdefault(claim.lower(), []).append(_record_id(record))

    for collection, records in result.collections.items():
        for record in records:
            claim = doi_claim(record)
            if claim is None:
                continue
            record_id = _record_id(record)
            sheet = origin.get(id(record), collection)
            others = [other for other in claimants[claim.lower()] if other != record_id]
            if others:
                outcome = keep_doi_as_link(record)
                target = "/metadata/identifiers"
                value: object = {"identifier": f"https://doi.org/{claim}", "scheme": "url"}
                reason = (
                    f"DOI also given for record(s) {', '.join(others)} — one DOI cannot "
                    "identify several records, so it is kept as a link and not registered"
                )
                result.issues.append(
                    Issue(
                        sheet,
                        record_id,
                        f"DOI {claim} is also given for record(s) {', '.join(others)} — "
                        "not registered as this record's DOI (kept as a link); "
                        "check which record it belongs to",
                    )
                )
            else:
                outcome = promote_doi_pid(
                    record,
                    provider=settings.provider,
                    keep_identifiers=settings.keep_identifiers,
                )
                target = "/pids/doi"
                value = dict(record["pids"]["doi"])
                reason = (
                    "existing DOI registered as the record's own "
                    f"({settings.provider}) DOI, in bare form"
                )
                for other_doi in outcome.conflicting:
                    result.issues.append(
                        Issue(
                            sheet,
                            record_id,
                            f"two different DOIs given: {claim} is registered as the "
                            f"record's DOI, {other_doi} is kept as a link",
                        )
                    )
            result.value_changes.append(
                ValueChange(
                    collection=collection,
                    record_id=record_id,
                    source="DOI",
                    target=target,
                    raw="; ".join(
                        f"{entry.get('scheme')}: {entry.get('identifier')}"
                        for entry in outcome.consumed
                    ),
                    result=value,
                    action="transformed",
                    reason=reason,
                )
            )


def _route_rows(
    table: Table, blocks: tuple[SheetProfile, ...], defaults: Defaults, issues: list[Issue]
) -> list[tuple[SheetProfile, Table]]:
    """Send each row to the first block whose `select` matches it.

    A block without a select is the catch-all. Blocks that receive no rows are
    skipped; rows no block selects are reported as issues (they would
    otherwise vanish silently).
    """
    if len(blocks) == 1 and blocks[0].select is None:
        return [(blocks[0], table)]
    routed: dict[int, list[dict]] = {i: [] for i in range(len(blocks))}
    for row in table.rows:
        for i, block in enumerate(blocks):
            select = block.select
            if select is None or row.get(select.column, "").strip() in select.values:
                routed[i].append(row)
                break
        else:
            record_id = row.get(defaults.record_id_column, "").strip() or "?"
            selectors = ", ".join(
                sorted({b.select.column for b in blocks if b.select})
            )
            issues.append(
                Issue(
                    table.name,
                    record_id,
                    f"row not covered by any profile section (no select on "
                    f"{selectors} matches it)",
                )
            )
    return [
        (blocks[i], Table(name=table.name, columns=table.columns, rows=tuple(rows)))
        for i, rows in routed.items()
        if rows
    ]


def _apply_row_filter(
    table: Table, sheet: SheetProfile, defaults: Defaults
) -> tuple[Table, dict | None]:
    """Drop rows excluded by the sheet's filter, documenting who was excluded."""
    if sheet.filter is None:
        return table, None
    kept, excluded_ids = [], []
    for row in table.rows:
        if row.get(sheet.filter.column, "") in sheet.filter.keep:
            kept.append(row)
        else:
            excluded_ids.append(row.get(defaults.record_id_column, "").strip() or "?")
    filter_doc = {
        "column": sheet.filter.column,
        "keep": list(sheet.filter.keep),
        "excluded": len(excluded_ids),
        "excluded_ids": excluded_ids,
    }
    return Table(name=table.name, columns=table.columns, rows=tuple(kept)), filter_doc


def _record_id(record: dict) -> str:
    for ident in record.get("metadata", {}).get("identifiers", []):
        if ident.get("scheme") == "import-recid":
            return ident["identifier"]
    return ""


def _collection_slug(table: Table, sheet_profile: SheetProfile) -> str:
    if sheet_profile.collection:
        return sheet_profile.collection
    if "issue" in table.columns:
        for row in table.rows:
            if row.get("issue"):
                return row["issue"]
    return _slugify(table.name)


def _needs_review(
    source: str, transform: str, args: dict, raw: str, value: object
) -> str | None:
    """A message for the issue list when a value was left out for a reason a
    person should look at (as opposed to routine normalization)."""
    if not raw or value is not None:
        return None
    if transform == "identifier" and args.get("normalize") == "doi":
        return f"{source} value {raw!r} is not a readable DOI — omitted"
    if transform == "rights_statement":
        excerpt = raw if len(raw) <= 60 else raw[:60] + "…"
        return (
            f"{source} text does not read as a copyright or rights statement — "
            f"not imported as copyright: {excerpt!r}"
        )
    return None


def _describe_change(
    transform: str, args: dict, raw: str, value: object, row: dict[str, str], as_of: str
) -> str:
    """Human explanation for why a transformed value differs from its source."""
    if transform == "edtf_date":
        if not raw:
            used = next(
                (c for c in args.get("fallback_columns", []) if row.get(c, "").strip()), "?"
            )
            return f"no date in this column — taken from {used} instead"
        season = row.get(args.get("season_column", ""), "").strip()
        if isinstance(value, str) and season and "-2" in value[4:]:
            return f"Bepress year-placeholder date refined to EDTF season using {season!r}"
        if isinstance(value, str) and len(value) == 4:
            return "Bepress placeholder date (1 January) reduced to the year alone"
        return "date normalized to EDTF"
    if transform == "identifier":
        scheme = args.get("scheme", "identifier")
        result_scheme = value.get("scheme") if isinstance(value, dict) else None
        if args.get("normalize") == "doi":
            if value is None:
                return "no readable DOI in this cell — value omitted"
            if result_scheme == "url":
                if value.get("identifier") != raw:
                    return "a PubMed id, not a DOI — linked as a PubMed URL"
                return "a link, not a DOI — kept as a url identifier"
            if value.get("identifier") != raw:
                return f"DOI normalized to bare form and recorded as a {scheme} identifier"
        if scheme == "url":
            if value is None:
                if args.get("doi_references") and is_resolver_address(raw):
                    return "DOI link whose DOI cannot be read — value omitted"
                return "not a valid http(s) URL — value omitted"
            if result_scheme == "doi":
                return "link to a DOI — recorded as the bare DOI"
            if value.get("identifier") != raw:
                return "first web link recovered from the cell and recorded as a url identifier"
        return f"recorded as a {scheme} identifier"
    if transform == "split":
        if "join" in args:
            return f"list separated by {args.get('sep', ',')!r} rejoined with {args['join']!r}"
        return f"split into separate items on {args.get('sep', ',')!r}"
    if transform == "strip_html":
        return "HTML markup removed"
    if transform == "rights_statement":
        if value is None:
            return (
                "does not read as a copyright or rights statement — kept out of the "
                "copyright field"
            )
        return "HTML markup removed"
    if transform == "misplaced_description":
        return (
            "descriptive text found in a rights column, and the record has no abstract "
            "of its own — used as the description"
        )
    if transform == "additional_description":
        return "HTML removed; stored as an additional description"
    if transform == "url":
        return f"not a valid http(s) URL — value omitted (as of {as_of})" \
            if value is None else "URL kept"
    if transform == "embargo":
        if value is None:
            return f"embargo date has already passed as of {as_of} — no embargo carried over"
        return "future embargo converted to a KC Works access embargo"
    if transform == "language_list":
        return "parsed into standard language-code entries"
    if transform == "constant_if_present":
        return "presence of source text mapped to a fixed entry (see profile)"
    if transform == "related_identifier":
        if value is None:
            return "not a valid http(s) URL — value omitted"
        return f"linked as a related identifier ({args.get('relation', 'related')})"
    if transform == "prefixed_tag":
        return f"imported as a namespaced tag ({args.get('prefix', '')})"
    if transform == "author_institution":
        return "taken from the first non-empty author institution column"
    if transform == "doi_mention":
        return "a DOI was written into this cell — recorded as the work's DOI"
    if transform == "publisher":
        match = publisher_evidence(row, args)
        if match is None and not raw:
            return (
                "no publisher given in the export and nothing in the row identifies "
                "one — the profile's fallback publisher is used"
            )
        if match is None:
            return "publisher as given in the export"
        clue = {
            "statement": f"the copyright statement names {match.detail!r}",
            "doi": f"the DOI prefix {match.detail} belongs to this publisher",
            "link": f"the link points at this publisher's site ({match.detail})",
        }[match.evidence]
        return f"no publisher given in the export — inferred: {clue}"
    if transform == "license_url":
        if value is None:
            return "license URL not recognized — value omitted"
        return "Creative Commons URL mapped to the matching KC Works rights id"
    return f"transform {transform!r} applied"


def _convert_sheet(
    table: Table,
    sheet: SheetProfile,
    defaults: Defaults,
    as_of: str,
    issues: list[Issue],
    collection: str,
    value_changes: list[ValueChange],
    ror: RorResolver | None = None,
) -> list[dict]:
    records = []
    for row in table.rows:
        record_id = row.get(defaults.record_id_column, "").strip()
        record: dict = {"metadata": {"identifiers": []}, "files": {"enabled": defaults.files_enabled}}

        if record_id:
            record["metadata"]["identifiers"].append(
                {"identifier": record_id, "scheme": "import-recid"}
            )
        else:
            issues.append(Issue(table.name, "", f"missing record id ({defaults.record_id_column})"))
        url_value = row.get(defaults.url_column, "").strip() if defaults.url_column else ""
        if url_value:
            record["metadata"]["identifiers"].append({"identifier": url_value, "scheme": "url"})

        _apply_resource_type(record, row, sheet, table.name, record_id, issues)

        for mapping in sheet.fields:
            raw = row.get(mapping.source, "").strip()
            args = dict(mapping.args)
            if mapping.transform == "embargo":
                args.setdefault("as_of", as_of)
            if mapping.transform:
                value = apply_transform(mapping.transform, raw, row, args)
                derived = not raw and value is not None and derives_value(mapping.transform)
                opportunistic = is_opportunistic(mapping.transform)
                passed_over = value is None and opportunistic
                # a value an opportunistic transform does pick up has been
                # re-routed, which is worth recording even if unaltered
                changed = value != raw or (opportunistic and value is not None)
                if (raw or derived) and changed and not passed_over:
                    value_changes.append(
                        ValueChange(
                            collection=collection,
                            record_id=record_id,
                            source=mapping.source,
                            target=mapping.target,
                            raw=raw,
                            result=value,
                            action="dropped" if value is None else "transformed",
                            reason=_describe_change(
                                mapping.transform, args, raw, value, row, as_of
                            ),
                        )
                    )
                concern = _needs_review(mapping.source, mapping.transform, args, raw, value)
                if concern:
                    issues.append(Issue(table.name, record_id, concern))
            else:
                value = raw or None
            if value is not None:
                set_pointer(record, mapping.target, value)
            if mapping.required and not get_pointer(record, mapping.target):
                issues.append(
                    Issue(table.name, record_id, f"required field {mapping.source!r} is missing")
                )

        creators = build_creators(row, defaults.authors)
        if creators:
            record["metadata"]["creators"] = creators
            if ror is not None:
                value_changes.extend(
                    _use_ror_ids(
                        creators, creator_positions(row, defaults.authors),
                        defaults.authors.prefix, ror, collection, record_id,
                    )
                )
        if sheet.contributors:
            contributors = build_contributors(row, sheet.contributors)
            if contributors:
                record["metadata"]["contributors"] = contributors
        if sheet.journal:
            journal = build_journal(row, sheet.journal)
            if journal:
                set_pointer(record, "/custom_fields/journal:journal", journal)
            for column, cell in implausible_journal_values(row, sheet.journal):
                excerpt = cell if len(cell) <= 60 else cell[:60] + "…"
                issues.append(
                    Issue(
                        table.name,
                        record_id,
                        f"{column} value {excerpt!r} is not a volume, issue or page "
                        "reference — omitted",
                    )
                )
                value_changes.append(
                    ValueChange(
                        collection=collection,
                        record_id=record_id,
                        source=column,
                        target="/custom_fields/journal:journal",
                        raw=cell,
                        result=None,
                        action="dropped",
                        reason="not a volume, issue or page reference — value omitted",
                    )
                )
        if sheet.imprint:
            imprint = build_imprint(row, sheet.imprint)
            if imprint:
                set_pointer(record, "/custom_fields/imprint:imprint", imprint)
        for pointer, constant in sheet.constants.items():
            set_pointer(record, pointer, constant)
        record["metadata"]["identifiers"] = _without_repeats(record["metadata"]["identifiers"])

        records.append(record)
    return records


def _without_repeats(identifiers: list[dict]) -> list[dict]:
    """The identifier list with exact repeats removed (the same link given in
    two columns is still one identifier)."""
    unique: list[dict] = []
    for entry in identifiers:
        if entry not in unique:
            unique.append(entry)
    return unique


def _apply_resource_type(
    record: dict,
    row: dict[str, str],
    sheet: SheetProfile,
    sheet_name: str,
    record_id: str,
    issues: list[Issue],
) -> None:
    rt = sheet.resource_type
    if rt is None:
        return
    if rt.constant:
        record["metadata"]["resource_type"] = {"id": rt.constant}
        return
    raw = row.get(rt.column, "").strip()
    mapped = rt.map.get(raw)
    if mapped:
        record["metadata"]["resource_type"] = {"id": mapped}
    elif not raw and rt.default:
        record["metadata"]["resource_type"] = {"id": rt.default}
    elif raw:
        # keep the raw value visible so the wrangler can propose a vocabulary fix
        record["metadata"]["resource_type"] = {"id": raw}
        issues.append(
            Issue(sheet_name, record_id, f"unmapped {rt.column} value {raw!r} kept verbatim")
        )
    else:
        issues.append(Issue(sheet_name, record_id, f"no {rt.column} value and no default"))
