"""Behavioural tests for ROR ids on creators' affiliations during conversion."""

from bepress_importer import conversion_log
from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import load_profile
from bepress_importer.readers import Table, Workbook
from bepress_importer.ror import RorResolver, RorUnavailable
from bepress_importer.transforms import known_transforms

COLUMNS = (
    "context_key", "title",
    *(f"author{n}_{part}" for n in (1, 2, 3, 4) for part in ("fname", "lname", "institution")),
)
AFFILIATIONS = """
[defaults.affiliations]
ror_lookup = true
[defaults.affiliations.ror_ids]
"00fc1qt65" = ["Bucknell University", "Bucknell"]
"""
PROFILE = """
[profile]
name = "p"
[defaults.author_columns]
prefix = "author"
max = 4
{affiliations}
[[sheet]]
match = "*"
collection = "articles"
[sheet.resource_type]
constant = "textDocument-journalArticle"
[[sheet.field]]
source = "title"
target = "/metadata/title"
"""
PENN_STATE = {
    "items": [
        {
            "chosen": True, "score": 1.0, "matching_type": "SINGLE SEARCH",
            "organization": {
                "id": "https://ror.org/04p491231", "status": "active",
                "names": [{"types": ["ror_display"], "value": "Pennsylvania State University"}],
            },
        }
    ]
}
NOTHING = {"items": []}


def fetch(text):
    return {"The Pennsylvania State University": PENN_STATE}.get(text, NOTHING)


def author(n, institution, fname="A", lname=None):
    return {
        f"author{n}_fname": fname, f"author{n}_lname": lname or f"Author{n}",
        f"author{n}_institution": institution,
    }


def convert(tmp_path, cells, ror=None, affiliations=AFFILIATIONS):
    path = tmp_path / "p.toml"
    path.write_text(PROFILE.format(affiliations=affiliations))
    row = {column: "" for column in COLUMNS} | {"context_key": "1", "title": "T"} | cells
    table = Table(name="Sheet", columns=COLUMNS, rows=(row,))
    profile = load_profile(path, known_transforms=known_transforms())
    return convert_workbook(Workbook(tables=(table,)), profile, as_of="2026-11-26", ror=ror)


def affiliations_of(result):
    creators = result.collections["articles"][0]["metadata"]["creators"]
    return [creator.get("affiliations") for creator in creators]


class TestRorIdsOnAffiliations:
    def test_an_institution_the_profile_fixes_carries_its_id_and_nothing_else(self, tmp_path):
        result = convert(tmp_path, author(1, "Bucknell University"))
        assert affiliations_of(result) == [[{"id": "00fc1qt65"}]]

    def test_a_certain_api_match_carries_its_id(self, tmp_path):
        result = convert(
            tmp_path, author(1, "The Pennsylvania State University"), ror=RorResolver(fetch=fetch)
        )
        assert affiliations_of(result) == [[{"id": "04p491231"}]]

    def test_an_affiliation_without_a_certain_match_stays_as_text(self, tmp_path):
        result = convert(
            tmp_path, author(1, "Lewisburg Neighborhoods"), ror=RorResolver(fetch=fetch)
        )
        assert affiliations_of(result) == [[{"name": "Lewisburg Neighborhoods"}]]

    def test_each_creator_is_settled_separately(self, tmp_path):
        cells = (
            author(1, "Bucknell University") | author(2, "The Pennsylvania State University")
            | author(3, "Lewisburg Neighborhoods") | author(4, "")
        )
        resolver = RorResolver(known={"00fc1qt65": ["Bucknell University"]}, fetch=fetch)
        assert affiliations_of(convert(tmp_path, cells, ror=resolver)) == [
            [{"id": "00fc1qt65"}], [{"id": "04p491231"}],
            [{"name": "Lewisburg Neighborhoods"}], None,
        ]

    def test_without_a_resolver_only_the_profiles_own_ids_are_used(self, tmp_path):
        cells = author(1, "Bucknell") | author(2, "The Pennsylvania State University")
        assert affiliations_of(convert(tmp_path, cells)) == [
            [{"id": "00fc1qt65"}], [{"name": "The Pennsylvania State University"}],
        ]

    def test_a_profile_that_does_not_ask_for_ror_ids_keeps_every_affiliation_as_text(
        self, tmp_path
    ):
        resolver = RorResolver(known={"00fc1qt65": ["Bucknell University"]}, fetch=fetch)
        cells = author(1, "Bucknell University") | author(2, "The Pennsylvania State University")
        result = convert(tmp_path, cells, ror=resolver, affiliations="")
        assert affiliations_of(result) == [
            [{"name": "Bucknell University"}], [{"name": "The Pennsylvania State University"}],
        ]
        assert result.value_changes == []

    def test_an_unreachable_api_leaves_the_text_and_does_not_stop_the_conversion(self, tmp_path):
        def down(text):
            raise RorUnavailable("down")

        result = convert(tmp_path, author(1, "The Pennsylvania State University"), ror=RorResolver(fetch=down))
        assert affiliations_of(result) == [[{"name": "The Pennsylvania State University"}]]


class TestRorChangesAreLogged:
    def changes(self, tmp_path, cells):
        resolver = RorResolver(known={"00fc1qt65": ["Bucknell University"]}, fetch=fetch)
        return convert(tmp_path, cells, ror=resolver)

    def test_each_affiliation_given_an_id_is_one_logged_change(self, tmp_path):
        cells = (
            author(1, "Bucknell University") | author(3, "The Pennsylvania State University")
            | author(4, "Lewisburg Neighborhoods")
        )
        logged = {c.source: c for c in self.changes(tmp_path, cells).value_changes}
        assert set(logged) == {"author1_institution", "author3_institution"}
        bucknell, penn = logged["author1_institution"], logged["author3_institution"]
        assert (bucknell.raw, bucknell.result) == ("Bucknell University", {"id": "00fc1qt65"})
        assert bucknell.target == "/metadata/creators/0/affiliations/0"
        assert (penn.raw, penn.result) == ("The Pennsylvania State University", {"id": "04p491231"})
        assert penn.target == "/metadata/creators/1/affiliations/0"
        assert penn.record_id == "1"

    def test_the_reason_names_the_organisation_the_api_matched(self, tmp_path):
        change = self.changes(tmp_path, author(1, "The Pennsylvania State University")).value_changes[0]
        assert "Pennsylvania State University" in change.reason

    def test_the_reason_tells_a_fixed_id_from_a_looked_up_one(self, tmp_path):
        cells = author(1, "Bucknell University") | author(2, "The Pennsylvania State University")
        fixed, looked_up = self.changes(tmp_path, cells).value_changes
        assert "ROR API" in looked_up.reason
        assert "ROR API" not in fixed.reason

    def test_the_log_text_carries_a_line_for_the_change(self, tmp_path):
        result = self.changes(tmp_path, author(1, "The Pennsylvania State University"))
        payload = conversion_log.build_payload(
            "in.xlsx", "p", "2026-11-26", result.sheet_docs, result.value_changes, result.issues
        )
        lines = [
            line for line in conversion_log.render_text(payload).splitlines()
            if "04p491231" in line or "The Pennsylvania State University" in line
        ]
        assert lines

    def test_the_mapping_rules_say_affiliations_take_ror_ids(self, tmp_path):
        result = self.changes(tmp_path, author(1, "Bucknell University"))
        assert "ROR" in result.sheet_docs[0]["builders"]["creators"]
