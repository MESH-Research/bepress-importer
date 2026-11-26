# Bucknell Content Inventory: import-readiness change log

What changed in the Content Inventory importer (`profiles/inventory-bucknell.toml`
and the code behind it) to make its output acceptable to the KC Works
streamlined Import API, and how the output differs as a result.

- **Source:** the four workbooks in `Data/Bucknell Final/`
- **Before:** the output as uploaded to staging on 2026-11-26
  (`converted/bucknell-staff-and-faculty.json/fac_journ.json`, 1 of 2,110
  records accepted)
- **After:** `converted/bucknell-final/<workbook>/`, converted with
  `--as-of 2026-11-26`

Every individual value change is recorded, with its reason, in the
`conversion-log.txt` / `conversion-log.json` written next to each output
directory. This document is the summary.

## Why the staging import failed

From `fac_journ.receipts.json`:

| Records | Server message | Cause |
|---:|---|---|
| 2,092 | Missing publisher field required for DOI registration. | KC Works registers a new DOI for every record that does not bring one, and needs `metadata.publisher` to do so. No record had a `pids` block or a publisher. |
| 10 | Invalid DOI identifier. | Cells such as `Unknown` or `10.3390` were exported with `scheme: doi`. |
| 7 | Invalid resource type | The cleaned export uses KC Works type names (`poeticWork`, `review`, `essay`…) that the profile's map did not list. |
| 1 | Missing data for required field (title) | Record 3071353. The title is present; at 263 characters it is the longest in the file. See open items. |

## What changed

### 1. Existing DOIs go to `pids.doi`

A record's own DOI is now written as

```json
"pids": {"doi": {"identifier": "10.1016/j.jmps.2018.02.012", "provider": "external"}}
```

and removed from `metadata.identifiers`. Enabled per profile with
`[defaults.doi_pid]`; `keep_identifiers = true` there keeps the identifier
entries as well.

A DOI is recognised in:

- the `doi` column, in any form (`10.…`, `doi:10.…`, `https://doi.org/…`,
  `http://dx.doi.org/…`, with or without scheme, with trailing punctuation,
  landing-page suffixes such as `/abstract` or `/full`, or leftover markup);
- the `pub_link` column, when the link is a DOI resolver address;
- the `volnum` / `issnum` columns, where a few rows have
  `Online First: doi:10…` typed in place of a number.

The identifier is reduced to the bare DOI. Where the `doi` column and a link
give the same DOI, the `doi` column's spelling is used.

Deliberately **not** promoted:

- a DOI that appears only inside a publisher landing-page URL
  (`https://onlinelibrary.wiley.com/doi/10.…/full`). The link is kept as a
  `url` identifier. 108 `fac_journ` rows are in this position; the DOI is
  still used to identify the publisher.
- a DOI given for more than one record. One DOI cannot identify two records,
  so neither gets it; each keeps it as an `https://doi.org/…` link and an
  issue is raised. Three pairs: 3257770/13564096, 28345075/33304211,
  12633636/12633637.
- anything that cannot be read as a DOI. It is omitted and raised as an issue
  rather than exported under `scheme: doi`.

Other identifier fixes: about 300 scheme-less `dx.doi.org/…` links that were
previously dropped as "not a URL" are now read; a PubMed id typed into the
`doi` cell becomes a PubMed link; the first link is recovered from cells with
stray text or a broken scheme; `ezproxy.bucknell.edu` is removed from link
hosts so the link works outside Bucknell; repeated identifiers are collapsed.

### 2. Publisher

`metadata.publisher` is the `publisher` column when filled. Otherwise it is
inferred, in this order of trust:

1. **the copyright statement** names a known publisher ("…directly from
   Taylor & Francis…", "© 2019 IEEE", "…published by Wiley…");
2. **the DOI prefix** belongs to a known publisher (`10.1016` → Elsevier);
3. **the link** points at a known publisher's platform (`tandfonline.com`).

The list is data, in `src/bepress_importer/vocab/publishers.toml`: about 150
academic publishers, each with the phrases and acronyms that name it, its DOI
prefixes and its hosts. Aggregators (JSTOR, Project MUSE, PubMed, PsycNET,
ResearchGate, EBSCO, ProQuest) are deliberately absent, since they identify
no publisher.

Steps 2 and 3 go beyond the copyright-string rule that was asked for. They
are there because only 56 `fac_journ` rows have a copyright statement at all,
and are switched per profile field (`doi_columns`, `link_columns`). In
`fac_journ` the 1,385 publishers came from: DOI prefix 1,236, link host 110,
copyright statement 39.

Bucknell's own work has no outside publisher, so the profile sets
`"Bucknell University"` as a constant for master's and honors theses, DSSRF
projects, the digital-scholarship project and the Bucknell: Occupied podcast.
BU Press records already carried "Bucknell University Press".

### 3. Copyright holds only rights statements

`pub_statement` is imported as `metadata.copyright` only when it reads as a
copyright, licence, permission, access or version statement. Four
`fac_journ` values failed that test:

| Record | Value | Now |
|---|---|---|
| 9579056 | the article's abstract | moved to `metadata.description` (the abstract column was empty) |
| 11695990 | a journal-issue blurb | moved to `metadata.description` |
| 8179766 | `Unsure` | omitted |
| 15075310 | `Teaching Children Mathematics` | omitted |

The remaining 56 values were read through in full and are all rights or
version statements. Two are long (Emerald's deposit-licence text on 38010585,
and BU Press 38404910) but are what they claim to be.

### 4. Document types

The resource-type maps now accept the KC Works type names used in the cleaned
export (`journalArticle`, `poeticWork`, `review`, `essay`, `book`,
`bookSection`, `interactiveResource`, `videoRecording`, `conferencePoster`…)
alongside the Digital Commons names.

### 5. Sanity fixes found by reading the output

| Problem in the output | Fix |
|---|---|
| Titles containing `<em>`, `<sub>`, doubled spaces | titles reduced to plain text without breaking words (`H<sub>2</sub>S` → `H2S`) |
| Keywords typed with `;` imported as one long tag | keywords split on `,` and `;` |
| Page cells holding paragraphs of article text, a URL, "not applicable", "Advance Article" | left out of `journal:journal.pages`, raised as issues |
| Volume/issue cells holding "Online; print edition forthcoming", a journal name, a DOI | left out, raised as issues (a DOI found there is used, see 1) |
| Newsletters and one report with no creators | corporate authors exist only in the `authors` JSON column; now read from there as organizational creators |
| `Bugniazet, Megan, '20` | a class year in the suffix column is not part of the name |
| An email address as an author's affiliation | not an affiliation |
| 18 student journal items with no publication date | the date posted to Digital Commons is used, and logged as such |

### 6. ROR ids for creator affiliations

A creator's affiliation is now `{"id": "<ror id>"}` instead of
`{"name": "…"}` wherever the institution is certain. Each replacement is a
line in the conversion log against its `authorN_institution` column, with the
original text and the organisation matched.

- **Bucknell is fixed in the profile** as `00fc1qt65` and never looked up:
  "Bucknell University", "Bucknell", "Bucknell U", "Bucknell Univ", alone or
  after a department ("Biology Department, Bucknell University"). The
  Geisinger-Bucknell Autism and Developmental Medicine Institute is a
  different body and is not treated as Bucknell.
- **Every other affiliation is put to the ROR API.** Of the organisations
  it returns, one is taken when every word of the text is in its name, or
  when the text is its whole name followed by words from its place.
  Otherwise the text stays. Aliases and acronyms do not count, and ROR's own
  "chosen" flag is not used.

ROR's chosen flag was tried first and dropped. At full score it returned
North Central State College for "NC State", the University of California
System for "University of California - Berkeley" and the Twin Cities
university for "University of Minnesota - Duluth". The word rule takes
Berkeley and Duluth from further down ROR's list and leaves "NC State" alone.

| | Affiliations | Distinct texts |
|---|---:|---:|
| Bucknell, fixed id | 4,969 | 8 |
| ROR id: the text is the organisation's name | 1,280 | 403 |
| ROR id: every word is in a longer name | 40 | 23 |
| ROR id: the name followed by its place | 93 | 29 |
| Left as text: a word no result has | 482 | 210 |
| Left as text: two results match equally | 20 | 11 |
| Left as text: ROR returned nothing | 53 | 26 |

Matches to look at, because the text is shorter than the name it was
matched to: "Exeter" → Phillips Exeter Academy (the only result ROR
returned); "Université Paris" → Université Paris 8; "University of
Tennessee" → University of Tennessee at Knoxville.

The most frequent texts left as text, which could be confirmed and added to
`ror_ids` in the profile: "University of Illinois at Urbana-Champaign" (36,
the name in ROR has no "at"), "Penn State University" (29, an alias), "The
Pennsylvania State University" (28, the name in ROR has no "The"), "SUNY
University at Buffalo" (10), "University of New Hampshire - Main Campus"
(10). Texts with two equal results include "York University", "University of
Georgia", "Northeastern University" and "National Institutes of Health".

Lookups are cached in `ror-cache.sqlite3` (git-ignored), so a re-run makes no
requests and is byte-identical. The before/after tables below were taken
before this change and do not count it; it touches every record with an
affiliation.

## How the output differs

### `fac_journ.json` (2,118 records, 1,538 changed)

| | Before | After |
|---|---:|---:|
| Records with `pids.doi` | 0 | 1,253 |
| `doi`-scheme entries in `identifiers` | 947 | 0 |
| `url` identifiers | 1,209 | 911 |
| …of which `doi.org` links | 318 | 4 (the shared DOIs) |
| Records with `publisher` | 0 | 1,385 |
| **Records with neither DOI nor publisher** | **2,118** | **642** |
| Records with `copyright` | 60 | 56 |
| Records with `description` | 1,761 | 1,763 |
| Titles with markup or doubled spaces | 62 | 0 |
| Tags containing `;` | 26 | 0 |
| User tags | 6,886 | 6,997 |
| Proxied links | 5 | 0 |
| Organizational creators | 0 | 3 |

### Other files

| File | Records | Changed | Neither DOI nor publisher | Other |
|---|---:|---:|---|---|
| Faculty `inventory.json` | 751 | 272 | 748 → 600 | `pids.doi` 0 → 27; publisher 3 → 151; no creators 4 → 0 |
| Faculty `books.json` | 157 | 10 | 1 → 1 | titles and tags tidied |
| `bucknell-occupied.json` | 28 | 28 | 28 → 0 | publisher constant |
| `bucknell_digital_scholarship.json` | 1 | 1 | 1 → 0 | publisher constant |
| `bucknell-press.json` | 136 | 1 | 0 → 0 | one title tidied |
| `dssrf.json` | 26 | 26 | 26 → 0 | publisher constant |
| Student `inventory.json` | 141 | 110 | 141 → 141 | no date 18 → 0; no creators 10 → 9 |
| `honors_theses.json` | 718 | 718 | 718 → 0 | publisher constant; titles tidied |
| `masters_theses.json` | 312 | 312 | 312 → 0 | publisher constant; titles tidied |

No record was added or removed in any file.

### Reported problems

| Workbook | Conversion issues | `check` findings |
|---|---|---|
| Faculty and Staff Scholarship | 104 → 43 | 124 → 3 |
| Student Scholarship | 149 → 0 | 159 → 9 |
| BU Press | 0 → 0 | 0 → 0 |
| Thesis Collection | 0 → 0 | 0 → 0 |

The 43 remaining Faculty issues are all values deliberately left out and
listed for a person to look at: 23 volume/issue/page cells, 10 unreadable
DOIs, 6 shared DOIs, 4 non-rights statements.

## Open items

### Will still be rejected by KC Works

1. **1,384 records have neither a DOI nor a publisher**: `fac_journ` 642,
   Faculty `inventory` 600, Student `inventory` 141, `books` 1. Nothing in
   their rows identifies a publisher (425 of the 642 have no link at all, and
   most of the rest link to JSTOR, Project MUSE or PubMed). The `publisher`
   transform accepts a `fallback` argument that names a publisher for exactly
   these rows; it is not set, because what to call the publisher of a journal
   article whose publisher is unknown is an editorial decision.
2. **9 student records have no creators**: front matter of the Comparative
   Humanities Review with an empty author list (5522171, 5522790, 5522793,
   5523005, 5523010, 5523020, 5523024, 5523044, 5523046).
3. **Record 3071353** failed on staging with "missing title" although it has
   one. It is the only title over 255 characters, which suggests a length
   limit; not confirmed, and the title has not been shortened.

### Not verified against the server

- That a record with an external `pids.doi` and no publisher is accepted
  (91 `fac_journ` records). The server message implies it, since no DOI is
  registered for them.
- The `pids` block follows the shape given for this work; the Import API
  reference does not document it.
- That every ROR id used is in the affiliations vocabulary of the KC Works
  instance. An id the instance does not know would fail validation.

### Source data worth correcting in the spreadsheet

- Unreadable DOIs, omitted: 14167445 (`10.3390`), 38462101
  (`10.193/pnasnexus/pgae195`), 38455108 and 38350916 (no prefix), 13564122
  and 11807791 (`.` where `/` belongs), 9578961 (`0.1016/…`), 22316567 (a
  space inside the DOI), 11690040, 11805300 (`Unknown`).
- Names: 28893249 (`[1823-1908]` as a family name), 39482337 (`Kim (Education
  Department)`), 34038163 and 16535464 (trailing comma).
- The three shared-DOI pairs listed above.

### Outside this work

- The client readme asks for Bucknell: Occupied, all BU Press items and the
  `honors_thesis_b` / `masters_thesis_b` items to be restricted to Bucknell.
  The output sets no access restriction.
- 151 journal articles in the two `inventory.json` files have no journal
  block, because their rows have no `src_journal` (for the student journals
  the journal is the collection itself).
