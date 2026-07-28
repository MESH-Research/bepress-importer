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
