"""Behavioural tests for scalar transforms: raw cell value in → normalized value out."""

import pytest

from bepress_importer.transforms import apply_transform


def apply(name, value, row=None, args=None):
    return apply_transform(name, value, row or {}, args or {})


class TestEmptyInput:
    @pytest.mark.parametrize(
        "name", ["edtf_date", "identifier", "split", "strip_html", "url", "embargo",
                 "language_list", "license_url"]
    )
    def test_empty_value_is_omitted(self, name):
        assert apply(name, "") is None
        assert apply(name, "   ") is None


class TestEdtfDate:
    def test_converts_date(self):
        assert apply("edtf_date", "2015-04-15") == "2015-04-15"

    def test_uses_season_column_from_row(self):
        result = apply(
            "edtf_date", "2015-01-01", row={"season": "Spring"}, args={"season_column": "season"}
        )
        assert result == "2015-21"

    def test_year_only_style(self):
        result = apply(
            "edtf_date",
            "2015-01-01",
            row={"season": "Spring"},
            args={"season_column": "season", "style": "year-only"},
        )
        assert result == "2015"

    def test_unparseable_value_passes_through_for_wrangler(self):
        assert apply("edtf_date", "Sometime 2015") == "Sometime 2015"


class TestIdentifier:
    def test_doi_url_is_normalized(self):
        assert apply(
            "identifier",
            "https://doi.org/10.1103/PhysRevE.83.011301",
            args={"scheme": "doi", "normalize": "doi"},
        ) == {"identifier": "10.1103/PhysRevE.83.011301", "scheme": "doi"}

    @pytest.mark.parametrize(
        "raw",
        ["10.1021/jp104865w", "http://dx.doi.org/10.1021/jp104865w", "doi:10.1021/jp104865w",
         "DOI: 10.1021/jp104865w"],
    )
    def test_doi_prefix_forms_normalize_identically(self, raw):
        result = apply("identifier", raw, args={"scheme": "doi", "normalize": "doi"})
        assert result == {"identifier": "10.1021/jp104865w", "scheme": "doi"}

    def test_plain_scheme_without_normalization(self):
        assert apply("identifier", "978-3-16-148410-0", args={"scheme": "isbn"}) == {
            "identifier": "978-3-16-148410-0",
            "scheme": "isbn",
        }

    def test_url_scheme_requires_a_real_url(self):
        assert apply("identifier", "Author", args={"scheme": "url"}) is None
        assert apply("identifier", "https://example.org/x", args={"scheme": "url"}) == {
            "identifier": "https://example.org/x",
            "scheme": "url",
        }

    def test_split_arg_takes_first_segment(self):
        # Bepress ISBN cells like "9781684480166; eISBN; PDF"
        assert apply(
            "identifier", "9781684480166; eISBN; PDF", args={"scheme": "isbn", "split": ";"}
        ) == {"identifier": "9781684480166", "scheme": "isbn"}


class TestSplit:
    def test_splits_and_strips_and_drops_empties(self):
        assert apply("split", "alpha, beta,, gamma ", args={"sep": ","}) == [
            "alpha",
            "beta",
            "gamma",
        ]

    def test_rejoins_when_join_given(self):
        assert apply("split", "a;b; c", args={"sep": ";", "join": ", "}) == "a, b, c"


class TestStripHtml:
    def test_removes_tags_and_unescapes_entities(self):
        assert (
            apply("strip_html", "<p>Hello <b>world</b> &amp; more</p>") == "Hello world & more"
        )

    def test_collapses_whitespace(self):
        assert apply("strip_html", "one\r\n  two\tthree") == "one two three"

    def test_plain_text_unchanged(self):
        assert apply("strip_html", "no markup here") == "no markup here"


class TestUrl:
    def test_valid_url_passes(self):
        assert apply("url", " https://example.org/x ") == "https://example.org/x"

    def test_non_url_is_omitted(self):
        assert apply("url", "not a url") is None


class TestEmbargo:
    def test_future_embargo_is_active(self):
        assert apply("embargo", "2029-01-01", args={"as_of": "2026-07-28"}) == {
            "embargo": {"active": True, "until": "2029-01-01"}
        }

    def test_past_embargo_is_omitted(self):
        assert apply("embargo", "2012-01-25", args={"as_of": "2026-07-28"}) is None

    def test_epoch_placeholder_is_omitted(self):
        assert apply("embargo", "1970-01-01", args={"as_of": "2026-07-28"}) is None


class TestLanguageList:
    def test_single_code(self):
        assert apply("language_list", "eng") == [{"id": "eng"}]

    def test_multiple_codes(self):
        assert apply("language_list", "eng, spa") == [{"id": "eng"}, {"id": "spa"}]

    def test_codes_are_lowercased(self):
        assert apply("language_list", "ENG") == [{"id": "eng"}]


class TestAdditionalDescription:
    def test_wraps_cleaned_text_in_invenio_structure(self):
        assert apply("additional_description", "<p>Co-Author: Jane Doe</p>") == [
            {"description": "Co-Author: Jane Doe", "type": {"id": "other"}}
        ]

    def test_type_is_configurable(self):
        result = apply("additional_description", "Methods notes", args={"type": "methods"})
        assert result == [{"description": "Methods notes", "type": {"id": "methods"}}]


class TestConstantIfPresent:
    def test_returns_fixed_value_when_source_has_data(self):
        result = apply(
            "constant_if_present", "© 2019 Someone. All rights reserved.",
            args={"value": [{"id": "arr"}]},
        )
        assert result == [{"id": "arr"}]

    def test_each_call_returns_an_independent_copy(self):
        args = {"value": [{"id": "arr"}]}
        first = apply("constant_if_present", "text", args=args)
        second = apply("constant_if_present", "other", args=args)
        first[0]["id"] = "mutated"
        assert second == [{"id": "arr"}]


class TestRelatedIdentifier:
    def test_url_becomes_related_identifier_entry(self):
        result = apply(
            "related_identifier", "https://press.example.org/book/9781",
            args={"scheme": "url", "relation": "isdescribedby"},
        )
        assert result == [
            {
                "identifier": "https://press.example.org/book/9781",
                "scheme": "url",
                "relation_type": {"id": "isdescribedby"},
            }
        ]

    def test_non_url_is_omitted_when_scheme_is_url(self):
        assert apply(
            "related_identifier", "07/14/2023", args={"scheme": "url", "relation": "isdescribedby"}
        ) is None


class TestPrefixedTag:
    def test_value_becomes_namespaced_tag(self):
        assert apply("prefixed_tag", "text; 226 pages", args={"prefix": "bu_type"}) == [
            "bu_type: text; 226 pages"
        ]


class TestAuthorInstitution:
    def test_takes_first_nonempty_author_institution(self):
        row = {
            "author1_institution": "",
            "author2_institution": "Bucknell University",
            "author3_institution": "Elsewhere",
        }
        result = apply(
            "author_institution", "anything", row=row, args={"prefix": "author", "max": 5}
        )
        assert result == "Bucknell University"

    def test_default_when_no_author_has_institution(self):
        result = apply(
            "author_institution", "x", row={},
            args={"prefix": "author", "max": 5, "default": "Bucknell University"},
        )
        assert result == "Bucknell University"

    def test_no_default_and_no_institution_is_omitted(self):
        assert apply(
            "author_institution", "x", row={}, args={"prefix": "author", "max": 5}
        ) is None

    def test_runs_even_when_its_own_source_cell_is_empty(self):
        # author1_institution may be blank while author2 carries the university
        row = {"author1_institution": "", "author2_institution": "Bucknell University"}
        result = apply(
            "author_institution", "", row=row, args={"prefix": "author", "max": 5}
        )
        assert result == "Bucknell University"

    def test_default_applies_when_source_cell_is_empty(self):
        result = apply(
            "author_institution", "", row={},
            args={"prefix": "author", "max": 5, "default": "Bucknell University"},
        )
        assert result == "Bucknell University"


class TestSplitAlsoColumns:
    def test_sibling_column_values_are_merged(self):
        result = apply(
            "split", "History; Sociology",
            row={"concentration": "Literary Studies"},
            args={"sep": ";", "join": ", ", "also_columns": ["concentration"]},
        )
        assert result == "History, Sociology, Literary Studies"

    def test_empty_sibling_is_ignored(self):
        result = apply(
            "split", "History",
            row={"concentration": ""},
            args={"sep": ";", "also_columns": ["concentration"]},
        )
        assert result == ["History"]


class TestLicenseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("http://creativecommons.org/licenses/by-nc/4.0/", "cc-by-nc-4.0"),
            ("https://creativecommons.org/licenses/by/3.0/", "cc-by-3.0"),
            ("http://creativecommons.org/licenses/by-nc-nd/4.0/", "cc-by-nc-nd-4.0"),
            ("https://creativecommons.org/publicdomain/zero/1.0/", "cc0-1.0"),
        ],
    )
    def test_cc_urls_map_to_rights_ids(self, raw, expected):
        assert apply("license_url", raw) == [{"id": expected}]

    def test_unknown_url_is_omitted(self):
        assert apply("license_url", "https://example.org/my-license") is None
