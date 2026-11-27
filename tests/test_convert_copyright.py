"""Behavioural tests for copyright-field hygiene across a conversion.

A rights column sometimes holds an abstract or a stray remark. The copyright
field must only receive genuine rights statements; prose is rescued as the
description when the record has none, and everything is reported.
"""

from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import load_profile
from bepress_importer.readers import Table, Workbook
from bepress_importer.transforms import known_transforms

COLUMNS = ("context_key", "title", "abstract", "pub_statement")
PROFILE = """
[profile]
name = "p"
[[sheet]]
match = "*"
collection = "articles"
[sheet.resource_type]
constant = "textDocument-journalArticle"
[[sheet.field]]
source = "title"
target = "/metadata/title"
[[sheet.field]]
source = "pub_statement"
target = "/metadata/description"
transform = "misplaced_description"
args = { unless_columns = ["abstract"] }
append = true
[[sheet.field]]
source = "abstract"
target = "/metadata/description"
transform = "strip_html"
append = true
[[sheet.field]]
source = "pub_statement"
target = "/metadata/copyright"
transform = "rights_statement"
"""
PROSE = (
    "Animals learn to prefer and increase consumption of flavors paired with postingestive "
    "nutrient sensing. Analogous effects have been difficult to observe in human studies."
)


def convert(tmp_path, **cells):
    path = tmp_path / "p.toml"
    path.write_text(PROFILE)
    row = {column: "" for column in COLUMNS} | {"context_key": "1", "title": "T"} | cells
    table = Table(name="Sheet", columns=COLUMNS, rows=(row,))
    profile = load_profile(path, known_transforms=known_transforms())
    return convert_workbook(Workbook(tables=(table,)), profile, as_of="2026-11-26")


def metadata(result):
    return result.collections["articles"][0]["metadata"]


def test_a_rights_statement_goes_to_copyright_and_nowhere_else(tmp_path):
    result = convert(tmp_path, pub_statement="Copyright © 2010 American Physical Society")
    assert metadata(result)["copyright"] == "Copyright © 2010 American Physical Society"
    assert "description" not in metadata(result)
    assert result.issues == []


def test_an_abstract_in_the_rights_column_becomes_the_description(tmp_path):
    result = convert(tmp_path, pub_statement=PROSE)
    assert "copyright" not in metadata(result)
    assert metadata(result)["description"] == PROSE


def test_the_records_own_abstract_is_kept_over_misplaced_prose(tmp_path):
    result = convert(tmp_path, pub_statement=PROSE, abstract="<p>The real abstract.</p>")
    assert metadata(result)["description"] == "The real abstract."
    assert "copyright" not in metadata(result)


def test_a_stray_remark_is_dropped_from_the_record(tmp_path):
    result = convert(tmp_path, pub_statement="Unsure")
    assert "copyright" not in metadata(result)
    assert "description" not in metadata(result)


def test_every_statement_kept_out_of_copyright_is_reported_for_review(tmp_path):
    for statement in (PROSE, "Unsure"):
        result = convert(tmp_path, pub_statement=statement)
        assert [(i.record_id, "pub_statement" in i.message) for i in result.issues] == [("1", True)]


def test_the_log_says_where_the_text_went_and_why(tmp_path):
    result = convert(tmp_path, pub_statement=PROSE)
    by_target = {c.target: c for c in result.value_changes if c.source == "pub_statement"}
    assert by_target["/metadata/copyright"].action == "dropped"
    assert "rights statement" in by_target["/metadata/copyright"].reason
    assert by_target["/metadata/description"].action == "transformed"
    assert "description" in by_target["/metadata/description"].reason


def test_a_dropped_remark_is_logged_once_as_dropped(tmp_path):
    result = convert(tmp_path, pub_statement="Unsure")
    changes = [c for c in result.value_changes if c.source == "pub_statement"]
    assert [(c.target, c.action) for c in changes] == [("/metadata/copyright", "dropped")]
