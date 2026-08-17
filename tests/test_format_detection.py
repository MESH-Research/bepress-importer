"""Behavioural tests for export-format detection (Content Inventory workbooks)."""

from pathlib import Path

import pytest

from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import SHIPPED_PROFILE_DIR, detect_profile, load_profile
from bepress_importer.readers import Table, Workbook
from bepress_importer.transforms import known_transforms

AS_OF = "2026-08-17"

INVENTORY_COLUMNS = (
    "title", "state", "submission_date", "document_type", "abstract", "keywords",
    "author1_fname", "author1_lname", "publication_date", "start_date", "context_key",
)


def inventory_table(name="Content Inventory", rows=()):
    return Table(name=name, columns=INVENTORY_COLUMNS, rows=tuple(rows))


def legend_table():
    return Table(
        name="Field Names",
        columns=("Fields included",),
        rows=({"Fields included": "title"}, {"Fields included": "state"}),
    )


def inventory_row(**overrides):
    row = {column: "" for column in INVENTORY_COLUMNS}
    row.update(
        title="A Study of Things",
        state="published",
        document_type="article",
        publication_date="2020-01-01",
        author1_fname="Ada",
        author1_lname="Lovelace",
        context_key="12345",
    )
    row.update(overrides)
    return row


class TestDetectProfile:
    def test_recognizes_content_inventory_workbook(self):
        workbook = Workbook(tables=(inventory_table(), legend_table()))
        profile = detect_profile(workbook, known_transforms=known_transforms())
        assert profile is not None
        assert profile.name == "inventory"

    def test_returns_none_for_collection_export(self):
        # collection exports (e.g. Bucknell .xls) have no `state` column
        columns = tuple(c for c in INVENTORY_COLUMNS if c not in ("state", "submission_date"))
        workbook = Workbook(tables=(Table(name="Fac Journal Articles", columns=columns, rows=()),))
        assert detect_profile(workbook, known_transforms=known_transforms()) is None

    def test_returns_none_for_empty_workbook(self):
        workbook = Workbook(tables=(Table(name="empty", columns=(), rows=()),))
        assert detect_profile(workbook, known_transforms=known_transforms()) is None


@pytest.fixture(scope="module")
def profile():
    return load_profile(
        SHIPPED_PROFILE_DIR / "inventory.toml", known_transforms=known_transforms()
    )


@pytest.fixture(scope="module")
def result(profile):
    event_row = inventory_row(
        title="Opening Keynote", document_type="keynote",
        publication_date="", start_date="2012-11-17", context_key="12346",
    )
    workbook = Workbook(
        tables=(
            inventory_table(rows=[inventory_row(), event_row]),
            legend_table(),
        )
    )
    return convert_workbook(workbook, profile, as_of=AS_OF)


class TestInventoryProfileSignature:
    def test_profile_declares_a_format_signature(self, profile):
        assert set(profile.signature_columns) == {"context_key", "state", "document_type"}

    def test_data_sheet_matches_with_its_columns(self, profile):
        assert profile.match_sheet("Content Inventory", columns=INVENTORY_COLUMNS) is not None

    def test_legend_sheet_does_not_match(self, profile):
        assert profile.match_sheet("Field Names", columns=("Fields included",)) is None

    def test_matching_by_name_alone_still_works(self, profile):
        assert profile.match_sheet("inventory") is not None


class TestConvertInventoryWorkbook:
    def test_data_rows_become_records(self, result):
        records = result.collections["inventory"]
        assert len(records) == 2
        assert records[0]["metadata"]["title"] == "A Study of Things"
        assert records[0]["metadata"]["resource_type"] == {"id": "textDocument-journalArticle"}

    def test_event_rows_take_publication_date_from_start_date(self, result):
        event = result.collections["inventory"][1]
        assert event["metadata"]["title"] == "Opening Keynote"
        assert event["metadata"]["publication_date"] == "2012-11-17"

    def test_legend_sheet_is_reported_unmatched_not_converted(self, result):
        assert result.unmatched_sheets == ["Field Names"]
        assert set(result.collections) == {"inventory"}


class TestShippedProfileLocation:
    def test_inventory_profile_ships_inside_the_package(self):
        assert (SHIPPED_PROFILE_DIR / "inventory.toml").is_file()
        assert SHIPPED_PROFILE_DIR.name == "profiles"
        assert Path(SHIPPED_PROFILE_DIR).parent.name == "bepress_importer"
