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

## The conversion log

`convert` writes a client-inspectable provenance log next to its output, in
two forms: `conversion-log.json` (precise) and `conversion-log.txt` (human
readable). It records, per sheet, every mapping rule applied — which column
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

Transforms available to profiles: `edtf_date` (with season support),
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
- The Import API's `all_or_none` is always true server-side: drive `check`
  findings to zero before uploading; per-collection files keep the blast
  radius contained.
