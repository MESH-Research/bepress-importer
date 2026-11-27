"""Behavioural tests for the Bucknell Content Inventory profile.

One flat inventory table carries every collection; the profile routes rows to
per-collection mapping groups via `select` on the `publication` column, so the
collections we remapped for the Bucknell collection export (theses, journal
articles, books, press, podcasts...) keep those mappings here too. Everything
else falls to a generic catch-all group.
"""

import json
from pathlib import Path

import pytest

from bepress_importer.convert import convert_workbook
from bepress_importer.profiles import load_profile
from bepress_importer.readers import Table, Workbook
from bepress_importer.transforms import known_transforms

PROFILE = Path(__file__).parent.parent / "profiles" / "inventory-bucknell.toml"
AS_OF = "2026-08-25"


@pytest.fixture(scope="module")
def profile():
    return load_profile(PROFILE, known_transforms=known_transforms())


def block(profile, collection):
    matches = [s for s in profile.sheets if s.collection == collection]
    assert matches, f"no [[sheet]] block for collection {collection!r}"
    return matches[0]


def field(sheet, target):
    matches = [f for f in sheet.fields if f.target == target]
    assert matches, f"no field targeting {target!r}"
    return matches[0]


class TestProfileShape:
    def test_profile_is_the_bucknell_content_inventory_mapping(self, profile):
        assert profile.name == "inventory-bucknell"

    def test_declares_the_content_inventory_format_signature(self, profile):
        assert set(profile.signature_columns) == {"context_key", "state", "document_type"}

    def test_every_bucknell_collection_has_a_selected_group(self, profile):
        selected = {
            s.collection: s.select.values
            for s in profile.sheets
            if s.select is not None
        }
        assert selected == {
            "fac_journ": ("fac_journ",),
            "masters_theses": ("masters_theses",),
            "honors_theses": ("honors_theses",),
            "books": ("books",),
            "bucknell-press": ("bucknell-press",),
            "bucknell_digital_scholarship": ("bucknell_digital_scholarship",),
            "dssrf": ("dssrf",),
            "bucknell-occupied": ("bucknell-occupied",),
        }

    def test_selection_column_is_publication(self, profile):
        for sheet in profile.sheets:
            if sheet.select is not None:
                assert sheet.select.column == "publication"

    def test_the_last_group_is_the_catch_all(self, profile):
        assert profile.sheets[-1].select is None
        assert profile.sheets[-1].collection == "inventory"

    def test_only_published_rows_are_imported_in_every_group(self, profile):
        for sheet in profile.sheets:
            assert sheet.filter is not None, f"{sheet.collection}: missing state filter"
            assert sheet.filter.column == "state"
            assert sheet.filter.keep == ("published",)

    def test_record_identity_is_context_key_with_no_url_column(self, profile):
        assert profile.defaults.record_id_column == "context_key"
        assert profile.defaults.url_column is None

    def test_author_columns_cover_the_widest_inventory_rows(self, profile):
        # bnell.xlsx carries author1..author72 column groups
        assert profile.defaults.authors.max >= 72

    def test_legend_sheets_never_match(self, profile):
        assert profile.match_sheets("Field Names", columns=("Fields included",)) == ()


class TestJournalArticlesGroup:
    def test_document_types_follow_the_bucknell_mapping(self, profile):
        rt = block(profile, "fac_journ").resource_type
        assert rt.map["article"] == "textDocument-journalArticle"
        assert rt.map["book_contribution"] == "textDocument-bookSection"
        assert rt.map["popular_press"] == "textDocument-magazineArticle"
        assert rt.default == "textDocument-journalArticle"

    def test_journal_metadata_columns_build_the_journal_field(self, profile):
        journal = block(profile, "fac_journ").journal
        assert journal.title == "src_journal"
        assert journal.volume == "volnum"
        assert journal.issue == "issnum"
        assert journal.pages_first == "fpage"
        assert journal.pages_last == "lpage"

    def test_publication_statement_becomes_copyright(self, profile):
        mapping = field(block(profile, "fac_journ"), "/metadata/copyright")
        assert mapping.source == "pub_statement"

    def test_pub_link_and_doi_accumulate_into_identifiers(self, profile):
        sheet = block(profile, "fac_journ")
        sources = {
            f.source for f in sheet.fields if f.target == "/metadata/identifiers"
        }
        assert {"pub_link", "doi"} <= sources


class TestThesesGroups:
    @pytest.mark.parametrize("collection", ["masters_theses", "honors_theses"])
    def test_thesis_custom_fields_follow_the_bucknell_mapping(self, profile, collection):
        sheet = block(profile, collection)
        assert field(sheet, "/custom_fields/thesis:thesis/type").source == "degree_name"
        assert field(sheet, "/custom_fields/thesis:thesis/department").source == "department"
        assert (
            field(sheet, "/custom_fields/kcr:institution_department").source == "department2"
        )

    @pytest.mark.parametrize("collection", ["masters_theses", "honors_theses"])
    def test_university_defaults_to_bucknell(self, profile, collection):
        mapping = field(block(profile, collection), "/custom_fields/thesis:thesis/university")
        assert mapping.transform == "author_institution"
        assert mapping.args.get("default") == "Bucknell University"

    @pytest.mark.parametrize("collection", ["masters_theses", "honors_theses"])
    def test_concentration_merges_into_disciplines(self, profile, collection):
        mapping = field(block(profile, collection), "/custom_fields/kcr:discipline")
        assert mapping.args.get("also_columns") == ["concentration"]

    @pytest.mark.parametrize("collection", ["masters_theses", "honors_theses"])
    def test_advisors_become_committee_members(self, profile, collection):
        contributors = block(profile, collection).contributors
        assert contributors.prefix == "advisor"
        assert contributors.role == "committeeMember"


class TestBooksAndPressGroups:
    def test_authored_books_are_books_with_an_imprint_place(self, profile):
        sheet = block(profile, "books")
        assert sheet.resource_type.constant == "textDocument-book"
        assert sheet.imprint.place == "city"
        assert field(sheet, "/metadata/publisher").source == "publisher"
        isbn = field(sheet, "/metadata/identifiers")
        assert isbn.source == "identifier"
        assert isbn.args.get("scheme") == "isbn"

    def test_press_records_get_the_press_publisher_constant(self, profile):
        sheet = block(profile, "bucknell-press")
        assert sheet.constants["/metadata/publisher"] == "Bucknell University Press"

    def test_press_bu_type_becomes_a_namespaced_tag(self, profile):
        sheet = block(profile, "bucknell-press")
        tags = [
            f for f in sheet.fields
            if f.target == "/custom_fields/kcr:user_defined_tags"
        ]
        assert {f.source for f in tags} == {"keywords", "bu_type"}
        bu_type = next(f for f in tags if f.source == "bu_type")
        assert bu_type.transform == "prefixed_tag"

    def test_press_all_rights_reserved_marker(self, profile):
        sheet = block(profile, "bucknell-press")
        rights = [f for f in sheet.fields if f.target == "/metadata/rights"]
        assert any(f.transform == "constant_if_present" for f in rights)


class TestPodcastsGroup:
    def test_bucknell_occupied_rows_are_podcast_episodes(self, profile):
        rt = block(profile, "bucknell-occupied").resource_type
        assert rt.map.get("interview") == "audiovisual-podcastEpisode"
        assert rt.default == "audiovisual-podcastEpisode"

    def test_duration_maps_to_sizes(self, profile):
        assert field(block(profile, "bucknell-occupied"), "/metadata/sizes").source == "duration"


class TestCatchAllGroup:
    def test_event_rows_fall_back_to_their_start_date(self, profile):
        mapping = field(block(profile, "inventory"), "/metadata/publication_date")
        assert mapping.args.get("fallback_columns")[0] == "start_date"

    def test_inventory_document_types_are_mapped(self, profile):
        rt = block(profile, "inventory").resource_type
        assert rt.map["poster"] == "presentation-conferencePoster"
        assert rt.map["conference_paper"] == "presentation-conferencePaper"
        assert rt.map["exhibition"] == "other-event"
        assert rt.map["abstracts"] == "textDocument-abstract"
        assert rt.map["installation"] == "image-visualArt"
        assert rt.default == "textDocument-other"

    def test_pub_link_is_a_work_level_url_identifier(self, profile):
        # odt convention: work URLs go to metadata.identifiers; the
        # kcr:publication_url custom field is reserved for series-level URLs
        mapping = next(
            f for f in block(profile, "inventory").fields if f.source == "pub_link"
        )
        assert mapping.target == "/metadata/identifiers"
        assert mapping.args.get("scheme") == "url"

    def test_no_group_maps_the_publication_url_custom_field(self, profile):
        for sheet in profile.sheets:
            targets = {f.target for f in sheet.fields}
            assert "/custom_fields/kcr:publication_url" not in targets, sheet.collection


def test_every_mapped_resource_type_exists_in_the_vocabulary(profile):
    vocab_path = (
        Path(__file__).parent.parent / "src" / "bepress_importer" / "vocab"
        / "resource_types.json"
    )
    known_ids = set(json.loads(vocab_path.read_text())["ids"])
    for sheet in profile.sheets:
        rt = sheet.resource_type
        assert set(rt.map.values()) <= known_ids, sheet.collection
        for constant in (rt.default, rt.constant):
            if constant:
                assert constant in known_ids, sheet.collection


COLUMNS = (
    "context_key", "state", "document_type", "publication", "title",
    "publication_date", "season", "start_date", "degree_name", "department",
    "department2", "concentration", "abstract", "keywords", "disciplines",
    "author1_fname", "author1_lname", "advisor1",
)


def inventory_row(**overrides):
    row = {column: "" for column in COLUMNS}
    row.update(state="published", author1_fname="Ada", author1_lname="Lovelace")
    row.update(overrides)
    return row


@pytest.fixture(scope="module")
def routed_result(profile):
    table = Table(
        name="Content Inventory",
        columns=COLUMNS,
        rows=(
            inventory_row(
                context_key="1", publication="fac_journ", document_type="article",
                title="A journal article", publication_date="2020-01-01",
            ),
            inventory_row(
                context_key="2", publication="masters_theses",
                document_type="masters_thesis", title="A thesis",
                publication_date="2019-05-01", degree_name="MSc",
                advisor1="Grace Hopper",
            ),
            inventory_row(
                context_key="3", publication="susquehanna-river-symposium",
                document_type="keynote", title="Opening keynote",
                start_date="2012-11-17",
            ),
            inventory_row(
                context_key="4", publication="fac_journ", document_type="article",
                title="Withdrawn", state="withdrawn",
            ),
        ),
    )
    legend = Table(name="Field Names", columns=("Fields included",), rows=())
    return convert_workbook(Workbook(tables=(table, legend)), profile, as_of=AS_OF)


class TestEndToEndRouting:
    def test_rows_are_routed_to_their_collections(self, routed_result):
        assert set(routed_result.collections) == {"fac_journ", "masters_theses", "inventory"}

    def test_thesis_rows_get_the_thesis_treatment(self, routed_result):
        thesis = routed_result.collections["masters_theses"][0]
        assert thesis["metadata"]["resource_type"] == {"id": "textDocument-thesis"}
        assert thesis["custom_fields"]["thesis:thesis"]["type"] == "MSc"
        assert thesis["custom_fields"]["thesis:thesis"]["university"] == "Bucknell University"
        assert thesis["metadata"]["contributors"][0]["person_or_org"]["name"] == "Hopper, Grace"

    def test_event_rows_fall_to_the_catch_all_with_their_start_date(self, routed_result):
        event = routed_result.collections["inventory"][0]
        assert event["metadata"]["title"] == "Opening keynote"
        assert event["metadata"]["publication_date"] == "2012-11-17"

    def test_unpublished_rows_are_filtered_and_legend_unmatched(self, routed_result):
        all_titles = [
            r["metadata"]["title"]
            for records in routed_result.collections.values()
            for r in records
        ]
        assert "Withdrawn" not in all_titles
        assert routed_result.unmatched_sheets == ["Field Names"]


IMPORT_COLUMNS = (
    *COLUMNS, "doi", "pub_link", "pub_statement", "publisher", "src_journal",
    "authors", "date_posted", "volnum", "issnum", "fpage", "lpage",
)


def import_row(**overrides):
    row = {column: "" for column in IMPORT_COLUMNS}
    row.update(
        state="published", author1_fname="Ada", author1_lname="Lovelace",
        publication="fac_journ", document_type="article", title="An article",
        publication_date="2020-01-01",
    )
    row.update(overrides)
    return row


def convert_rows(profile, *rows):
    table = Table(name="Content Inventory", columns=IMPORT_COLUMNS, rows=tuple(rows))
    return convert_workbook(Workbook(tables=(table,)), profile, as_of=AS_OF)


def records_by_id(result):
    return {
        next(
            i["identifier"] for i in r["metadata"]["identifiers"] if i["scheme"] == "import-recid"
        ): r
        for records in result.collections.values()
        for r in records
    }


class TestExistingDoisBecomePids:
    """KC Works must be told about a DOI a work already has, in `pids`."""

    @pytest.mark.parametrize(
        "cells",
        [
            {"doi": "10.1016/j.jmps.2018.02.012"},
            {"doi": "https://doi.org/10.1016/j.jmps.2018.02.012"},
            {"pub_link": "https://doi.org/10.1016/j.jmps.2018.02.012"},
            {"pub_link": "http://dx.doi.org/10.1016/j.jmps.2018.02.012"},
            {"pub_link": "https://dx.doi.org/10.1016/j.jmps.2018.02.012"},
            {"pub_link": "dx.doi.org/10.1016/j.jmps.2018.02.012"},
            {
                "doi": "10.1016/j.jmps.2018.02.012",
                "pub_link": "https://doi.org/10.1016/j.jmps.2018.02.012",
            },
        ],
    )
    def test_journal_article_doi_is_registered_as_an_external_pid(self, profile, cells):
        record = records_by_id(convert_rows(profile, import_row(context_key="1", **cells)))["1"]
        assert record["pids"] == {
            "doi": {"identifier": "10.1016/j.jmps.2018.02.012", "provider": "external"}
        }
        assert record["metadata"]["identifiers"] == [
            {"identifier": "1", "scheme": "import-recid"}
        ]

    def test_rows_outside_the_journal_group_get_the_same_treatment(self, profile):
        row = import_row(
            context_key="1", publication="fac_books", document_type="book",
            pub_link="https://doi.org/10.1093/oxfordhb/9780195396706.013.0020",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["pids"]["doi"] == {
            "identifier": "10.1093/oxfordhb/9780195396706.013.0020", "provider": "external",
        }

    def test_publisher_page_stays_an_identifier_and_no_pid_is_invented(self, profile):
        link = "https://www.sciencedirect.com/science/article/pii/S0195666317300491"
        record = records_by_id(
            convert_rows(profile, import_row(context_key="1", pub_link=link))
        )["1"]
        assert "pids" not in record
        assert {"identifier": link, "scheme": "url"} in record["metadata"]["identifiers"]

    def test_no_record_keeps_a_doi_scheme_identifier(self, profile):
        result = convert_rows(
            profile,
            import_row(context_key="1", doi="10.1016/j.jmps.2018.02.012"),
            import_row(context_key="2", doi="Unknown"),
            import_row(context_key="3", doi="PMID: 21506449"),
        )
        for record in records_by_id(result).values():
            assert all(i["scheme"] != "doi" for i in record["metadata"]["identifiers"])


class TestPublisherIsFilledIn:
    def test_copyright_naming_a_publisher_sets_the_publisher(self, profile):
        statement = (
            "If you would like to request permissions directly from Taylor & Francis, "
            "please email your request directly to permissionrequest@tandf.co.uk."
        )
        record = records_by_id(
            convert_rows(profile, import_row(context_key="1", pub_statement=statement))
        )["1"]
        assert record["metadata"]["publisher"] == "Taylor & Francis"
        assert record["metadata"]["copyright"] == statement

    @pytest.mark.parametrize(
        "cells, publisher",
        [
            ({"pub_statement": "© 2019 IEEE. Personal use is permitted."}, "IEEE"),
            ({"pub_statement": "in accordance with Wiley Terms and Conditions"}, "Wiley"),
            ({"doi": "10.1016/j.jmps.2018.02.012"}, "Elsevier"),
            ({"pub_link": "https://www.tandfonline.com/toc/rsgj20/current"}, "Taylor & Francis"),
        ],
    )
    def test_journal_article_publisher_is_inferred(self, profile, cells, publisher):
        record = records_by_id(convert_rows(profile, import_row(context_key="1", **cells)))["1"]
        assert record["metadata"]["publisher"] == publisher

    def test_an_article_with_no_trace_of_its_publisher_has_none(self, profile):
        record = records_by_id(convert_rows(profile, import_row(context_key="1")))["1"]
        assert "publisher" not in record["metadata"]

    def test_a_publisher_named_in_the_export_is_kept(self, profile):
        row = import_row(
            context_key="1", publication="griot-books", document_type="book",
            publisher="Bucknell University Press", pub_link="https://doi.org/10.1016/x.1",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["metadata"]["publisher"] == "Bucknell University Press"


class TestCopyrightHoldsOnlyRightsStatements:
    ABSTRACT = (
        "Animals learn to prefer and increase consumption of flavors paired with "
        "postingestive nutrient sensing. Analogous effects have been difficult to observe."
    )

    def test_open_access_is_a_reasonable_copyright_value(self, profile):
        record = records_by_id(
            convert_rows(profile, import_row(context_key="1", pub_statement="Open Access"))
        )["1"]
        assert record["metadata"]["copyright"] == "Open Access"

    def test_an_abstract_never_lands_in_copyright(self, profile):
        result = convert_rows(profile, import_row(context_key="1", pub_statement=self.ABSTRACT))
        record = records_by_id(result)["1"]
        assert "copyright" not in record["metadata"]
        assert record["metadata"]["description"] == self.ABSTRACT
        assert [i.record_id for i in result.issues] == ["1"]

    def test_the_real_abstract_is_not_displaced(self, profile):
        row = import_row(
            context_key="1", pub_statement=self.ABSTRACT, abstract="The real abstract."
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["metadata"]["description"] == "The real abstract."


class TestCleanedDocumentTypes:
    """Bucknell's cleaned export names some types the way KC Works does."""

    @pytest.mark.parametrize("collection", ["fac_journ", "inventory"])
    @pytest.mark.parametrize(
        "document_type, resource_type",
        [
            ("poeticWork", "textDocument-poeticWork"),
            ("review", "textDocument-review"),
            ("essay", "textDocument-essay"),
            ("book", "textDocument-book"),
            ("bookSection", "textDocument-bookSection"),
            ("onlinePublication", "textDocument-onlinePublication"),
            ("interactiveResource", "other-interactiveResource"),
            ("videoRecording", "audiovisual-videoRecording"),
            ("musicalRecording", "audiovisual-musicalRecording"),
            ("patent", "other-patent"),
            ("proceedingsPaper", "textDocument-conferenceProceeding"),
            ("textDocument/other", "textDocument-other"),
        ],
    )
    def test_kc_works_style_type_names_are_understood(
        self, profile, collection, document_type, resource_type
    ):
        publication = "fac_journ" if collection == "fac_journ" else "fac_pubs"
        result = convert_rows(
            profile,
            import_row(context_key="1", publication=publication, document_type=document_type),
        )
        record = records_by_id(result)["1"]
        assert record["metadata"]["resource_type"] == {"id": resource_type}
        assert result.issues == []


class TestSensibleValues:
    """Things a reader of the imported record would otherwise trip over."""

    @pytest.mark.parametrize(
        "publication, document_type",
        [
            ("fac_journ", "article"), ("masters_theses", "masters_thesis"),
            ("honors_theses", "honors_thesis"), ("books", "book"),
            ("bucknell-press", "book"), ("dssrf", "digital_project"),
            ("bucknell-occupied", "interview"), ("fac_pubs", "article"),
            ("bucknell_digital_scholarship", "digital_project"),
        ],
    )
    def test_titles_are_plain_text_in_every_group(self, profile, publication, document_type):
        row = import_row(
            context_key="1", publication=publication, document_type=document_type,
            title="Measuring H<sub>2</sub>S over <em>Solanum</em>  sites",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["metadata"]["title"] == "Measuring H2S over Solanum sites"

    @pytest.mark.parametrize(
        "publication, document_type",
        [
            ("fac_journ", "article"), ("masters_theses", "masters_thesis"),
            ("honors_theses", "honors_thesis"), ("books", "book"),
            ("bucknell-press", "book"), ("dssrf", "digital_project"),
            ("bucknell-occupied", "interview"), ("fac_pubs", "article"),
            ("bucknell_digital_scholarship", "digital_project"),
        ],
    )
    def test_keywords_typed_with_semicolons_become_separate_tags(
        self, profile, publication, document_type
    ):
        row = import_row(
            context_key="1", publication=publication, document_type=document_type,
            keywords="aluminum alloys; cold spray; corrosion resistance",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["custom_fields"]["kcr:user_defined_tags"][:3] == [
            "aluminum alloys", "cold spray", "corrosion resistance",
        ]

    def test_library_proxy_links_are_made_public(self, profile):
        row = import_row(
            context_key="1",
            pub_link="http://www.jstor.org.ezproxy.bucknell.edu/stable/40157007",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert {"identifier": "http://www.jstor.org/stable/40157007", "scheme": "url"} in (
            record["metadata"]["identifiers"]
        )

    def test_corporate_authors_are_not_lost(self, profile):
        row = import_row(
            context_key="1", publication="newsletters", document_type="newsletters",
            author1_fname="", author1_lname="",
            authors='[{"CORPORATE_AUTHOR": "Bucknell University Environmental Center", '
                    '"IS_CORPORATE_AUTHOR": "1"}]',
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert [c["person_or_org"] for c in record["metadata"]["creators"]] == [
            {"type": "organizational", "name": "Bucknell University Environmental Center"}
        ]

    def test_an_undated_item_takes_the_date_it_was_posted(self, profile):
        row = import_row(
            context_key="1", publication="humanities-review", document_type="journalArticle",
            publication_date="", date_posted="2017-10-23 06:30:18",
        )
        result = convert_rows(profile, row)
        assert records_by_id(result)["1"]["metadata"]["publication_date"] == "2017-10-23"
        assert result.issues == []

    def test_an_events_own_start_date_is_preferred_to_the_posting_date(self, profile):
        row = import_row(
            context_key="1", publication="lit_pubs", document_type="conference",
            publication_date="", start_date="2012-11-17", date_posted="2017-10-23 06:30:18",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["metadata"]["publication_date"] == "2012-11-17"

    def test_notes_in_volume_and_page_cells_are_left_out(self, profile):
        row = import_row(
            context_key="1", src_journal="J", volnum="Online; print edition forthcoming",
            issnum="2", fpage="062105", lpage="not applicable",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["custom_fields"]["journal:journal"] == {
            "title": "J", "issue": "2", "pages": "062105",
        }


class TestBucknellIsThePublisherOfItsOwnWork:
    """Theses and Bucknell's own digital projects have no outside publisher;
    KC Works needs one to register their DOIs."""

    @pytest.mark.parametrize(
        "publication, document_type",
        [
            ("masters_theses", "masters_thesis"), ("honors_theses", "honors_thesis_b"),
            ("dssrf", "digital_project"), ("bucknell-occupied", "interview"),
            ("bucknell_digital_scholarship", "digital_project"),
        ],
    )
    def test_publisher_is_bucknell_university(self, profile, publication, document_type):
        row = import_row(context_key="1", publication=publication, document_type=document_type)
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["metadata"]["publisher"] == "Bucknell University"

    def test_the_press_keeps_its_own_imprint(self, profile):
        row = import_row(context_key="1", publication="bucknell-press", document_type="book")
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["metadata"]["publisher"] == "Bucknell University Press"


class TestDoiStrandedInAVolumeCell:
    def test_it_is_registered_and_the_cell_is_not_used_as_a_volume(self, profile):
        row = import_row(
            context_key="1", src_journal="J",
            volnum="Online First: doi:10.1177/1468087411424376",
            issnum="Online First: doi:10.1177/1468087411424376",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["pids"]["doi"]["identifier"] == "10.1177/1468087411424376"
        assert record["custom_fields"]["journal:journal"] == {"title": "J"}
        assert record["metadata"]["publisher"] == "SAGE Publications"

    def test_the_doi_column_still_takes_precedence(self, profile):
        row = import_row(
            context_key="1", doi="10.1016/J.JMPS.2018.02.012",
            volnum="doi: 10.1016/j.jmps.2018.02.012",
        )
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["pids"]["doi"]["identifier"] == "10.1016/J.JMPS.2018.02.012"


class TestAffiliationRorIds:
    @pytest.mark.parametrize(
        "institution",
        [
            "Bucknell University", "Bucknell", "bucknell", "Bucknell U", "Bucknell U.",
            "Bucknell Univ", "Biology Department, Bucknell University",
        ],
    )
    def test_bucknell_always_carries_its_ror_id(self, profile, institution):
        row = import_row(context_key="1", author1_institution=institution)
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["metadata"]["creators"][0]["affiliations"] == [{"id": "00fc1qt65"}]

    def test_a_joint_institute_is_not_taken_for_bucknell(self, profile):
        name = "Geisinger-Bucknell Autism and Developmental Medicine Institute"
        row = import_row(context_key="1", author1_institution=name)
        record = records_by_id(convert_rows(profile, row))["1"]
        assert record["metadata"]["creators"][0]["affiliations"] == [{"name": name}]

    def test_other_institutions_are_looked_up_in_ror(self, profile):
        assert profile.defaults.affiliations.ror_lookup is True
