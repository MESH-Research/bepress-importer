"""Behavioural tests for multi-column builders: row in → KC Works sub-object out."""

from bepress_importer.builders import (
    build_contributors,
    build_creators,
    build_imprint,
    build_journal,
    creator_positions,
    implausible_journal_values,
)
from bepress_importer.profiles import (
    AuthorColumns,
    ContributorColumns,
    ImprintMapping,
    JournalMapping,
)

AUTHORS = AuthorColumns(prefix="author", max=5)
ADVISORS = ContributorColumns(prefix="advisor", max=3, role="committeeMember")
JOURNAL = JournalMapping(
    title="src_journal", volume="volnum", issue="issnum", pages_first="fpage", pages_last="lpage"
)
IMPRINT = ImprintMapping(title="publisher", isbn="isbn", place="city")


class TestBuildCreators:
    def test_personal_author(self):
        row = {
            "author1_fname": "Kathleen",
            "author1_lname": "Fitzpatrick",
            "author1_institution": "Modern Languages Association",
        }
        assert build_creators(row, AUTHORS) == [
            {
                "person_or_org": {
                    "type": "personal",
                    "name": "Fitzpatrick, Kathleen",
                    "given_name": "Kathleen",
                    "family_name": "Fitzpatrick",
                },
                "role": {"id": "author"},
                "affiliations": [{"name": "Modern Languages Association"}],
            }
        ]

    def test_middle_name_joins_given_name(self):
        row = {"author1_fname": "John", "author1_mname": "Q.", "author1_lname": "Smith"}
        creator = build_creators(row, AUTHORS)[0]["person_or_org"]
        assert creator["given_name"] == "John Q."
        assert creator["name"] == "Smith, John Q."

    def test_suffix_is_appended_to_name(self):
        row = {"author1_fname": "John", "author1_lname": "Smith", "author1_suffix": "Jr."}
        creator = build_creators(row, AUTHORS)[0]["person_or_org"]
        assert creator["name"] == "Smith, John, Jr."

    def test_corporate_author_is_organizational(self):
        row = {"author1_lname": "Bucknell University", "author1_is_corporate": "TRUE"}
        assert build_creators(row, AUTHORS) == [
            {
                "person_or_org": {"type": "organizational", "name": "Bucknell University"},
                "role": {"id": "author"},
            }
        ]

    def test_corporate_name_falls_back_to_fname(self):
        row = {"author1_fname": "Bucknell University Press", "author1_is_corporate": "TRUE"}
        creator = build_creators(row, AUTHORS)[0]["person_or_org"]
        assert creator["name"] == "Bucknell University Press"

    def test_empty_author_slots_are_skipped_and_order_kept(self):
        row = {
            "author1_fname": "Ada",
            "author1_lname": "Lovelace",
            "author2_fname": "",
            "author2_lname": "",
            "author3_fname": "Alan",
            "author3_lname": "Turing",
        }
        names = [c["person_or_org"]["family_name"] for c in build_creators(row, AUTHORS)]
        assert names == ["Lovelace", "Turing"]

    def test_slots_beyond_max_are_ignored(self):
        row = {"author6_fname": "Too", "author6_lname": "Many"}
        assert build_creators(row, AUTHORS) == []

    def test_no_affiliation_key_when_institution_empty(self):
        row = {"author1_fname": "Ada", "author1_lname": "Lovelace", "author1_institution": ""}
        assert "affiliations" not in build_creators(row, AUTHORS)[0]


class TestBuildContributors:
    def test_family_comma_given_form(self):
        row = {"advisor1": "Smith, Jane"}
        assert build_contributors(row, ADVISORS) == [
            {
                "person_or_org": {
                    "type": "personal",
                    "name": "Smith, Jane",
                    "given_name": "Jane",
                    "family_name": "Smith",
                },
                "role": {"id": "committeeMember"},
            }
        ]

    def test_given_family_form(self):
        row = {"advisor1": "John Ronald Reuel Tolkien"}
        person = build_contributors(row, ADVISORS)[0]["person_or_org"]
        assert person["family_name"] == "Tolkien"
        assert person["given_name"] == "John Ronald Reuel"
        assert person["name"] == "Tolkien, John Ronald Reuel"

    def test_single_token_name(self):
        person = build_contributors({"advisor1": "Aristotle"}, ADVISORS)[0]["person_or_org"]
        assert person["family_name"] == "Aristotle"
        assert person["name"] == "Aristotle"

    def test_empty_slots_skipped(self):
        row = {"advisor1": "", "advisor2": "Smith, Jane", "advisor3": ""}
        assert len(build_contributors(row, ADVISORS)) == 1


class TestBuildJournal:
    def test_full_journal(self):
        row = {
            "src_journal": "Journal of Scholarly Publishing",
            "volnum": "43",
            "issnum": "4",
            "fpage": "347",
            "lpage": "362",
        }
        assert build_journal(row, JOURNAL) == {
            "title": "Journal of Scholarly Publishing",
            "volume": "43",
            "issue": "4",
            "pages": "347-362",
        }

    def test_first_page_only(self):
        row = {"src_journal": "JSP", "fpage": "347", "lpage": ""}
        assert build_journal(row, JOURNAL)["pages"] == "347"

    def test_all_empty_returns_none(self):
        assert build_journal({}, JOURNAL) is None


class TestBuildImprint:
    def test_full_imprint(self):
        row = {"publisher": "Bucknell University Press", "isbn": "978-1", "city": "Lewisburg"}
        assert build_imprint(row, IMPRINT) == {
            "title": "Bucknell University Press",
            "isbn": "978-1",
            "place": "Lewisburg",
        }

    def test_all_empty_returns_none(self):
        assert build_imprint({}, IMPRINT) is None


AUTHORS_WITH_JSON = AuthorColumns(prefix="author", max=5, json_column="authors")


def organisation(name):
    return {"person_or_org": {"type": "organizational", "name": name}, "role": {"id": "author"}}


class TestCorporateAuthorsFromTheJsonColumn:
    def test_a_corporate_author_found_only_in_the_json_column_becomes_a_creator(self):
        row = {
            "authors": '[{"CORPORATE_AUTHOR": "Bucknell University Environmental Center", '
                       '"IS_CORPORATE_AUTHOR": "1"}]',
        }
        assert build_creators(row, AUTHORS_WITH_JSON) == [
            organisation("Bucknell University Environmental Center")
        ]

    def test_a_corporate_author_keeps_its_place_among_the_people(self):
        row = {
            "authors": '[{"FNAME": "Joshua", "LNAME": "Livnat"}, '
                       '{"CORPORATE_AUTHOR": "QMA", "IS_CORPORATE_AUTHOR": 1}, '
                       '{"FNAME": "Selina", "LNAME": "Pei"}]',
            "author1_fname": "Joshua", "author1_lname": "Livnat",
            "author3_fname": "Selina", "author3_lname": "Pei",
        }
        names = [c["person_or_org"]["name"] for c in build_creators(row, AUTHORS_WITH_JSON)]
        assert names == ["Livnat, Joshua", "QMA", "Pei, Selina"]

    def test_people_are_taken_from_their_columns_not_duplicated_from_the_json(self):
        row = {
            "authors": '[{"FNAME": "Ada", "LNAME": "Lovelace"}]',
            "author1_fname": "Ada", "author1_lname": "Lovelace",
        }
        assert len(build_creators(row, AUTHORS_WITH_JSON)) == 1

    def test_an_unreadable_or_empty_json_cell_changes_nothing(self):
        for cell in ("", "[]", "not json", '{"CORPORATE_AUTHOR": "x"}'):
            row = {"authors": cell, "author1_fname": "Ada", "author1_lname": "Lovelace"}
            names = [c["person_or_org"]["name"] for c in build_creators(row, AUTHORS_WITH_JSON)]
            assert names == ["Lovelace, Ada"], cell

    def test_the_json_column_is_ignored_unless_configured(self):
        row = {"authors": '[{"CORPORATE_AUTHOR": "QMA", "IS_CORPORATE_AUTHOR": 1}]'}
        assert build_creators(row, AUTHORS) == []


class TestAffiliationSanity:
    def test_an_email_address_is_not_an_affiliation(self):
        row = {
            "author1_fname": "Kate", "author1_lname": "Suslava",
            "author1_institution": "ks063@bucknell.edu",
        }
        assert "affiliations" not in build_creators(row, AUTHORS)[0]


class TestJournalPlausibility:
    def journal(self, **cells):
        return build_journal({"src_journal": "J", **cells}, JOURNAL)

    def test_an_end_page_that_is_a_remark_is_left_off(self):
        assert self.journal(fpage="062105", lpage="not applicable")["pages"] == "062105"

    def test_a_paragraph_in_a_page_cell_is_not_a_page(self):
        text = "1. Money and Value The more than century-long controversy concerning value"
        assert "pages" not in self.journal(fpage=text, lpage=text)

    def test_a_link_in_a_page_cell_is_not_a_page(self):
        assert "pages" not in self.journal(fpage="https://example.org/article/1861/view/")

    def test_a_word_in_a_page_cell_is_not_a_page(self):
        assert "pages" not in self.journal(fpage="Advance Article", lpage="Advance Article")
        assert "pages" not in self.journal(fpage="Online")

    def test_article_numbers_and_roman_numerals_are_pages(self):
        assert self.journal(fpage="Article 68")["pages"] == "Article 68"
        assert self.journal(fpage="e01795-16")["pages"] == "e01795-16"
        assert self.journal(fpage="vi", lpage="xvi")["pages"] == "vi-xvi"
        assert self.journal(fpage="251, 346", lpage="265, 347")["pages"] == "251, 346-265, 347"

    def test_a_note_in_place_of_a_volume_or_issue_is_left_off(self):
        journal = self.journal(
            volnum="Online First: doi:10.1177/1468087411424376",
            issnum="Latest Issue (Jan-Feb. 2020)",
        )
        assert "volume" not in journal and "issue" not in journal

    def test_ordinary_volumes_and_issues_are_kept(self):
        journal = self.journal(volnum="122", issnum="Special Issue 3")
        assert (journal["volume"], journal["issue"]) == ("122", "Special Issue 3")

    def test_every_value_left_out_is_named(self):
        row = {
            "src_journal": "J", "volnum": "Online; print edition forthcoming",
            "issnum": "4", "fpage": "062105", "lpage": "not applicable",
        }
        assert implausible_journal_values(row, JOURNAL) == [
            ("volnum", "Online; print edition forthcoming"),
            ("lpage", "not applicable"),
        ]

    def test_a_clean_row_has_nothing_implausible(self):
        row = {"src_journal": "J", "volnum": "3", "issnum": "7", "fpage": "1", "lpage": "9"}
        assert implausible_journal_values(row, JOURNAL) == []


class TestNameSuffixes:
    def test_a_class_year_is_not_part_of_the_name(self):
        row = {"author1_fname": "Megan", "author1_lname": "Bugniazet", "author1_suffix": "'20"}
        person = build_creators(row, AUTHORS)[0]["person_or_org"]
        assert person["name"] == "Bugniazet, Megan"

    def test_a_curly_apostrophe_class_year_is_recognised_too(self):
        row = {"author1_fname": "Erin", "author1_lname": "Grundy", "author1_suffix": "’18"}
        assert build_creators(row, AUTHORS)[0]["person_or_org"]["name"] == "Grundy, Erin"

    def test_a_genuine_suffix_is_kept(self):
        row = {"author1_fname": "Martin", "author1_lname": "King", "author1_suffix": "Jr."}
        assert build_creators(row, AUTHORS)[0]["person_or_org"]["name"] == "King, Martin, Jr."


class TestCreatorPositions:
    def test_each_creator_is_traced_to_its_author_number(self):
        row = {
            "author1_fname": "Ada", "author1_lname": "Lovelace",
            "author3_fname": "Alan", "author3_lname": "Turing",
        }
        assert creator_positions(row, AUTHORS) == [1, 3]
        assert len(build_creators(row, AUTHORS)) == 2

    def test_a_corporate_author_from_the_json_column_holds_its_position(self):
        row = {
            "authors": '[{"FNAME": "J", "LNAME": "L"}, {"CORPORATE_AUTHOR": "QMA"}, '
                       '{"FNAME": "S", "LNAME": "P"}]',
            "author1_fname": "J", "author1_lname": "L",
            "author3_fname": "S", "author3_lname": "P",
        }
        assert creator_positions(row, AUTHORS_WITH_JSON) == [1, 2, 3]

    def test_no_authors_no_positions(self):
        assert creator_positions({}, AUTHORS) == []
