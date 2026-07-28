"""EDTF (Extended Date/Time Format) emission and validation.

Covers exactly the subset this importer emits: year (2015), year-month
(2015-04), full date (2015-04-01) and EDTF level-1 seasons (2015-21..24).

Bepress convention: a publication_date of YYYY-01-01 is a year-only
placeholder, optionally refined by a separate season column.
"""

from __future__ import annotations

import datetime
import re

SEASONS = {"spring": "21", "summer": "22", "autumn": "23", "fall": "23", "winter": "24"}


_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def to_edtf(date_str: str, season: str | None = None, style: str = "edtf-season") -> str:
    """Normalize an ISO-ish date string (plus optional season) to EDTF.

    Raises ValueError for input that cannot be interpreted.
    """
    value = date_str.strip().split(" ")[0]  # drop any time component
    match = _DATE_RE.match(value)
    if not match:
        raise ValueError(f"Cannot interpret {date_str!r} as a date")
    year, month, day = match.groups()

    if month == "01" and day == "01":
        # Bepress placeholder: year-only, possibly refined by a season column
        season_code = SEASONS.get((season or "").strip().lower())
        if season_code and style == "edtf-season":
            return f"{year}-{season_code}"
        return year

    result = year
    if month:
        result += f"-{month}"
    if day:
        result += f"-{day}"
    if not is_valid(result):
        raise ValueError(f"{date_str!r} is not a real calendar date")
    return result


def is_valid(value: str) -> bool:
    """True if value is valid EDTF in the emitted subset (incl. calendar checks)."""
    match = _DATE_RE.match(value)
    if not match:
        return False
    year, month, day = match.groups()
    if month is None:
        return day is None
    month_num = int(month)
    if day is None:
        # a bare month, or an EDTF level-1 season code
        return 1 <= month_num <= 12 or 21 <= month_num <= 24
    try:
        datetime.date(int(year), month_num, int(day))
    except ValueError:
        return False
    return True
