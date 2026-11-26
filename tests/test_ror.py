"""Behavioural tests for ROR ids: profile-fixed ids, reading the ROR API's
answer, choosing a result by its words, the lookup cache, and the resolver
that ties them together. Nothing here touches the network."""

import pytest

from bepress_importer.ror import (
    RorCache,
    RorCandidate,
    RorLookup,
    RorMatch,
    RorResolver,
    RorUnavailable,
    best_match,
    fetch_affiliation,
    read_response,
)

BUCKNELL = {"00fc1qt65": ["Bucknell University", "Bucknell", "Bucknell U", "Bucknell Univ"]}
US = ("United States", "US")


def item(ror_id, name, score=0.9, chosen=False, aliases=(), labels=(), acronyms=(),
         place=("State College", "Pennsylvania", "PA", *US), status="active"):
    city, region, region_code, country, country_code = place
    return {
        "chosen": chosen,
        "matching_type": "SINGLE SEARCH",
        "score": score,
        "substring": "x",
        "organization": {
            "id": f"https://ror.org/{ror_id}",
            "status": status,
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
# what the API really answers for "University of Minnesota - Duluth": it
# chooses the Twin Cities university and lists Duluth third
MINNESOTA = response(
    item("017zqws13", "University of Minnesota", 1.0, chosen=True,
         aliases=("University of Minnesota, Twin Cities",),
         place=("Minneapolis", "Minnesota", "MN", *US)),
    item("05b5sds65", "University of Misan", 0.94, place=("Amarah", "Maysan", "MA", "Iraq", "IQ")),
    item("01hy4qx27", "University of Minnesota, Duluth", 0.94, acronyms=("UMD",),
         place=("Duluth", "Minnesota", "MN", *US)),
    item("05vzqzh92", "University of Minnesota Morris", 0.89,
         place=("Morris", "Minnesota", "MN", *US)),
)
NC_STATE = response(
    item("04b6b6f76", "North Central State College", 1.0, chosen=True, aliases=("NC State",),
         place=("Mansfield", "Ohio", "OH", *US)),
    item("04p491231", "Pennsylvania State University", 0.93, aliases=("Penn State",)),
)
COLORADO = response(
    item("03k1gpj17", "Colorado State University", 1.0, chosen=True,
         place=("Fort Collins", "Colorado", "CO", *US)),
    item("02gn3zg65", "Colorado State University Pueblo", 0.9,
         place=("Pueblo", "Colorado", "CO", *US)),
)
UNION_COLLEGES = response(
    item("058w5nk68", "Union College", 1.0, place=("Schenectady", "New York", "NY", *US)),
    item("03ypdv455", "Union College", 1.0, place=("Lincoln", "Nebraska", "NE", *US)),
)
NOTHING = response()


def match_for(text, payload):
    found = best_match(text, read_response(payload))
    return found and found[0].ror_id


class TestReadResponse:
    def test_every_organisation_returned_is_kept_in_the_apis_order(self):
        lookup = read_response(MINNESOTA)
        assert [c.ror_id for c in lookup.candidates] == [
            "017zqws13", "05b5sds65", "01hy4qx27", "05vzqzh92",
        ]

    def test_an_organisation_carries_its_names_place_score_and_whether_it_was_chosen(self):
        assert read_response(PENN_STATE).candidates[0] == RorCandidate(
            ror_id="04p491231",
            name="Pennsylvania State University",
            names=("Pennsylvania State University", "Universidad Estatal de Pensilvania"),
            aliases=("Penn State", "PSU"),
            places=("State College", "Pennsylvania", "PA", "United States", "US"),
            score=1.0,
            chosen=True,
        )

    def test_an_empty_answer_has_no_organisations(self):
        assert read_response(NOTHING) == RorLookup()

    def test_organisations_that_are_no_longer_active_are_left_out(self):
        payload = response(item("0aa", "Old College", 1.0, chosen=True, status="withdrawn"))
        assert read_response(payload).candidates == ()


class TestBestMatch:
    """An organisation is taken when every word of the text is in its name,
    or in its name and its place; otherwise the text is left alone."""

    def test_an_exact_name_is_taken(self):
        assert match_for("Pennsylvania State University", PENN_STATE) == "04p491231"

    @pytest.mark.parametrize(
        "text",
        [
            "pennsylvania state university", "Pennsylvania  State University.",
            "Universidad Estatal de Pensilvania",
        ],
    )
    def test_case_punctuation_and_language_do_not_matter(self, text):
        assert match_for(text, PENN_STATE) == "04p491231"

    @pytest.mark.parametrize(
        "name, text",
        [
            ("Bauhaus-Universität Weimar", "Bauhaus Universitat Weimar"),
            ("Texas A&M University", "Texas A & M University"),
            ("Université Laval", "Universite Laval"),
        ],
    )
    def test_accents_and_ampersands_do_not_matter(self, name, text):
        assert match_for(text, response(item("0xx", name, 1.0))) == "0xx"

    def test_a_result_further_down_the_list_is_taken_when_it_has_all_the_words(self):
        # the API's own choice lacks "Duluth"; its third result has every word
        assert match_for("University of Minnesota - Duluth", MINNESOTA) == "01hy4qx27"

    def test_the_closest_name_wins_when_several_results_have_all_the_words(self):
        assert match_for("University of Minnesota", MINNESOTA) == "017zqws13"

    def test_word_order_cannot_turn_one_university_into_another(self):
        payload = response(
            item("02dgjyy92", "University of Miami", 1.0, chosen=True),
            item("05nbqxr67", "Miami University", 0.98),
        )
        assert match_for("Miami University", payload) == "05nbqxr67"
        assert match_for("University of Miami", payload) == "02dgjyy92"

    def test_a_shorter_text_is_taken_when_one_result_holds_all_its_words(self):
        payload = response(
            item("05vt9qd57", "Rutgers, The State University of New Jersey", 1.0, chosen=True)
        )
        assert match_for("Rutgers University", payload) == "05vt9qd57"

    @pytest.mark.parametrize(
        "text",
        [
            "Colorado State University - Fort Collins", "Colorado State University, Colorado",
            "Colorado State University, Fort Collins, CO", "Colorado State University, US",
        ],
    )
    def test_words_may_come_from_the_name_and_the_place_together(self, text):
        assert match_for(text, COLORADO) == "03k1gpj17"

    def test_a_name_holding_every_word_is_preferred_to_a_name_helped_by_its_place(self):
        payload = response(
            item("01kg8sb98", "Indiana University", 1.0, chosen=True,
                 place=("Bloomington", "Indiana", "IN", *US)),
            item("02k40bc56", "Indiana University Bloomington", 0.9,
                 place=("Bloomington", "Indiana", "IN", *US)),
        )
        assert match_for("Indiana University - Bloomington", payload) == "02k40bc56"

    def test_the_place_tells_two_organisations_of_one_name_apart(self):
        assert match_for("Union College - Schenectady, NY", UNION_COLLEGES) == "058w5nk68"

    def test_how_the_words_were_found_is_reported(self):
        lookup = read_response(COLORADO)
        assert best_match("Colorado State University", lookup)[1] == "name"
        assert best_match("Colorado State University - Fort Collins", lookup)[1] == "name and place"

    @pytest.mark.parametrize(
        "text, payload",
        [
            # words only an alias or acronym has: "NC State" is what people
            # call North Carolina State University
            ("NC State", NC_STATE),
            ("Penn State University", PENN_STATE),
            ("PSU", PENN_STATE),
            # a word no result has
            ("University of Minnesota - Crookston", MINNESOTA),
            ("Shamokin Creek Restoration Alliance",
             response(item("010r6td27", "Digital Research Alliance of Canada", 1.0, chosen=True))),
            ("IIIT Delhi",
             response(item("049tgcd06", "Indian Institute of Technology Delhi", 1.0, chosen=True))),
            ("Massachusetts General Hospital and Harvard Medical School",
             response(item("002pd6e78", "Massachusetts General Hospital", 1.0, chosen=True))),
            ("Anything", NOTHING),
        ],
    )
    def test_a_text_with_a_word_no_result_has_is_left_alone(self, text, payload):
        assert match_for(text, payload) is None

    def test_a_place_cannot_stand_in_for_part_of_the_name(self):
        # "State" is in the name and "NC" is the region code — but the text
        # is not this organisation's name followed by where it is
        payload = response(
            item("051m4vc48", "Appalachian State University", 0.86,
                 place=("Boone", "North Carolina", "NC", *US))
        )
        assert match_for("NC State", payload) is None
        assert match_for("Appalachian State University, Boone, NC", payload) == "051m4vc48"

    def test_a_place_alone_is_not_a_match(self):
        assert match_for("Fort Collins", COLORADO) is None

    def test_two_organisations_matching_equally_well_are_left_alone(self):
        assert match_for("Union College", UNION_COLLEGES) is None


class TestRorCache:
    def test_an_unknown_text_is_a_miss(self, tmp_path):
        assert RorCache(tmp_path / "ror.sqlite3").get("Penn State University") is None

    def test_a_stored_answer_comes_back_whole(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        lookup = read_response(MINNESOTA)
        cache.put("University of Minnesota - Duluth", lookup)
        assert cache.get("University of Minnesota - Duluth") == lookup

    def test_answers_survive_on_disk(self, tmp_path):
        path = tmp_path / "ror.sqlite3"
        first = RorCache(path)
        first.put("Pennsylvania State University", read_response(PENN_STATE))
        first.close()
        assert RorCache(path).get("Pennsylvania State University") == read_response(PENN_STATE)

    def test_an_answer_without_any_organisation_is_remembered_as_such(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put("Lewisburg Neighborhoods", RorLookup())
        assert cache.get("Lewisburg Neighborhoods") == RorLookup()

    def test_case_and_spacing_do_not_make_a_different_text(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put("Penn State University", read_response(PENN_STATE))
        assert cache.get("  penn  state UNIVERSITY ") == read_response(PENN_STATE)

    def test_a_later_answer_replaces_an_earlier_one(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put("X", RorLookup())
        cache.put("X", read_response(PENN_STATE))
        assert cache.get("X") == read_response(PENN_STATE)

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
        cache.put("TRIUMF", read_response(PENN_STATE))
        assert cache.get("TRIUMF") == read_response(PENN_STATE)

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


def down(text):
    raise RorUnavailable("down")


PSU = "Pennsylvania State University"


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
    def test_a_result_with_all_the_words_is_used(self):
        resolver = RorResolver(fetch=api({PSU: PENN_STATE}))
        assert resolver.resolve(PSU) == RorMatch(
            ror_id="04p491231", name=PSU, evidence="api", detail="name"
        )

    def test_the_match_says_when_the_place_was_needed(self):
        text = "Colorado State University - Fort Collins"
        match = RorResolver(fetch=api({text: COLORADO})).resolve(text)
        assert (match.ror_id, match.detail) == ("03k1gpj17", "name and place")

    def test_the_apis_own_choice_is_not_followed_when_it_lacks_a_word(self):
        text = "University of Minnesota - Duluth"
        assert RorResolver(fetch=api({text: MINNESOTA})).resolve(text).ror_id == "01hy4qx27"

    @pytest.mark.parametrize(
        "text, payload", [("NC State", NC_STATE), ("Union College", UNION_COLLEGES), ("x", NOTHING)]
    )
    def test_a_text_no_result_answers_to_is_left_alone(self, text, payload):
        assert RorResolver(fetch=api({text: payload})).resolve(text) is None

    def test_without_a_fetch_only_known_and_cached_answers_are_given(self, tmp_path):
        cache = RorCache(tmp_path / "ror.sqlite3")
        cache.put(PSU, read_response(PENN_STATE))
        resolver = RorResolver(known=BUCKNELL, cache=cache)
        assert resolver.resolve(PSU).ror_id == "04p491231"
        assert resolver.resolve("Bucknell").ror_id == "00fc1qt65"
        assert resolver.resolve("Colorado State University") is None

    def test_a_text_looked_up_once_is_answered_from_the_cache_afterwards(self, tmp_path):
        path = tmp_path / "ror.sqlite3"
        first = RorResolver(cache=RorCache(path), fetch=api({PSU: PENN_STATE}))
        assert first.resolve(PSU).ror_id == "04p491231"
        later = RorResolver(cache=RorCache(path), fetch=never)
        assert later.resolve(PSU) == first.resolve(PSU)

    def test_a_text_without_a_match_is_not_asked_about_again(self, tmp_path):
        path = tmp_path / "ror.sqlite3"
        RorResolver(cache=RorCache(path), fetch=api({"NC State": NC_STATE})).resolve("NC State")
        assert RorResolver(cache=RorCache(path), fetch=never).resolve("NC State") is None

    def test_an_unavailable_api_leaves_the_text_alone_and_is_remembered_as_a_failure(self):
        resolver = RorResolver(fetch=down)
        assert resolver.resolve(PSU) is None
        assert resolver.failures == [PSU]

    def test_a_failed_lookup_is_not_cached_as_an_answer(self, tmp_path):
        path = tmp_path / "ror.sqlite3"
        RorResolver(cache=RorCache(path), fetch=down).resolve(PSU)
        again = RorResolver(cache=RorCache(path), fetch=api({PSU: PENN_STATE}))
        assert again.resolve(PSU).ror_id == "04p491231"

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
