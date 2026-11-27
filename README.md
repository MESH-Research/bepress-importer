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
A receipts file left by an earlier run is never overwritten: it is first
renamed with the time it was written, e.g.
`fac_journ.receipts.20261126-143210.json`, and the new run then writes its own.

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

`upload-client` can also split a large file across several requests:

```sh
uv run bepress-importer upload-client wrangled/fac_journ.json --collection-id <id> --batch 20
```

`--batch N` sends the records `N` at a time, in file order, one request per
batch (the last batch carries whatever is left). Without it the whole file
goes in one request.

- Each batch is a separate import, so `--all-or-none` holds within a batch
  and not across the file: batches that have already gone through stay
  imported if a later one fails.
- Every batch is sent whatever happened to the ones before it, so a single
  run surfaces the validation errors of every batch that fails. A rejected
  batch, or one that gets no response, leaves gaps: the other batches are
  still imported.
- One line is printed per batch, then a summary. The receipts file covers
  every batch that got a response (a batch with no response leaves no entries
  for its records), and the exit code is non-zero unless every batch was
  imported in full.
- With `--debug`, each batch saves its own replay payload
  (`<file>.batch-N.payload.json`).

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
`identifier` (DOI normalization, segment splitting; `doi_references` turns a
resolver link into a DOI, `find_url` recovers the link from a messy cell,
`unproxy` strips a library proxy from the host), `doi_mention` (a DOI typed
into some other cell), `publisher`, `rights_statement`,
`misplaced_description`, `plain_text`, `split` (one separator or several),
`strip_html`, `additional_description`, `url`, `embargo`, `language_list`,
`license_url`.
Composite builders: `authorN_*` columns → `creators` (corporate detection
included; `json_column` names a JSON author list to read corporate authors
from), advisor columns → `contributors`, journal/imprint column groups →
`journal:journal` / `imprint:imprint` custom fields (page, volume and issue
cells that hold remarks instead of numbers are left out and reported).

### Existing DOIs and publishers

KC Works registers a DOI for every imported record that does not bring one,
and refuses to do so without `metadata.publisher`. Two profile features
address this:

```toml
[defaults.doi_pid]
provider = "external"       # keep_identifiers = true also leaves the entries in identifiers
```

moves each record's own DOI out of `metadata.identifiers` into
`pids.doi` (`{"identifier": "10.…", "provider": "external"}`), in bare form.
A DOI claimed by several records is registered for none of them and reported.

```toml
[[sheet.field]]
source = "publisher"
target = "/metadata/publisher"
transform = "publisher"
args = { statement_columns = ["pub_statement"], doi_columns = ["doi"], link_columns = ["pub_link"] }
```

fills an empty publisher from a copyright statement that names one, the
DOI's prefix or the link's host, using the list in
`src/bepress_importer/vocab/publishers.toml` (add publishers there, not in
code). `fallback = "…"` names a publisher for rows nothing identifies.

### ROR ids for affiliations

```toml
[defaults.affiliations]
ror_lookup = true            # look the others up in the ROR API

  [defaults.affiliations.ror_ids]
  "00fc1qt65" = ["Bucknell University", "Bucknell", "Bucknell U"]
```

A creator's affiliation is written as `{"id": "<ror id>"}` in place of
`{"name": "…"}` when an organisation can be settled on:

- **ids fixed in the profile** (`ror_ids`) are applied without any lookup, to
  an affiliation that is one of the listed names or has one as a
  comma-separated part (`Biology Department, Bucknell University`);
- **every other affiliation**, when `ror_lookup` is on, is put to the ROR
  API's [affiliation matcher](https://ror.readme.io/v2/docs/api-affiliation).
  Of the organisations it returns (up to ten), one is taken when **every
  word of the affiliation text is in its name**, or when the text is its
  whole name followed by words from its place (city, region, country):
  `University of Minnesota - Duluth` → University of Minnesota, Duluth;
  `Colorado State University - Fort Collins` → Colorado State University.
  A text no result answers to stays as text.

The details of that rule:

- words are compared without case, accents or punctuation, and `&` is "and";
- `the`, `at`, `main` and `campus` are passed over, in the text and in the
  name (`The Pennsylvania State University`, `University of Illinois at
  Urbana-Champaign`, `University of Pittsburgh - Main Campus`);
- a single word is taken only when it is the organisation's whole name
  (`TRIUMF`). `Exeter` is not enough to pick Phillips Exeter Academy by;
- a name is the organisation's display name or a label in another language.
  Aliases and acronyms do not count, because organisations share them
  (`NC State` is an alias of North Central State College);
- ROR's own `chosen` flag and score are not used: its first choice for
  `University of Minnesota - Duluth` is the Twin Cities university;
- when several results have all the words, the name with the fewest other
  words wins (`Miami University` is not the University of Miami);
- two results that match equally well (ROR has two organisations called
  `University of Georgia`) are not chosen between: the text stays;
- a place cannot stand in for part of the name (`NC State` is not
  Appalachian State University, although NC is where it is).

Each replacement is one line in the conversion log, with the original text
and the organisation it was matched to. An institution the rule leaves as
text can be confirmed by hand and added to `ror_ids`.

Lookups are remembered in a SQLite file (`--ror-cache`, default
`ror-cache.sqlite3`; table `affiliation_lookup`). The whole answer is kept,
including answers with no organisation, so each text is asked about once, a
re-run is offline and byte-identical, and the rule can change without asking
again. A lookup that fails (network down, rate limit that does not clear) is
reported, left as text and tried again on the next run.
`convert --no-ror-lookup` never contacts the API: it uses the profile's ids
and whatever the cache already holds. Only the affiliation text is sent to
ROR.

`rights_statement` keeps a statement out of `metadata.copyright` unless it
reads as one; `misplaced_description` can route such prose to the
description instead. `profiles/bucknell_import_readiness.MD` records how
these were applied to the Bucknell inventory and what the output looks like
before and after.

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
