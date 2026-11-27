"""Behavioural tests for inferring a work's publisher from its row."""

import pytest

from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import load_profile
from bepress_importer.publishers import (
    find_publisher,
    known_publishers,
    publisher_from_doi,
    publisher_from_link,
    publisher_from_statement,
)
from bepress_importer.readers import Table, Workbook
from bepress_importer.transforms import apply_transform, known_transforms

TANDF_STATEMENT = (
    "If you would like to request permissions directly from Taylor & Francis, please "
    "email your request directly to permissionrequest@tandf.co.uk. For more information "
    "please visit our Permissions help page."
)


def name_of(match):
    return match.name if match else None


class TestPublisherFromStatement:
    @pytest.mark.parametrize(
        "statement, publisher",
        [
            (TANDF_STATEMENT, "Taylor & Francis"),
            ("An article published by Taylor and Francis in Regional Studies", "Taylor & Francis"),
            ("Accepted Manuscript of an article published by Taylor & Francis Group", "Taylor & Francis"),
            ("published by TAYLOR & FRANCIS", "Taylor & Francis"),
            ("Acta Borealia is available online at: www.tandfonline.com", "Taylor & Francis"),
            (
                ("© 2019 IEEE. Personal use of this material is permitted. Permission from "
                "IEEE must be obtained for all other uses."),
                "IEEE",
            ),
            (
                ("may be used for non-commercial purposes in accordance with Wiley Terms "
                "and Conditions for Use of Self-Archived Versions."),
                "Wiley",
            ),
            ("© 2022 The Authors. Published by Elsevier B.V.", "Elsevier"),
            ("Copyright © 2010 American Physical Society", "American Physical Society"),
            ("© ASCE", "American Society of Civil Engineers"),
            ("The final publication is available at www.springerlink.com", "Springer"),
        ],
    )
    def test_statement_naming_a_publisher_identifies_it(self, statement, publisher):
        assert name_of(publisher_from_statement(statement)) == publisher

    @pytest.mark.parametrize(
        "statement",
        [
            "Open Access",
            "Unsure",
            "",
            'This is the "Submitted Version".',
            ("This is an open access article under the CC BY license "
            "(http://creativecommons.org/licenses/by/4.0/)."),
            ("Animals learn to prefer and increase consumption of flavors paired with "
            "postingestive nutrient sensing."),
        ],
    )
    def test_statement_naming_no_publisher_identifies_none(self, statement):
        assert publisher_from_statement(statement) is None

    def test_the_publisher_mentioned_first_wins(self):
        statement = (
            "Published by Cambridge University Press on behalf of the American "
            "Psychological Association"
        )
        assert name_of(publisher_from_statement(statement)) == "Cambridge University Press"

    def test_the_fuller_name_wins_over_a_name_it_contains(self):
        statement = "is subject to Springer Nature’s AM terms of use"
        assert name_of(publisher_from_statement(statement)) == "Springer Nature"

    def test_names_only_match_as_whole_words(self):
        assert publisher_from_statement("measured by Brillouin scattering") is None
        assert publisher_from_statement("the Wileyan method") is None

    def test_acronyms_only_match_in_their_own_case(self):
        assert publisher_from_statement("offers sage advice to the reader") is None
        assert name_of(publisher_from_statement("© 2020 SAGE")) == "SAGE Publications"

    def test_the_match_says_what_gave_the_publisher_away(self):
        match = publisher_from_statement("Copyright © 2019 IEEE")
        assert (match.evidence, match.detail) == ("statement", "IEEE")


class TestPublisherFromDoi:
    @pytest.mark.parametrize(
        "doi, publisher",
        [
            ("10.1016/j.jmps.2018.02.012", "Elsevier"),
            ("10.1080/14788810.2017.1410753", "Taylor & Francis"),
            ("10.1109/MCOM.2012.6231288", "IEEE"),
            ("10.1002/ajb2.1765", "Wiley"),
            ("10.1111/russ.12239", "Wiley"),
            ("10.1007/s10479-020-03709-2", "Springer"),
        ],
    )
    def test_registrant_prefix_identifies_the_publisher(self, doi, publisher):
        match = publisher_from_doi(doi)
        assert name_of(match) == publisher
        assert (match.evidence, match.detail) == ("doi", doi.split("/")[0])

    @pytest.mark.parametrize("doi", ["10.99999/unknown", "", "not a doi"])
    def test_unknown_prefix_identifies_no_one(self, doi):
        assert publisher_from_doi(doi) is None

    @pytest.mark.parametrize("doi", ["10.2307/1771565", "10.1353/atj.2024.a927716"])
    def test_aggregator_prefixes_identify_no_one(self, doi):
        # JSTOR and Project MUSE register DOIs for many different publishers
        assert publisher_from_doi(doi) is None

    def test_a_prefix_is_not_matched_by_a_longer_one(self):
        assert publisher_from_doi("10.10160/x") is None


class TestPublisherFromLink:
    @pytest.mark.parametrize(
        "link, publisher",
        [
            ("https://www.sciencedirect.com/science/article/pii/S0195666317300491", "Elsevier"),
            ("http://www.tandfonline.com/doi/abs/10.1300/J031v03n03_06", "Taylor & Francis"),
            ("https://besjournals.onlinelibrary.wiley.com/doi/full/10.1111/1365-2435.13228", "Wiley"),
            ("https://ieeexplore.ieee.org/document/1234567", "IEEE"),
            ("HTTP://LINK.SPRINGER.COM/article/10.1007/s11407-014-9161-y", "Springer"),
        ],
    )
    def test_publisher_platform_identifies_the_publisher(self, link, publisher):
        assert name_of(publisher_from_link(link)) == publisher

    @pytest.mark.parametrize(
        "link",
        [
            "https://www.jstor.org/stable/10.13110/criticism.59.1.0075",
            "https://muse.jhu.edu/article/123456",
            "https://www.ncbi.nlm.nih.gov/pubmed/10131298",
            "https://www.researchgate.net/publication/11831045",
            "https://psycnet.apa.org/record/2011-12345-001",
            "https://example.org/an-article",
            "not a link",
            "",
        ],
    )
    def test_aggregators_and_unknown_sites_identify_no_one(self, link):
        assert publisher_from_link(link) is None

    def test_a_lookalike_domain_is_not_the_publisher(self):
        assert publisher_from_link("https://wiley.com.example.org/x") is None
        assert publisher_from_link("https://notwiley.com/x") is None

    def test_the_match_names_the_host(self):
        match = publisher_from_link("https://www.sciencedirect.com/science/article/pii/S1")
        assert (match.evidence, match.detail) == ("link", "www.sciencedirect.com")


class TestFindPublisher:
    def test_statement_beats_doi_beats_link(self):
        statement = "© 2019 IEEE"
        doi = "10.1016/j.jmps.2018.02.012"
        link = "https://www.tandfonline.com/doi/full/10.1080/1"
        assert name_of(find_publisher([statement], [doi], [link])) == "IEEE"
        assert name_of(find_publisher([], [doi], [link])) == "Elsevier"
        assert name_of(find_publisher(["Open Access"], [], [link])) == "Taylor & Francis"

    def test_no_evidence_no_publisher(self):
        assert find_publisher() is None
        assert find_publisher(["Open Access"], ["10.99999/x"], ["https://example.org"]) is None


class TestPublisherList:
    def test_every_publisher_has_a_name_and_some_way_of_being_recognised(self):
        publishers = known_publishers()
        assert len(publishers) > 50
        for publisher in publishers:
            assert publisher.name.strip()
            assert (
                publisher.statement or publisher.acronyms
                or publisher.doi_prefixes or publisher.hosts
            ), publisher.name

    def test_no_publisher_is_listed_twice(self):
        names = [p.name for p in known_publishers()]
        assert len(names) == len(set(names))

    def test_no_doi_prefix_or_host_points_at_two_publishers(self):
        for kind in ("doi_prefixes", "hosts"):
            seen = [value for p in known_publishers() for value in getattr(p, kind)]
            assert len(seen) == len(set(seen)), kind

    def test_doi_prefixes_are_well_formed(self):
        for publisher in known_publishers():
            for prefix in publisher.doi_prefixes:
                assert prefix.startswith("10.") and "/" not in prefix, publisher.name


class TestPublisherTransform:
    def apply(self, value="", **row):
        args = {
            "statement_columns": ["pub_statement"],
            "doi_columns": ["doi"],
            "link_columns": ["pub_link"],
        }
        return apply_transform("publisher", value, row, args)

    def test_a_publisher_given_in_the_row_is_used_as_it_stands(self):
        assert self.apply("Bucknell University Press", pub_statement="© 2019 IEEE") == (
            "Bucknell University Press"
        )

    def test_publisher_is_read_from_the_copyright_statement(self):
        assert self.apply(pub_statement=TANDF_STATEMENT) == "Taylor & Francis"

    def test_html_in_the_statement_does_not_hide_the_publisher(self):
        assert self.apply(pub_statement="<p>published by Taylor &amp; Francis</p>") == (
            "Taylor & Francis"
        )

    def test_publisher_is_read_from_the_doi_when_no_statement_names_one(self):
        assert self.apply(pub_statement="Open Access", doi="https://doi.org/10.1109/5.771073") == "IEEE"

    def test_a_doi_inside_a_link_counts_as_doi_evidence(self):
        assert self.apply(pub_link="https://www.jstor.org/stable/10.1525/sop.2012.55.2.241") == (
            "University of California Press"
        )

    def test_publisher_is_read_from_the_link_as_a_last_resort(self):
        assert self.apply(pub_link="https://www.sciencedirect.com/science/article/pii/S1") == "Elsevier"

    def test_no_trace_of_a_publisher_leaves_the_field_empty(self):
        assert self.apply(pub_statement="Open Access", pub_link="https://example.org/x") is None
        assert self.apply() is None

    def test_only_the_configured_evidence_is_consulted(self):
        result = apply_transform(
            "publisher", "", {"doi": "10.1109/5.771073", "pub_statement": "© Elsevier"},
            {"statement_columns": ["pub_statement"]},
        )
        assert result == "Elsevier"
        result = apply_transform("publisher", "", {"doi": "10.1109/5.771073"}, {})
        assert result is None


class TestPublisherProvenance:
    PROFILE = """
[profile]
name = "p"
[[sheet]]
match = "*"
collection = "articles"
[sheet.resource_type]
constant = "textDocument-journalArticle"
[[sheet.field]]
source = "title"
target = "/metadata/title"
[[sheet.field]]
source = "publisher"
target = "/metadata/publisher"
transform = "publisher"
args = { statement_columns = ["pub_statement"], doi_columns = ["doi"], link_columns = ["pub_link"] }
"""
    COLUMNS = ("context_key", "title", "publisher", "pub_statement", "doi", "pub_link")

    def convert(self, tmp_path, **cells):
        path = tmp_path / "p.toml"
        path.write_text(self.PROFILE)
        row = {column: "" for column in self.COLUMNS} | {"context_key": "1", "title": "T"} | cells
        table = Table(name="Sheet", columns=self.COLUMNS, rows=(row,))
        profile = load_profile(path, known_transforms=known_transforms())
        return convert_workbook(Workbook(tables=(table,)), profile, as_of="2026-11-26")

    def test_inferred_publisher_reaches_the_record(self, tmp_path):
        result = self.convert(tmp_path, pub_statement="© 2019 IEEE")
        assert result.collections["articles"][0]["metadata"]["publisher"] == "IEEE"

    def test_record_with_no_trace_of_a_publisher_has_none(self, tmp_path):
        result = self.convert(tmp_path)
        assert "publisher" not in result.collections["articles"][0]["metadata"]

    @pytest.mark.parametrize(
        "cells, clue",
        [
            ({"pub_statement": "© 2019 IEEE"}, "IEEE"),
            ({"doi": "10.1016/j.jmps.2018.02.012"}, "10.1016"),
            ({"pub_link": "https://www.tandfonline.com/toc/x"}, "www.tandfonline.com"),
        ],
    )
    def test_an_inferred_publisher_is_logged_with_what_gave_it_away(self, tmp_path, cells, clue):
        result = self.convert(tmp_path, **cells)
        changes = [c for c in result.value_changes if c.target == "/metadata/publisher"]
        assert len(changes) == 1
        assert changes[0].raw == ""
        assert changes[0].action == "transformed"
        assert clue in changes[0].reason

    def test_a_publisher_given_in_the_export_is_not_logged_as_a_change(self, tmp_path):
        result = self.convert(tmp_path, publisher="Some Press", pub_statement="© 2019 IEEE")
        assert result.collections["articles"][0]["metadata"]["publisher"] == "Some Press"
        assert [c for c in result.value_changes if c.target == "/metadata/publisher"] == []
