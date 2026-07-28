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
