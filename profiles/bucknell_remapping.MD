# Bucknell profile remapping report

Applied to `profiles/bucknell.toml` from the client mapping instructions
document (`bucknell_mapping.odt`, received 2026-08). Every change to the
mapping is listed below, followed by the points that need clarification.
Where the instructions confirmed what the profile already did, that is noted
too, so this report is a complete account of how the instructions were
handled.

## Conventions adopted (from the instructions' general notes)

- **Nested custom fields keep both namespace words**: `thesis:thesis`,
  `journal:journal`, `imprint:imprint`. This corrected a latent error: the
  profile previously wrote `custom_fields.thesis:university`, which is not a
  valid field — it is now `custom_fields.thesis:thesis.university`.
- **`kcr:publication_url` is reserved for the larger publication** (the
  journal, series or podcast as a whole). All work-level URLs now go to
  `metadata.identifiers` (scheme `url`). After this remapping, **no sheet
  maps `kcr:publication_url` at all** — none of the source columns identified
  so far holds a series-level URL.

## Changes by sheet

### Fac Journal Articles

| Column | Before | After |
|---|---|---|
| `pub_link` | `custom_fields.kcr:publication_url` | `metadata.identifiers` (scheme `url`; non-URL values are dropped and logged) |
| `comments` | not imported | `metadata.additional_descriptions` (type `other`, HTML stripped) |
| `custom_citation` | not imported | `metadata.additional_descriptions` (type `other`) — per instruction, "just to not lose the data" |
| `pub_statement` | not imported | `metadata.copyright` (HTML stripped) |

Unchanged, as confirmed by the instructions: journal columns →
`journal:journal.{title, volume, issue}` (plus `pages`, which the profile
already built from `fpage`/`lpage`); `embargo_date` → `access.embargo`.

### Masters Theses and Honors Theses (identical changes to both)

| Column | Before | After |
|---|---|---|
| `department` | `custom_fields.kcr:institution_department` | `custom_fields.thesis:thesis.department` |
| `department2` | Masters: `kcr:sponsoring_institution`; Honors: not imported | `custom_fields.kcr:institution_department` |
| `degree_name` | `custom_fields.kcr:degree` | `custom_fields.thesis:thesis.type` |
| `authorN_institution` | creator affiliations only | **also** `custom_fields.thesis:thesis.university`, taken from the first author slot (1–5) with a non-empty institution, defaulting to "Bucknell University" when none is present (the previous hard-coded constant is removed) |
| `concentration` | not imported | merged into the `disciplines` value → `custom_fields.kcr:discipline` |
| `disciplines` | already comma-demarcated to `kcr:discipline` | unchanged (instruction confirmed), now with `concentration` appended |
| `multimedia_format` | not imported | `custom_fields.kcr:media` (list) |
| `comments` (Honors) | not imported (Masters already mapped) | `metadata.additional_descriptions` (type `other`) on both sheets |

### BU Authored Books

| Column | Before | After |
|---|---|---|
| `buy_link` | `custom_fields.kcr:publication_url` | `metadata.related_identifiers` (scheme `url`, relation `isdescribedby` — see question 5) |
| `comments` | not imported | `metadata.additional_descriptions` (type `other`) |

Unchanged: `city` → `imprint:imprint.place` (instruction confirmed);
`identifier` → ISBN identifier; `publisher` → `metadata.publisher`;
`department` → `kcr:institution_department` (see question 8).

### Bu Press

| Column | Before | After |
|---|---|---|
| `buy_link` | `custom_fields.kcr:publication_url` | `metadata.related_identifiers` (scheme `url`, relation `isdescribedby`) |
| `rights` | not imported | **two** mappings: the free text → `metadata.copyright` (HTML/whitespace cleaned), and its presence → `metadata.rights` = the "All rights reserved" licence (`arr`) |
| `bu_type` | not imported | `custom_fields.kcr:user_defined_tags` as a namespaced tag, e.g. `"bu_type: text; 226 pages"` |
| `multimedia_format` | not imported | `custom_fields.kcr:media` |
| `create_openurl` | not imported | still not imported — following the instruction's suggestion to rely on `access.files` permissions rather than a tag |

### BU Digital Scholarship

| Column | Before | After |
|---|---|---|
| `fulltext_url` | `custom_fields.kcr:publication_url` | `metadata.identifiers` (scheme `url`) — note the instruction's caveat that these should be URLs that persist after migration; the column is empty in the current export, so nothing is affected yet |
| `custom_citation` | not imported | `metadata.additional_descriptions` (type `other`) |
| `copyright_note` | not imported | `metadata.copyright` (empty in the current export, mapped per the "might map if there is anything" instruction) |
| `multimedia_format` | not imported | `custom_fields.kcr:media` |

### Student Digital Projects (DSSRF)

| Column | Before | After |
|---|---|---|
| `multimedia_url` | `custom_fields.kcr:publication_url` | `metadata.identifiers` (scheme `url`) — these URLs are the projects themselves (ArcGIS/Scalar sites), so they are work-level identifiers |
| `custom_citation` | not imported | `metadata.additional_descriptions` (type `other`) |
| `rights` | not imported | `metadata.copyright` (see question 4 about the `arr` licence) |
| `multimedia_format` | not imported | `custom_fields.kcr:media` |

### BU Podcasts

| Column | Before | After |
|---|---|---|
| `multimedia_url` | `custom_fields.kcr:publication_url` | `metadata.identifiers` (scheme `url`) — the Kaltura links are the episodes themselves |
| `duration` | not imported | `metadata.sizes` (free-text list, e.g. `["00:25:14"]`) |
| `rights` | not imported | `metadata.copyright` (see question 4) |
| `multimedia_format` | not imported | `custom_fields.kcr:media` |
| `contributor` | not imported | still not imported — see question 6 |

## Still deliberately not imported

`ctmtime` (see question 1), `open_access` (workflow flag),
Fac Journal `department2` (see question 8), theses and Bu Press
`multimedia_url` (see questions 2–3), `create_openurl`, `update_reason`,
`cover_image_url` (empty), Podcasts `contributor` (question 6).

## Clarifying questions

1. **`ctmtime`**: the instruction says to map it to the record's top-level
   `created` timestamp *"if this is record creation time"*. It does not
   appear to be: the values are Unix epochs clustered around May 2023 on
   records published in 2011, so this looks like Bepress's **last-modified**
   time, not creation. We have left it unmapped. Should we (a) leave it out,
   (b) import it as `created` anyway, or (c) put it somewhere else (e.g. a
   dates entry typed "updated")?

2. **Theses `multimedia_url`**: values are a mix of junk (the literal string
   "Author"), Kaltura short links and YouTube links — apparently recordings
   *about* the thesis (defence/presentation?) rather than the thesis itself.
   Under the "work itself vs. overall series" rule neither case clearly
   applies. Should these become work-level `url` identifiers (junk would be
   dropped automatically), or stay unimported?

3. **Bu Press `multimedia_url`**: four values, mixing bare dates
   ("07/14/2023") with publisher catalogue URLs. Same question as 2; the
   catalogue URLs might belong with `buy_link` as related identifiers.

4. **`rights` vs. `distribution_license` conflict (DSSRF and Podcasts)**:
   the instruction says to use the "All rights reserved" licence for all
   `rights` entries. But DSSRF and Podcasts rows *also* carry a Creative
   Commons licence in `distribution_license` (mapped to `metadata.rights`),
   and CC-licensed and all-rights-reserved are contradictory. We applied
   `arr` only on **Bu Press** (which has no distribution licence data) and
   mapped the free text to `metadata.copyright` everywhere. Should rows
   with a CC licence really get `arr` as well?

5. **`buy_link` relation type**: the instruction offers `related_identifiers`
   with relation "Describes"? "Is version of"?, or plain `identifiers`. We
   chose `related_identifiers` with relation `isdescribedby` (the publisher
   page describes the work; from the work's perspective the work *is
   described by* that URL). Happy to switch to `isversionof` — arguably the
   publisher's edition *is a version of* the deposited work — or to plain
   `url` identifiers if preferred.

6. **Podcasts `contributor`**: values mix bare personal names
   ("David Roediger"), name-plus-affiliation ("Adam Goodman, University of
   Illinois -- Chicago") and multi-person lists ("Elaine Lac, Amanda Wooden,
   Steve Buonopane, Dina El-Mogazi"). Because commas serve as both name
   separators and affiliation separators, automatic parsing would guess
   wrong. Options: (a) leave unimported, (b) import each whole string as a
   single contributor name, (c) hand-curate via the wrangler after import.
   Currently (a).

7. **`metadata.copyright`**: this field is not in the KC Works v12 metadata
   documentation we built against (we understand it arrives with the
   Invenio 13 upgrade mentioned in the instructions). The mappings are in
   place as instructed; please confirm the import API will accept the field,
   or whether it should be held back until after the upgrade.

8. **`department` for non-thesis types**: the instruction allows
   `kcr:institution_department` **or** `kcr:sponsoring_institution`. We kept
   `kcr:institution_department` everywhere outside theses (and Fac Journal
   `department2` remains unimported, since the department2 instruction was
   scoped to theses). Confirm, or tell us which sheets should use
   `sponsoring_institution` — and whether Fac Journal `department2` should
   now also go to `kcr:institution_department` in the way thesis
   `department2` does.

## Verification

Converted the full Bucknell export with the revised profile: all 3,633
records convert with zero conversion issues; the conversion log records
17,164 value changes (up from 14,916, reflecting the newly imported
columns); `check` reports the same 16 pre-existing data-quality findings
(broken DOIs, two name fixes) — no new findings introduced by the
remapping. The full test suite (291 tests) passes.
