"""Behavioural tests for export-format recognition via profile signatures.

Profiles live in the user's profile directory (e.g. profiles/); one that
declares `signature_columns` claims a format. `detect_profile` scans a
directory and returns the path of the profile whose signature the workbook
carries — used to hint at the right profile when the wrong one is passed.
"""

from pathlib import Path

import pytest

from bepress_importer.profiles import detect_profile, load_profile
from bepress_importer.readers import Table, Workbook
from bepress_importer.transforms import known_transforms

INVENTORY_COLUMNS = (
    "title", "state", "document_type", "publication", "abstract", "keywords",
    "author1_fname", "author1_lname", "publication_date", "start_date", "context_key",
)

COLLECTION_COLUMNS = tuple(
    c for c in INVENTORY_COLUMNS if c not in ("state", "publication")
)

USER_PROFILE_DIR = Path(__file__).parent.parent / "profiles"


def inventory_workbook():
    return Workbook(
        tables=(
            Table(name="Content Inventory", columns=INVENTORY_COLUMNS, rows=()),
            Table(name="Field Names", columns=("Fields included",), rows=()),
        )
    )


def collection_workbook():
    return Workbook(
        tables=(Table(name="Fac Journal Articles", columns=COLLECTION_COLUMNS, rows=()),)
    )


SIGNATURE_PROFILE = """
[profile]
name = "sig"
schema_version = 1
signature_columns = ["context_key", "state", "document_type"]

[[sheet]]
match = "*"
require_columns = ["context_key", "state", "document_type"]

  [[sheet.field]]
  source = "title"
  target = "/metadata/title"
"""

PLAIN_PROFILE = """
[profile]
name = "plain"
schema_version = 1

[[sheet]]
match = "Fac Journal Articles"

  [[sheet.field]]
  source = "title"
  target = "/metadata/title"
"""


@pytest.fixture()
def profile_dir(tmp_path):
    (tmp_path / "sig.toml").write_text(SIGNATURE_PROFILE)
    (tmp_path / "plain.toml").write_text(PLAIN_PROFILE)
    return tmp_path


class TestDetectProfile:
    def test_returns_the_path_of_the_matching_signature_profile(self, profile_dir):
        found = detect_profile(
            inventory_workbook(), profile_dir, known_transforms=known_transforms()
        )
        assert found == profile_dir / "sig.toml"

    def test_returns_none_when_no_signature_matches(self, profile_dir):
        assert detect_profile(
            collection_workbook(), profile_dir, known_transforms=known_transforms()
        ) is None

    def test_profiles_without_signatures_never_match(self, tmp_path):
        (tmp_path / "plain.toml").write_text(PLAIN_PROFILE)
        assert detect_profile(
            inventory_workbook(), tmp_path, known_transforms=known_transforms()
        ) is None

    def test_empty_directory_matches_nothing(self, tmp_path):
        assert detect_profile(inventory_workbook(), tmp_path) is None


class TestUserProfileDirectory:
    def test_inventory_bucknell_lives_in_the_user_profile_dir(self):
        assert (USER_PROFILE_DIR / "inventory-bucknell.toml").is_file()

    def test_no_profile_ships_inside_the_package(self):
        package_dir = (
            Path(__file__).parent.parent / "src" / "bepress_importer" / "profiles"
        )
        assert list(package_dir.glob("*.toml")) == []

    def test_inventory_bucknell_claims_the_content_inventory_format(self):
        found = detect_profile(
            inventory_workbook(), USER_PROFILE_DIR, known_transforms=known_transforms()
        )
        assert found == USER_PROFILE_DIR / "inventory-bucknell.toml"

    def test_bucknell_collection_export_matches_no_signature(self):
        profile = load_profile(
            USER_PROFILE_DIR / "bucknell.toml", known_transforms=known_transforms()
        )
        assert profile.signature_columns == ()
        assert detect_profile(
            collection_workbook(), USER_PROFILE_DIR, known_transforms=known_transforms()
        ) is None
