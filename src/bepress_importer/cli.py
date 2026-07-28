"""bpress-importer command line interface."""

from __future__ import annotations

import datetime
from pathlib import Path

import click

from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import ProfileError, load_profile
from bepress_importer.readers import Workbook, read_workbook
from bepress_importer.serialize import write_json
from bepress_importer.transforms import known_transforms


@click.group()
@click.version_option(package_name="bepress-importer")
def cli() -> None:
    """Convert Bepress batch exports to KC Works import JSON, wrangle and upload them."""


@cli.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--profile", "profile_path", type=click.Path(exists=True, dir_okay=False),
              help="Show mapping coverage against this profile.")
@click.option("--scaffold", is_flag=True, help="Print a starter profile inferred from the headers.")
def inspect(input_file: str, profile_path: str | None, scaffold: bool) -> None:
    """List sheets, row counts and columns of a Bepress export."""
    workbook = read_workbook(input_file)
    if scaffold:
        click.echo(_scaffold_profile(workbook))
        return
    profile = _load_profile_or_fail(profile_path) if profile_path else None
    for table in workbook.tables:
        click.echo(f"Sheet {table.name!r}: {len(table.rows)} rows, {len(table.columns)} columns")
        if profile is None:
            click.echo("  columns: " + ", ".join(table.columns))
            continue
        sheet = profile.match_sheet(table.name)
        if sheet is None:
            click.echo("  (no profile match)")
            continue
        mapped = _mapped_columns(sheet, profile)
        unmapped = [c for c in table.columns if c not in mapped and not _is_empty(table, c)]
        empty = [c for c in table.columns if _is_empty(table, c)]
        click.echo(f"  mapped: {sum(1 for c in table.columns if c in mapped)}"
                   f" / unmapped (non-empty): {len(unmapped)} / empty: {len(empty)}")
        if unmapped:
            click.echo("  unmapped columns: " + ", ".join(unmapped))


def _is_empty(table, column: str) -> bool:
    return all(not row.get(column, "") for row in table.rows)


def _mapped_columns(sheet, profile) -> set[str]:
    mapped = {f.source for f in sheet.fields}
    for f in sheet.fields:
        if "season_column" in f.args:
            mapped.add(f.args["season_column"])
    if sheet.resource_type and sheet.resource_type.column:
        mapped.add(sheet.resource_type.column)
    defaults = profile.defaults
    mapped |= {defaults.record_id_column, "issue"}
    if defaults.url_column:
        mapped.add(defaults.url_column)
    prefix = defaults.authors.prefix
    for n in range(1, defaults.authors.max + 1):
        for part in ("fname", "mname", "lname", "suffix", "email", "institution", "is_corporate"):
            mapped.add(f"{prefix}{n}_{part}")
    if sheet.contributors:
        for n in range(1, sheet.contributors.max + 1):
            mapped.add(f"{sheet.contributors.prefix}{n}")
    for composite in (sheet.journal, sheet.imprint):
        if composite:
            for column in vars(composite).values():
                if column:
                    mapped.add(column)
    return mapped


def _scaffold_profile(workbook: Workbook) -> str:
    lines = ['[profile]', 'name = "CHANGEME"', "schema_version = 1", ""]
    lines += ["[defaults]", 'record_id.column = "context_key"',
              'url_identifier.column = "calc_url"', "files_enabled = false", ""]
    for table in workbook.tables:
        lines += ["[[sheet]]", f'match = "{table.name}"', ""]
        for column in table.columns:
            lines += [
                "  [[sheet.field]]",
                f'  source = "{column}"',
                f'  target = "/CHANGEME/{column}"',
                "",
            ]
    return "\n".join(lines)


def _load_profile_or_fail(profile_path: str):
    try:
        return load_profile(profile_path, known_transforms=known_transforms())
    except ProfileError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--profile", "profile_path", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", "output_dir", required=True, type=click.Path(file_okay=False))
@click.option("--sheet", "sheets", multiple=True,
              help="Convert only these sheets (repeatable; default: all matched).")
@click.option("--as-of", default=None,
              help="ISO date for embargo-activity decisions (default: today; "
                   "pass explicitly for reproducible output).")
def convert(
    input_file: str, profile_path: str, output_dir: str, sheets: tuple[str, ...], as_of: str | None
) -> None:
    """Convert an export to per-collection KC Works JSON files plus a report."""
    workbook = read_workbook(input_file)
    if sheets:
        available = {t.name for t in workbook.tables}
        missing = [s for s in sheets if s not in available]
        if missing:
            raise click.ClickException(f"Sheets not found in input: {', '.join(missing)}")
        workbook = Workbook(tables=tuple(t for t in workbook.tables if t.name in sheets))
    profile = _load_profile_or_fail(profile_path)
    as_of = as_of or datetime.date.today().isoformat()  # noqa: DTZ011

    result = convert_workbook(workbook, profile, as_of=as_of)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for slug, records in result.collections.items():
        write_json(out / f"{slug}.json", records)
        click.echo(f"{slug}: {len(records)} records → {out / f'{slug}.json'}")
    write_json(
        out / "report.json",
        {
            "as_of": as_of,
            "issues": [vars(issue) for issue in result.issues],
            "unmatched_sheets": result.unmatched_sheets,
        },
    )
    if result.unmatched_sheets:
        click.echo(f"unmatched sheets: {', '.join(result.unmatched_sheets)}")
    click.echo(f"{len(result.issues)} conversion issue(s) → {out / 'report.json'}")


def _current_state(data_dir, log_path):
    """Load collections and replay the log (if given) so we work on current values."""
    from bepress_importer.wrangle.changelog import ChangeLog
    from bepress_importer.wrangle.session import load_collections, replayed_state

    collections = load_collections(data_dir)
    log = ChangeLog.load(log_path) if log_path else ChangeLog()
    wrangled, conflicts = replayed_state(collections, log)
    if conflicts:
        for c in conflicts:
            click.echo(
                f"conflict: Change {c.change_id} on record {c.record_id} {c.field}: "
                f"expected {c.expected!r}, found {c.found!r}", err=True
            )
        raise click.ClickException(
            "wrangling log does not replay cleanly over this data (see conflicts above)"
        )
    return collections, log, wrangled


def _findings_for(wrangled, rule_names, record_id, as_of):
    from bepress_importer.wrangle.rules import run_rules
    from bepress_importer.wrangle.session import flatten

    findings = run_rules(
        flatten(wrangled), names=list(rule_names) or None,
        as_of=as_of or datetime.date.today().isoformat(),  # noqa: DTZ011
    )
    if record_id:
        findings = [f for f in findings if f.record_id == record_id]
    return findings


@cli.command()
@click.argument("data_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--log", "log_path", type=click.Path(dir_okay=False),
              help="Wrangling log to replay before checking (checks current state).")
@click.option("--rule", "rule_names", multiple=True)
@click.option("--record", "record_id", default=None)
@click.option("--as-of", default=None)
def check(data_dir, log_path, rule_names, record_id, as_of) -> None:
    """Run validation rules read-only; exit 1 if there are findings."""
    from bepress_importer.wrangle.session import render_finding

    _, _, wrangled = _current_state(data_dir, log_path)
    findings = _findings_for(wrangled, rule_names, record_id, as_of)
    for finding in findings:
        click.echo(render_finding(finding))
        click.echo()
    click.echo(f"{len(findings)} finding(s)")
    if findings:
        raise SystemExit(1)


@cli.command()
@click.argument("data_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--log", "log_path", required=True, type=click.Path(dir_okay=False))
@click.option("-o", "--output", "output_dir", required=True, type=click.Path(file_okay=False))
@click.option("--rule", "rule_names", multiple=True)
@click.option("--record", "record_id", default=None)
@click.option("--yes", is_flag=True, help="Accept every proposed fix without prompting.")
@click.option("--as-of", default=None)
def fix(data_dir, log_path, output_dir, rule_names, record_id, yes, as_of) -> None:
    """Interactively accept proposed fixes; log them and regenerate the output."""
    from bepress_importer.wrangle.session import (
        now_iso,
        run_fix_session,
        save_log,
        titles_of,
        write_outputs,
    )

    collections, log, wrangled = _current_state(data_dir, log_path)
    findings = _findings_for(wrangled, rule_names, record_id, as_of)
    accepted, skipped = run_fix_session(findings, log, at=now_iso(), accept_all=yes)
    save_log(log_path, log, titles_of(collections))
    write_outputs(output_dir, collections, log)
    click.echo(f"{accepted} change(s) applied, {skipped} skipped → {output_dir}")


@cli.command()
@click.argument("data_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--log", "log_path", required=True, type=click.Path(dir_okay=False))
@click.option("-o", "--output", "output_dir", required=True, type=click.Path(file_okay=False))
@click.option("--record", "record_id", required=True)
@click.option("--field", "field_pointer", required=True)
@click.option("--set", "set_value", default=None, help="New string value.")
@click.option("--set-json", "set_json", default=None, help="New value as JSON.")
@click.option("--unset", is_flag=True, help="Remove the field.")
@click.option("--note", default=None)
def edit(data_dir, log_path, output_dir, record_id, field_pointer, set_value, set_json,
         unset, note) -> None:
    """Make one logged manual change to one record."""
    import json as json_module

    from bepress_importer.convert import get_pointer
    from bepress_importer.wrangle.rules import record_id_of
    from bepress_importer.wrangle.session import (
        flatten,
        now_iso,
        save_log,
        titles_of,
        write_outputs,
    )

    if sum(bool(x) for x in (set_value is not None, set_json is not None, unset)) != 1:
        raise click.ClickException("Provide exactly one of --set, --set-json or --unset")
    collections, log, wrangled = _current_state(data_dir, log_path)
    record = next(
        (r for r in flatten(wrangled) if record_id_of(r) == record_id), None
    )
    if record is None:
        raise click.ClickException(f"No record with import-recid {record_id!r}")
    before = get_pointer(record, field_pointer)
    if unset:
        after = None
    elif set_json is not None:
        try:
            after = json_module.loads(set_json)
        except json_module.JSONDecodeError as exc:
            raise click.ClickException(f"--set-json is not valid JSON: {exc}") from exc
    else:
        after = set_value
    change = log.append_change(
        record_id, field_pointer, before=before, after=after, at=now_iso(),
        rule="manual", note=note,
    )
    save_log(log_path, log, titles_of(collections))
    write_outputs(output_dir, collections, log)
    click.echo(f"Change {change.id} recorded: {record_id} {field_pointer}")


@cli.command()
@click.argument("data_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--log", "log_path", required=True, type=click.Path(dir_okay=False))
@click.option("-o", "--output", "output_dir", required=True, type=click.Path(file_okay=False))
def apply(data_dir, log_path, output_dir) -> None:
    """Replay the wrangling log over converter output; exit 1 on conflicts."""
    from bepress_importer.wrangle.session import write_outputs

    collections, log, _ = _current_state(data_dir, log_path)
    write_outputs(output_dir, collections, log)
    click.echo(f"{len(log.changes)} event(s) replayed → {output_dir}")


@cli.command()
@click.option("--log", "log_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--record", "record_id", default=None)
@click.option("--field", "field_pointer", default=None)
def history(log_path, record_id, field_pointer) -> None:
    """Show the change history, optionally filtered by record or field."""
    from bepress_importer.wrangle.changelog import ChangeLog, summarize

    log = ChangeLog.load(log_path)
    changes = log.changes
    if record_id:
        changes = [c for c in changes if c.record_id == record_id]
    if field_pointer:
        changes = [c for c in changes if c.field == field_pointer]
    filtered = ChangeLog(changes=list(changes), schema_version=log.schema_version)
    output = summarize(filtered)
    click.echo(output if output else "(no changes)")


@cli.command()
@click.option("--log", "log_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--change", "change_id", type=int, default=None)
@click.option("--cascade", is_flag=True)
@click.option("--record", "record_id", default=None)
def undo(log_path, change_id, cascade, record_id) -> None:
    """Revert one change (by id) or every live change on a record.

    Appends revert events; run `apply` afterwards to regenerate output files.
    """
    from bepress_importer.wrangle.changelog import ChangeLog, UndoError, summarize
    from bepress_importer.wrangle.session import now_iso

    if (change_id is None) == (record_id is None):
        raise click.ClickException("Provide exactly one of --change or --record")
    log = ChangeLog.load(log_path)
    try:
        if change_id is not None:
            reverts = log.undo_change(change_id, at=now_iso(), cascade=cascade)
        else:
            reverts = log.undo_record(record_id, at=now_iso())
    except UndoError as exc:
        raise click.ClickException(str(exc)) from exc
    log.save(log_path)
    summary_path = Path(log_path).with_suffix(".log")
    summary_path.write_text(summarize(log), encoding="utf-8")
    click.echo(f"{len(reverts)} revert event(s) appended; run `apply` to regenerate output")


@cli.group()
def vocab() -> None:
    """Vocabulary snapshot management."""


@vocab.command("sync")
@click.option("--api-url", default="https://works.hcommons.org", show_default=True)
@click.option("--dest", "dest_dir", default=None,
              help="Write snapshots here instead of the packaged vocab directory.")
def vocab_sync_cmd(api_url, dest_dir) -> None:
    """Refresh vocabulary snapshots from a live KC Works instance."""
    from bepress_importer.vocab import VOCAB_DIR
    from bepress_importer.vocab_sync import sync_vocabularies

    counts = sync_vocabularies(api_url, vocab_dir=dest_dir or VOCAB_DIR)
    for name, count in counts.items():
        click.echo(f"{name}: {count} ids")


@cli.command()
@click.argument("metadata_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--collection-id", required=True)
@click.option("--api-url", default=None,
              help="Base URL (default: $KCWORKS_IMPORT_API_URL or https://works.hcommons.org).")
@click.option("--api-key-env", default=None,
              help="Environment variable holding the bearer token "
                   "(default: KCWORKS_IMPORT_API_KEY).")
@click.option("--api-key-file", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Read the bearer token from this file instead.")
@click.option("--receipts", "receipts_path", type=click.Path(dir_okay=False), default=None,
              help="Where to write per-record receipts (default: <metadata>.receipts.json).")
@click.option("--dry-run", is_flag=True, help="Validate and describe the request; POST nothing.")
@click.option("--notify-record-owners", is_flag=True)
@click.option("--review-required/--no-review-required", "review_required", default=None)
@click.option("--strict-validation/--no-strict-validation", "strict_validation", default=None)
def upload(metadata_file, collection_id, api_url, api_key_env, api_key_file, receipts_path,
           dry_run, notify_record_owners, review_required, strict_validation) -> None:
    """Upload a finished per-collection JSON file to the KC Works Import API."""
    raise NotImplementedError
