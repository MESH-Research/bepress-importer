"""Behavioural tests for ROR ids: profile-fixed ids, reading the ROR API's
answer, the lookup cache, and the resolver that ties them together.
Nothing here touches the network."""

import pytest

from bepress_importer.ror import (
    RorCache,
    RorLookup,
    RorMatch,
    RorResolver,
    RorUnavailable,
    fetch_affiliation,
    is_certain,
    read_response,
)

BUCKNELL = {"00fc1qt65": ["Bucknell University", "Bucknell", "Bucknell U", "Bucknell Univ"]}


def item(ror_id, name, score, chosen=False, aliases=(), labels=(), acronyms=(),
         place=("State College", "Pennsylvania", "PA", "United States", "US")):
    city, region, region_code, country, country_code = place
    return {
        "chosen": chosen,
        "matching_type": "SINGLE SEARCH",
        "score": score,
        "substring": "x",
        "organization": {
            "id": f"https://ror.org/{ror_id}",
            "status": "active",
            "names": [
                *({"lang": "en", "types": ["alias"], "value": alias} for alias in aliases),
                *({"lang": None, "types": ["acronym"], "value": a} for a in acronyms),
                {"lang": "en", "types": ["ror_display", "label"], "value": name},
                *({"lang": "es", "types": ["label"], "value": label} for label in labels),
            ],
            "locations": [
                {
                    "geonames_id": 1,
                    "geonames_details": {
                        "name": city, "country_subdivision_name": region,
                        "country_subdivision_code": region_code,
                        "country_name": country, "country_code": country_code,
                    },
                }
            ],
        },
    }


def response(*items):
    return {"items": list(items), "number_of_results": len(items)}


PENN_STATE = response(
    item(
        "04p491231", "Pennsylvania State University", 1.0, chosen=True,
        aliases=("Penn State",), acronyms=("PSU",),
        labels=("Universidad Estatal de Pensilvania",),
    ),
    item("035h06756", "Magtymguly Turkmen State University", 0.95),
)
UNION_COLLEGES = response(
    item("058w5nk68", "Union College", 1.0, chosen=True),
    item("03ypdv455", "Union College", 1.0),
)
PENN_STATE_LOOKUP = RorLookup(
    ror_id="04p491231", name="Pennsylvania State University", score=1.0,
    names=("Pennsylvania State University", "Universidad Estatal de Pensilvania"),
    places=("State College", "Pennsylvania", "PA", "United States", "US"),
    rivals=("Magtymguly State University",),
)


def chosen(name, text_place=("Fort Collins", "Colorado", "CO", "United States", "US"), **more):
    """The lookup for an API answer choosing one organisation at full score."""
    return read_response(response(item("0xx", name, 1.0, chosen=True, place=text_place, **more)))
NO_CHOICE = response(item("03hamhx47", "University of Massachusetts Lowell", 0.96))
TIED = response(
    item("00jkdhd30", "Saint Mary's University", 1.0),
    item("010zh7098", "Saint Mary's University", 1.0),
)
NOTHING = response()


class TestReadResponse:
    def test_the_chosen_organisation_is_reported_with_its_bare_id_and_display_name(self):
        lookup = read_response(PENN_STATE)
        assert (lookup.ror_id, lookup.name, lookup.score, lookup.rivals) == (
            "04p491231", "Pennsylvania State University", 1.0, ()
        )

    def test_its_official_names_are_kept_but_not_its_aliases_or_acronyms(self):
        assert read_response(PENN_STATE).names == (
            "Pennsylvania State University", "Universidad Estatal de Pensilvania",
        )

    def test_where_it_is_is_kept(self):
        assert set(read_response(PENN_STATE).places) == {
            "State College", "Pennsylvania", "PA", "United States", "US"
        }

    def test_a_high_score_the_api_did_not_choose_is_no_match(self):
        assert read_response(NO_CHOICE).ror_id is None

    def test_an_empty_answer_is_no_match(self):
        assert read_response(NOTHING) == RorLookup()

    def test_organisations_scoring_as_high_as_the_chosen_one_are_kept_as_rivals(self):
        payload = response(
            item("058w5nk68", "Union College", 1.0, chosen=True),
            item("037x4qk98", "International Union Against Tuberculosis", 1.0,
                 labels=("Union Internationale Contre la Tuberculose",), aliases=("The Union",)),
            item("01j78w442", "Germantown Academy", 0.86),
        )
        assert read_response(payload).rivals == (
            "International Union Against Tuberculosis",
            "Union Internationale Contre la Tuberculose",
        )


class TestIsCertain:
    """Certain means: ROR chose the organisation, at full score, AND the text
    is that organisation's own official name, shared with no equal rival."""

    def test_the_official_name_chosen_at_full_score_is_certain(self):
        assert is_certain(read_response(PENN_STATE), "Pennsylvania State University")

    @pytest.mark.parametrize(
        "text",
        [
            "The Pennsylvania State University", "pennsylvania state university",
            "  Pennsylvania  State University. ", "Universidad Estatal de Pensilvania",
        ],
    )
    def test_an_article_case_or_another_language_do_not_matter(self, text):
        assert is_certain(read_response(PENN_STATE), text)

    @pytest.mark.parametrize(
        "name, text",
        [
            ("Bauhaus-Universität Weimar", "Bauhaus Universitat Weimar"),
            ("Texas A&M University", "Texas A & M University"),
            ("Université Laval", "Universite Laval"),
        ],
    )
    def test_accents_and_punctuation_do_not_matter(self, name, text):
        assert is_certain(chosen(name), text)

    @pytest.mark.parametrize(
        "text",
        [
            "Colorado State University - Fort Collins", "Colorado State University, Colorado",
            "Colorado State University, Fort Collins, CO", "Colorado State University, USA",
            "Colorado State University-Fort Collins", "Colorado State University at Fort Collins",
            "Colorado State University - Main Campus", "Colorado State University, United States",
        ],
    )
    def test_the_name_followed_by_where_the_organisation_is_stays_certain(self, text):
        assert is_certain(chosen("Colorado State University"), text)

    @pytest.mark.parametrize(
        "name, text",
        [
            # a text ROR matched on an alias: "NC State" is also what people
            # call North Carolina State University
            ("North Central State College", "NC State"),
            ("Phillips Exeter Academy", "Exeter"),
            ("Pennsylvania State University", "Penn State University"),
            # a different campus or a second institution after the name
            ("University of Minnesota", "University of Minnesota - Duluth"),
            ("Massachusetts General Hospital",
             "Massachusetts General Hospital and Harvard Medical School"),
            ("Massachusetts General Hospital",
             "Massachusetts General Hospital Institute of Health"),
            # a text that merely shares words with the organisation chosen
            ("Digital Research Alliance of Canada", "Shamokin Creek Restoration Alliance"),
            ("Research Institute of Japan", "Hanzaki Research Institute of Japan"),
            ("Indian Institute of Technology Delhi", "IIIT Delhi"),
            ("Colorado School of Mines", "TRIUMF / Colorado School of Mines"),
        ],
    )
    def test_a_text_that_is_not_the_organisations_official_name_is_not_certain(self, name, text):
        aliases = ("NC State", "Exeter", "Penn State")
        assert not is_certain(chosen(name, aliases=aliases), text)

    @pytest.mark.parametrize("payload", [NO_CHOICE, TIED, NOTHING])
    def test_no_chosen_organisation_is_never_certain(self, payload):
        assert not is_certain(read_response(payload), "Saint Mary's University")

    def test_a_chosen_match_below_full_score_is_not_certain(self):
        payload = response(item("04p491231", "Pennsylvania State University", 0.97, chosen=True))
        text = "Pennsylvania State University"
        assert not is_certain(read_response(payload), text)
        assert is_certain(read_response(payload), text, min_score=0.95)

    def test_an_equally_scored_organisation_of_the_same_name_makes_it_uncertain(self):
        payload = response(
            item("058w5nk68", "Union College", 1.0, chosen=True),
            item("03ypdv455", "Union College", 1.0, place=("Lincoln", "Nebraska", "NE",
                                                           "United States", "US")),
        )
        assert not is_certain(read_response(payload), "Union College")
        assert not is_certain(read_response(payload), "The Union College, Pennsylvania")

    def test_an_equally_scored_organisation_of_another_name_does_not(self):
        payload = response(
            item("047rhhm47", "Brigham Young University", 1.0, chosen=True),
            item("03cs8cm72", "Brigham Young University–Hawaii", 1.0),
            item("01gqmkc84", "Brigham Young University–Idaho", 1.0),
        )
        assert is_certain(read_response(payload), "Brigham Young University")


class TestRorCache:
    def test_an_unknown_text_is_a_miss(self, tmp_path):
        assert RorCache(tmp_path / "ror.sqlite3").get("Penn State University") is None

    def test_a_stored_answer_comes_back(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put("Pennsylvania State University", PENN_STATE_LOOKUP)
        assert cache.get("Pennsylvania State University") == PENN_STATE_LOOKUP

    def test_answers_survive_on_disk(self, tmp_path):
        path = tmp_path / "ror.sqlite3"
        first = RorCache(path)
        first.put("TRIUMF", RorLookup("03kgj4539", "TRIUMF", 1.0))
        first.close()
        assert RorCache(path).get("TRIUMF").ror_id == "03kgj4539"

    def test_an_answer_without_a_match_is_remembered_as_such(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put("Lewisburg Neighborhoods", RorLookup())
        assert cache.get("Lewisburg Neighborhoods") == RorLookup()

    def test_case_and_spacing_do_not_make_a_different_text(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put("Penn State University", RorLookup("04p491231", "PSU", 1.0))
        assert cache.get("  penn  state UNIVERSITY ").ror_id == "04p491231"

    def test_a_later_answer_replaces_an_earlier_one(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put("X", RorLookup())
        cache.put("X", RorLookup("03kgj4539", "TRIUMF", 1.0))
        assert cache.get("X").ror_id == "03kgj4539"

    def test_a_cache_file_in_an_older_layout_is_started_afresh(self, tmp_path):
        import sqlite3

        path = tmp_path / "ror.sqlite3"
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE affiliation_lookup (query TEXT PRIMARY KEY, ror_id TEXT)")
        old.execute("INSERT INTO affiliation_lookup VALUES ('triumf', '03kgj4539')")
        old.commit()
        old.close()
        cache = RorCache(path)
        assert cache.get("TRIUMF") is None
        cache.put("TRIUMF", PENN_STATE_LOOKUP)
        assert cache.get("TRIUMF") == PENN_STATE_LOOKUP

    def test_the_cache_file_is_created_in_a_missing_directory(self, tmp_path):
        cache = RorCache(tmp_path / "deep" / "er" / "ror.sqlite3")
        cache.put("X", RorLookup())
        assert (tmp_path / "deep" / "er" / "ror.sqlite3").exists()


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Answers each request with the next scripted response; echoes the
    affiliation asked about into 200 answers that carry no script payload."""

    def __init__(self, *responses):
        self.responses = list(responses)

    def get(self, url, params=None, timeout=None):
        answer = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(answer, Exception):
            raise answer
        if answer.status_code == 200 and answer._payload == "echo":
            return FakeResponse(200, {"items": [], "asked": params["affiliation"], "url": url})
        return answer


def no_sleep(seconds):
    pass


class TestFetchAffiliation:
    def test_the_text_is_put_to_the_ror_affiliation_endpoint(self):
        payload = fetch_affiliation(
            "Penn State University", session=FakeSession(FakeResponse(200, "echo")), sleep=no_sleep
        )
        assert payload["asked"] == "Penn State University"
        assert payload["url"] == "https://api.ror.org/v2/organizations"

    def test_the_api_answer_is_returned(self):
        session = FakeSession(FakeResponse(200, PENN_STATE))
        assert fetch_affiliation("x", session=session, sleep=no_sleep) == PENN_STATE

    def test_a_rate_limited_request_is_retried(self):
        session = FakeSession(
            FakeResponse(429, headers={"Retry-After": "2"}), FakeResponse(200, PENN_STATE)
        )
        assert fetch_affiliation("x", session=session, sleep=no_sleep) == PENN_STATE

    def test_a_passing_server_error_is_retried(self):
        session = FakeSession(FakeResponse(503), FakeResponse(200, PENN_STATE))
        assert fetch_affiliation("x", session=session, sleep=no_sleep) == PENN_STATE

    def test_an_api_that_keeps_failing_is_reported_as_unavailable(self):
        with pytest.raises(RorUnavailable):
            fetch_affiliation("x", session=FakeSession(FakeResponse(500)), sleep=no_sleep)

    def test_an_api_that_keeps_rate_limiting_is_reported_as_unavailable(self):
        with pytest.raises(RorUnavailable):
            fetch_affiliation("x", session=FakeSession(FakeResponse(429)), sleep=no_sleep)

    def test_a_network_failure_is_reported_as_unavailable(self):
        import requests

        session = FakeSession(requests.ConnectionError("down"))
        with pytest.raises(RorUnavailable):
            fetch_affiliation("x", session=session, sleep=no_sleep)

    def test_an_answer_that_is_not_json_is_reported_as_unavailable(self):
        with pytest.raises(RorUnavailable):
            fetch_affiliation("x", session=FakeSession(FakeResponse(200)), sleep=no_sleep)


def api(answers):
    """A fetch that answers from a dict and fails loudly for anything else."""

    def fetch(text):
        return answers[text]

    return fetch


def never(text):
    raise AssertionError(f"the ROR API must not be asked about {text!r}")


class TestKnownInstitutions:
    @pytest.mark.parametrize(
        "text",
        [
            "Bucknell University", "bucknell", "Bucknell U.", "Bucknell Univ",
            "  Bucknell   University ", "Biology Department, Bucknell University",
            "Cell Biology/Biochemistry Program, Bucknell University",
        ],
    )
    def test_a_text_naming_a_known_institution_gets_its_id_without_a_lookup(self, text):
        resolver = RorResolver(known=BUCKNELL, fetch=never)
        assert resolver.resolve(text) == RorMatch(
            ror_id="00fc1qt65", name="Bucknell University", evidence="profile"
        )

    def test_a_different_institution_with_the_name_inside_its_own_is_not_assumed(self):
        text = "Geisinger-Bucknell Autism and Developmental Medicine Institute"
        assert RorResolver(known=BUCKNELL).resolve(text) is None
        assert RorResolver(known=BUCKNELL).resolve("Bucknell University Press") is None


class TestResolver:
    def test_a_certain_api_match_is_used(self):
        resolver = RorResolver(fetch=api({"The Pennsylvania State University": PENN_STATE}))
        assert resolver.resolve("The Pennsylvania State University") == RorMatch(
            ror_id="04p491231", name="Pennsylvania State University", evidence="api", score=1.0
        )

    @pytest.mark.parametrize("payload", [NO_CHOICE, TIED, NOTHING])
    def test_anything_short_of_certain_is_left_alone(self, payload):
        assert RorResolver(fetch=api({"x": payload})).resolve("x") is None

    def test_the_certainty_threshold_is_the_resolvers(self):
        payload = response(item("04p491231", "Pennsylvania State University", 0.97, chosen=True))
        text = "Pennsylvania State University"
        assert RorResolver(fetch=api({text: payload})).resolve(text) is None
        assert RorResolver(fetch=api({text: payload}), min_score=0.95).resolve(text) is not None

    def test_without_a_fetch_only_known_and_cached_answers_are_given(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put("TRIUMF", RorLookup("03kgj4539", "TRIUMF", 1.0, names=("TRIUMF",)))
        resolver = RorResolver(known=BUCKNELL, cache=cache)
        assert resolver.resolve("TRIUMF").ror_id == "03kgj4539"
        assert resolver.resolve("Bucknell").ror_id == "00fc1qt65"
        assert resolver.resolve("The Pennsylvania State University") is None

    def test_a_text_looked_up_once_is_answered_from_the_cache_afterwards(self, tmp_path):
        path = tmp_path / "ror.sqlite3"
        first = RorResolver(cache=RorCache(path), fetch=api({"The Pennsylvania State University": PENN_STATE}))
        assert first.resolve("The Pennsylvania State University").ror_id == "04p491231"
        later = RorResolver(cache=RorCache(path), fetch=never)
        assert later.resolve("The Pennsylvania State University").ror_id == "04p491231"
        assert later.resolve("The Pennsylvania State University").evidence == "api"

    def test_a_text_without_a_match_is_not_asked_about_again(self, tmp_path):
        path = tmp_path / "ror.sqlite3"
        RorResolver(cache=RorCache(path), fetch=api({"Lewisburg Neighborhoods": NOTHING})).resolve(
            "Lewisburg Neighborhoods"
        )
        assert RorResolver(cache=RorCache(path), fetch=never).resolve(
            "Lewisburg Neighborhoods"
        ) is None

    def test_a_cached_answer_is_judged_by_the_current_threshold(self, tmp_path):
        path = tmp_path / "ror.sqlite3"
        payload = response(item("04p491231", "Pennsylvania State University", 0.97, chosen=True))
        text = "Pennsylvania State University"
        assert RorResolver(cache=RorCache(path), fetch=api({text: payload})).resolve(text) is None
        assert RorResolver(cache=RorCache(path), fetch=never, min_score=0.95).resolve(text)

    def test_an_unavailable_api_leaves_the_text_alone_and_is_remembered_as_a_failure(self):
        def down(text):
            raise RorUnavailable("down")

        resolver = RorResolver(fetch=down)
        assert resolver.resolve("The Pennsylvania State University") is None
        assert resolver.failures == ["The Pennsylvania State University"]

    def test_a_failed_lookup_is_not_cached_as_an_answer(self, tmp_path):
        path = tmp_path / "ror.sqlite3"

        def down(text):
            raise RorUnavailable("down")

        RorResolver(cache=RorCache(path), fetch=down).resolve("The Pennsylvania State University")
        again = RorResolver(cache=RorCache(path), fetch=api({"The Pennsylvania State University": PENN_STATE}))
        assert again.resolve("The Pennsylvania State University").ror_id == "04p491231"

    def test_an_api_that_keeps_failing_is_given_up_on_for_the_rest_of_the_run(self):
        state = {"failures_left": 3}

        def flaky(text):
            if state["failures_left"]:
                state["failures_left"] -= 1
                raise RorUnavailable("down")
            return PENN_STATE

        resolver = RorResolver(fetch=flaky)
        for text in ("a", "b", "c", "d", "e"):
            assert resolver.resolve(text) is None
        assert resolver.failures == ["a", "b", "c", "d", "e"]

    def test_empty_text_is_never_looked_up(self):
        assert RorResolver(fetch=never).resolve("   ") is None

    def test_a_text_the_api_matched_on_an_alias_is_left_alone(self):
        payload = response(
            item("04b6b6f76", "North Central State College", 1.0, chosen=True, aliases=("NC State",))
        )
        assert RorResolver(fetch=api({"NC State": payload})).resolve("NC State") is None

    def test_a_name_two_equally_scored_organisations_share_is_left_alone(self):
        resolver = RorResolver(fetch=api({"Union College": UNION_COLLEGES}))
        assert resolver.resolve("Union College") is None
