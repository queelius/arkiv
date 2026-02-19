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
