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

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bepress_importer.convert import get_pointer


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
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        changes = [Change(**raw) for raw in data.get("changes", [])]
        return cls(changes=changes, schema_version=data.get("schema_version", 1))

    def save(self, path: str | Path) -> None:
        payload = {
            "schema_version": self.schema_version,
            "changes": [asdict(change) for change in self.changes],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        Path(path).write_text(text, encoding="utf-8")

    def _next_id(self) -> int:
        return max((c.id for c in self.changes), default=0) + 1

    def _chain_stacks(self) -> dict[tuple[str, str], list[Change]]:
        """Live chain per (record_id, field), oldest→newest, reverts popped off."""
        stacks: dict[tuple[str, str], list[Change]] = {}
        for change in self.changes:
            stack = stacks.setdefault((change.record_id, change.field), [])
            if change.op == "change":
                stack.append(change)
            else:  # revert of the then-head
                if stack and stack[-1].id == change.target:
                    stack.pop()
        return stacks

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
        head = self.head(record_id, field)
        change = Change(
            id=self._next_id(),
            op="change",
            record_id=record_id,
            field=field,
            before=before,
            after=after,
            at=at,
            parent=head.id if head else None,
            rule=rule,
            note=note,
        )
        self.changes.append(change)
        return change

    def head(self, record_id: str, field: str) -> Change | None:
        """The live head of a chain: newest change not neutralized by a revert."""
        stack = self._chain_stacks().get((record_id, field), [])
        return stack[-1] if stack else None

    def live_changes(self) -> list[Change]:
        """All changes currently in effect, in id order."""
        live = [c for stack in self._chain_stacks().values() for c in stack]
        return sorted(live, key=lambda c: c.id)

    def _append_revert(self, target: Change, at: str) -> Change:
        revert = Change(
            id=self._next_id(),
            op="revert",
            record_id=target.record_id,
            field=target.field,
            before=target.after,
            after=target.before,
            at=at,
            target=target.id,
        )
        self.changes.append(revert)
        return revert

    def undo_change(self, change_id: int, at: str, cascade: bool = False) -> list[Change]:
        """Append revert event(s) for one change; head-only unless cascade."""
        target = next((c for c in self.changes if c.id == change_id), None)
        if target is None:
            raise UndoError(f"No change with id {change_id}")
        if target.op != "change":
            raise UndoError(f"Change {change_id} is a revert event and cannot itself be undone")
        stack = self._chain_stacks().get((target.record_id, target.field), [])
        if target not in stack:
            raise UndoError(f"Change {change_id} has already been reverted")
        position = stack.index(target)
        descendants = stack[position + 1 :]
        if descendants and not cascade:
            blocking = ", ".join(str(c.id) for c in descendants)
            raise UndoError(
                f"Change {change_id} is not the head of its field's history; later change(s) "
                f"{blocking} build on it. Revert those first or use cascade."
            )
        return [self._append_revert(c, at) for c in reversed(stack[position:])]

    def undo_record(self, record_id: str, at: str) -> list[Change]:
        """Append revert events returning the record to its converter-output state."""
        live = [c for c in self.live_changes() if c.record_id == record_id]
        return [self._append_revert(c, at) for c in reversed(live)]


def summarize(log: ChangeLog, titles: dict[str, str] | None = None) -> str:
    """Human-readable line-per-change narrative, regenerated from the log.

    A derived artifact (never the source of truth): scannable by eye, with
    explicit wording for additions, removals and reverts so lossy changes
    stand out. `titles` maps record ids to display titles.
    """
    titles = titles or {}
    lines = []
    for event in log.changes:
        stamp = event.at.replace("T", " ")[:16]
        title = titles.get(event.record_id)
        record = f"Record {event.record_id}" + (f' ("{title}")' if title else "")
        before, after = _render(event.before), _render(event.after)
        if event.op == "revert":
            lines.append(
                f"{stamp} [Change {event.id}] reverts Change {event.target}: {record} "
                f'field "{event.field}" restored to {after}'
            )
            continue
        if event.before is None:
            action = f"added: {after}"
        elif event.after is None:
            action = f"removed (was: {before})"
        else:
            action = f"changed: {before} -> {after}"
        line = f'{stamp} [Change {event.id}] {record} field "{event.field}" {action}'
        annotations = []
        if event.rule:
            annotations.append(f"rule: {event.rule}")
        if event.note:
            annotations.append(f"note: {event.note}")
        if annotations:
            line += f" ({'; '.join(annotations)})"
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def _render(value: object) -> str:
    if value is None or isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "), sort_keys=True)


def _delete_pointer(obj: dict, pointer: str) -> None:
    parts = pointer.lstrip("/").split("/")
    node: object = obj
    for part in parts[:-1]:
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            node = node.get(part)
        if node is None:
            return
    last = parts[-1]
    if isinstance(node, list):
        index = int(last)
        if 0 <= index < len(node):
            del node[index]
    elif isinstance(node, dict):
        node.pop(last, None)


def _set_pointer_exact(obj: dict, pointer: str, value: object) -> None:
    """Set the exact value at a pointer (no list-append/dict-merge magic)."""
    parts = pointer.lstrip("/").split("/")
    node: object = obj
    for part in parts[:-1]:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node.setdefault(part, {})
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def replay(log: ChangeLog, records: list[dict]) -> tuple[list[dict], list[Conflict]]:
    """Fold the log over converter-output records (unmodified copies are returned).

    Each event's `before` must match the current value at its pointer;
    mismatches are reported as conflicts and the event is skipped.
    """
    wrangled = copy.deepcopy(records)
    by_id: dict[str, dict] = {}
    for record in wrangled:
        for ident in record.get("metadata", {}).get("identifiers", []):
            if ident.get("scheme") == "import-recid":
                by_id[ident["identifier"]] = record
    conflicts: list[Conflict] = []
    for event in log.changes:
        record = by_id.get(event.record_id)
        if record is None:
            conflicts.append(
                Conflict(event.id, event.record_id, event.field, event.before, None)
            )
            continue
        current = get_pointer(record, event.field)
        if current != event.before:
            conflicts.append(
                Conflict(event.id, event.record_id, event.field, event.before, current)
            )
            continue
        if event.after is None:
            _delete_pointer(record, event.field)
        else:
            _set_pointer_exact(record, event.field, event.after)
    return wrangled, conflicts
