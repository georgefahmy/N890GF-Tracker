"""
Tests for pure utility functions defined in app.py.

Covers: validate_float, convection, parse_date_obj, parse_date_safe,
        sanitize_for_json, compute_nav_status, append_unique_row
"""

import csv
import math
import os
import tempfile
from datetime import datetime, timedelta

import pytest


class TestValidateFloat:
    """Tests for the validate_float() helper."""

    def test_valid_float(self, app):
        from app import validate_float

        assert validate_float(3.14159) == 3.14

    def test_valid_integer(self, app):
        from app import validate_float

        assert validate_float(5) == 5.0

    def test_valid_string_number(self, app):
        from app import validate_float

        assert validate_float("12.345") == 12.35

    def test_none_returns_default(self, app):
        from app import validate_float

        assert validate_float(None) == 0.0

    def test_none_returns_custom_default(self, app):
        from app import validate_float

        assert validate_float(None, default=99.0) == 99.0

    def test_invalid_string(self, app):
        from app import validate_float

        assert validate_float("not_a_number") == 0.0

    def test_empty_string(self, app):
        from app import validate_float

        assert validate_float("") == 0.0

    def test_rounds_to_two_decimals(self, app):
        from app import validate_float

        assert validate_float(1.999) == 2.0

    def test_negative_number(self, app):
        from app import validate_float

        assert validate_float(-5.678) == -5.68

    def test_zero(self, app):
        from app import validate_float

        assert validate_float(0) == 0.0


class TestConvection:
    """Tests for the convection() thermal layer calculator."""

    def test_basic_calculation(self, app):
        from app import convection

        # (OAT - DewPoint) / 4.4 * 1000
        result = convection(dew_point=50.0, outside_air_temp=72.0)
        expected = (72.0 - 50.0) / 4.4 * 1000
        assert abs(result - expected) < 0.01

    def test_zero_spread(self, app):
        from app import convection

        result = convection(dew_point=60.0, outside_air_temp=60.0)
        assert result == 0.0

    def test_negative_spread(self, app):
        from app import convection

        # Dew point higher than OAT (unusual but possible)
        result = convection(dew_point=70.0, outside_air_temp=60.0)
        assert result < 0

    def test_large_spread(self, app):
        from app import convection

        result = convection(dew_point=30.0, outside_air_temp=90.0)
        expected = (90.0 - 30.0) / 4.4 * 1000
        assert abs(result - expected) < 0.01


class TestParseDateObj:
    """Tests for parse_date_obj() — returns a datetime object."""

    def test_iso_format(self, app):
        from app import parse_date_obj

        result = parse_date_obj("2024-03-15")
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15

    def test_us_format_slash(self, app):
        from app import parse_date_obj

        result = parse_date_obj("03/15/2024")
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15

    def test_us_format_dash(self, app):
        from app import parse_date_obj

        result = parse_date_obj("03-15-2024")
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15

    def test_empty_returns_today(self, app):
        from app import parse_date_obj

        result = parse_date_obj("")
        assert result.date() == datetime.today().date()

    def test_none_returns_today(self, app):
        from app import parse_date_obj

        result = parse_date_obj(None)
        assert result.date() == datetime.today().date()

    def test_invalid_returns_now(self, app):
        from app import parse_date_obj

        result = parse_date_obj("not-a-date")
        # Falls through all formats, returns datetime.now()
        assert isinstance(result, datetime)


class TestSanitizeForJson:
    """Tests for sanitize_for_json() — makes data JSON-safe."""

    def test_nan_replaced(self, app):
        from app import sanitize_for_json

        result = sanitize_for_json(float("nan"))
        assert result == 0

    def test_inf_replaced(self, app):
        from app import sanitize_for_json

        result = sanitize_for_json(float("inf"))
        assert result == 0

    def test_negative_inf_replaced(self, app):
        from app import sanitize_for_json

        result = sanitize_for_json(float("-inf"))
        assert result == 0

    def test_none_replaced(self, app):
        from app import sanitize_for_json

        result = sanitize_for_json(None)
        assert result == 0

    def test_valid_float_unchanged(self, app):
        from app import sanitize_for_json

        assert sanitize_for_json(3.14) == 3.14

    def test_valid_int_unchanged(self, app):
        from app import sanitize_for_json

        assert sanitize_for_json(42) == 42

    def test_string_unchanged(self, app):
        from app import sanitize_for_json

        assert sanitize_for_json("hello") == "hello"

    def test_nested_dict(self, app):
        from app import sanitize_for_json

        data = {"a": float("nan"), "b": {"c": float("inf"), "d": 5}}
        result = sanitize_for_json(data)
        assert result == {"a": 0, "b": {"c": 0, "d": 5}}

    def test_nested_list(self, app):
        from app import sanitize_for_json

        data = [1, float("nan"), [None, 3.0]]
        result = sanitize_for_json(data)
        assert result == [1, 0, [0, 3.0]]

    def test_mixed_nested(self, app):
        from app import sanitize_for_json

        data = {"items": [{"val": float("inf")}, {"val": 10}]}
        result = sanitize_for_json(data)
        assert result == {"items": [{"val": 0}, {"val": 10}]}

    def test_ndarray_sanitized(self, app):
        import numpy as np
        from app import sanitize_for_json

        data = {
            "arr": np.array([1.5, 2.5, np.nan]),
            "scalar": np.float64(4.2),
        }
        result = sanitize_for_json(data)
        assert isinstance(result["arr"], list)
        assert result["arr"] == [1.5, 2.5, 0]
        assert isinstance(result["scalar"], float)
        assert result["scalar"] == 4.2


class TestComputeNavStatus:
    """Tests for compute_nav_status() — aviation/obstacle database status."""

    def test_both_current(self, app):
        from app import compute_nav_status

        today = datetime(2024, 3, 15).date()
        nav_date = datetime(2024, 3, 10).date()
        date_aviation = datetime(2024, 3, 1).date()  # cycle ends 3/29
        date_obstacle = datetime(2024, 2, 15).date()  # cycle ends 4/11

        av_status, ob_status = compute_nav_status(
            nav_date, date_aviation, date_obstacle, today
        )
        assert av_status == "Current"
        assert ob_status == "Current"

    def test_aviation_overdue(self, app):
        from app import compute_nav_status

        today = datetime(2024, 4, 15).date()
        nav_date = datetime(2024, 2, 1).date()
        date_aviation = datetime(2024, 3, 1).date()  # cycle ended 3/29
        date_obstacle = datetime(2024, 3, 15).date()  # cycle ends 5/10

        av_status, ob_status = compute_nav_status(
            nav_date, date_aviation, date_obstacle, today
        )
        assert av_status == "Overdue"

    def test_obstacle_overdue(self, app):
        from app import compute_nav_status

        today = datetime(2024, 6, 1).date()
        nav_date = datetime(2024, 3, 1).date()
        date_aviation = datetime(2024, 5, 20).date()  # cycle ends 6/17
        date_obstacle = datetime(2024, 3, 1).date()  # cycle ended 4/26

        av_status, ob_status = compute_nav_status(
            nav_date, date_aviation, date_obstacle, today
        )
        assert ob_status == "Overdue"

    def test_grace_window_allows_early_update(self, app):
        from app import compute_nav_status

        # Nav updated 2 days before aviation cycle start (within 3-day grace)
        date_aviation = datetime(2024, 3, 10).date()
        nav_date = datetime(2024, 3, 8).date()  # 2 days before
        date_obstacle = datetime(2024, 3, 1).date()
        today = datetime(2024, 3, 15).date()

        av_status, _ = compute_nav_status(
            nav_date, date_aviation, date_obstacle, today
        )
        assert av_status == "Current"


class TestAppendUniqueRow:
    """Tests for append_unique_row() — CSV deduplication."""

    def test_new_row_appended(self, app):
        from app import append_unique_row

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            writer = csv.writer(f)
            writer.writerow(["existing", "row"])
            f.flush()
            filepath = f.name

        try:
            append_unique_row(filepath, ["new", "row"])

            with open(filepath, "r") as f:
                rows = list(csv.reader(f))
            assert len(rows) == 2
            assert rows[1] == ["new", "row"]
        finally:
            os.unlink(filepath)

    def test_duplicate_row_skipped(self, app):
        from app import append_unique_row

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            writer = csv.writer(f)
            writer.writerow(["existing", "row"])
            f.flush()
            filepath = f.name

        try:
            append_unique_row(filepath, ["existing", "row"])

            with open(filepath, "r") as f:
                rows = list(csv.reader(f))
            assert len(rows) == 1  # No duplicate added
        finally:
            os.unlink(filepath)
