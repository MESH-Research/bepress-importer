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
)
from bepress_importer.profiles import Defaults, Profile, SheetProfile
from bepress_importer.readers import Table, Workbook
from bepress_importer.transforms import apply_transform


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


def convert_workbook(workbook: Workbook, profile: Profile, as_of: str) -> ConversionResult:
    """Convert every profile-matched sheet to a per-collection list of KC Works records.

    as_of: ISO date used for embargo-activity decisions; an explicit input so
    output is reproducible.
    """
    result = ConversionResult()
    for table in workbook.tables:
        sheet_profile = profile.match_sheet(table.name)
        if sheet_profile is None:
            result.unmatched_sheets.append(table.name)
            continue
        slug = _collection_slug(table, sheet_profile)
        table, filter_doc = _apply_row_filter(table, sheet_profile, profile.defaults)
        records = _convert_sheet(
            table, sheet_profile, profile.defaults, as_of, result.issues,
            slug, result.value_changes,
        )
        result.collections.setdefault(slug, []).extend(records)
        result.collections[slug].sort(key=lambda r: _sort_key(_record_id(r)))
        doc = conversion_log.describe_sheet(table, sheet_profile, profile.defaults, slug)
        if filter_doc:
            doc["row_filter"] = filter_doc
        result.sheet_docs.append(doc)
    return result


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


def _describe_change(
    transform: str, args: dict, raw: str, value: object, row: dict[str, str], as_of: str
) -> str:
    """Human explanation for why a transformed value differs from its source."""
    if transform == "edtf_date":
        season = row.get(args.get("season_column", ""), "").strip()
        if isinstance(value, str) and season and "-2" in value[4:]:
            return f"Bepress year-placeholder date refined to EDTF season using {season!r}"
        if isinstance(value, str) and len(value) == 4:
            return "Bepress placeholder date (1 January) reduced to the year alone"
        return "date normalized to EDTF"
    if transform == "identifier":
        scheme = args.get("scheme", "identifier")
        if args.get("normalize") == "doi" and isinstance(value, dict) and value.get(
            "identifier"
        ) != raw:
            return f"DOI normalized to bare form and recorded as a {scheme} identifier"
        return f"recorded as a {scheme} identifier"
    if transform == "split":
        if "join" in args:
            return f"list separated by {args.get('sep', ',')!r} rejoined with {args['join']!r}"
        return f"split into separate items on {args.get('sep', ',')!r}"
    if transform == "strip_html":
        return "HTML markup removed"
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
                if raw and value != raw:
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
        if sheet.contributors:
            contributors = build_contributors(row, sheet.contributors)
            if contributors:
                record["metadata"]["contributors"] = contributors
        if sheet.journal:
            journal = build_journal(row, sheet.journal)
            if journal:
                set_pointer(record, "/custom_fields/journal:journal", journal)
        if sheet.imprint:
            imprint = build_imprint(row, sheet.imprint)
            if imprint:
                set_pointer(record, "/custom_fields/imprint:imprint", imprint)
        for pointer, constant in sheet.constants.items():
            set_pointer(record, pointer, constant)

        records.append(record)
    return records


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
