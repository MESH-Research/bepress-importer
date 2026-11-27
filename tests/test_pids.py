"""Behavioural tests for registering an existing DOI in a record's `pids` block."""

import pytest

from bepress_importer.pids import doi_claim, keep_doi_as_link, promote_doi_pid

RECID = {"identifier": "11707029", "scheme": "import-recid"}
DOI = "10.1016/j.jmps.2018.02.012"


def record(*identifiers):
    return {
        "metadata": {"identifiers": [dict(RECID), *(dict(i) for i in identifiers)]},
        "files": {"enabled": False},
    }


def doi(value):
    return {"identifier": value, "scheme": "doi"}


def url(value):
    return {"identifier": value, "scheme": "url"}


class TestPromoteDoiPid:
    def test_doi_identifier_becomes_an_external_doi_pid(self):
        rec = record(doi(DOI))
        promote_doi_pid(rec)
        assert rec["pids"] == {"doi": {"identifier": DOI, "provider": "external"}}

    @pytest.mark.parametrize(
        "link",
        [
            f"https://doi.org/{DOI}",
            f"http://doi.org/{DOI}",
            f"https://dx.doi.org/{DOI}",
            f"http://dx.doi.org/{DOI}",
        ],
    )
    def test_resolver_url_identifier_is_reduced_to_the_bare_doi(self, link):
        rec = record(url(link))
        promote_doi_pid(rec)
        assert rec["pids"] == {"doi": {"identifier": DOI, "provider": "external"}}

    def test_doi_identifier_given_as_a_url_is_reduced_to_the_bare_doi(self):
        rec = record(doi(f"https://doi.org/{DOI}"))
        promote_doi_pid(rec)
        assert rec["pids"]["doi"]["identifier"] == DOI

    def test_the_promoted_doi_leaves_the_identifier_list(self):
        rec = record(doi(DOI))
        promote_doi_pid(rec)
        assert rec["metadata"]["identifiers"] == [RECID]

    def test_doi_and_resolver_url_for_the_same_doi_collapse_into_one_pid(self):
        rec = record(url(f"https://doi.org/{DOI.upper()}"), doi(DOI))
        result = promote_doi_pid(rec)
        assert rec["pids"]["doi"]["identifier"] == DOI
        assert rec["metadata"]["identifiers"] == [RECID]
        assert len(result.consumed) == 2

    def test_other_identifiers_are_left_alone(self):
        others = [
            url("https://www.sciencedirect.com/science/article/pii/S0022509618300644"),
            {"identifier": "9781684480166", "scheme": "isbn"},
        ]
        rec = record(*others, doi(DOI))
        promote_doi_pid(rec)
        assert rec["metadata"]["identifiers"] == [RECID, *others]

    def test_record_without_a_doi_gets_no_pids_block(self):
        rec = record(url("https://example.org/article"))
        assert promote_doi_pid(rec) is None
        assert "pids" not in rec
        assert rec["metadata"]["identifiers"] == [RECID, url("https://example.org/article")]

    def test_a_landing_page_with_a_doi_in_its_path_is_not_promoted(self):
        landing = url("http://onlinelibrary.wiley.com/doi/10.1002/qua.560560711/abstract")
        rec = record(landing)
        assert promote_doi_pid(rec) is None
        assert "pids" not in rec
        assert rec["metadata"]["identifiers"] == [RECID, landing]

    def test_doi_identifier_takes_precedence_over_a_different_resolver_url(self):
        rec = record(url("https://doi.org/10.2000/other"), doi(DOI))
        result = promote_doi_pid(rec)
        assert rec["pids"]["doi"]["identifier"] == DOI
        assert result.conflicting == ("10.2000/other",)
        # the other DOI is not lost: it stays as a link
        assert rec["metadata"]["identifiers"] == [RECID, url("https://doi.org/10.2000/other")]

    def test_a_second_doi_identifier_stays_behind_as_a_link(self):
        rec = record(doi(DOI), doi("10.2000/other"))
        promote_doi_pid(rec)
        assert rec["pids"]["doi"]["identifier"] == DOI
        assert rec["metadata"]["identifiers"] == [RECID, url("https://doi.org/10.2000/other")]

    def test_an_unreadable_doi_identifier_is_not_promoted(self):
        rec = record(doi("Unknown"))
        assert promote_doi_pid(rec) is None
        assert "pids" not in rec

    def test_provider_is_configurable(self):
        rec = record(doi(DOI))
        promote_doi_pid(rec, provider="datacite")
        assert rec["pids"]["doi"]["provider"] == "datacite"

    def test_identifiers_can_be_kept_alongside_the_pid(self):
        rec = record(doi(DOI), url(f"https://doi.org/{DOI}"))
        promote_doi_pid(rec, keep_identifiers=True)
        assert rec["pids"]["doi"]["identifier"] == DOI
        assert rec["metadata"]["identifiers"] == [RECID, doi(DOI), url(f"https://doi.org/{DOI}")]

    def test_result_reports_the_doi_and_what_named_it(self):
        rec = record(doi(f"doi:{DOI}"))
        result = promote_doi_pid(rec)
        assert result.doi == DOI
        assert result.consumed == (doi(f"doi:{DOI}"),)
        assert result.conflicting == ()


class TestDoiClaim:
    def test_claim_is_the_bare_doi_and_does_not_change_the_record(self):
        rec = record(url(f"http://dx.doi.org/{DOI}"))
        assert doi_claim(rec) == DOI
        assert rec == record(url(f"http://dx.doi.org/{DOI}"))

    def test_no_doi_no_claim(self):
        assert doi_claim(record(url("https://example.org/x"))) is None
        assert doi_claim({"metadata": {}}) is None


class TestKeepDoiAsLink:
    def test_doi_becomes_a_resolver_link_and_no_pid_is_set(self):
        rec = record(doi(DOI))
        result = keep_doi_as_link(rec)
        assert "pids" not in rec
        assert rec["metadata"]["identifiers"] == [RECID, url(f"https://doi.org/{DOI}")]
        assert result.doi == DOI

    def test_doi_and_resolver_url_collapse_into_a_single_link(self):
        rec = record(doi(DOI), url(f"http://dx.doi.org/{DOI}"))
        keep_doi_as_link(rec)
        assert rec["metadata"]["identifiers"] == [RECID, url(f"https://doi.org/{DOI}")]

    def test_record_without_a_doi_is_untouched(self):
        rec = record(url("https://example.org/x"))
        assert keep_doi_as_link(rec) is None
        assert rec == record(url("https://example.org/x"))
