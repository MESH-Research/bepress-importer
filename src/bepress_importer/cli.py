"""bpress-importer command line interface."""

from __future__ import annotations

import click


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
    raise NotImplementedError


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
    raise NotImplementedError
