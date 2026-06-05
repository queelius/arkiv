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


class TestRunSqlCapped:
    """The MCP sql_query surface must bound rows returned to the LLM so a
    broad query cannot exfiltrate or OOM the whole archive."""

    def _server(self, tmp_path, n_rows):
        from arkiv.database import Database

        f = tmp_path / "data.jsonl"
        f.write_text(
            "".join(f'{{"content": "r{i}"}}\n' for i in range(n_rows))
        )
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="data")
        db.close()
        return ArkivServer(db_path=tmp_path / "test.db")

    def test_truncates_and_flags(self, tmp_path):
        srv = self._server(tmp_path, n_rows=10)
        out = srv.run_sql_capped("SELECT content FROM records", max_rows=3)
        srv.close()
        assert out["truncated"] is True
        assert out["row_count"] == 3
        assert len(out["rows"]) == 3
        assert "note" in out

    def test_not_truncated_when_under_cap(self, tmp_path):
        srv = self._server(tmp_path, n_rows=2)
        out = srv.run_sql_capped("SELECT content FROM records", max_rows=10)
        srv.close()
        assert out["truncated"] is False
        assert out["row_count"] == 2
        assert "note" not in out

    def test_rejects_writes(self, tmp_path):
        srv = self._server(tmp_path, n_rows=1)
        with pytest.raises(ValueError):
            srv.run_sql_capped("DELETE FROM records", max_rows=10)
        srv.close()


class TestWriteRecordMethod:
    """ArkivServer.write_record holds the MCP write tool's logic (so the
    error paths are testable). Returns a result dict or {'error': ...}."""

    def _writable(self, tmp_path):
        return ArkivServer(db_path=tmp_path / "w.db", writable=True)

    def test_success(self, tmp_path):
        srv = self._writable(tmp_path)
        out = srv.write_record("notes", "hello", metadata='{"k": "v"}')
        srv.close()
        assert "id" in out
        assert out["collection"] == "notes"

    def test_invalid_metadata_json(self, tmp_path):
        srv = self._writable(tmp_path)
        out = srv.write_record("notes", "hi", metadata="{not json")
        srv.close()
        assert "error" in out
        assert "JSON" in out["error"]

    def test_non_dict_metadata(self, tmp_path):
        srv = self._writable(tmp_path)
        out = srv.write_record("notes", "hi", metadata="[1, 2, 3]")
        srv.close()
        assert "error" in out
        assert "object" in out["error"]

    def test_bad_collection_name(self, tmp_path):
        srv = self._writable(tmp_path)
        out = srv.write_record("../escape", "hi")
        srv.close()
        assert "error" in out

    def test_read_only_server_refuses_write(self, tmp_path):
        from arkiv.database import Database

        Database(tmp_path / "ro.db").close()
        srv = ArkivServer(db_path=tmp_path / "ro.db")  # not writable
        out = srv.write_record("notes", "hi")
        srv.close()
        assert "error" in out
        srv.close()
