"""Read .xls, .xlsx and .csv exports into normalized tables.

Every cell value is normalized to a string: Excel date serials become ISO
dates, integral floats lose their trailing ".0", empty cells become "".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Table:
    """One sheet: a name, ordered column headers, and rows as column→value dicts."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class Workbook:
    """An ordered collection of tables read from one input file."""

    tables: tuple[Table, ...]


def read_workbook(path: str | Path) -> Workbook:
    """Read a .xls, .xlsx or .csv file into a Workbook of normalized tables."""
    raise NotImplementedError
