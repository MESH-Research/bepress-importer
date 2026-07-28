"""Behavioural tests for validation rules: records in → findings (with proposals) out."""

from bepress_importer.wrangle.rules import Proposal, available_rules, run_rules


def record(record_id="1", **overrides):
    base = {
        "metadata": {
            "identifiers": [{"identifier": record_id, "scheme": "import-recid"}],
            "title": "A Title",
            "publication_date": "2015",
            "resource_type": {"id": "textDocument-journalArticle"},
            "creators": [
                {
                    "person_or_org": {
                        "type": "personal",
                        "name": "Smith, Jane",
                        "given_name": "Jane",
                        "family_name": "Smith",
                    },
                    "role": {"id": "author"},
                }
            ],
        },
        "files": {"enabled": False},
    }
    base["metadata"].update(overrides)
    return base


def findings_for(rule, records, **kwargs):
    return [f for f in run_rules(records, **kwargs) if f.rule == rule]


class TestRegistry:
    def test_all_planned_rules_are_available(self):
        names = available_rules()
        for expected in [
            "required-fields", "resource-type-vocab", "edtf-date", "doi-format",
            "rights-vocab", "language-code", "name-sanity", "duplicate-recid", "embargo-past",
        ]:
            assert expected in names

    def test_names_filter_limits_rules_run(self):
        bad = record(resource_type={"id": "bogus"}, publication_date="Spring 2015")
        findings = run_rules([bad], names=["edtf-date"])
        assert {f.rule for f in findings} == {"edtf-date"}

    def test_clean_record_yields_no_findings(self):
        assert run_rules([record()], as_of="2026-07-28") == []


class TestRequiredFields:
    def test_missing_title_flagged(self):
        rec = record()
        del rec["metadata"]["title"]
        findings = findings_for("required-fields", [rec])
        assert any(f.field == "/metadata/title" for f in findings)

    def test_missing_creators_flagged(self):
        rec = record(creators=[])
        findings = findings_for("required-fields", [rec])
        assert any(f.field == "/metadata/creators" for f in findings)


class TestResourceTypeVocab:
    def test_unknown_type_proposes_nearest_match(self):
        rec = record(resource_type={"id": "textDocument-journalArticl"})
        findings = findings_for("resource-type-vocab", [rec])
        assert len(findings) == 1
        assert findings[0].field == "/metadata/resource_type/id"
        assert findings[0].proposal == Proposal("textDocument-journalArticle")

    def test_raw_bepress_value_proposes_match(self):
        rec = record(resource_type={"id": "masters_thesis"})
        findings = findings_for("resource-type-vocab", [rec])
        assert findings[0].proposal == Proposal("textDocument-thesis")

    def test_valid_type_passes(self):
        assert findings_for("resource-type-vocab", [record()]) == []


class TestEdtfDate:
    def test_season_word_proposes_edtf(self):
        rec = record(publication_date="Spring 2015")
        findings = findings_for("edtf-date", [rec])
        assert findings[0].field == "/metadata/publication_date"
        assert findings[0].proposal == Proposal("2015-21")

    def test_month_name_proposes_year_month(self):
        rec = record(publication_date="April 2015")
        assert findings_for("edtf-date", [rec])[0].proposal == Proposal("2015-04")

    def test_slash_date_proposes_iso(self):
        rec = record(publication_date="2015/04/01")
        assert findings_for("edtf-date", [rec])[0].proposal == Proposal("2015-04-01")

    def test_unparseable_is_flag_only(self):
        rec = record(publication_date="unknown era")
        findings = findings_for("edtf-date", [rec])
        assert findings[0].proposal is None


class TestDoiFormat:
    def test_bad_doi_with_url_prefix_proposes_extraction(self):
        rec = record(
            identifiers=[
                {"identifier": "1", "scheme": "import-recid"},
                {"identifier": "https://doi.org/10.1000/xyz", "scheme": "doi"},
            ]
        )
        findings = findings_for("doi-format", [rec])
        assert findings[0].field == "/metadata/identifiers/1/identifier"
        assert findings[0].proposal == Proposal("10.1000/xyz")

    def test_clean_doi_passes(self):
        rec = record(
            identifiers=[
                {"identifier": "1", "scheme": "import-recid"},
                {"identifier": "10.1000/xyz", "scheme": "doi"},
            ]
        )
        assert findings_for("doi-format", [rec]) == []


class TestRightsVocab:
    def test_unknown_rights_id_flagged(self):
        rec = record(rights=[{"id": "all-rights-reserved-custom"}])
        findings = findings_for("rights-vocab", [rec])
        assert findings[0].field == "/metadata/rights/0/id"

    def test_known_cc_id_passes(self):
        rec = record(rights=[{"id": "cc-by-nc-4.0"}])
        assert findings_for("rights-vocab", [rec]) == []


class TestLanguageCode:
    def test_bad_code_flagged(self):
        rec = record(languages=[{"id": "english"}])
        assert findings_for("language-code", [rec])[0].field == "/metadata/languages/0/id"

    def test_iso639_3_passes(self):
        rec = record(languages=[{"id": "eng"}, {"id": "spa"}])
        assert findings_for("language-code", [rec]) == []


class TestNameSanity:
    def test_trailing_punctuation_proposes_cleanup(self):
        rec = record(
            creators=[
                {
                    "person_or_org": {
                        "type": "personal",
                        "name": "Smith, Jane,",
                        "given_name": "Jane",
                        "family_name": "Smith,",
                    },
                    "role": {"id": "author"},
                }
            ]
        )
        findings = findings_for("name-sanity", [rec])
        cleaned = [f for f in findings if f.field.endswith("family_name")]
        assert cleaned[0].proposal == Proposal("Smith")

    def test_personal_creator_without_family_name_flagged(self):
        rec = record(
            creators=[
                {"person_or_org": {"type": "personal", "name": "Cher"}, "role": {"id": "author"}}
            ]
        )
        assert findings_for("name-sanity", [rec]) != []


class TestDuplicateRecid:
    def test_colliding_ids_flagged_on_both(self):
        findings = findings_for("duplicate-recid", [record("7"), record("7")])
        assert len(findings) == 2

    def test_distinct_ids_pass(self):
        assert findings_for("duplicate-recid", [record("1"), record("2")]) == []


class TestEmbargoPast:
    def test_expired_embargo_proposes_removal(self):
        rec = record()
        rec["access"] = {"embargo": {"active": True, "until": "2012-01-01"}}
        findings = findings_for("embargo-past", [rec], as_of="2026-07-28")
        assert findings[0].field == "/access/embargo"
        assert findings[0].proposal == Proposal(None)

    def test_future_embargo_passes(self):
        rec = record()
        rec["access"] = {"embargo": {"active": True, "until": "2030-01-01"}}
        assert findings_for("embargo-past", [rec], as_of="2026-07-28") == []
