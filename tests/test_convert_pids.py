"""Behavioural tests for DOI handling across a whole conversion.

With `[defaults.doi_pid]` set in the profile, a record's existing DOI ends up
in its `pids` block; DOIs that two records both claim are registered for
neither.
"""

from bepress_importer import conversion_log
from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import load_profile
from bepress_importer.readers import Table, Workbook
from bepress_importer.transforms import known_transforms

AS_OF = "2026-11-26"
COLUMNS = (
    "context_key", "title", "publication_date", "doi", "pub_link",
    "author1_fname", "author1_lname",
)
PROFILE = """
[profile]
name = "p"
{defaults}
[[sheet]]
match = "*"
collection = "articles"
[sheet.resource_type]
constant = "textDocument-journalArticle"
[[sheet.field]]
source = "title"
target = "/metadata/title"
# the doi column is listed first, so it wins over a link that disagrees
[[sheet.field]]
source = "doi"
target = "/metadata/identifiers"
transform = "identifier"
args = {{ scheme = "doi", normalize = "doi" }}
append = true
[[sheet.field]]
source = "pub_link"
target = "/metadata/identifiers"
transform = "identifier"
args = {{ scheme = "url", doi_references = true }}
append = true
"""
WITH_PID = '[defaults.doi_pid]\nprovider = "external"\n'


def row(key, **cells):
    base = {column: "" for column in COLUMNS}
    base.update(context_key=key, title=f"Article {key}", author1_fname="A", author1_lname="B")
    base.update(cells)
    return base


def convert(tmp_path, rows, defaults=WITH_PID):
    path = tmp_path / "p.toml"
    path.write_text(PROFILE.format(defaults=defaults))
    profile = load_profile(path, known_transforms=known_transforms())
    table = Table(name="Sheet", columns=COLUMNS, rows=tuple(rows))
    return convert_workbook(Workbook(tables=(table,)), profile, as_of=AS_OF)


def by_id(result):
    return {
        next(i["identifier"] for i in r["metadata"]["identifiers"] if i["scheme"] == "import-recid"): r
        for r in result.collections["articles"]
    }


class TestProfileOption:
    def test_profiles_do_not_register_doi_pids_unless_asked(self, tmp_path):
        result = convert(tmp_path, [row("1", doi="10.1000/a")], defaults="")
        record = by_id(result)["1"]
        assert "pids" not in record
        assert {"identifier": "10.1000/a", "scheme": "doi"} in record["metadata"]["identifiers"]

    def test_doi_pid_settings_are_read_from_the_profile(self, tmp_path):
        path = tmp_path / "p.toml"
        path.write_text(PROFILE.format(defaults=WITH_PID))
        assert load_profile(path).defaults.doi_pid.provider == "external"
        assert load_profile(path).defaults.doi_pid.keep_identifiers is False
        path.write_text(PROFILE.format(defaults=""))
        assert load_profile(path).defaults.doi_pid is None


class TestDoiPidDuringConversion:
    def test_doi_column_becomes_the_external_doi_pid(self, tmp_path):
        record = by_id(convert(tmp_path, [row("1", doi="https://doi.org/10.1000/a")]))["1"]
        assert record["pids"] == {"doi": {"identifier": "10.1000/a", "provider": "external"}}
        assert record["metadata"]["identifiers"] == [{"identifier": "1", "scheme": "import-recid"}]

    def test_resolver_link_becomes_the_external_doi_pid(self, tmp_path):
        result = convert(
            tmp_path,
            [
                row("1", pub_link="https://dx.doi.org/10.1000/a"),
                row("2", pub_link="dx.doi.org/10.1000/b"),
                row("3", pub_link="http://doi.org/10.1000/c"),
            ],
        )
        assert {k: r["pids"]["doi"]["identifier"] for k, r in by_id(result).items()} == {
            "1": "10.1000/a", "2": "10.1000/b", "3": "10.1000/c",
        }

    def test_link_and_doi_column_for_the_same_doi_leave_no_duplicate_behind(self, tmp_path):
        record = by_id(
            convert(tmp_path, [row("1", doi="10.1000/a", pub_link="http://dx.doi.org/10.1000/A")])
        )["1"]
        assert record["pids"]["doi"]["identifier"] == "10.1000/a"
        assert record["metadata"]["identifiers"] == [{"identifier": "1", "scheme": "import-recid"}]

    def test_ordinary_links_stay_and_records_without_a_doi_get_no_pids(self, tmp_path):
        result = convert(
            tmp_path,
            [
                row("1", doi="10.1000/a", pub_link="https://publisher.example/article/1"),
                row("2", pub_link="https://publisher.example/article/2"),
            ],
        )
        records = by_id(result)
        assert {"identifier": "https://publisher.example/article/1", "scheme": "url"} in (
            records["1"]["metadata"]["identifiers"]
        )
        assert "pids" not in records["2"]

    def test_identifiers_can_be_kept_alongside_the_pid(self, tmp_path):
        defaults = '[defaults.doi_pid]\nprovider = "external"\nkeep_identifiers = true\n'
        record = by_id(convert(tmp_path, [row("1", doi="10.1000/a")], defaults=defaults))["1"]
        assert record["pids"]["doi"]["identifier"] == "10.1000/a"
        assert {"identifier": "10.1000/a", "scheme": "doi"} in record["metadata"]["identifiers"]


class TestSharedDois:
    def rows(self):
        return [
            row("1", doi="10.1000/shared"),
            row("2", pub_link="https://doi.org/10.1000/SHARED"),
            row("3", doi="10.1000/own"),
        ]

    def test_a_doi_claimed_by_two_records_is_registered_for_neither(self, tmp_path):
        records = by_id(convert(tmp_path, self.rows()))
        assert "pids" not in records["1"]
        assert "pids" not in records["2"]
        assert records["3"]["pids"]["doi"]["identifier"] == "10.1000/own"

    def test_the_shared_doi_survives_as_a_link_on_both(self, tmp_path):
        records = by_id(convert(tmp_path, self.rows()))
        for key in ("1", "2"):
            links = [
                i["identifier"].lower()
                for i in records[key]["metadata"]["identifiers"]
                if i["scheme"] == "url"
            ]
            assert links == ["https://doi.org/10.1000/shared"]
            assert all(i["scheme"] != "doi" for i in records[key]["metadata"]["identifiers"])

    def test_each_claimant_is_reported_with_the_other(self, tmp_path):
        issues = {
            i.record_id: i.message for i in convert(tmp_path, self.rows()).issues
        }
        assert set(issues) == {"1", "2"}
        assert "10.1000/shared" in issues["1"].lower() and "2" in issues["1"]
        assert "10.1000/shared" in issues["2"].lower() and "1" in issues["2"]


class TestUnreadableDois:
    def test_an_unreadable_doi_is_omitted_and_reported(self, tmp_path):
        result = convert(tmp_path, [row("1", doi="10.1007.s00709-017-1117-9")])
        record = by_id(result)["1"]
        assert "pids" not in record
        assert record["metadata"]["identifiers"] == [{"identifier": "1", "scheme": "import-recid"}]
        assert [(i.record_id, "10.1007.s00709-017-1117-9" in i.message) for i in result.issues] == [
            ("1", True)
        ]

    def test_the_same_link_given_twice_is_recorded_once(self, tmp_path):
        link = "https://joi.pm-research.com/content/28/5/122"
        record = by_id(convert(tmp_path, [row("1", doi=link, pub_link=link)]))["1"]
        assert record["metadata"]["identifiers"] == [
            {"identifier": "1", "scheme": "import-recid"},
            {"identifier": link, "scheme": "url"},
        ]


class TestProvenance:
    def test_promotion_is_recorded_as_a_value_change(self, tmp_path):
        result = convert(tmp_path, [row("1", doi="https://doi.org/10.1000/a")])
        changes = [c for c in result.value_changes if c.target == "/pids/doi"]
        assert len(changes) == 1
        assert changes[0].record_id == "1"
        assert changes[0].collection == "articles"
        assert changes[0].result == {"identifier": "10.1000/a", "provider": "external"}

    def test_the_log_explains_the_doi_pid_rule_for_the_sheet(self, tmp_path):
        result = convert(tmp_path, [row("1", doi="10.1000/a")])
        payload = conversion_log.build_payload(
            "in.xlsx", "p", AS_OF, result.sheet_docs, result.value_changes, result.issues
        )
        assert payload["sheets"][0]["doi_pid"]["provider"] == "external"
        assert "pids.doi" in conversion_log.render_text(payload)

    def test_conversion_stays_deterministic(self, tmp_path):
        rows = TestSharedDois().rows()
        first, second = convert(tmp_path, rows), convert(tmp_path, rows)
        assert first.collections == second.collections
        assert first.value_changes == second.value_changes
        assert first.issues == second.issues
