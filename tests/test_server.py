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

        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="conversations")

        # Write manifest
        from arkiv.manifest import Manifest, Collection, save_manifest

        m = Manifest(
            description="Test archive",
            collections=[Collection(file="test.jsonl", record_count=2)],
        )
        save_manifest(m, tmp_path / "manifest.json")

        srv = ArkivServer(
            db_path=tmp_path / "test.db",
            manifest_path=tmp_path / "manifest.json",
        )
        yield srv
        srv.close()

    def test_get_manifest(self, server):
        result = server.get_manifest()
        assert result["description"] == "Test archive"
        assert len(result["collections"]) == 1

    def test_get_schema(self, server):
        result = server.get_schema("conversations")
        assert "metadata_keys" in result
        assert "role" in result["metadata_keys"]

    def test_get_schema_all(self, server):
        result = server.get_schema()
        assert "conversations" in result

    def test_sql_query(self, server):
        results = server.sql_query(
            "SELECT content FROM records WHERE json_extract(metadata, '$.role') = 'user'"
        )
        assert len(results) == 1
        assert results[0]["content"] == "hello"

    def test_sql_query_rejects_writes(self, server):
        with pytest.raises(ValueError):
            server.sql_query("DELETE FROM records")

    def test_get_manifest_without_manifest_file(self, tmp_path):
        """When no manifest file exists, generate from DB info."""
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        from arkiv.database import Database

        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="data")

        srv = ArkivServer(db_path=tmp_path / "test.db")
        result = srv.get_manifest()
        assert len(result["collections"]) == 1
        assert result["collections"][0]["file"] == "data.jsonl"
        srv.close()
