"""Behavioural tests for undo semantics: head-only, cascade, revert-object."""

import pytest

from bepress_importer.wrangle.changelog import ChangeLog, UndoError, replay
from test_changelog import AT, make_record


def three_change_log():
    """One record, one field changed twice, a second field changed once."""
    log = ChangeLog()
    c1 = log.append_change("100", "/metadata/title", "Original Title", "Better", at=AT)
    c2 = log.append_change("100", "/metadata/title", "Better", "Best", at=AT)
    c3 = log.append_change("100", "/metadata/publication_date", "2015", "2016", at=AT)
    return log, c1, c2, c3


class TestUndoChange:
    def test_undo_head_restores_previous_chain_value(self):
        log, _c1, c2, _ = three_change_log()
        reverts = log.undo_change(c2.id, at=AT)
        assert len(reverts) == 1
        assert reverts[0].target == c2.id
        wrangled, conflicts = replay(log, [make_record()])
        assert conflicts == []
        assert wrangled[0]["metadata"]["title"] == "Better"

    def test_undo_non_head_without_cascade_raises_naming_blockers(self):
        log, c1, c2, _ = three_change_log()
        with pytest.raises(UndoError, match=str(c2.id)):
            log.undo_change(c1.id, at=AT)

    def test_undo_non_head_with_cascade_reverts_suffix_newest_first(self):
        log, c1, c2, _ = three_change_log()
        reverts = log.undo_change(c1.id, at=AT, cascade=True)
        assert [r.target for r in reverts] == [c2.id, c1.id]
        wrangled, conflicts = replay(log, [make_record()])
        assert conflicts == []
        assert wrangled[0]["metadata"]["title"] == "Original Title"

    def test_undo_already_reverted_change_raises(self):
        log, _, c2, _ = three_change_log()
        log.undo_change(c2.id, at=AT)
        with pytest.raises(UndoError, match="reverted"):
            log.undo_change(c2.id, at=AT)

    def test_undo_a_revert_event_raises(self):
        log, _, c2, _ = three_change_log()
        revert = log.undo_change(c2.id, at=AT)[0]
        with pytest.raises(UndoError):
            log.undo_change(revert.id, at=AT)

    def test_undo_unknown_id_raises(self):
        log, *_ = three_change_log()
        with pytest.raises(UndoError, match="999"):
            log.undo_change(999, at=AT)

    def test_new_change_after_revert_links_to_restored_head(self):
        log, c1, c2, _ = three_change_log()
        log.undo_change(c2.id, at=AT)
        c_new = log.append_change("100", "/metadata/title", "Better", "Newest", at=AT)
        assert c_new.parent == c1.id


class TestUndoRecord:
    def test_record_returns_to_converter_state(self):
        log, *_ = three_change_log()
        log.undo_record("100", at=AT)
        wrangled, conflicts = replay(log, [make_record()])
        assert conflicts == []
        assert wrangled[0]["metadata"]["title"] == "Original Title"
        assert wrangled[0]["metadata"]["publication_date"] == "2015"

    def test_other_records_are_untouched(self):
        log, *_ = three_change_log()
        log.append_change("200", "/metadata/title", "Second", "Renamed", at=AT)
        log.undo_record("100", at=AT)
        records = [make_record("100"), make_record("200", "Second")]
        wrangled, conflicts = replay(log, records)
        assert conflicts == []
        assert wrangled[1]["metadata"]["title"] == "Renamed"

    def test_undo_record_with_no_changes_appends_nothing(self):
        log, *_ = three_change_log()
        before = len(log.changes)
        assert log.undo_record("999", at=AT) == []
        assert len(log.changes) == before

    def test_history_is_preserved_after_undo(self):
        log, _c1, _c2, _c3 = three_change_log()
        log.undo_record("100", at=AT)
        # nothing is erased: 3 changes + 3 revert events
        assert len(log.changes) == 6
        assert log.live_changes() == []
