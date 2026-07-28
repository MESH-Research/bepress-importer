"""Shared wrangling-session plumbing: data loading, state, and the interactive fix loop."""

from __future__ import annotations

import datetime
from pathlib import Path

import click

from bepress_importer.serialize import write_json
from bepress_importer.wrangle.changelog import ChangeLog, Conflict, replay, summarize
from bepress_importer.wrangle.rules import Finding


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_collections(data_dir: str | Path) -> dict[str, list[dict]]:
    """Load every per-collection JSON file (report.json excluded), sorted by name."""
    import json

    collections = {}
    for path in sorted(Path(data_dir).glob("*.json")):
        if path.name == "report.json" or not path.is_file():
            continue
        collections[path.name] = json.loads(path.read_text(encoding="utf-8"))
    if not collections:
        raise click.ClickException(f"No collection JSON files found in {data_dir}")
    return collections


def flatten(collections: dict[str, list[dict]]) -> list[dict]:
    return [record for records in collections.values() for record in records]


def replayed_state(
    collections: dict[str, list[dict]], log: ChangeLog
) -> tuple[dict[str, list[dict]], list[Conflict]]:
    """Replay the log over each collection, preserving the file layout."""
    wrangled = {}
    conflicts: list[Conflict] = []
    for name, records in collections.items():
        new_records, file_conflicts = replay(log, records)
        wrangled[name] = new_records
        conflicts.extend(
            c for c in file_conflicts if _recid_in(records, c.record_id)
        )
    return wrangled, conflicts


def _recid_in(records: list[dict], record_id: str) -> bool:
    from bepress_importer.wrangle.rules import record_id_of

    return any(record_id_of(r) == record_id for r in records)


def titles_of(collections: dict[str, list[dict]]) -> dict[str, str]:
    from bepress_importer.wrangle.rules import record_id_of

    return {
        record_id_of(record): record.get("metadata", {}).get("title", "")
        for record in flatten(collections)
        if record_id_of(record)
    }


def write_outputs(
    out_dir: str | Path, collections: dict[str, list[dict]], log: ChangeLog
) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wrangled, conflicts = replayed_state(collections, log)
    if conflicts:  # callers check first; this is a safety net
        raise click.ClickException(f"{len(conflicts)} replay conflict(s); not writing output")
    for name, records in wrangled.items():
        write_json(out / name, records)


def save_log(log_path: str | Path, log: ChangeLog, titles: dict[str, str]) -> None:
    """Persist the log and regenerate the human-readable summary beside it."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log.save(log_path)
    summary_path = log_path.with_suffix(".log")
    summary_path.write_text(summarize(log, titles), encoding="utf-8")


def render_finding(finding: Finding) -> str:
    lines = [
        f"  rule: {finding.rule}   record: {finding.record_id}   field: {finding.field}",
        f"  current:  {finding.current!r}",
    ]
    if finding.proposal is not None:
        rendered = "(remove field)" if finding.proposal.value is None else repr(finding.proposal.value)
        lines.append(f"  proposed: {rendered}")
    if finding.note:
        lines.append(f"  note: {finding.note}")
    return "\n".join(lines)


def run_fix_session(
    findings: list[Finding],
    log: ChangeLog,
    at: str,
    accept_all: bool = False,
) -> tuple[int, int]:
    """Walk findings; append accepted proposals to the log.

    Returns (accepted, skipped). Prompts y/n/a (all for this rule)/s (skip
    rule)/q unless accept_all.
    """
    accepted = skipped = 0
    accept_rule: str | None = None
    skip_rule: str | None = None
    for finding in findings:
        if finding.proposal is None:
            click.echo(f"[flag-only] {finding.rule}: record {finding.record_id} "
                       f"{finding.field} — {finding.note or 'needs manual edit'} (use `edit`)")
            continue
        decision = None
        if accept_all or finding.rule == accept_rule:
            decision = "y"
        elif finding.rule == skip_rule:
            decision = "n"
        else:
            click.echo(render_finding(finding))
            decision = click.prompt(
                "  apply? [y]es / [n]o / [a]ll for this rule / [s]kip rule / [q]uit",
                type=click.Choice(["y", "n", "a", "s", "q"]),
                show_choices=False,
            )
        if decision == "q":
            break
        if decision == "a":
            accept_rule, decision = finding.rule, "y"
        elif decision == "s":
            skip_rule, decision = finding.rule, "n"
        if decision == "y":
            log.append_change(
                finding.record_id,
                finding.field,
                before=finding.current,
                after=finding.proposal.value,
                at=at,
                rule=finding.rule,
                note=finding.note,
            )
            accepted += 1
        else:
            skipped += 1
    return accepted, skipped
