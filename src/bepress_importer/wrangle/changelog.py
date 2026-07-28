"""Append-only change log with per-(record, field) history chains.

Event-sourcing model: converter output is immutable; this log records every
accepted change (and every revert, as a new event — history is never erased).
The wrangled dataset is derived by replaying the log; replay verifies each
event's `before` against the current value so converter drift surfaces as
conflicts instead of silent corruption.

A value of None in before/after means "field absent": before=None is an
addition, after=None is a removal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class UndoError(ValueError):
    """Raised when a revert request violates chain ordering."""


@dataclass(frozen=True)
class Change:
    id: int
    op: str  # "change" | "revert"
    record_id: str
    field: str
    before: object
    after: object
    at: str
    parent: int | None = None  # previous live change on this (record, field) chain
    target: int | None = None  # for op="revert": the change being reverted
    rule: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Conflict:
    change_id: int
    record_id: str
    field: str
    expected: object
    found: object


@dataclass
class ChangeLog:
    changes: list[Change] = field(default_factory=list)
    schema_version: int = 1

    @classmethod
    def load(cls, path: str | Path) -> ChangeLog:
        """Load a log from disk; a missing file is an empty log."""
        raise NotImplementedError

    def save(self, path: str | Path) -> None:
        raise NotImplementedError

    def append_change(
        self,
        record_id: str,
        field: str,
        before: object,
        after: object,
        at: str,
        rule: str | None = None,
        note: str | None = None,
    ) -> Change:
        """Append a change, linking it to the live head of its (record, field) chain."""
        raise NotImplementedError

    def head(self, record_id: str, field: str) -> Change | None:
        """The live head of a chain: newest change not neutralized by a revert."""
        raise NotImplementedError

    def live_changes(self) -> list[Change]:
        """All changes currently in effect, in id order."""
        raise NotImplementedError

    def undo_change(self, change_id: int, at: str, cascade: bool = False) -> list[Change]:
        """Append revert event(s) for one change; head-only unless cascade."""
        raise NotImplementedError

    def undo_record(self, record_id: str, at: str) -> list[Change]:
        """Append revert events returning the record to its converter-output state."""
        raise NotImplementedError


def replay(log: ChangeLog, records: list[dict]) -> tuple[list[dict], list[Conflict]]:
    """Fold the log over converter-output records (unmodified copies are returned).

    Each event's `before` must match the current value at its pointer;
    mismatches are reported as conflicts and the event is skipped.
    """
    raise NotImplementedError
