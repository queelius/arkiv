"""Tests for timestamp normalization (M2 + M3).

records.timestamp is normalized to canonical UTC on import so lexicographic
order equals chronological order and --since/--until slices are correct.
The exact original string is preserved in records.timestamp_original (NULL
when unchanged) and written back on export, so the directory form stays
lossless.
"""

import sqlite3

import pytest

from arkiv.database import Database
from arkiv.record import normalize_timestamp


class TestNormalizeTimestamp:
    def test_offset_converted_to_utc_with_original(self):
        norm, orig = normalize_timestamp("2024-01-01T08:00:00-05:00")
        assert norm == "2024-01-01T13:00:00Z"
        assert orig == "2024-01-01T08:00:00-05:00"

    def test_positive_offset(self):
        norm, orig = normalize_timestamp("2024-01-01T02:00:00+05:00")
        assert norm == "2023-12-31T21:00:00Z"
        assert orig == "2024-01-01T02:00:00+05:00"

    def test_z_is_already_canonical(self):
        norm, orig = normalize_timestamp("2024-01-01T08:00:00Z")
        assert norm == "2024-01-01T08:00:00Z"
        assert orig is None

    def test_explicit_utc_offset_spelled_back_to_z(self):
        norm, orig = normalize_timestamp("2024-01-01T08:00:00+00:00")
        assert norm == "2024-01-01T08:00:00Z"
        assert orig == "2024-01-01T08:00:00+00:00"

    def test_naive_left_untouched(self):
        # No zone: cannot normalize without assuming one.
        norm, orig = normalize_timestamp("2024-01-01T08:00:00")
        assert norm == "2024-01-01T08:00:00"
        assert orig is None

    def test_date_only_left_untouched(self):
        norm, orig = normalize_timestamp("2024-01-15")
        assert norm == "2024-01-15"
        assert orig is None

    def test_none_and_unparseable(self):
        assert normalize_timestamp(None) == (None, None)
        assert normalize_timestamp("not a date") == ("not a date", None)


class TestImportNormalizes:
    def test_stored_timestamp_is_utc_original_preserved(self, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"content": "a", "timestamp": "2024-01-01T08:00:00-05:00"}\n'
        )
        db = Database(tmp_path / "a.db")
        db.import_jsonl(f, collection="data")
        row = db.conn.execute(
            "SELECT timestamp, timestamp_original FROM records"
        ).fetchone()
        db.close()
        assert row["timestamp"] == "2024-01-01T13:00:00Z"
        assert row["timestamp_original"] == "2024-01-01T08:00:00-05:00"

    def test_order_by_timestamp_is_chronological(self, tmp_path):
        f = tmp_path / "data.jsonl"
        # -05:00 record is 13:00Z (LATER); Z record is 08:00Z (EARLIER).
        # Raw lexicographic order would put '-05:00' first (wrong).
        f.write_text(
            '{"content": "later",  "timestamp": "2024-01-01T08:00:00-05:00"}\n'
            '{"content": "earlier","timestamp": "2024-01-01T08:00:00Z"}\n'
        )
        db = Database(tmp_path / "a.db")
        db.import_jsonl(f, collection="data")
        rows = db.query(
            "SELECT content FROM records ORDER BY timestamp"
        )
        db.close()
        assert [r["content"] for r in rows] == ["earlier", "later"]

    def test_insert_record_normalizes(self, tmp_path):
        db = Database(tmp_path / "a.db")
        db.insert_record(
            "data", "x", timestamp="2024-06-01T00:00:00-04:00"
        )
        row = db.conn.execute(
            "SELECT timestamp, timestamp_original FROM records"
        ).fetchone()
        db.close()
        assert row["timestamp"] == "2024-06-01T04:00:00Z"
        assert row["timestamp_original"] == "2024-06-01T00:00:00-04:00"


class TestExportPreservesOriginal:
    def test_roundtrip_keeps_original_timestamp(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.jsonl").write_text(
            '{"content": "a", "timestamp": "2024-01-01T08:00:00-05:00"}\n'
        )
        (src / "README.md").write_text(
            "---\ncontents:\n- path: data.jsonl\n---\n"
        )
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        out = tmp_path / "out"
        db.export(out)
        db.close()
        text = (out / "data.jsonl").read_text()
        assert "2024-01-01T08:00:00-05:00" in text  # original, not the UTC form

    def test_canonical_utc_not_duplicated_as_original(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.jsonl").write_text(
            '{"content": "a", "timestamp": "2024-01-01T08:00:00Z"}\n'
        )
        (src / "README.md").write_text(
            "---\ncontents:\n- path: data.jsonl\n---\n"
        )
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        row = db.conn.execute(
            "SELECT timestamp_original FROM records"
        ).fetchone()
        out = tmp_path / "out"
        db.export(out)
        db.close()
        assert row["timestamp_original"] is None
        assert "2024-01-01T08:00:00Z" in (out / "data.jsonl").read_text()


class TestTemporalSliceAcrossOffsets:
    def _seed(self, tmp_path, ts):
        db = Database(tmp_path / "a.db")
        f = tmp_path / "data.jsonl"
        f.write_text(f'{{"content": "x", "timestamp": "{ts}"}}\n')
        db.import_jsonl(f, collection="data")
        return db

    def test_since_includes_offset_record_that_belongs_in_range(
        self, tmp_path
    ):
        # 2023-12-31T20:00:00-05:00 == 2024-01-01T01:00:00Z: it IS in 2024.
        db = self._seed(tmp_path, "2023-12-31T20:00:00-05:00")
        out = tmp_path / "out"
        db.export(out, since="2024-01-01")
        db.close()
        assert (out / "data.jsonl").exists()
        assert "2023-12-31T20:00:00-05:00" in (out / "data.jsonl").read_text()

    def test_since_excludes_offset_record_outside_range(self, tmp_path):
        # 2024-01-01T02:00:00+05:00 == 2023-12-31T21:00:00Z: NOT in 2024.
        db = self._seed(tmp_path, "2024-01-01T02:00:00+05:00")
        out = tmp_path / "out"
        db.export(out, since="2024-01-01")
        db.close()
        assert not (out / "data.jsonl").exists()


class TestBackwardCompat:
    def test_export_old_db_without_timestamp_original_column(self, tmp_path):
        # A genuine pre-migration database: records table has no
        # timestamp_original column. Opened read-only, export must not raise.
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, collection TEXT, "
            "mimetype TEXT, uri TEXT, content TEXT, timestamp TEXT, "
            "metadata JSON);"
            "CREATE TABLE _schema (collection TEXT, key_path TEXT, type TEXT, "
            "count INTEGER, sample_values TEXT, description TEXT);"
            "CREATE TABLE _metadata (key TEXT PRIMARY KEY, value TEXT);"
        )
        conn.execute(
            "INSERT INTO records (collection, content, timestamp) "
            "VALUES ('data', 'a', '2024-01-01T08:00:00Z')"
        )
        conn.commit()
        conn.close()

        db = Database(db_path, read_only=True)
        out = tmp_path / "out"
        db.export(out)  # must not raise despite missing timestamp_original
        db.close()
        assert "2024-01-01T08:00:00Z" in (out / "data.jsonl").read_text()

    def test_open_old_db_read_write_migrates_column(self, tmp_path):
        # Opening a pre-migration db read-write adds the column.
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, collection TEXT, "
            "mimetype TEXT, uri TEXT, content TEXT, timestamp TEXT, "
            "metadata JSON);"
            "CREATE TABLE _schema (collection TEXT, key_path TEXT, type TEXT, "
            "count INTEGER, sample_values TEXT, description TEXT);"
            "CREATE TABLE _metadata (key TEXT PRIMARY KEY, value TEXT);"
        )
        conn.commit()
        conn.close()

        db = Database(db_path)  # read-write: _ensure_tables migrates
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(records)")}
        db.close()
        assert "timestamp_original" in cols
