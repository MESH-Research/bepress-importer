"""Dump one record's converted metadata straight from an export.

Converts a single spreadsheet row on the fly (the record may be excluded
from, or broken in, the normal conversion output) and marks required-but-
empty fields with a MISSING sentinel so problems called out in the
conversion report can be inspected in place.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass

import click

from bepress_importer.convert import (
    _collection_slug,
    _convert_sheet,
    get_pointer,
    set_pointer,
)
from bepress_importer.profiles import Profile, SheetProfile
from bepress_importer.readers import Table, Workbook

MISSING = "MISSING"


@dataclass(frozen=True)
class RecordView:
    """One row's conversion outcome: the record, its gaps, and its routing."""

    record: dict | None
    missing: tuple[str, ...]  # JSON pointers of required targets left empty
    sheet: str | None = None
    collection: str | None = None
    excluded: str | None = None  # why the normal conversion would drop the row


def explain_record(
    workbook: Workbook, profile: Profile, record_id: str, as_of: str
) -> RecordView | None:
    """Convert just the row whose record-id column equals `record_id`.

    Returns None when no profile-matched sheet has such a row. The row is
    converted even when a row filter would exclude it (the reason is
    reported in `excluded`), so withdrawn/pending records can be inspected.
    """
    id_column = profile.defaults.record_id_column
    for table in workbook.tables:
        blocks = profile.match_sheets(table.name, columns=table.columns)
        if not blocks:
            continue
        row = next(
            (r for r in table.rows if r.get(id_column, "").strip() == record_id), None
        )
        if row is None:
            continue
        block = _routed_block(row, blocks)
        if block is None:
            selectors = ", ".join(sorted({b.select.column for b in blocks if b.select}))
            return RecordView(
                record=None,
                missing=(),
                sheet=table.name,
                excluded=f"no profile section selects this row "
                         f"(no select on {selectors} matches it)",
            )
        excluded = None
        if block.filter is not None:
            value = row.get(block.filter.column, "")
            if value not in block.filter.keep:
                excluded = (
                    f"the normal conversion excludes this row: its "
                    f"{block.filter.column} is {value!r}, not one of "
                    f"{list(block.filter.keep)}"
                )
        one_row = Table(name=table.name, columns=table.columns, rows=(row,))
        slug = _collection_slug(one_row, block)
        record = _convert_sheet(
            one_row, block, profile.defaults, as_of, issues=[], collection=slug,
            value_changes=[],
        )[0]
        missing = tuple(
            f.target
            for f in block.fields
            if f.required and not get_pointer(record, f.target)
        )
        return RecordView(
            record=record, missing=missing, sheet=table.name, collection=slug,
            excluded=excluded,
        )
    return None


def _routed_block(
    row: dict[str, str], blocks: tuple[SheetProfile, ...]
) -> SheetProfile | None:
    for block in blocks:
        select = block.select
        if select is None or row.get(select.column, "").strip() in select.values:
            return block
    return None


def annotate_missing(record: dict, missing: tuple[str, ...]) -> dict:
    """A deep copy of the record with MISSING placed at each absent pointer."""
    annotated = copy.deepcopy(record)
    for pointer in missing:
        set_pointer(annotated, pointer, MISSING)
    return annotated


def render(record: dict, plain: bool = False) -> str:
    """Serialize for display: pretty JSON with MISSING lines styled red,
    or (plain=True) one line of unstyled JSON."""
    if plain:
        return json.dumps(record, sort_keys=True, ensure_ascii=False)
    text = json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False)
    sentinel = json.dumps(MISSING)
    return "\n".join(
        click.style(line, fg="red") if line.rstrip(",").endswith(sentinel) else line
        for line in text.splitlines()
    )
