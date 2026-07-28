"""EDTF (Extended Date/Time Format) emission and validation.

Covers exactly the subset this importer emits: year (2015), year-month
(2015-04), full date (2015-04-01) and EDTF level-1 seasons (2015-21..24).

Bepress convention: a publication_date of YYYY-01-01 is a year-only
placeholder, optionally refined by a separate season column.
"""

from __future__ import annotations

SEASONS = {"spring": "21", "summer": "22", "autumn": "23", "fall": "23", "winter": "24"}


def to_edtf(date_str: str, season: str | None = None, style: str = "edtf-season") -> str:
    """Normalize an ISO-ish date string (plus optional season) to EDTF.

    Raises ValueError for input that cannot be interpreted.
    """
    raise NotImplementedError


def is_valid(value: str) -> bool:
    """True if value is valid EDTF in the emitted subset (incl. calendar checks)."""
    raise NotImplementedError
