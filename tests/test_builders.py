"""Behavioural tests for multi-column builders: row in → KC Works sub-object out."""

from bepress_importer.builders import (
    build_contributors,
    build_creators,
    build_imprint,
    build_journal,
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
