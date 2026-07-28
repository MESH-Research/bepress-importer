"""Behavioural tests for the plaintext wrangling.log summary."""

from bepress_importer.wrangle.changelog import ChangeLog, summarize

AT = "2026-07-28T11:07:00Z"
TITLES = {"2404130": "Nonlinear dynamics of granular flows"}


def test_change_line_is_fully_narrated():
    log = ChangeLog()
    log.append_change(
        "2404130", "/metadata/publication_date", "Spring 2015", "2015", at=AT, rule="edtf-date"
    )
    line = summarize(log, TITLES).splitlines()[0]
    assert "2026-07-28 11:07" in line
    assert "[Change 1]" in line
    assert 'Record 2404130 ("Nonlinear dynamics of granular flows")' in line
    assert '"/metadata/publication_date"' in line
    assert '"Spring 2015" -> "2015"' in line
    assert "(rule: edtf-date)" in line


def test_one_line_per_event_in_order():
    log = ChangeLog()
    log.append_change("2404130", "/metadata/title", "A", "B", at=AT)
    log.append_change("2404130", "/metadata/title", "B", "C", at=AT)
    lines = summarize(log, TITLES).splitlines()
    assert len(lines) == 2
    assert "[Change 1]" in lines[0]
    assert "[Change 2]" in lines[1]


def test_addition_wording():
    log = ChangeLog()
    log.append_change("2404130", "/metadata/publisher", None, "New Press", at=AT)
    assert 'added: "New Press"' in summarize(log, TITLES)


def test_removal_wording_shows_lost_value():
    log = ChangeLog()
    log.append_change("2404130", "/metadata/publication_date", "2015", None, at=AT)
    assert 'removed (was: "2015")' in summarize(log, TITLES)


def test_revert_wording_references_target_change():
    log = ChangeLog()
    c1 = log.append_change("2404130", "/metadata/title", "A", "B", at=AT)
    log.undo_change(c1.id, at=AT)
    lines = summarize(log, TITLES).splitlines()
    assert f"reverts Change {c1.id}" in lines[1]
    assert 'restored to "A"' in lines[1]


def test_note_is_included():
    log = ChangeLog()
    log.append_change("2404130", "/metadata/title", "A", "B", at=AT, rule="manual", note="client")
    assert "note: client" in summarize(log, TITLES)


def test_unknown_title_falls_back_to_bare_record_id():
    log = ChangeLog()
    log.append_change("999", "/metadata/title", "A", "B", at=AT)
    line = summarize(log, TITLES).splitlines()[0]
    assert "Record 999 " in line
    assert '("' not in line.split("]")[1].split("field")[0]


def test_structured_values_render_as_compact_json():
    log = ChangeLog()
    log.append_change("2404130", "/metadata/rights", None, [{"id": "cc-by-4.0"}], at=AT)
    assert '[{"id": "cc-by-4.0"}]' in summarize(log, TITLES)


def test_summary_is_deterministic():
    log = ChangeLog()
    log.append_change("2404130", "/metadata/title", "A", "B", at=AT)
    assert summarize(log, TITLES) == summarize(log, TITLES)
