"""Behavioural tests for readers: any supported input → normalized string tables."""

from pathlib import Path

import pytest

from bepress_importer.readers import read_workbook

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_COLUMNS = ("title", "publication_date", "context_key", "price", "empty_col", "note")
EXPECTED_ROWS = (
    {
        "title": "First Item",
        "publication_date": "2015-04-01",
        "context_key": "2404130",
        "price": "3.5",
        "empty_col": "",
        "note": "padded",
    },
    {
        "title": 'Second, "quoted"',
        "publication_date": "1998-01-01",
        "context_key": "2404131",
        "price": "12",
        "empty_col": "",
        "note": "unicode: séance—ok",
    },
)


@pytest.mark.parametrize("filename", ["mini.csv", "mini.xls", "mini.xlsx"])
def test_reads_normalized_rows_from_any_format(filename):
    workbook = read_workbook(FIXTURES / filename)
    assert len(workbook.tables) == 1
    table = workbook.tables[0]
    assert table.name == "mini"
    assert table.columns == EXPECTED_COLUMNS
    assert table.rows == EXPECTED_ROWS


def test_xls_and_csv_read_identically():
    assert read_workbook(FIXTURES / "mini.xls") == read_workbook(FIXTURES / "mini.csv")


def test_all_cell_values_are_strings():
    workbook = read_workbook(FIXTURES / "mini.xls")
    for row in workbook.tables[0].rows:
        assert all(isinstance(v, str) for v in row.values())


def test_excel_integer_cells_have_no_decimal_suffix():
    workbook = read_workbook(FIXTURES / "mini.xls")
    assert workbook.tables[0].rows[0]["context_key"] == "2404130"  # not "2404130.0"


def test_excel_date_cells_become_iso_dates():
    workbook = read_workbook(FIXTURES / "mini.xls")
    assert workbook.tables[0].rows[0]["publication_date"] == "2015-04-01"


def test_whitespace_is_stripped():
    workbook = read_workbook(FIXTURES / "mini.xls")
    assert workbook.tables[0].rows[0]["note"] == "padded"


def test_empty_trailing_rows_are_skipped():
    workbook = read_workbook(FIXTURES / "mini.xls")
    assert len(workbook.tables[0].rows) == 2


def test_duplicate_headers_are_disambiguated():
    workbook = read_workbook(FIXTURES / "dup_headers.csv")
    table = workbook.tables[0]
    assert table.columns == ("a", "a_2", "b")
    assert table.rows[0] == {"a": "1", "a_2": "2", "b": "3"}


def test_unknown_extension_is_an_error(tmp_path):
    weird = tmp_path / "data.parquet"
    weird.write_text("nope")
    with pytest.raises(ValueError, match="parquet"):
        read_workbook(weird)
