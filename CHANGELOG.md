## 1.1.0 (2026-07-29)

### Feat

- **convert**: conversion provenance log in json and plaintext
- **profiles**: bucknell profile covering all eight export sheets
- **transforms**: identifier segment splitting and additional description wrapper
- **upload**: KC Works import API upload with per-record receipts
- **cli**: interactive wrangling workflow with audited change log
- **vocab**: vocabulary sync from live InvenioRDM endpoints
- **rules**: rule registry, built-in validation rules and vocab snapshots
- **changelog**: human-readable wrangling.log summary derived from the change log
- **changelog**: revert events for change-level and record-level undo
- **changelog**: append-only change log with per-field chains and replay
- **cli**: inspect and convert commands with coverage report and profile scaffold
- **convert**: deterministic conversion to KC Works import JSON
- **transforms**: author, contributor and journal/imprint builders
- **transforms**: scalar transforms for dates, identifiers, licenses and text
- **edtf**: EDTF subset emitter and validator
- **profiles**: TOML sheet-mapping profiles
- **readers**: normalized table reading for xls, xlsx and csv

### Fix

- **cli**: ignore directories when loading collection json files
- **cli**: shorten command summaries so help lines are not truncated
- **rules**: stop flagging legitimate trailing periods in names

### Refactor

- **cli**: rename command entry point to bepress-importer
