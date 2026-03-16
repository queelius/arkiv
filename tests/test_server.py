"""Tests for arkiv MCP server tools (unit tests, no MCP transport)."""

import json
import pytest
from arkiv.server import ArkivServer


class TestArkivServer:
    @pytest.fixture
    def server(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"content": "hello", "metadata": {"role": "user"}}\n'
            '{"content": "world", "metadata": {"role": "assistant"}}\n'
        )
        from arkiv.database import Database
        from arkiv.readme import Readme, save_readme

        # Import via README.md with metadata
        readme = Readme(
            frontmatter={
                "name": "Test archive",
                "description": "Test archive",
                "contents": [{"path": "test.jsonl", "description": "Test data"}],
            },
        )
        save_readme(readme, tmp_path / "README.md")

        db = Database(tmp_path / "test.db")
        db.import_readme(tmp_path / "README.md")
        db.close()

        srv = ArkivServer(db_path=tmp_path / "test.db")
        yield srv
        srv.close()

    def test_get_manifest(self, server):
        result = server.get_manifest()
        assert result["description"] == "Test archive"
        assert len(result["collections"]) == 1

    def test_get_manifest_has_schema(self, server):
        result = server.get_manifest()
        coll = result["collections"][0]
        assert "schema" in coll
        assert "role" in coll["schema"]["metadata_keys"]

    def test_get_manifest_has_description(self, server):
        result = server.get_manifest()
        coll = result["collections"][0]
        assert coll["description"] == "Test data"

    def test_get_schema(self, server):
        result = server.get_schema("test")
        assert "metadata_keys" in result
        assert "role" in result["metadata_keys"]

    def test_get_schema_all(self, server):
        result = server.get_schema()
        assert "test" in result

    def test_sql_query(self, server):
        results = server.sql_query(
            "SELECT content FROM records WHERE json_extract(metadata, '$.role') = 'user'"
        )
        assert len(results) == 1
        assert results[0]["content"] == "hello"

    def test_sql_query_rejects_writes(self, server):
        with pytest.raises(ValueError):
            server.sql_query("DELETE FROM records")

    def test_get_manifest_bare_import(self, tmp_path):
        """When no README metadata exists, generate from DB info."""
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        from arkiv.database import Database

        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="data")
        db.close()

        srv = ArkivServer(db_path=tmp_path / "test.db")
        result = srv.get_manifest()
        assert len(result["collections"]) == 1
        assert result["collections"][0]["file"] == "data.jsonl"
        srv.close()


class TestWritableServer:
    def test_insert_record_via_server(self, tmp_path):
        """Write via Database.insert_record, read back via ArkivServer."""
        from arkiv.database import Database

        db = Database(tmp_path / "test.db")
        db.insert_record("test", "hello", metadata={"key": "val"})
        db.close()

        srv = ArkivServer(db_path=tmp_path / "test.db")
        result = srv.sql_query("SELECT content FROM records WHERE collection = 'test'")
        assert len(result) == 1
        assert result[0]["content"] == "hello"
        srv.close()

    def test_writable_server_can_write(self, tmp_path):
        """ArkivServer with writable=True opens DB in read-write mode."""
        srv = ArkivServer(db_path=tmp_path / "test.db", writable=True)
        result = srv.db.insert_record("test", "written via writable server")
        assert result["id"] is not None
        rows = srv.sql_query("SELECT content FROM records WHERE collection = 'test'")
        assert len(rows) == 1
        srv.close()

    def test_readonly_server_cannot_write(self, tmp_path):
        """ArkivServer without writable flag opens DB read-only."""
        # Create DB first so it exists for read-only open
        from arkiv.database import Database

        db = Database(tmp_path / "test.db")
        db.close()

        srv = ArkivServer(db_path=tmp_path / "test.db")
        # read_only DB should reject writes
        with pytest.raises(Exception):
            srv.db.insert_record("test", "should fail")
        srv.close()
