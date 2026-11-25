# bepress-importer

Convert Bepress (Digital Commons) batch exports into KC Works (InvenioRDM)
import JSON, clean the metadata through an auditable wrangling workflow, and
upload the result to the KC Works Import API.

## Install

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run bepress-importer --help
```

## Pipeline overview

```
export.xls ──convert──▶ converted/*.json ──check/fix/edit──▶ wrangled/*.json ──upload──▶ KC Works
                              ▲                   │
                              │             wrangling.json  (append-only change log)
                              └────apply──────────┘ wrangling.log (human-readable summary)
```

The converter output is **immutable**; every correction is an event in
`wrangling.json` and the wrangled output is **derived** by replaying that log.
Nothing is ever silently erased: undo appends *revert* events, and the full
history of every field survives for audit.

## Runbook

```sh
# 1. See what is in the export and how well the profile covers it
uv run bepress-importer inspect "Data/Export.xls" --profile profiles/bucknell.toml

# 2. Convert to per-collection KC Works JSON (one file per sheet/collection).
#    Pass --as-of for byte-reproducible output (embargo decisions).
uv run bepress-importer convert "Data/Export.xls" \
    --profile profiles/bucknell.toml -o converted --as-of 2026-07-28

# 2b. Content Inventory exports need an inventory profile. The converter
#     checks the profile against the export's columns and refuses a mismatch
#     (pointing at the sibling profile that does match), so passing a
#     collection profile for an inventory export fails loudly instead of
#     silently converting nothing.
uv run bepress-importer convert "Data/Inventory.xlsx" \
    --profile profiles/inventory-bucknell.toml -o converted --as-of 2026-07-28

# 2c. Inspect one record straight from the export — e.g. an id from the
#     issues at the top of report.json / conversion-log.txt. Prints the
#     record's KC Works JSON with required-but-empty fields marked "MISSING"
#     (highlighted red in a terminal); --plain emits one line of unstyled
#     JSON for piping. Works even for rows the conversion excludes
#     (withdrawn/pending), with the reason on stderr.
uv run bepress-importer show "Data/Inventory.xlsx" \
    --profile profiles/inventory-bucknell.toml --record 5523024

# 3. Validate against KC Works vocabularies and field rules (read-only)
uv run bepress-importer check converted --as-of 2026-07-28

# 4. Interactively accept proposed fixes (y/n/a=all for rule/s=skip rule/q=quit).
#    Accepted changes are appended to wrangling.json and wrangled/ is regenerated.
uv run bepress-importer fix converted --log wrangling.json -o wrangled --as-of 2026-07-28

# 5. Fix the stragglers by hand — equally logged
uv run bepress-importer edit converted --log wrangling.json -o wrangled \
    --record 11805300 --field /metadata/identifiers/2 --unset --note "junk DOI"

# 6. Review the history at any time
uv run bepress-importer history --log wrangling.json [--record ID] [--field PTR]
cat wrangling.log        # the same story as plaintext, one line per change

# 7. Undo, if needed (appends revert events; then re-apply)
uv run bepress-importer undo --log wrangling.json --change 7            # head of its chain
uv run bepress-importer undo --log wrangling.json --change 3 --cascade  # + everything above it
uv run bepress-importer undo --log wrangling.json --record 11805300     # whole record
uv run bepress-importer apply converted --log wrangling.json -o wrangled

# 8. Upload one collection at a time (each file targets one KC Works collection)
export KCWORKS_IMPORT_API_KEY=...   # never passed on the command line
uv run bepress-importer upload wrangled/fac_journ.json --collection-id <id> --dry-run
uv run bepress-importer upload wrangled/fac_journ.json --collection-id <id>
```

`upload` writes `<file>.receipts.json` mapping each record's `import-recid` to
the created KC Works record URL (or its per-field errors on failure).

`upload-client` is a drop-in alternative that sends the same file through
MESH's [`kcworks-import-client`](https://github.com/MESH-Research/kcworks-import-client)
library instead of this tool's own request code:

```sh
uv run bepress-importer upload-client wrangled/fac_journ.json --collection-id <id>
```

It takes the same options as `upload` except `--review-required` and
`--strict-validation`, which the library cannot send (the server defaults,
both true, apply). The library also always sends `id_scheme=import-recid`
and `no_updates=false`, which `upload` leaves to the server.

## Clearing a test import (hard delete)

`hard-delete` permanently removes every record in a collection, through KC
Works' REST
[hard-delete API](https://mesh-research.github.io/knowledge-commons-works/admin_guide/record_hard_delete.html).
It is meant for emptying a collection on dev or staging between test imports.
Hard-deleted records cannot be restored.

```sh
export KCWORKS_HARD_DELETE_API_KEY=...   # not the import key; see below
export KCWORKS_IMPORT_API_URL=https://works.hcommons-staging.org

uv run bepress-importer hard-delete <collection-slug> --yes-i-want-to-run-this
```

- **Confirmation.** Without `--yes-i-want-to-run-this` the command refuses and
  contacts nothing.
- **Production.** When the instance is `works.hcommons.org` (which is also the
  default when neither `--api-url` nor `$KCWORKS_IMPORT_API_URL` is set), it
  refuses unless `--yes-i-want-to-run-this-on-production` is given as well.
- **Its own key.** The token is read from `KCWORKS_HARD_DELETE_API_KEY` (or
  `--api-key-env` / `--api-key-file`); the import key is never used. Create a
  separate token carrying the `records:delete` scope, owned by an account with
  the administration role, and keep one per instance.
- **Sub-collections.** By default only records that sit in the collection
  itself are deleted; a record that also belongs to one of its sub-collections
  is skipped and logged. `--cascade` deletes the records of every
  sub-collection too, at any depth. The collections themselves are never
  removed.
- **Log.** Each record is written to stdout as `DELETED`, `FAILED` (with the
  server's reason) or `SKIPPED`, followed by a summary line; the exit status is
  non-zero if any record failed. Redirect stdout to keep the log.

A record that is also filed in an unrelated collection is deleted from there
too, since it is the record itself that is removed. Records are sent
`--batch-size` at a time (default 25, server maximum 100).

## The conversion log

`convert` writes a client-inspectable provenance log next to its output, in
two forms: `conversion-log.json` (precise) and `conversion-log.txt` (human
readable). Conversion issues (missing required fields, unmapped document
types, unrouted rows) appear **at the top** of the log — and first in
`report.json` — so problems are visible before the mapping documentation.
The log then records, per sheet, every mapping rule applied — which column
went to which KC Works field, how, and why — including the columns
deliberately **not** imported; and then, per record, every value that left
the spreadsheet in a different form than it arrived (dates normalized to
EDTF, DOIs stripped to bare form, keywords split, expired embargoes omitted,
…) with the reason. Both files are deterministic: re-running the same
conversion produces byte-identical logs, so a log can be re-verified at any
time.

## The change log

`wrangling.json` is an ordered, append-only event log. Each change carries:

- `id` — monotonic integer
- `record_id` — the record's `import-recid` (Bepress `context_key`)
- `field` — JSON pointer to the changed value
- `before` / `after` — the values at that pointer only (diffs, never full records)
- `parent` — the previous change to the same field, forming a per-field history
  chain (you cannot revert the middle of a chain without `--cascade`)
- `rule` / `note` / `at` — provenance

`apply` verifies each event's `before` against the current value, so if the
converter improves and you re-convert, drift is reported as conflicts instead
of silently corrupting data. `wrangling.log` is a derived plaintext summary —
one scannable line per change, with explicit wording for removals and reverts.

## Profiles

All sheet→KC Works mapping lives in a TOML profile (see
`profiles/bucknell.toml`). Profiles contain **no logic** — only column names,
JSON-pointer targets, transform names and value maps — so a new client export
means a new profile, not new code.

```sh
uv run bepress-importer inspect "Data/NewClient.xls" --scaffold > profiles/newclient.toml
```

Two Bucknell profiles live in `profiles/`: `bucknell.toml` (multi-sheet
collection export) and `inventory-bucknell.toml` (site-wide Content
Inventory report: one flattened table of every collection keyed on
`context_key`, arriving either as a cp1252 CSV or as a "Content Inventory"
.xlsx workbook whose "Field Names" legend sheet is skipped).

An inventory export mixes every collection in one table, so
`inventory-bucknell.toml` routes rows to per-collection mapping groups with
a `select` declared on each `[[sheet]]` block — pure profile data, nothing
hardcoded:

```toml
[[sheet]]
match = "*"
collection = "masters_theses"
select = { column = "publication", values = ["masters_theses"] }
```

Rows go to the first block whose select matches; a block without a select is
the catch-all. This is how the collection-specific mappings agreed for the
Bucknell collection export (thesis fields, journal groups, press constants,
podcasts…) apply equally to inventory rows, with output split into the same
per-collection files.

An inventory profile also declares `signature_columns`
(`context_key`/`state`/`document_type`); `convert` refuses to run a profile
whose signature the export doesn't carry, and when a profile matches no
sheet at all it fails with a hint at the sibling profile whose signature does
match. Inventory exports include unpublished material, so every group uses a
row filter —

```toml
[sheet.filter]
column = "state"
keep = ["published"]
```

— and the conversion log lists every excluded record id. Several sources may
accumulate into one list target (e.g. `doi` and `isbn` both appending to
`/metadata/identifiers`) by declaring `append = true` on each field.

Transforms available to profiles: `edtf_date` (with season support and
fallback columns for empty cells, e.g. an event's `start_date`),
`identifier` (DOI normalization, segment splitting), `split`, `strip_html`,
`additional_description`, `url`, `embargo`, `language_list`, `license_url`.
Composite builders: `authorN_*` columns → `creators` (corporate detection
included), advisor columns → `contributors`, journal/imprint column groups →
`journal:journal` / `imprint:imprint` custom fields.

## Vocabularies

Validation runs offline against committed snapshots in
`src/bepress_importer/vocab/`. Refresh them from a live instance (the diff is
reviewable before it changes validation behaviour):

```sh
uv run bepress-importer vocab sync --api-url https://works.hcommons.org
```

## Development

Red/green TDD throughout; tests are behavioural (input → output, no
implementation coupling).

```sh
uv run pytest
uv run ruff check
```

## Known caveats

- EDTF level-1 seasons (`2015-21`) are emitted for season-qualified dates; if
  the target instance rejects them, set `season_style = "year-only"` in the
  profile's `[defaults]`.
- The `thesis:university` custom field and `kcr:discipline` cardinality should
  be confirmed against the live instance before a production import.
- Uploads send `all_or_none=true` explicitly by default rather than relying on
  the Import API's default, so one bad record rejects the whole file: drive
  `check` findings to zero before uploading; per-collection files keep the blast
  radius contained. Pass `--no-all-or-none` to `upload` or `upload-client` to
  import the records that pass and get per-record errors for the rest.
