"""Behavioural tests for reading DOIs out of spreadsheet cells."""

import pytest

from bepress_importer.doi import doi_reference, extract_doi


class TestExtractDoi:
    def test_bare_doi_is_returned_unchanged(self):
        assert extract_doi("10.1016/j.jmps.2018.02.012") == "10.1016/j.jmps.2018.02.012"

    @pytest.mark.parametrize(
        "raw",
        [
            "https://doi.org/10.1016/j.jmps.2018.02.012",
            "http://doi.org/10.1016/j.jmps.2018.02.012",
            "https://dx.doi.org/10.1016/j.jmps.2018.02.012",
            "http://dx.doi.org/10.1016/j.jmps.2018.02.012",
            "https://www.doi.org/10.1016/j.jmps.2018.02.012",
            "https://DOI.org/10.1016/j.jmps.2018.02.012",
            "doi.org/10.1016/j.jmps.2018.02.012",
            "dx.doi.org/10.1016/j.jmps.2018.02.012",
            "https://doi.org//10.1016/j.jmps.2018.02.012",
            "doi:10.1016/j.jmps.2018.02.012",
            "DOI: 10.1016/j.jmps.2018.02.012",
            "DOI\thttps://doi.org/10.1016/j.jmps.2018.02.012",
            "I 10.1016/j.jmps.2018.02.012",
            "http://10.1016/j.jmps.2018.02.012",
            "  10.1016/j.jmps.2018.02.012  ",
        ],
    )
    def test_every_wrapping_reduces_to_the_bare_doi(self, raw):
        assert extract_doi(raw) == "10.1016/j.jmps.2018.02.012"

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("http://dx.doi.org/10.17169/fqs-19.3.2661.", "10.17169/fqs-19.3.2661"),
            ("doi:10.1353/sdn.2021.0021.", "10.1353/sdn.2021.0021"),
            ("10.1080/00343404.2022.2108543 .", "10.1080/00343404.2022.2108543"),
            ("(doi:10.1000/abc123)", "10.1000/abc123"),
            ("10.1000/abc123,", "10.1000/abc123"),
            ("10.1000/abc123;", "10.1000/abc123"),
        ],
    )
    def test_trailing_punctuation_is_not_part_of_the_doi(self, raw, expected):
        assert extract_doi(raw) == expected

    def test_balanced_parentheses_inside_a_doi_are_kept(self):
        assert (
            extract_doi("https://doi.org/10.1061/(ASCE)GT.1943-5606.0002196")
            == "10.1061/(ASCE)GT.1943-5606.0002196"
        )
        assert (
            extract_doi("https://doi.org/10.1016/S2542-5196(21)00196-0")
            == "10.1016/S2542-5196(21)00196-0"
        )

    def test_stray_space_after_the_prefix_is_closed_up(self):
        assert (
            extract_doi("https://doi.org/10.1016/ S2542-5196(21)00196-0")
            == "10.1016/S2542-5196(21)00196-0"
        )
        assert extract_doi("dx.doi.org/ 10.1002/cmr.a.21298") == "10.1002/cmr.a.21298"

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("doi/10.1111/j.1527-2001.2003.tb01413.x/abstract", "10.1111/j.1527-2001.2003.tb01413.x"),
            ("http://onlinelibrary.wiley.com/doi/10.1111/ajt.12067/full", "10.1111/ajt.12067"),
            ("http://pubs.example.org/doi/10.1021/es204005g/pdf", "10.1021/es204005g"),
            (
                "http://www.tandfonline.com/doi/abs/10.1080/00369220218737148?journalCode=rsgj20#preview",
                "10.1080/00369220218737148",
            ),
            (
                "https://www.tandfonline.com/doi/full/10.1080/08831157.2024.2372244#abstract",
                "10.1080/08831157.2024.2372244",
            ),
        ],
    )
    def test_landing_page_decorations_are_removed(self, raw, expected):
        assert extract_doi(raw) == expected

    def test_percent_encoded_characters_are_decoded(self):
        assert (
            extract_doi("http://ascelibrary.org/doi/pdf/10.1061/%28ASCE%29GT.1943-5606.0000729")
            == "10.1061/(ASCE)GT.1943-5606.0000729"
        )

    def test_a_doi_inside_html_stops_at_the_closing_quote(self):
        raw = '< a href="http://link.aps.org/doi/10.1103/PhysRevD.83.052007">link'
        assert extract_doi(raw) == "10.1103/PhysRevD.83.052007"

    def test_a_doi_repeated_with_citation_text_glued_on_yields_the_clean_one(self):
        raw = (
            "https://doi.org/10.1080/25742442.2022.2163582Greenspon, E. B. (2023). "
            "Subvocalization. https://doi.org/10.1080/25742442.2022.2163582"
        )
        assert extract_doi(raw) == "10.1080/25742442.2022.2163582"

    def test_first_of_several_different_dois_wins(self):
        assert extract_doi("10.1000/first 10.2000/second") == "10.1000/first"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "Unknown",
            "10.3390",
            "PMID: 21506449",
            "j.aime.2025.100161",
            "10.1007.s00709-017-1117-9",
            "http://dx.doi.org/10.1037.pmu0000211.",
            "doi:0.1016/j.appet.2017.01.013",
            "10.193/pnasnexus/pgae195",
            "https://joi.pm-research.com/content/28/5/122",
            "406.74/426370/0253902005S9P2L0S.1P7L.0.1076..07019.97201",
        ],
    )
    def test_values_that_are_not_dois_yield_nothing(self, raw):
        assert extract_doi(raw) is None

    def test_a_doi_broken_by_a_space_is_not_guessed_at(self):
        # "journal. pone.0247579" — truncating to "10.1371/journal" would
        # register a DOI that belongs to something else
        assert extract_doi("https://doi.org/10.1371/journal. pone.0247579") is None


class TestDoiReference:
    @pytest.mark.parametrize(
        "raw",
        [
            "https://doi.org/10.1016/j.jmps.2018.02.012",
            "http://doi.org/10.1016/j.jmps.2018.02.012",
            "https://dx.doi.org/10.1016/j.jmps.2018.02.012",
            "http://dx.doi.org/10.1016/j.jmps.2018.02.012",
            "http://www.dx.doi.org/10.1016/j.jmps.2018.02.012",
            "dx.doi.org/10.1016/j.jmps.2018.02.012",
            "doi.org/10.1016/j.jmps.2018.02.012",
            "dx.doi.org/ 10.1016/j.jmps.2018.02.012",
            "http://dx/doi.org/10.1016/j.jmps.2018.02.012",
            "dx.doi/org/10.1016/j.jmps.2018.02.012",
            "ttps://doi.org/10.1016/j.jmps.2018.02.012",
            "DOI: 10.1016/j.jmps.2018.02.012",
            "doi:10.1016/j.jmps.2018.02.012",
            "Early View Online DOI: 10.1016/j.jmps.2018.02.012",
            "10.1016/j.jmps.2018.02.012",
            "http://10.1016/j.jmps.2018.02.012",
        ],
    )
    def test_resolver_addresses_and_labels_are_doi_references(self, raw):
        assert doi_reference(raw) == "10.1016/j.jmps.2018.02.012"

    @pytest.mark.parametrize(
        "raw",
        [
            "http://onlinelibrary.wiley.com/doi/10.1002/qua.560560711/abstract",
            "https://link.springer.com/article/10.1007/s10539-018-9615-5",
            "https://journals.sagepub.com/doi/full/10.1177/1087724X211003249",
            "www.pnas.org/cgi/doi/10.1073/pnas.1919764117",
            "https://www.jstor.org/stable/10.13110/criticism.59.1.0075",
            "https://authorservices.wiley.com/bauthor/onlineLibraryTPS.asp?DOI=10.1111/jaac.12321&ArticleID=6695109",
            "https://www.sciencedirect.com/science/article/pii/S0195666317300491",
            "Journal of University Teaching and Learning Practice",
            "",
        ],
    )
    def test_landing_pages_and_plain_text_are_not_doi_references(self, raw):
        assert doi_reference(raw) is None

    def test_a_resolver_address_with_no_readable_doi_is_not_a_reference(self):
        assert doi_reference("http://dx.doi.org/10.1037.pmu0000211.") is None
