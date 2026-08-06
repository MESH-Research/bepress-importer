"""Behavioural tests for conversion: workbook + profile in → KC Works records out."""

import json
from pathlib import Path

from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import load_profile
from bepress_importer.readers import read_workbook
from bepress_importer.serialize import canonical_dumps

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = "2026-07-28"


def convert_golden():
    workbook = read_workbook(FIXTURES / "journal.csv")
    profile = load_profile(FIXTURES / "golden_profile.toml")
    return convert_workbook(workbook, profile, as_of=AS_OF)


def test_golden_conversion_matches_expected_records():
    result = convert_golden()
    expected = json.loads((FIXTURES / "golden" / "fac_journ.expected.json").read_text())
    assert result.collections == {"fac_journ": expected}


def test_conversion_is_byte_deterministic():
    first = canonical_dumps(convert_golden().collections)
    second = canonical_dumps(convert_golden().collections)
    assert first == second


def test_records_are_sorted_by_record_id(tmp_path):
    csv = tmp_path / "s.csv"
    csv.write_text(
        "title,publication_date,document_type,author1_fname,author1_lname,context_key,issue\n"
        "B,2001-01-01,article,A,B,900,coll\n"
        "A,2000-01-01,article,A,B,200,coll\n"
    )
    workbook = read_workbook(csv)
    profile_toml = tmp_path / "p.toml"
    profile_toml.write_text(
        '[profile]\nname = "p"\n[[sheet]]\nmatch = "*"\n'
        '[sheet.resource_type]\nconstant = "textDocument-other"\n'
        '[[sheet.field]]\nsource = "title"\ntarget = "/metadata/title"\n'
    )
    result = convert_workbook(workbook, load_profile(profile_toml), as_of=AS_OF)
    titles = [r["metadata"]["title"] for r in result.collections["coll"]]
    assert titles == ["A", "B"]


def test_unmatched_sheets_are_reported():
    workbook = read_workbook(FIXTURES / "mini.csv")
    profile = load_profile(FIXTURES / "golden_profile.toml")
    result = convert_workbook(workbook, profile, as_of=AS_OF)
    assert result.unmatched_sheets == ["mini"]
    assert result.collections == {}


def test_missing_required_field_is_reported_but_record_emitted(tmp_path):
    csv = tmp_path / "journal.csv"
    csv.write_text(
        "title,publication_date,document_type,context_key,issue\n"
        ",2001-01-01,article,42,coll\n"
    )
    profile = load_profile(FIXTURES / "golden_profile.toml")
    result = convert_workbook(read_workbook(csv), profile, as_of=AS_OF)
    assert len(result.collections["coll"]) == 1
    assert any(i.record_id == "42" and "title" in i.message for i in result.issues)


def test_unmapped_document_type_keeps_raw_value_and_reports(tmp_path):
    csv = tmp_path / "journal.csv"
    csv.write_text(
        "title,publication_date,document_type,context_key,issue\n"
        "T,2001-01-01,weird_type,42,coll\n"
    )
    profile = load_profile(FIXTURES / "golden_profile.toml")
    result = convert_workbook(read_workbook(csv), profile, as_of=AS_OF)
    record = result.collections["coll"][0]
    assert record["metadata"]["resource_type"] == {"id": "weird_type"}
    assert any("weird_type" in i.message for i in result.issues)


def test_collection_slug_falls_back_to_sheet_name(tmp_path):
    csv = tmp_path / "My Sheet!.csv"
    csv.write_text("title,context_key\nT,1\n")
    profile_toml = tmp_path / "p.toml"
    profile_toml.write_text(
        '[profile]\nname = "p"\n[[sheet]]\nmatch = "*"\n'
        '[[sheet.field]]\nsource = "title"\ntarget = "/metadata/title"\n'
    )
    result = convert_workbook(read_workbook(csv), load_profile(profile_toml), as_of=AS_OF)
    assert list(result.collections) == ["my_sheet"]


FILTER_PROFILE = (
    '[profile]\nname = "p"\n[[sheet]]\nmatch = "*"\n'
    '[sheet.filter]\ncolumn = "state"\nkeep = ["published"]\n'
    '[[sheet.field]]\nsource = "title"\ntarget = "/metadata/title"\n'
)


def test_row_filter_excludes_rows_and_documents_them(tmp_path):
    csv = tmp_path / "inv.csv"
    csv.write_text(
        "title,state,context_key,issue\n"
        "Keep Me,published,1,coll\n"
        "Withdrawn Item,withdrawn,2,coll\n"
        "Pending Item,pending,3,coll\n"
    )
    profile_toml = tmp_path / "p.toml"
    profile_toml.write_text(FILTER_PROFILE)
    result = convert_workbook(read_workbook(csv), load_profile(profile_toml), as_of=AS_OF)
    titles = [r["metadata"]["title"] for r in result.collections["coll"]]
    assert titles == ["Keep Me"]
    doc = result.sheet_docs[0]
    assert doc["row_filter"]["column"] == "state"
    assert doc["row_filter"]["excluded"] == 2
    assert set(doc["row_filter"]["excluded_ids"]) == {"2", "3"}


def test_explicit_collection_overrides_issue_column(tmp_path):
    csv = tmp_path / "journal.csv"
    csv.write_text("title,context_key,issue\nT,1,ignored_slug\n")
    profile_toml = tmp_path / "p.toml"
    profile_toml.write_text(
        '[profile]\nname = "p"\n[[sheet]]\nmatch = "*"\ncollection = "override"\n'
        '[[sheet.field]]\nsource = "title"\ntarget = "/metadata/title"\n'
    )
    result = convert_workbook(read_workbook(csv), load_profile(profile_toml), as_of=AS_OF)
    assert list(result.collections) == ["override"]
