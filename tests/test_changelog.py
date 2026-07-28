"""Behavioural tests for the change log: chains, persistence, replay, conflicts."""

from bepress_importer.wrangle.changelog import ChangeLog, replay

AT = "2026-07-28T10:00:00Z"


def make_record(record_id="100", title="Original Title", date="2015"):
    return {
        "metadata": {
            "identifiers": [{"identifier": record_id, "scheme": "import-recid"}],
            "publication_date": date,
            "title": title,
        },
        "files": {"enabled": False},
    }


class TestAppendAndChains:
    def test_ids_are_monotonic_from_one(self):
        log = ChangeLog()
        c1 = log.append_change("100", "/metadata/title", "A", "B", at=AT)
        c2 = log.append_change("100", "/metadata/title", "B", "C", at=AT)
        assert (c1.id, c2.id) == (1, 2)

    def test_first_change_to_a_field_has_no_parent(self):
        log = ChangeLog()
        c1 = log.append_change("100", "/metadata/title", "A", "B", at=AT)
        assert c1.parent is None

    def test_second_change_to_same_field_links_to_first(self):
        log = ChangeLog()
        c1 = log.append_change("100", "/metadata/title", "A", "B", at=AT)
        c2 = log.append_change("100", "/metadata/title", "B", "C", at=AT)
        assert c2.parent == c1.id

    def test_changes_to_different_fields_have_independent_chains(self):
        log = ChangeLog()
        log.append_change("100", "/metadata/title", "A", "B", at=AT)
        c2 = log.append_change("100", "/metadata/publication_date", "2015", "2016", at=AT)
        c3 = log.append_change("200", "/metadata/title", "X", "Y", at=AT)
        assert c2.parent is None
        assert c3.parent is None

    def test_head_is_newest_change_on_chain(self):
        log = ChangeLog()
        log.append_change("100", "/metadata/title", "A", "B", at=AT)
        c2 = log.append_change("100", "/metadata/title", "B", "C", at=AT)
        assert log.head("100", "/metadata/title") == c2

    def test_head_of_untouched_field_is_none(self):
        assert ChangeLog().head("100", "/metadata/title") is None

    def test_rule_and_note_are_recorded(self):
        log = ChangeLog()
        c1 = log.append_change(
            "100", "/metadata/title", "A", "B", at=AT, rule="edtf-date", note="why"
        )
        assert (c1.rule, c1.note) == ("edtf-date", "why")


class TestPersistence:
    def test_roundtrip(self, tmp_path):
        log = ChangeLog()
        log.append_change("100", "/metadata/title", "A", "B", at=AT, rule="manual")
        log.append_change("100", "/metadata/title", "B", None, at=AT)
        path = tmp_path / "wrangling.json"
        log.save(path)
        assert ChangeLog.load(path) == log

    def test_missing_file_is_empty_log(self, tmp_path):
        log = ChangeLog.load(tmp_path / "absent.json")
        assert log.changes == []


class TestReplay:
    def test_applies_changes_in_order(self):
        log = ChangeLog()
        log.append_change("100", "/metadata/title", "Original Title", "Better", at=AT)
        log.append_change("100", "/metadata/title", "Better", "Best", at=AT)
        wrangled, conflicts = replay(log, [make_record()])
        assert conflicts == []
        assert wrangled[0]["metadata"]["title"] == "Best"

    def test_original_records_are_not_mutated(self):
        log = ChangeLog()
        log.append_change("100", "/metadata/title", "Original Title", "Changed", at=AT)
        records = [make_record()]
        replay(log, records)
        assert records[0]["metadata"]["title"] == "Original Title"

    def test_addition_when_before_is_none(self):
        log = ChangeLog()
        log.append_change("100", "/metadata/publisher", None, "New Press", at=AT)
        wrangled, conflicts = replay(log, [make_record()])
        assert conflicts == []
        assert wrangled[0]["metadata"]["publisher"] == "New Press"

    def test_removal_when_after_is_none(self):
        log = ChangeLog()
        log.append_change("100", "/metadata/publication_date", "2015", None, at=AT)
        wrangled, conflicts = replay(log, [make_record()])
        assert conflicts == []
        assert "publication_date" not in wrangled[0]["metadata"]

    def test_before_mismatch_is_a_conflict_and_event_skipped(self):
        log = ChangeLog()
        log.append_change("100", "/metadata/title", "Stale Value", "Changed", at=AT)
        wrangled, conflicts = replay(log, [make_record()])
        assert len(conflicts) == 1
        assert conflicts[0].expected == "Stale Value"
        assert conflicts[0].found == "Original Title"
        assert wrangled[0]["metadata"]["title"] == "Original Title"

    def test_unknown_record_is_a_conflict(self):
        log = ChangeLog()
        log.append_change("999", "/metadata/title", "A", "B", at=AT)
        _, conflicts = replay(log, [make_record()])
        assert len(conflicts) == 1
        assert conflicts[0].record_id == "999"

    def test_records_in_multiple_collections_addressed_by_import_recid(self):
        log = ChangeLog()
        log.append_change("200", "/metadata/title", "Second", "Renamed", at=AT)
        records = [make_record("100", "First"), make_record("200", "Second")]
        wrangled, conflicts = replay(log, records)
        assert conflicts == []
        assert wrangled[0]["metadata"]["title"] == "First"
        assert wrangled[1]["metadata"]["title"] == "Renamed"


class TestReplayAfterRevert:
    def test_reverted_change_leaves_original_value(self):
        log = ChangeLog()
        c1 = log.append_change("100", "/metadata/title", "Original Title", "Changed", at=AT)
        log.undo_change(c1.id, at=AT)
        wrangled, conflicts = replay(log, [make_record()])
        assert conflicts == []
        assert wrangled[0]["metadata"]["title"] == "Original Title"
