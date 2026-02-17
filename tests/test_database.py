"""Tests for arkiv.database."""

import json
import sqlite3
import pytest
from arkiv.database import Database


class TestImport:
    def test_import_jsonl(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"mimetype": "text/plain", "content": "hello", "metadata": {"role": "user"}}\n'
            '{"mimetype": "text/plain", "content": "world", "metadata": {"role": "assistant"}}\n'
        )
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM records").fetchone()
        assert rows[0] == 2
        conn.close()

    def test_import_preserves_fields(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"mimetype": "text/plain", "uri": "https://example.com", "content": "hello", "timestamp": "2024-01-15", "metadata": {"key": "val"}}\n'
        )
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT mimetype, uri, content, timestamp, metadata FROM records"
        ).fetchone()
        assert row[0] == "text/plain"
        assert row[1] == "https://example.com"
        assert row[2] == "hello"
        assert row[3] == "2024-01-15"
        assert json.loads(row[4]) == {"key": "val"}
        conn.close()

    def test_import_empty_record(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("{}\n")
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT mimetype, content FROM records").fetchone()
        assert row[0] is None
        assert row[1] is None
        conn.close()

    def test_import_computes_schema(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"metadata": {"role": "user"}}\n'
            '{"metadata": {"role": "assistant"}}\n'
        )
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT key_path, type, count FROM _schema WHERE collection = 'test'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "role"
        assert rows[0][1] == "string"
        assert rows[0][2] == 2
        conn.close()

    def test_collection_name_from_filename(self, tmp_path):
        f = tmp_path / "conversations.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f)
        db.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT collection FROM records").fetchone()
        assert row[0] == "conversations"
        conn.close()


class TestQuery:
    def test_sql_query(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"content": "hello", "metadata": {"role": "user"}}\n'
            '{"content": "world", "metadata": {"role": "assistant"}}\n'
        )
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")

        results = db.query(
            "SELECT content FROM records WHERE json_extract(metadata, '$.role') = 'user'"
        )
        assert len(results) == 1
        assert results[0]["content"] == "hello"
        db.close()

    def test_query_returns_dicts(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello", "mimetype": "text/plain"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")

        results = db.query("SELECT content, mimetype FROM records")
        assert results[0]["content"] == "hello"
        assert results[0]["mimetype"] == "text/plain"
        db.close()

    def test_query_rejects_writes(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        with pytest.raises(ValueError):
            db.query("DROP TABLE records")
        db.close()


class TestReadOnly:
    def test_read_only_nonexistent_raises(self, tmp_path):
        db_path = tmp_path / "nonexistent.db"
        with pytest.raises(FileNotFoundError, match="Database not found"):
            Database(db_path, read_only=True)

    def test_read_only_prevents_writes(self, tmp_path):
        # Create a valid DB first
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        # Open read-only and try to write
        db = Database(db_path, read_only=True)
        with pytest.raises(Exception):
            db.conn.execute("INSERT INTO records (content) VALUES ('bad')")
        db.close()


class TestReplaceSemantics:
    def test_double_import_replaces(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.import_jsonl(f, collection="test")

        results = db.query("SELECT COUNT(*) as cnt FROM records")
        assert results[0]["cnt"] == 1
        db.close()

    def test_replace_only_affects_same_collection(self, tmp_path):
        f1 = tmp_path / "a.jsonl"
        f1.write_text('{"content": "aaa"}\n')
        f2 = tmp_path / "b.jsonl"
        f2.write_text('{"content": "bbb"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f1, collection="a")
        db.import_jsonl(f2, collection="b")
        # Re-import a
        db.import_jsonl(f1, collection="a")

        results = db.query("SELECT COUNT(*) as cnt FROM records")
        assert results[0]["cnt"] == 2
        db.close()


class TestQueryGuard:
    def test_with_insert_rejected(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")

        with pytest.raises(ValueError):
            db.query(
                "WITH x AS (SELECT 1) INSERT INTO records (content) VALUES ('hack')"
            )
        db.close()

    def test_delete_rejected(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        with pytest.raises(ValueError):
            db.query("DELETE FROM records")
        db.close()

    def test_read_only_query_blocks_write_attempt(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        db = Database(db_path, read_only=True)
        with pytest.raises(ValueError):
            db.query("DROP TABLE records")
        db.close()


class TestInfo:
    def test_get_info(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "a"}\n{"content": "b"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")

        info = db.get_info()
        assert info["total_records"] == 2
        assert "test" in info["collections"]
        assert info["collections"]["test"]["record_count"] == 2
        db.close()
