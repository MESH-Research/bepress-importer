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

    def test_empty_value_falls_back_to_named_columns(self):
        result = apply(
            "edtf_date", "", row={"start_date": "2012-11-17"},
            args={"fallback_columns": ["start_date"]},
        )
        assert result == "2012-11-17"

    def test_fallback_scans_columns_in_order_skipping_empties(self):
        result = apply(
            "edtf_date", "", row={"start_date": "  ", "end_date": "2012-11-17"},
            args={"fallback_columns": ["start_date", "end_date"]},
        )
        assert result == "2012-11-17"

    def test_non_empty_value_ignores_fallback_columns(self):
        result = apply(
            "edtf_date", "2015-04-15", row={"start_date": "2012-11-17"},
            args={"fallback_columns": ["start_date"]},
        )
        assert result == "2015-04-15"

    def test_empty_value_with_empty_fallbacks_is_omitted(self):
        result = apply(
            "edtf_date", "", row={"start_date": ""}, args={"fallback_columns": ["start_date"]}
        )
        assert result is None


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

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("http://dx.doi.org/10.17169/fqs-19.3.2661.", "10.17169/fqs-19.3.2661"),
            ("doi/10.1111/j.1527-2001.2003.tb01413.x/abstract", "10.1111/j.1527-2001.2003.tb01413.x"),
            ("https://doi.org/10.1016/ S2542-5196(21)00196-0", "10.1016/S2542-5196(21)00196-0"),
        ],
    )
    def test_doi_is_cleaned_of_punctuation_and_page_suffixes(self, raw, expected):
        result = apply("identifier", raw, args={"scheme": "doi", "normalize": "doi"})
        assert result == {"identifier": expected, "scheme": "doi"}

    @pytest.mark.parametrize(
        "raw",
        ["Unknown", "10.3390", "j.aime.2025.100161", "10.1007.s00709-017-1117-9",
         "doi:0.1016/j.appet.2017.01.013", "https://doi.org/10.1371/journal. pone.0247579"],
    )
    def test_doi_cell_without_a_readable_doi_is_omitted(self, raw):
        assert apply("identifier", raw, args={"scheme": "doi", "normalize": "doi"}) is None

    def test_pubmed_id_in_a_doi_cell_becomes_a_pubmed_link(self):
        result = apply("identifier", "PMID: 21506449", args={"scheme": "doi", "normalize": "doi"})
        assert result == {
            "identifier": "https://pubmed.ncbi.nlm.nih.gov/21506449/",
            "scheme": "url",
        }

    def test_plain_url_in_a_doi_cell_is_kept_as_a_link(self):
        result = apply(
            "identifier",
            "https://joi.pm-research.com/content/28/5/122",
            args={"scheme": "doi", "normalize": "doi"},
        )
        assert result == {
            "identifier": "https://joi.pm-research.com/content/28/5/122",
            "scheme": "url",
        }

    @pytest.mark.parametrize(
        "raw",
        [
            "https://doi.org/10.1016/j.jmps.2018.02.012",
            "http://dx.doi.org/10.1016/j.jmps.2018.02.012",
            "dx.doi.org/10.1016/j.jmps.2018.02.012",
            "doi.org/10.1016/j.jmps.2018.02.012",
            "DOI: 10.1016/j.jmps.2018.02.012",
        ],
    )
    def test_link_cell_holding_a_doi_reference_yields_a_doi_identifier(self, raw):
        result = apply("identifier", raw, args={"scheme": "url", "doi_references": True})
        assert result == {"identifier": "10.1016/j.jmps.2018.02.012", "scheme": "doi"}

    def test_landing_page_link_stays_a_url_even_when_dois_are_recognised(self):
        raw = "http://onlinelibrary.wiley.com/doi/10.1002/qua.560560711/abstract"
        result = apply("identifier", raw, args={"scheme": "url", "doi_references": True})
        assert result == {"identifier": raw, "scheme": "url"}

    def test_resolver_link_stays_a_url_unless_doi_references_is_set(self):
        raw = "https://doi.org/10.1016/j.jmps.2018.02.012"
        assert apply("identifier", raw, args={"scheme": "url"}) == {
            "identifier": raw,
            "scheme": "url",
        }

    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                "http://pennsci.org/JPAS-88-1.2.pdf https://www.jstor.org/stable/10.5325/x",
                "http://pennsci.org/JPAS-88-1.2.pdf",
            ),
            (
                "https://www.proquest.com/redirect; https://substance.org/issue/substance-166/",
                "https://www.proquest.com/redirect",
            ),
            (
                "http://www.jstor.org/stable/1 or http://www.jstor.org/stable/pdf/1.pdf",
                "http://www.jstor.org/stable/1",
            ),
            (
                "On-line early view available at: http://onlinelibrary.wiley.com/journal/1",
                "http://onlinelibrary.wiley.com/journal/1",
            ),
            (
                '< a href="http://link.aps.org/doi/10.1103/PhysRevD.83.052007">http://link.aps.org/x',
                "http://link.aps.org/doi/10.1103/PhysRevD.83.052007",
            ),
            (
                "\ufeff\ufeffhttps://iopscience.iop.org/article/10.3847/0004-637X/830/2/55/meta",
                "https://iopscience.iop.org/article/10.3847/0004-637X/830/2/55/meta",
            ),
            ("ttps://www.routledge.com/p/book/9780367632373", "https://www.routledge.com/p/book/9780367632373"),
            ("www.pnas.org/cgi/doi/10.1073/pnas.1919764117", "http://www.pnas.org/cgi/doi/10.1073/pnas.1919764117"),
            ("https://example.org/x", "https://example.org/x"),
        ],
    )
    def test_find_url_recovers_the_first_link_from_a_messy_cell(self, raw, expected):
        result = apply("identifier", raw, args={"scheme": "url", "find_url": True})
        assert result == {"identifier": expected, "scheme": "url"}

    @pytest.mark.parametrize(
        "raw",
        ["No online access", "Link to full text", "Bulletin of Mathematical Biology",
         "file:///Users/jrv010/Downloads/Paper.pdf", "IEEE Xplore - Abstract Page"],
    )
    def test_find_url_omits_cells_with_no_web_link(self, raw):
        assert apply("identifier", raw, args={"scheme": "url", "find_url": True}) is None

    def test_broken_resolver_link_is_omitted_rather_than_truncated(self):
        args = {"scheme": "url", "doi_references": True, "find_url": True}
        assert apply("identifier", "https://doi.org/10.1371/journal. pcbi.1011847", args=args) is None
        assert apply("identifier", "dx.doi.org/0.1093/oxfordhb/9780195396706.013.0020", args=args) is None

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


ABSTRACT_IN_THE_WRONG_COLUMN = (
    "Animals learn to prefer and increase consumption of flavors paired with postingestive "
    "nutrient sensing. Analogous effects have been difficult to observe in human studies. "
    "One possibility is experience with the modern, processed diet impairs learning."
)
ISSUE_BLURB = (
    "The second issue of Latin American Literature highlights the Caribbean and queer "
    "literature from across Latin America, featuring dossiers of two writers."
)


class TestRightsStatement:
    @pytest.mark.parametrize(
        "statement",
        [
            "Open Access",
            "© ASCE",
            "Copyright © 2010 American Physical Society",
            "Copyright 2012, Anna Kell",
            "(c) 2019 The Authors",
            "This article © 2012 Massachusetts Institute of Technology",
            ("If you would like to request permissions directly from Taylor & Francis, please "
            "email your request directly to permissionrequest@tandf.co.uk."),
            ("This is an open access article under the CC BY license "
            "(http://creativecommons.org/licenses/by/4.0/)."),
            'This is the "Submitted Version".',
            "The final publication is available at www.springerlink.com",
            ("First published in Mathematics of Computation in Vol. 81, No. 280, Oct. 2012, "
            "published by the American Mathematical Society."),
            ("This is an Accepted Manuscript of an article published by Taylor & Francis in "
            "Regional Studies on September 2022, available at: 10.1080/00343404.2022.2108543 ."),
            ("This pre-print represents the version of the article initially submitted to the "
            "publisher, before peer review or other editorial processes."),
            "The publisher does not allow for Open Access availability of the published article.",
            "Published in Politics & Gender, 2023 All rights reserved",
        ],
    )
    def test_rights_and_version_statements_are_kept(self, statement):
        assert apply("rights_statement", statement) == statement

    @pytest.mark.parametrize(
        "junk",
        [
            "Unsure",
            "Teaching Children Mathematics",
            ABSTRACT_IN_THE_WRONG_COLUMN,
            ISSUE_BLURB,
            "We compare (a) sweet, (b) salty and (c) bitter flavours across three cohorts.",
        ],
    )
    def test_text_that_is_not_a_rights_statement_is_omitted(self, junk):
        assert apply("rights_statement", junk) is None

    def test_a_long_passage_needs_more_than_a_passing_word_to_count(self):
        # an abstract that merely mentions a "published" study is still an abstract
        passage = (
            "Previously published studies disagree on this point. " * 9
            + "We therefore measured the effect directly in three cohorts."
        )
        assert apply("rights_statement", passage) is None

    def test_html_is_removed_from_a_kept_statement(self):
        assert apply("rights_statement", "<p>Copyright &copy; 2010 <b>APS</b></p>") == (
            "Copyright © 2010 APS"
        )


class TestMisplacedDescription:
    ARGS = {"unless_columns": ["abstract"]}  # noqa: RUF012

    def test_prose_in_a_rights_column_is_rescued_when_there_is_no_abstract(self):
        result = apply(
            "misplaced_description", ABSTRACT_IN_THE_WRONG_COLUMN,
            row={"abstract": ""}, args=dict(self.ARGS),
        )
        assert result == ABSTRACT_IN_THE_WRONG_COLUMN

    def test_the_real_abstract_is_never_displaced(self):
        result = apply(
            "misplaced_description", ABSTRACT_IN_THE_WRONG_COLUMN,
            row={"abstract": "The actual abstract."}, args=dict(self.ARGS),
        )
        assert result is None

    @pytest.mark.parametrize(
        "statement", ["Open Access", "Copyright © 2010 American Physical Society"]
    )
    def test_a_rights_statement_is_not_a_description(self, statement):
        assert apply("misplaced_description", statement, row={"abstract": ""},
                     args=dict(self.ARGS)) is None

    @pytest.mark.parametrize("remark", ["Unsure", "Teaching Children Mathematics"])
    def test_a_stray_remark_is_not_a_description(self, remark):
        assert apply("misplaced_description", remark, row={"abstract": ""},
                     args=dict(self.ARGS)) is None

    def test_the_length_that_counts_as_prose_is_adjustable(self):
        args = {"unless_columns": ["abstract"], "min_length": 10}
        assert apply("misplaced_description", "A short remark.", row={}, args=args) == (
            "A short remark."
        )

    def test_html_is_removed(self):
        result = apply("misplaced_description", f"<p>{ISSUE_BLURB}</p>", row={}, args={})
        assert result == ISSUE_BLURB


class TestPlainText:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Characterizations of A<sub>2</sub> Matrix Power Weights",
             "Characterizations of A2 Matrix Power Weights"),
            ("Measuring H<sub>2</sub>S<sub>(g)</sub> Concentrations",
             "Measuring H2S(g) Concentrations"),
            ("pathogen in Nearctic <em>Myotis lucifugus</em> and Palearctic bats",
             "pathogen in Nearctic Myotis lucifugus and Palearctic bats"),
            ("<em>Baptisia australis</em> var. <em>australis</em> in Pennsylvania",
             "Baptisia australis var. australis in Pennsylvania"),
            ("Visions of Egypt in Midrash:  Pharaoh’s Birthday", "Visions of Egypt in Midrash: Pharaoh’s Birthday"),
            ("Intelligent Souls?  : Feminist Orientalism", "Intelligent Souls? : Feminist Orientalism"),
            ("<p>Part one</p><p>Part two</p>", "Part one Part two"),
            ("First line<br/>second line", "First line second line"),
            ("Research &amp; Practice", "Research & Practice"),
            ("  padded \n title ", "padded title"),
        ],
    )
    def test_markup_and_stray_whitespace_are_removed(self, raw, expected):
        assert apply("plain_text", raw) == expected

    @pytest.mark.parametrize(
        "title",
        ["Genetic Diversity & Connectivity of a Rare Species", "When a < b and b > c", "Plain"],
    )
    def test_ordinary_titles_are_untouched(self, title):
        assert apply("plain_text", title) == title

    def test_nothing_but_markup_is_omitted(self):
        assert apply("plain_text", "<p> </p>") is None


class TestSplitOnSeveralSeparators:
    def test_a_list_of_separators_splits_on_any_of_them(self):
        args = {"sep": [",", ";"]}
        assert apply("split", "aluminum alloys; cold spray; corrosion", args=args) == [
            "aluminum alloys", "cold spray", "corrosion",
        ]
        assert apply("split", "birds, development; estradiol", args=args) == [
            "birds", "development", "estradiol",
        ]

    def test_a_single_separator_still_works(self):
        assert apply("split", "a; b, c", args={"sep": ","}) == ["a; b", "c"]

    def test_several_separators_can_be_rejoined(self):
        assert apply("split", "a; b,c", args={"sep": [",", ";"], "join": ", "}) == "a, b, c"


class TestUnproxiedLinks:
    ARGS = {"scheme": "url", "unproxy": ["ezproxy.bucknell.edu"]}  # noqa: RUF012

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("http://www.jstor.org.ezproxy.bucknell.edu/stable/10.5406/x", "http://www.jstor.org/stable/10.5406/x"),
            ("http://muse.jhu.edu.ezproxy.bucknell.edu/journals/a.html", "http://muse.jhu.edu/journals/a.html"),
            ("https://www-ams-org.ezproxy.bucknell.edu/journals/x", "https://www.ams.org/journals/x"),
            ("https://www.jstor.org/stable/1", "https://www.jstor.org/stable/1"),
            ("https://example.org/?u=http://x.ezproxy.bucknell.edu/", "https://example.org/?u=http://x.ezproxy.bucknell.edu/"),
        ],
    )
    def test_library_proxy_is_removed_from_the_link(self, raw, expected):
        assert apply("identifier", raw, args=dict(self.ARGS)) == {
            "identifier": expected, "scheme": "url",
        }

    def test_links_are_left_proxied_unless_asked(self):
        raw = "http://www.jstor.org.ezproxy.bucknell.edu/stable/1"
        assert apply("identifier", raw, args={"scheme": "url"})["identifier"] == raw
