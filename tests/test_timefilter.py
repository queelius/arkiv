"""Tests for temporal filtering helpers."""

import pytest
from arkiv.timefilter import increment_iso_prefix, build_time_filter


class TestIncrementIsoPrefix:
    def test_year(self):
        assert increment_iso_prefix("2024") == "2025"

    def test_year_month(self):
        assert increment_iso_prefix("2024-12") == "2025-01"

    def test_year_month_day(self):
        assert increment_iso_prefix("2024-12-31") == "2025-01-01"

    def test_mid_year(self):
        assert increment_iso_prefix("2024-06") == "2024-07"

    def test_mid_month(self):
        assert increment_iso_prefix("2024-06-15") == "2024-06-16"

    def test_february_non_leap(self):
        assert increment_iso_prefix("2025-02-28") == "2025-03-01"

    def test_february_leap(self):
        assert increment_iso_prefix("2024-02-29") == "2024-03-01"


class TestBuildTimeFilter:
    def test_no_filters(self):
        clause, params = build_time_filter()
        assert clause == ""
        assert params == []

    def test_since_only(self):
        clause, params = build_time_filter(since="2024-01-01")
        assert "timestamp IS NULL" in clause
        assert "timestamp >= ?" in clause
        assert "2024-01-01" in params

    def test_until_prefix(self):
        clause, params = build_time_filter(until="2024-12-31")
        assert "timestamp <" in clause
        assert "2025-01-01" in params

    def test_until_full_timestamp(self):
        clause, params = build_time_filter(until="2024-12-31T23:59:59Z")
        assert "timestamp <=" in clause
        assert "2024-12-31T23:59:59Z" in params

    def test_both(self):
        clause, params = build_time_filter(since="2024-01-01", until="2024-12-31")
        assert len(params) == 2
