"""Behavioural tests for EDTF emission and validation."""

import pytest

from bepress_importer.edtf import is_valid, to_edtf


class TestToEdtf:
    def test_full_date_passes_through(self):
        assert to_edtf("2015-04-15") == "2015-04-15"

    def test_january_first_collapses_to_year(self):
        assert to_edtf("2015-01-01") == "2015"

    def test_january_first_with_season_becomes_edtf_season(self):
        assert to_edtf("2015-01-01", season="Spring") == "2015-21"
        assert to_edtf("2015-01-01", season="Summer") == "2015-22"
        assert to_edtf("2015-01-01", season="Fall") == "2015-23"
        assert to_edtf("2015-01-01", season="Winter") == "2015-24"

    def test_season_style_year_only(self):
        assert to_edtf("2015-01-01", season="Spring", style="year-only") == "2015"

    def test_real_date_wins_over_season(self):
        assert to_edtf("2015-04-15", season="Spring") == "2015-04-15"

    def test_year_and_year_month_pass_through(self):
        assert to_edtf("1998") == "1998"
        assert to_edtf("1998-04") == "1998-04"

    def test_datetime_reading_is_accepted(self):
        # readers emit "YYYY-MM-DD HH:MM:SS" for datetime cells
        assert to_edtf("2015-04-15 10:30:00") == "2015-04-15"

    def test_unparseable_input_raises(self):
        with pytest.raises(ValueError):
            to_edtf("Sometime in the nineties")

    def test_empty_input_raises(self):
        with pytest.raises(ValueError):
            to_edtf("")


class TestIsValid:
    @pytest.mark.parametrize(
        "value", ["2015", "2015-04", "2015-04-01", "2015-21", "2015-24", "1998-12-31"]
    )
    def test_valid(self, value):
        assert is_valid(value) is True

    @pytest.mark.parametrize(
        "value",
        ["", "Spring 2015", "2015-13", "2015-25", "2015-04-31", "2015-00", "15", "2015-4-1", "2015/04"],
    )
    def test_invalid(self, value):
        assert is_valid(value) is False
