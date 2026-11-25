"""Behavioural tests for hard-deleting a collection's records over the REST API.

The real session runs against a fake KC Works instance mounted as a
transport adapter, so nothing touches the network and we assert on what
is left on the "server" afterwards.
"""

import json
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from click.testing import CliRunner
from requests.adapters import BaseAdapter

from bepress_importer import hard_delete
from bepress_importer.cli import cli
from bepress_importer.hard_delete import (
    HardDeleteError,
    hard_delete_collection,
    is_production,
)

STAGING = "https://works.hcommons-staging.org"
DEV = "https://works.hcommons-dev.org"
PRODUCTION = "https://works.hcommons.org"
DELETE_KEY = "delete-sekrit"
IMPORT_KEY = "import-sekrit"


class FakeKCWorks(BaseAdapter):
    """An in-memory KC Works: collections, records, listings and bulk hard-delete."""

    def __init__(self, result_window=10_000):
        super().__init__()
        self.collections = {}  # slug -> parent slug (or None)
        self.records = {}  # recid -> {"title": str, "collections": [slug, ...]}
        self.failing = {}  # recid -> error message
        self.result_window = result_window
        self.listing_rejects_token = False
        self.delete_status = None  # force this HTTP status on every hard-delete
        self.error = None
        self.requests = []
        self.notes = []
        self.batch_sizes = []

    # -- building the fixture -------------------------------------------------

    def add_collection(self, slug, parent=None):
        self.collections[slug] = parent
        return self

    def add_records(self, prefix, count, *collections):
        for number in range(count):
            recid = f"{prefix}-{number:05d}"
            self.records[recid] = {
                "title": f"Title of {recid}",
                "collections": list(collections),
            }
        return self

    def recids_in(self, slug):
        return [r for r, record in self.records.items() if slug in record["collections"]]

    # -- the HTTP surface -----------------------------------------------------

    def send(self, request, **kwargs):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        url = urlparse(request.url)
        query = {name: values[0] for name, values in parse_qs(url.query).items()}
        parts = url.path.strip("/").split("/")
        status, payload = 404, {"status": 404, "message": "Not found."}
        if request.method == "GET" and parts[:2] == ["api", "communities"] and len(parts) == 4:
            status, payload = self._listing(request, parts[2], parts[3], query)
        elif request.method == "POST" and parts == ["api", "records", "hard-delete"]:
            status, payload = self._hard_delete(request)
        return self._respond(request, status, payload)

    def _respond(self, request, status, payload):
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(payload).encode("utf-8")
        response.request = request
        response.url = request.url
        return response

    def _listing(self, request, slug, kind, query):
        if self.listing_rejects_token and "Authorization" in request.headers:
            return 403, {"status": 403, "message": "Token lacks the scope for this route."}
        if slug not in self.collections:
            return 404, {"status": 404, "message": "The persistent identifier does not exist."}
        page, size = int(query.get("page", 1)), int(query.get("size", 25))
        if page * size > self.result_window:
            return 400, {"status": 400, "message": "Invalid querystring parameters."}
        if kind == "records":
            hits = [
                {
                    "id": recid,
                    "metadata": {"title": record["title"]},
                    "parent": {
                        "communities": {
                            "ids": [f"uuid-{name}" for name in record["collections"]]
                        }
                    },
                }
                for recid, record in self.records.items()
                if slug in record["collections"]
            ]
        elif kind == "subcommunities":
            hits = [
                {"id": f"uuid-{child}", "slug": child, "metadata": {"title": child.title()}}
                for child, parent in self.collections.items()
                if parent == slug
            ]
        else:
            return 404, {"status": 404, "message": "Not found."}
        start = (page - 1) * size
        return 200, {"hits": {"total": len(hits), "hits": hits[start:start + size]}}

    def _hard_delete(self, request):
        if self.delete_status is not None:
            return self.delete_status, {"status": self.delete_status, "message": "Refused."}
        if request.headers.get("Authorization") != f"Bearer {DELETE_KEY}":
            return 403, {"status": 403, "message": "Permission denied."}
        body = json.loads(request.body)
        ids = body.get("ids") or body.get("recids") or []
        self.batch_sizes.append(len(ids))
        if not ids or len(ids) > 100 or body.get("id_type", "recid") != "recid":
            return 400, {"status": 400, "message": "Invalid payload."}
        self.notes.append(body.get("note"))
        results = []
        for recid in ids:
            result = {"id": recid, "id_type": "recid", "recid": recid, "ok": True}
            if recid in self.failing:
                result.update(ok=False, error="hard_delete_failed", message=self.failing[recid])
            elif recid not in self.records:
                result.update(ok=False, error="not_found", message="Record not found.")
            else:
                del self.records[recid]
            results.append(result)
        failed = sum(1 for result in results if not result["ok"])
        return (207 if failed else 200), {
            "results": results,
            "total": len(results),
            "succeeded": len(results) - failed,
            "failed": failed,
        }

    def close(self):
        pass


def session_with(server):
    session = requests.Session()
    session.mount("https://", server)
    session.mount("http://", server)
    return session


def nested_server():
    """A parent with a child and a grandchild, plus an unrelated collection.

    Some child records are also members of the parent (how KC Works files
    them by default) and some are not (a child linked to its parent later).
    """
    server = FakeKCWorks()
    server.add_collection("parent").add_collection("child", parent="parent")
    server.add_collection("grandchild", parent="child").add_collection("other")
    server.add_records("own", 3, "parent")
    server.add_records("shared", 2, "parent", "child")
    server.add_records("childonly", 2, "child")
    server.add_records("deep", 2, "parent", "child", "grandchild")
    server.add_records("deeponly", 1, "grandchild")
    server.add_records("other", 4, "other")
    return server


class TestIsProduction:
    @pytest.mark.parametrize("url", [
        "https://works.hcommons.org",
        "https://works.hcommons.org/",
        "https://works.hcommons.org/api",
        "http://works.hcommons.org",
        "https://WORKS.HCOMMONS.ORG",
        "https://works.hcommons.org:443",
        "https://works.hcommons.org.",
        "works.hcommons.org",
        "  https://works.hcommons.org  ",
        "https://works.hcommons-dev.org@works.hcommons.org/",
    ])
    def test_production_urls(self, url):
        assert is_production(url) is True

    @pytest.mark.parametrize("url", [
        STAGING,
        DEV,
        "https://works.hcommons-staging.org/works.hcommons.org",
        "https://works.hcommons.org.example.com",
        "http://localhost:5000",
    ])
    def test_other_urls(self, url):
        assert is_production(url) is False


class TestHardDeleteCollection:
    def delete(self, server, slug="parent", **kwargs):
        kwargs.setdefault("api_url", STAGING)
        return hard_delete_collection(
            slug, api_key=DELETE_KEY, session=session_with(server), **kwargs
        )

    def test_every_record_in_the_collection_is_removed(self):
        server = FakeKCWorks().add_collection("coll").add_collection("other")
        server.add_records("a", 7, "coll").add_records("b", 3, "other")
        result = self.delete(server, "coll")
        assert server.recids_in("coll") == []
        assert result.success
        assert result.succeeded == 7 and result.failed == 0
        assert sorted(o.recid for o in result.outcomes) == [f"a-{n:05d}" for n in range(7)]

    def test_records_in_other_collections_are_untouched(self):
        server = FakeKCWorks().add_collection("coll").add_collection("other")
        server.add_records("a", 7, "coll").add_records("b", 3, "other")
        self.delete(server, "coll")
        assert len(server.recids_in("other")) == 3

    def test_an_empty_collection_succeeds_with_nothing_to_do(self):
        server = FakeKCWorks().add_collection("coll")
        result = self.delete(server, "coll")
        assert result.success
        assert result.outcomes == []

    def test_by_default_sub_collection_records_are_left_alone(self):
        server = nested_server()
        result = self.delete(server)
        assert sorted(server.recids_in("parent")) == [
            "deep-00000", "deep-00001", "shared-00000", "shared-00001",
        ]
        assert len(server.recids_in("child")) == 6
        assert len(server.recids_in("grandchild")) == 3
        assert result.succeeded == 3
        assert sorted(result.skipped) == [
            "deep-00000", "deep-00001", "shared-00000", "shared-00001",
        ]

    def test_default_run_reports_the_sub_collections_it_left_alone(self):
        result = self.delete(nested_server())
        assert result.cascade is False
        assert sorted(result.subcollections) == ["child", "grandchild"]

    def test_cascade_removes_sub_collection_records_at_every_depth(self):
        server = nested_server()
        result = self.delete(server, cascade=True)
        for slug in ("parent", "child", "grandchild"):
            assert server.recids_in(slug) == []
        assert result.succeeded == 10
        assert result.skipped == []
        assert len(server.recids_in("other")) == 4

    def test_cascade_deletes_each_record_once(self):
        server = nested_server()
        result = self.delete(server, cascade=True)
        recids = [o.recid for o in result.outcomes]
        assert len(recids) == len(set(recids))
        assert result.failed == 0

    def test_deleting_a_sub_collection_does_not_climb_to_its_parent(self):
        server = nested_server()
        self.delete(server, "grandchild")
        assert server.recids_in("grandchild") == []
        assert len(server.recids_in("child")) == 4
        assert len(server.recids_in("parent")) == 5

    def test_large_collections_are_sent_within_the_servers_batch_limit(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 430, "coll")
        result = self.delete(server, "coll", batch_size=100)
        assert server.recids_in("coll") == []
        assert result.succeeded == 430
        assert max(server.batch_sizes) <= 100

    def test_batch_size_is_honoured(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 30, "coll")
        self.delete(server, "coll", batch_size=7)
        assert server.recids_in("coll") == []
        assert max(server.batch_sizes) <= 7

    def test_collections_larger_than_the_search_window_are_emptied(self):
        server = FakeKCWorks(result_window=300).add_collection("coll")
        server.add_records("a", 750, "coll")
        result = self.delete(server, "coll", batch_size=100)
        assert server.recids_in("coll") == []
        assert result.succeeded == 750

    def test_a_record_that_fails_is_reported_and_the_rest_still_go(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 5, "coll")
        server.failing["a-00002"] = "DataCite refused the DOI removal."
        result = self.delete(server, "coll")
        assert server.recids_in("coll") == ["a-00002"]
        assert not result.success
        assert result.succeeded == 4 and result.failed == 1
        failure = next(o for o in result.outcomes if not o.ok)
        assert failure.recid == "a-00002"
        assert "DataCite refused" in failure.message

    def test_outcomes_carry_record_titles(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 2, "coll")
        result = self.delete(server, "coll")
        assert {o.title for o in result.outcomes} == {"Title of a-00000", "Title of a-00001"}

    def test_a_key_without_permission_stops_with_an_error_and_deletes_nothing(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 5, "coll")
        with pytest.raises(HardDeleteError) as raised:
            hard_delete_collection(
                "coll", api_key="wrong", api_url=STAGING, session=session_with(server)
            )
        assert len(server.recids_in("coll")) == 5
        assert "403" in str(raised.value)
        assert "wrong" not in str(raised.value)

    def test_a_server_error_marks_the_batch_failed(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 3, "coll")
        server.delete_status = 502
        result = self.delete(server, "coll")
        assert not result.success
        assert result.failed == 3
        assert all("502" in o.message for o in result.outcomes)

    def test_unknown_collection_is_an_error_naming_the_slug(self):
        server = FakeKCWorks().add_collection("coll")
        with pytest.raises(HardDeleteError) as raised:
            self.delete(server, "no-such-collection")
        assert "no-such-collection" in str(raised.value)

    def test_network_failure_is_an_error_and_not_a_crash(self):
        server = FakeKCWorks().add_collection("coll")
        server.error = requests.exceptions.ConnectionError("no route to host")
        with pytest.raises(HardDeleteError) as raised:
            self.delete(server, "coll")
        assert "no route to host" in str(raised.value)

    def test_requests_go_to_the_given_instance(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 2, "coll")
        self.delete(server, "coll", api_url=DEV + "/")
        assert server.recids_in("coll") == []
        assert {urlparse(r.url).netloc for r in server.requests} == {"works.hcommons-dev.org"}
        assert all("//api" not in urlparse(r.url).path for r in server.requests)

    def test_listing_still_works_when_the_key_is_refused_for_reads(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 4, "coll")
        server.listing_rejects_token = True
        result = self.delete(server, "coll")
        assert server.recids_in("coll") == []
        assert result.succeeded == 4

    def test_the_audit_note_names_the_collection_unless_overridden(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 1, "coll")
        self.delete(server, "coll")
        assert "coll" in server.notes[0]
        server.add_records("b", 1, "coll")
        self.delete(server, "coll", note="purge duplicate import")
        assert server.notes[-1] == "purge duplicate import"

    def test_the_log_names_every_record_and_its_fate_but_never_the_key(self):
        server = FakeKCWorks().add_collection("coll")
        server.add_records("a", 4, "coll")
        server.failing["a-00001"] = "DataCite refused the DOI removal."
        lines = []
        self.delete(server, "coll", log=lines.append)
        for recid in ("a-00000", "a-00002", "a-00003"):
            assert sum(1 for line in lines if recid in line and "DELETED" in line) == 1
        failed = [line for line in lines if "a-00001" in line]
        assert len(failed) == 1
        assert "FAILED" in failed[0] and "DataCite refused" in failed[0]
        assert DELETE_KEY not in "\n".join(lines)

    def test_the_log_names_records_skipped_for_their_sub_collections(self):
        lines = []
        self.delete(nested_server(), log=lines.append)
        text = "\n".join(lines)
        assert "shared-00000" in text and "deep-00001" in text
        assert not any("DELETED" in line and "shared-00000" in line for line in lines)


class TestHardDeleteCommand:
    def run(self, monkeypatch, *args, server=None, env=None):
        self.server = server or FakeKCWorks().add_collection("coll").add_records("a", 5, "coll")
        monkeypatch.setattr(hard_delete, "make_session", lambda: session_with(self.server))
        base_env = {
            "KCWORKS_IMPORT_API_URL": "",
            "KCWORKS_IMPORT_API_KEY": "",
            "KCWORKS_HARD_DELETE_API_KEY": DELETE_KEY,
        }
        return CliRunner().invoke(
            cli, ["hard-delete", *map(str, args)], env={**base_env, **(env or {})}
        )

    def test_deletes_on_staging_and_logs_to_stdout(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this"
        )
        assert result.exit_code == 0, result.output
        assert self.server.recids_in("coll") == []
        for number in range(5):
            assert f"a-{number:05d}" in result.stdout
        assert "works.hcommons-staging.org" in result.stdout
        assert DELETE_KEY not in result.output

    def test_deletes_on_dev(self, monkeypatch):
        result = self.run(monkeypatch, "coll", "--api-url", DEV, "--yes-i-want-to-run-this")
        assert result.exit_code == 0, result.output
        assert self.server.recids_in("coll") == []

    def test_refuses_without_the_confirmation_flag(self, monkeypatch):
        result = self.run(monkeypatch, "coll", "--api-url", STAGING)
        assert result.exit_code != 0
        assert "--yes-i-want-to-run-this" in result.output
        assert self.server.requests == []
        assert len(self.server.recids_in("coll")) == 5

    def test_refuses_production_without_the_production_flag(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--api-url", PRODUCTION, "--yes-i-want-to-run-this"
        )
        assert result.exit_code != 0
        assert "--yes-i-want-to-run-this-on-production" in result.output
        assert self.server.requests == []
        assert len(self.server.recids_in("coll")) == 5

    def test_the_default_instance_is_treated_as_production(self, monkeypatch):
        result = self.run(monkeypatch, "coll", "--yes-i-want-to-run-this")
        assert result.exit_code != 0
        assert "--yes-i-want-to-run-this-on-production" in result.output
        assert self.server.requests == []

    def test_production_named_in_the_environment_is_protected_too(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--yes-i-want-to-run-this",
            env={"KCWORKS_IMPORT_API_URL": PRODUCTION + "/"},
        )
        assert result.exit_code != 0
        assert self.server.requests == []

    def test_the_production_flag_alone_is_not_enough(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--api-url", PRODUCTION,
            "--yes-i-want-to-run-this-on-production",
        )
        assert result.exit_code != 0
        assert self.server.requests == []
        assert len(self.server.recids_in("coll")) == 5

    def test_runs_on_production_with_both_flags(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--api-url", PRODUCTION, "--yes-i-want-to-run-this",
            "--yes-i-want-to-run-this-on-production",
        )
        assert result.exit_code == 0, result.output
        assert self.server.recids_in("coll") == []

    def test_instance_url_can_come_from_the_environment(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--yes-i-want-to-run-this",
            env={"KCWORKS_IMPORT_API_URL": STAGING},
        )
        assert result.exit_code == 0, result.output
        assert self.server.recids_in("coll") == []
        assert {urlparse(r.url).netloc for r in self.server.requests} == {
            "works.hcommons-staging.org"
        }

    def test_missing_key_names_the_hard_delete_variable(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this",
            env={"KCWORKS_HARD_DELETE_API_KEY": ""},
        )
        assert result.exit_code != 0
        assert "KCWORKS_HARD_DELETE_API_KEY" in result.output
        assert self.server.requests == []

    def test_the_import_key_is_never_used_in_its_place(self, monkeypatch):
        # The import key would be accepted by this server, so using it would delete.
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this",
            env={"KCWORKS_HARD_DELETE_API_KEY": "", "KCWORKS_IMPORT_API_KEY": DELETE_KEY},
        )
        assert result.exit_code != 0
        assert len(self.server.recids_in("coll")) == 5

    def test_key_can_come_from_another_variable_or_a_file(self, monkeypatch, tmp_path):
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this",
            "--api-key-env", "STAGING_DELETE_KEY",
            env={"KCWORKS_HARD_DELETE_API_KEY": "", "STAGING_DELETE_KEY": DELETE_KEY},
        )
        assert result.exit_code == 0, result.output
        key_file = tmp_path / "key.txt"
        key_file.write_text(DELETE_KEY + "\n")
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this",
            "--api-key-file", key_file, env={"KCWORKS_HARD_DELETE_API_KEY": ""},
        )
        assert result.exit_code == 0, result.output
        assert self.server.recids_in("coll") == []

    def test_sub_collections_are_spared_unless_cascade_is_given(self, monkeypatch):
        result = self.run(
            monkeypatch, "parent", "--api-url", STAGING, "--yes-i-want-to-run-this",
            server=nested_server(),
        )
        assert result.exit_code == 0, result.output
        assert len(self.server.recids_in("child")) == 6
        result = self.run(
            monkeypatch, "parent", "--api-url", STAGING, "--yes-i-want-to-run-this",
            "--cascade", server=nested_server(),
        )
        assert result.exit_code == 0, result.output
        assert self.server.recids_in("child") == []
        assert self.server.recids_in("grandchild") == []

    def test_a_failed_record_exits_nonzero_and_is_logged(self, monkeypatch):
        server = FakeKCWorks().add_collection("coll").add_records("a", 3, "coll")
        server.failing["a-00001"] = "DataCite refused the DOI removal."
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this",
            server=server,
        )
        assert result.exit_code != 0
        assert "a-00001" in result.stdout and "DataCite refused" in result.stdout
        assert server.recids_in("coll") == ["a-00001"]

    def test_a_refused_key_exits_nonzero_with_a_message(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this",
            env={"KCWORKS_HARD_DELETE_API_KEY": "not-the-key"},
        )
        assert result.exit_code != 0
        assert isinstance(result.exception, SystemExit)
        assert "403" in result.output
        assert "not-the-key" not in result.output
        assert len(self.server.recids_in("coll")) == 5

    def test_unknown_collection_exits_nonzero(self, monkeypatch):
        result = self.run(
            monkeypatch, "nope", "--api-url", STAGING, "--yes-i-want-to-run-this"
        )
        assert result.exit_code != 0
        assert "nope" in result.output
        assert len(self.server.recids_in("coll")) == 5

    def test_note_and_batch_size_reach_the_server(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this",
            "--note", "clearing test import", "--batch-size", 2,
        )
        assert result.exit_code == 0, result.output
        assert set(self.server.notes) == {"clearing test import"}
        assert max(self.server.batch_sizes) <= 2

    def test_batch_size_above_the_server_limit_is_rejected(self, monkeypatch):
        result = self.run(
            monkeypatch, "coll", "--api-url", STAGING, "--yes-i-want-to-run-this",
            "--batch-size", 101,
        )
        assert result.exit_code != 0
        assert self.server.requests == []
