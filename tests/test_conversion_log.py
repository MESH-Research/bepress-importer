"""Behavioural tests for conversion provenance: value-change capture and log rendering."""

import json
from pathlib import Path

from click.testing import CliRunner

from bepress_importer.cli import cli
from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import load_profile
from bepress_importer.readers import read_workbook

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = "2026-07-28"


def convert_golden():
    workbook = read_workbook(FIXTURES / "journal.csv")
    profile = load_profile(FIXTURES / "golden_profile.toml")
    return convert_workbook(workbook, profile, as_of=AS_OF)


def changes_for(result, record_id, source):
    return [
        c for c in result.value_changes if c.record_id == record_id and c.source == source
    ]


class TestValueChangeCapture:
    def test_doi_normalization_is_recorded(self):
        change = changes_for(convert_golden(), "2404130", "doi")[0]
        assert change.action == "transformed"
        assert change.raw == "https://doi.org/10.3138/jsp.43.4.347"
        assert change.result == {"identifier": "10.3138/jsp.43.4.347", "scheme": "doi"}
        assert change.target == "/metadata/identifiers"

    def test_edtf_season_change_names_the_season(self):
        change = changes_for(convert_golden(), "2404130", "publication_date")[0]
        assert change.raw == "2012-01-01"
        assert change.result == "2012-23"
        assert "Fall" in change.reason

    def test_keyword_split_is_recorded(self):
        change = changes_for(convert_golden(), "2404130", "keywords")[0]
        assert change.result == ["open access", "publishing"]

    def test_expired_embargo_drop_is_recorded_with_as_of(self):
        change = changes_for(convert_golden(), "2404130", "embargo_date")[0]
        assert change.action == "dropped"
        assert AS_OF in change.reason

    def test_active_embargo_is_recorded_as_transformed(self):
        change = changes_for(convert_golden(), "2404131", "embargo_date")[0]
        assert change.action == "transformed"
        assert change.result == {"embargo": {"active": True, "until": "2029-06-01"}}

    def test_verbatim_copies_are_not_logged(self):
        assert changes_for(convert_golden(), "2404130", "title") == []

    def test_capture_is_deterministic(self):
        assert convert_golden().value_changes == convert_golden().value_changes


class TestConversionLogFiles:
    def run_convert(self, tmp_path):
        out = tmp_path / "out"
        result = CliRunner().invoke(
            cli,
            ["convert", str(FIXTURES / "journal.csv"),
             "--profile", str(FIXTURES / "golden_profile.toml"),
             "-o", str(out), "--as-of", AS_OF],
        )
        assert result.exit_code == 0, result.output
        return out

    def test_json_log_documents_mappings_and_changes(self, tmp_path):
        out = self.run_convert(tmp_path)
        log = json.loads((out / "conversion-log.json").read_text())
        assert log["profile"] == "golden"
        assert log["as_of"] == AS_OF
        sheet = log["sheets"][0]
        assert sheet["collection"] == "fac_journ"
        sources = {m["source"] for m in sheet["mappings"]}
        assert {"title", "publication_date", "doi", "keywords"} <= sources
        title = next(m for m in sheet["mappings"] if m["source"] == "title")
        assert title["target"] == "/metadata/title"
        assert log["value_changes"]  # per-record diffs present

    def test_text_log_is_written_and_covers_mappings_and_changes(self, tmp_path):
        out = self.run_convert(tmp_path)
        text = (out / "conversion-log.txt").read_text()
        # every mapped source column is explained
        for source in ("title", "publication_date", "abstract", "doi", "keywords"):
            assert source in text
        # builders and identifiers are explained
        assert "creators" in text
        assert "import-recid" in text
        # per-record value changes appear with record ids
        assert "2404130" in text
        assert "10.3138/jsp.43.4.347" in text

    def test_unmapped_nonempty_columns_are_called_out(self, tmp_path):
        csv = tmp_path / "journal.csv"
        csv.write_text(
            "title,publication_date,document_type,context_key,issue,mystery_column\n"
            "T,2001-01-01,article,42,coll,secret data\n"
        )
        out = tmp_path / "out"
        result = CliRunner().invoke(
            cli,
            ["convert", str(csv), "--profile", str(FIXTURES / "golden_profile.toml"),
             "-o", str(out), "--as-of", AS_OF],
        )
        assert result.exit_code == 0, result.output
        log = json.loads((out / "conversion-log.json").read_text())
        assert "mystery_column" in log["sheets"][0]["unmapped_columns"]
        assert "mystery_column" in (out / "conversion-log.txt").read_text()

    def test_row_filter_appears_in_text_log(self, tmp_path):
        csv = tmp_path / "inv.csv"
        csv.write_text(
            "title,state,context_key,issue\n"
            "Keep,published,1,coll\nGone,withdrawn,2,coll\n"
        )
        profile_toml = tmp_path / "p.toml"
        profile_toml.write_text(
            '[profile]\nname = "p"\n[[sheet]]\nmatch = "*"\n'
            '[sheet.filter]\ncolumn = "state"\nkeep = ["published"]\n'
            '[[sheet.field]]\nsource = "title"\ntarget = "/metadata/title"\n'
        )
        out = tmp_path / "out"
        result = CliRunner().invoke(
            cli, ["convert", str(csv), "--profile", str(profile_toml),
                  "-o", str(out), "--as-of", AS_OF],
        )
        assert result.exit_code == 0, result.output
        text = (out / "conversion-log.txt").read_text()
        assert "state" in text
        assert "published" in text
        assert "1" in text  # excluded count
        assert "2" in text  # excluded record id

    def test_log_files_are_byte_deterministic(self, tmp_path):
        out1 = self.run_convert(tmp_path / "a")
        out2 = self.run_convert(tmp_path / "b")
        for name in ("conversion-log.json", "conversion-log.txt"):
            assert (out1 / name).read_bytes() == (out2 / name).read_bytes()
