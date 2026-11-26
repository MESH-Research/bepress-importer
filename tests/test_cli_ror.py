"""Behavioural tests for ROR lookups from the convert command. The ROR API is
replaced by a fake throughout; nothing here touches the network."""

import json

import pytest
from click.testing import CliRunner

from bepress_importer import ror
from bepress_importer.cli import cli

CSV = (
    "context_key,title,author1_fname,author1_lname,author1_institution,"
    "author2_fname,author2_lname,author2_institution\n"
    "1,First,Ada,Lovelace,Bucknell University,Alan,Turing,Penn State University\n"
    "2,Second,Grace,Hopper,Lewisburg Neighborhoods,,,\n"
)
PROFILE = """
[profile]
name = "p"
[defaults.author_columns]
prefix = "author"
max = 2
[defaults.affiliations]
ror_lookup = {lookup}
[defaults.affiliations.ror_ids]
"00fc1qt65" = ["Bucknell University"]
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
            "chosen": True, "score": 1.0,
            "organization": {
                "id": "https://ror.org/04p491231", "status": "active",
                "names": [{"types": ["ror_display"], "value": "Pennsylvania State University"}],
            },
        }
    ]
}


def answering(text, **kwargs):
    return PENN_STATE if text == "Penn State University" else {"items": []}


def forbidden(text, **kwargs):
    raise AssertionError(f"the ROR API must not be asked about {text!r}")


def unreachable(text, **kwargs):
    raise ror.RorUnavailable("down")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "in.csv").write_text(CSV)
    (tmp_path / "p.toml").write_text(PROFILE.format(lookup="true"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def convert(workspace, *extra, out="out"):
    result = CliRunner().invoke(
        cli,
        ["convert", "in.csv", "--profile", "p.toml", "-o", out, "--as-of", "2026-11-26", *extra],
    )
    affiliations = None
    if result.exit_code == 0:
        records = json.loads((workspace / out / "articles.json").read_text())
        affiliations = [
            creator.get("affiliations")
            for record in records
            for creator in record["metadata"]["creators"]
        ]
    return result, affiliations


class TestConvertLooksAffiliationsUp:
    def test_fixed_and_looked_up_ids_reach_the_output(self, workspace, monkeypatch):
        monkeypatch.setattr(ror, "fetch_affiliation", answering)
        result, affiliations = convert(workspace, "--ror-cache", "cache/ror.sqlite3")
        assert result.exit_code == 0, result.output
        assert affiliations == [
            [{"id": "00fc1qt65"}], [{"id": "04p491231"}], [{"name": "Lewisburg Neighborhoods"}],
        ]

    def test_a_second_run_needs_no_api_and_gives_the_same_bytes(self, workspace, monkeypatch):
        monkeypatch.setattr(ror, "fetch_affiliation", answering)
        convert(workspace, "--ror-cache", "ror.sqlite3", out="a")
        monkeypatch.setattr(ror, "fetch_affiliation", forbidden)
        result, _ = convert(workspace, "--ror-cache", "ror.sqlite3", out="b")
        assert result.exit_code == 0, result.output
        for name in ("articles.json", "conversion-log.json", "conversion-log.txt"):
            assert (workspace / "a" / name).read_bytes() == (workspace / "b" / name).read_bytes()

    def test_the_cache_has_a_default_place(self, workspace, monkeypatch):
        monkeypatch.setattr(ror, "fetch_affiliation", answering)
        convert(workspace, out="a")
        monkeypatch.setattr(ror, "fetch_affiliation", forbidden)
        result, affiliations = convert(workspace, out="b")
        assert result.exit_code == 0, result.output
        assert affiliations[1] == [{"id": "04p491231"}]

    def test_no_ror_lookup_keeps_the_run_off_the_network(self, workspace, monkeypatch):
        monkeypatch.setattr(ror, "fetch_affiliation", forbidden)
        result, affiliations = convert(workspace, "--no-ror-lookup")
        assert result.exit_code == 0, result.output
        assert affiliations == [
            [{"id": "00fc1qt65"}], [{"name": "Penn State University"}],
            [{"name": "Lewisburg Neighborhoods"}],
        ]

    def test_no_ror_lookup_still_uses_answers_already_cached(self, workspace, monkeypatch):
        monkeypatch.setattr(ror, "fetch_affiliation", answering)
        convert(workspace, out="a")
        monkeypatch.setattr(ror, "fetch_affiliation", forbidden)
        _, affiliations = convert(workspace, "--no-ror-lookup", out="b")
        assert affiliations[1] == [{"id": "04p491231"}]

    def test_a_profile_that_does_not_ask_for_lookups_makes_none(self, workspace, monkeypatch):
        (workspace / "p.toml").write_text(PROFILE.format(lookup="false"))
        monkeypatch.setattr(ror, "fetch_affiliation", forbidden)
        result, affiliations = convert(workspace)
        assert result.exit_code == 0, result.output
        assert affiliations[:2] == [[{"id": "00fc1qt65"}], [{"name": "Penn State University"}]]

    def test_an_unreachable_api_does_not_fail_the_conversion_but_is_reported(
        self, workspace, monkeypatch
    ):
        monkeypatch.setattr(ror, "fetch_affiliation", unreachable)
        result, affiliations = convert(workspace)
        assert result.exit_code == 0, result.output
        assert affiliations[1] == [{"name": "Penn State University"}]
        assert "ROR" in result.output

    def test_a_lookup_that_failed_is_tried_again_next_time(self, workspace, monkeypatch):
        monkeypatch.setattr(ror, "fetch_affiliation", unreachable)
        convert(workspace, out="a")
        monkeypatch.setattr(ror, "fetch_affiliation", answering)
        _, affiliations = convert(workspace, out="b")
        assert affiliations[1] == [{"id": "04p491231"}]
