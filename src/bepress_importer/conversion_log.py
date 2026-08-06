"""Conversion provenance: what was mapped where, why, and what changed.

Produces the client-facing conversion log in two forms: a precise JSON payload
and a human-readable plaintext narrative. Both are deterministic (no
timestamps) so re-running a conversion yields byte-identical logs.
"""

from __future__ import annotations

import json

from bepress_importer.profiles import Defaults, SheetProfile
from bepress_importer.readers import Table

AUTHOR_PARTS = ("fname", "mname", "lname", "suffix", "email", "institution", "is_corporate")


def mapped_columns(sheet: SheetProfile, defaults: Defaults) -> set[str]:
    """Every source column consumed by a sheet's mapping rules."""
    mapped = {f.source for f in sheet.fields}
    for f in sheet.fields:
        if "season_column" in f.args:
            mapped.add(f.args["season_column"])
    if sheet.resource_type and sheet.resource_type.column:
        mapped.add(sheet.resource_type.column)
    mapped |= {defaults.record_id_column, "issue"}
    if defaults.url_column:
        mapped.add(defaults.url_column)
    for n in range(1, defaults.authors.max + 1):
        for part in AUTHOR_PARTS:
            mapped.add(f"{defaults.authors.prefix}{n}_{part}")
    if sheet.contributors:
        for n in range(1, sheet.contributors.max + 1):
            mapped.add(f"{sheet.contributors.prefix}{n}")
    for composite in (sheet.journal, sheet.imprint):
        if composite:
            for column in vars(composite).values():
                if column:
                    mapped.add(column)
    return mapped


def column_is_empty(table: Table, column: str) -> bool:
    return all(not row.get(column, "") for row in table.rows)


_TRANSFORM_NOTES = {
    "edtf_date": "date normalized to EDTF",
    "identifier": "wrapped as a work identifier",
    "split": "delimited text split into items",
    "strip_html": "HTML markup removed, entities unescaped",
    "additional_description": "HTML removed; wrapped as an additional description",
    "url": "kept only if a valid http(s) URL",
    "embargo": "emitted as an access embargo only if still active",
    "language_list": "parsed into a list of language codes",
    "license_url": "license URL mapped to a KC Works rights id",
    "constant_if_present": "presence of a value maps to a fixed entry",
    "related_identifier": "linked as a related identifier",
    "prefixed_tag": "imported as a namespaced user-defined tag",
    "author_institution": "first non-empty author institution column",
}


def describe_sheet(
    table: Table, sheet: SheetProfile, defaults: Defaults, collection: str
) -> dict:
    """A client-inspectable description of every mapping rule applied to a sheet."""
    mappings = []
    for f in sheet.fields:
        entry: dict = {"source": f.source, "target": f.target}
        if f.transform:
            entry["transform"] = f.transform
            entry["how"] = _TRANSFORM_NOTES.get(f.transform, f"transform {f.transform!r}")
            if f.args:
                entry["args"] = dict(f.args)
        else:
            entry["how"] = "copied unchanged"
        if f.required:
            entry["required"] = True
        mappings.append(entry)

    doc: dict = {
        "sheet": table.name,
        "collection": collection,
        "records": len(table.rows),
        "record_id": {
            "column": defaults.record_id_column,
            "target": "metadata.identifiers (scheme import-recid)",
            "why": "stable per-record key: correlates each KC Works record back "
                   "to its Bepress source row, and prevents duplicate imports",
        },
        "mappings": mappings,
    }
    if defaults.url_column:
        doc["source_url"] = {
            "column": defaults.url_column,
            "target": "metadata.identifiers (scheme url)",
            "why": "preserves the canonical Bepress landing page",
        }
    if sheet.resource_type:
        rt = sheet.resource_type
        doc["resource_type"] = (
            {"constant": rt.constant}
            if rt.constant
            else {"column": rt.column, "map": dict(rt.map), "default": rt.default}
        )

    builders: dict = {}
    prefix = defaults.authors.prefix
    if any(c.startswith(f"{prefix}1_") for c in table.columns):
        builders["creators"] = (
            f"{prefix}1..{prefix}{defaults.authors.max} name/institution columns → "
            "metadata.creators (personal names assembled as 'Family, Given'; "
            "is_corporate rows become organizational creators)"
        )
    if sheet.contributors:
        builders["contributors"] = (
            f"{sheet.contributors.prefix}1..{sheet.contributors.prefix}"
            f"{sheet.contributors.max} → metadata.contributors "
            f"(role {sheet.contributors.role})"
        )
    if sheet.journal:
        builders["journal"] = {
            k: v for k, v in vars(sheet.journal).items() if v
        } | {"target": "custom_fields.journal:journal"}
    if sheet.imprint:
        builders["imprint"] = {
            k: v for k, v in vars(sheet.imprint).items() if v
        } | {"target": "custom_fields.imprint:imprint"}
    if builders:
        doc["builders"] = builders
    if sheet.constants:
        doc["constants"] = dict(sheet.constants)

    mapped = mapped_columns(sheet, defaults)
    doc["unmapped_columns"] = [
        c for c in table.columns if c not in mapped and not column_is_empty(table, c)
    ]
    doc["empty_columns"] = [c for c in table.columns if column_is_empty(table, c)]
    return doc


def build_payload(
    input_name: str,
    profile_name: str,
    as_of: str,
    sheet_docs: list[dict],
    value_changes: list,
) -> dict:
    return {
        "input": input_name,
        "profile": profile_name,
        "as_of": as_of,
        "sheets": sheet_docs,
        "value_changes": [vars(change) for change in value_changes],
    }


def _render_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))


def render_text(payload: dict) -> str:
    """The human-readable conversion log."""
    lines = [
        "Conversion log",
        "==============",
        f"input:   {payload['input']}",
        f"profile: {payload['profile']}",
        f"embargo decisions made as of: {payload['as_of']}",
        "",
        "This log records every mapping rule applied during conversion and every",
        "place a value was altered or omitted, so the transformation from the",
        "Bepress export to KC Works records is fully inspectable.",
    ]

    for doc in payload["sheets"]:
        lines += [
            "",
            (
                f"=== Sheet {doc['sheet']!r} → collection {doc['collection']!r} "
                f"({doc['records']} records) ==="
            ),
            "",
            "Record identity:",
            f"  {doc['record_id']['column']} → {doc['record_id']['target']}",
            f"    why: {doc['record_id']['why']}",
        ]
        if "source_url" in doc:
            lines += [
                f"  {doc['source_url']['column']} → {doc['source_url']['target']}",
                f"    why: {doc['source_url']['why']}",
            ]
        if "row_filter" in doc:
            rf = doc["row_filter"]
            lines += [
                "Row filter:",
                (
                    f"  only rows with {rf['column']} in {rf['keep']} were imported; "
                    f"{rf['excluded']} row(s) excluded"
                ),
            ]
            if rf["excluded_ids"]:
                lines.append(
                    "  excluded record ids: " + ", ".join(rf["excluded_ids"])
                )
        if "resource_type" in doc:
            rt = doc["resource_type"]
            lines.append("Resource type:")
            if "constant" in rt:
                lines.append(f"  every record → {rt['constant']}")
            else:
                for raw, target in rt["map"].items():
                    lines.append(f"  {rt['column']} = {raw!r} → {target}")
                if rt.get("default"):
                    lines.append(f"  (blank {rt['column']}) → {rt['default']} (default)")
        lines.append("Field mappings:")
        for m in doc["mappings"]:
            flags = " [required]" if m.get("required") else ""
            lines.append(f"  {m['source']} → {m['target']}{flags}")
            how = m["how"]
            if m.get("args"):
                how += f" (settings: {json.dumps(m['args'], sort_keys=True)})"
            lines.append(f"    how: {how}")
        for name, description in doc.get("builders", {}).items():
            lines.append(f"Built {name}:")
            if isinstance(description, dict):
                target = description.pop("target", "")
                cols = ", ".join(f"{k} ← {v}" for k, v in description.items())
                lines.append(f"  {cols} → {target}")
            else:
                lines.append(f"  {description}")
        for pointer, value in doc.get("constants", {}).items():
            lines.append(f"Constant: {pointer} = {value!r} on every record")
        if doc["unmapped_columns"]:
            lines += [
                "Columns NOT imported (contain data; deliberately unmapped):",
                "  " + ", ".join(doc["unmapped_columns"]),
            ]
        if doc["empty_columns"]:
            lines.append(
                f"Columns empty in this export (nothing to import): "
                f"{len(doc['empty_columns'])}"
            )

    changes = payload["value_changes"]
    lines += [
        "",
        f"=== Per-record value changes ({len(changes)}) ===",
        "",
        "Every entry below is a value that left the spreadsheet in a different",
        "form than it arrived (or was omitted), and why.",
        "",
    ]
    for c in changes:
        rendered_raw = _render_value(c["raw"])
        if c["action"] == "dropped":
            lines.append(
                f"[{c['collection']} {c['record_id']}] {c['source']}: "
                f"{rendered_raw} omitted — {c['reason']}"
            )
        else:
            lines.append(
                f"[{c['collection']} {c['record_id']}] {c['source']}: "
                f"{rendered_raw} -> {_render_value(c['result'])} — {c['reason']}"
            )
    return "\n".join(lines) + "\n"
