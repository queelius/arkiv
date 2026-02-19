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


class TestSchemaDescription:
    def test_schema_has_description_column(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="test")

        schema = db.get_schema("test")
        # Description defaults to None when not curated
        assert "description" not in schema["metadata_keys"]["role"]
        db.close()

    def test_merge_curated_schema(self, tmp_path):
        from arkiv.schema import SchemaEntry

        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"metadata": {"role": "user"}}\n'
            '{"metadata": {"role": "assistant"}}\n'
        )
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="test")

        curated = {
            "role": SchemaEntry(
                type="string", count=0, description="Speaker identity"
            ),
        }
        db.merge_curated_schema("test", curated)

        schema = db.get_schema("test")
        assert schema["metadata_keys"]["role"]["description"] == "Speaker identity"
        # Live fields should come from auto-discovered data
        assert schema["metadata_keys"]["role"]["count"] == 2
        db.close()

    def test_merge_curated_adds_missing_keys(self, tmp_path):
        from arkiv.schema import SchemaEntry

        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="test")

        curated = {
            "old_key": SchemaEntry(
                type="string", count=10, description="Deprecated"
            ),
        }
        db.merge_curated_schema("test", curated)

        schema = db.get_schema("test")
        assert "old_key" in schema["metadata_keys"]
        assert schema["metadata_keys"]["old_key"]["count"] == 0
        assert schema["metadata_keys"]["old_key"]["description"] == "Deprecated"
        db.close()

    def test_reimport_preserves_descriptions(self, tmp_path):
        from arkiv.schema import SchemaEntry

        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="test")

        # Add curated description
        curated = {
            "role": SchemaEntry(
                type="string", count=0, description="Speaker identity"
            ),
        }
        db.merge_curated_schema("test", curated)

        # Re-import same JSONL
        db.import_jsonl(f, collection="test")

        schema = db.get_schema("test")
        assert schema["metadata_keys"]["role"]["description"] == "Speaker identity"
        db.close()


class TestReadmeMetadata:
    def test_store_and_load_readme(self, tmp_path):
        from arkiv.readme import Readme

        db = Database(tmp_path / "test.db")
        readme = Readme(
            frontmatter={"name": "Test", "description": "A test"},
            body="# Test\n",
        )
        db._store_readme_metadata(readme)
        loaded = db._load_readme_metadata()
        assert loaded.frontmatter["name"] == "Test"
        assert loaded.frontmatter["description"] == "A test"
        assert "# Test" in loaded.body
        db.close()

    def test_load_returns_none_when_empty(self, tmp_path):
        db = Database(tmp_path / "test.db")
        loaded = db._load_readme_metadata()
        assert loaded is None
        db.close()

    def test_import_readme_stores_metadata(self, tmp_path):
        (tmp_path / "data.jsonl").write_text('{"content": "hello"}\n')
        readme_text = (
            "---\nname: Test Archive\ndescription: A test\n"
            "contents:\n- path: data.jsonl\n  description: Test data\n---\n"
            "# Test Archive\n"
        )
        (tmp_path / "README.md").write_text(readme_text)

        db = Database(tmp_path / "test.db")
        count = db.import_readme(tmp_path / "README.md")
        assert count == 1

        loaded = db._load_readme_metadata()
        assert loaded.frontmatter["name"] == "Test Archive"
        db.close()

    def test_import_readme_merges_schema_yaml(self, tmp_path):
        (tmp_path / "data.jsonl").write_text(
            '{"metadata": {"role": "user"}}\n'
        )
        readme_text = (
            "---\ncontents:\n- path: data.jsonl\n---\n"
        )
        (tmp_path / "README.md").write_text(readme_text)

        schema_yaml = (
            "data:\n  record_count: 1\n  metadata_keys:\n"
            "    role:\n      description: Speaker identity\n"
            "      type: string\n      count: 1\n"
        )
        (tmp_path / "schema.yaml").write_text(schema_yaml)

        db = Database(tmp_path / "test.db")
        db.import_readme(tmp_path / "README.md")

        schema = db.get_schema("data")
        assert schema["metadata_keys"]["role"]["description"] == "Speaker identity"
        db.close()

    def test_import_manifest_stores_as_readme_metadata(self, tmp_path):
        """Backwards compat: import manifest.json → metadata survives in _metadata."""
        (tmp_path / "data.jsonl").write_text('{"content": "hello"}\n')
        manifest = {
            "description": "My archive",
            "created": "2024-06-15",
            "collections": [
                {"file": "data.jsonl", "description": "Test data"},
            ],
        }
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))

        db = Database(tmp_path / "test.db")
        db.import_manifest(tmp_path / "manifest.json")

        loaded = db._load_readme_metadata()
        assert loaded.frontmatter["description"] == "My archive"
        assert loaded.frontmatter["datetime"] == "2024-06-15"
        assert loaded.frontmatter["contents"][0]["description"] == "Test data"
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
