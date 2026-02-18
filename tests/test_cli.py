"""Tests for arkiv CLI."""

import json
import subprocess
import sys
import pytest


def run_arkiv(*args):
    result = subprocess.run(
        [sys.executable, "-m", "arkiv.cli", *args],
        capture_output=True,
        text=True,
    )
    return result


class TestCLI:
    def test_version(self):
        result = run_arkiv("--version")
        assert "0.1.0" in result.stdout

    def test_help(self):
        result = run_arkiv("--help")
        assert "import" in result.stdout
        assert "export" in result.stdout
        assert "detect" in result.stdout
        assert "mcp" in result.stdout

    def test_import_jsonl(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        result = run_arkiv("import", str(f), "--db", str(db_path))
        assert result.returncode == 0
        assert db_path.exists()

    def test_import_manifest(self, tmp_path):
        (tmp_path / "data.jsonl").write_text('{"content": "hello"}\n')
        manifest = {"collections": [{"file": "data.jsonl"}]}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        db_path = tmp_path / "test.db"
        result = run_arkiv(
            "import", str(tmp_path / "manifest.json"), "--db", str(db_path)
        )
        assert result.returncode == 0

    def test_query(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        run_arkiv("import", str(f), "--db", str(db_path))
        result = run_arkiv(
            "query", str(db_path), "SELECT content FROM records"
        )
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_schema(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n')
        result = run_arkiv("schema", str(f))
        assert result.returncode == 0
        assert "role" in result.stdout

    def test_schema_from_db(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n')
        db_path = tmp_path / "test.db"
        run_arkiv("import", str(f), "--db", str(db_path))
        result = run_arkiv("schema", str(db_path))
        assert result.returncode == 0
        assert "role" in result.stdout

    def test_info(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "a"}\n{"content": "b"}\n')
        db_path = tmp_path / "test.db"
        run_arkiv("import", str(f), "--db", str(db_path))
        result = run_arkiv("info", str(db_path))
        assert result.returncode == 0
        assert "2" in result.stdout

    def test_import_db_file_rejected(self, tmp_path):
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")
        result = run_arkiv("import", str(db_path))
        assert result.returncode == 1
        assert "database file" in result.stderr.lower()

    def test_query_nonexistent_db(self, tmp_path):
        db_path = tmp_path / "nope.db"
        result = run_arkiv("query", str(db_path), "SELECT 1")
        assert result.returncode == 1
        assert "Error" in result.stderr
        assert not db_path.exists()

    def test_info_nonexistent_db(self, tmp_path):
        db_path = tmp_path / "nope.db"
        result = run_arkiv("info", str(db_path))
        assert result.returncode == 1
        assert "Error" in result.stderr

    def test_schema_nonexistent_db(self, tmp_path):
        db_path = tmp_path / "nope.db"
        result = run_arkiv("schema", str(db_path))
        assert result.returncode == 1
        assert "Error" in result.stderr

    def test_double_import_no_duplicates(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        run_arkiv("import", str(f), "--db", str(db_path))
        run_arkiv("import", str(f), "--db", str(db_path))
        result = run_arkiv(
            "query", str(db_path), "SELECT COUNT(*) as cnt FROM records"
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data[0]["cnt"] == 1

    # --- info on JSONL ---

    def test_info_jsonl(self, tmp_path):
        f = tmp_path / "conversations.jsonl"
        f.write_text('{"content": "a", "metadata": {"role": "user"}}\n{"content": "b"}\n')
        result = run_arkiv("info", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_records"] == 2
        assert "conversations" in data["collections"]

    def test_info_jsonl_shows_schema_keys(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n{"metadata": {"role": "assistant"}}\n')
        result = run_arkiv("info", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "role" in data["collections"]["test"].get("metadata_keys", {})

    # --- helpful errors for JSONL on DB-only commands ---

    def test_query_jsonl_suggests_import(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        result = run_arkiv("query", str(f), "SELECT content FROM records")
        assert result.returncode == 1
        assert "import" in result.stderr.lower()

    def test_export_jsonl_suggests_import(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        result = run_arkiv("export", str(f))
        assert result.returncode == 1
        assert "import" in result.stderr.lower()

    # --- detect command ---

    def test_detect_valid_jsonl(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"content": "hello", "mimetype": "text/plain", "metadata": {"role": "user"}}\n'
            '{"content": "world"}\n'
        )
        result = run_arkiv("detect", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valid"] is True
        assert data["total_records"] == 2

    def test_detect_shows_fields_and_keys(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hi", "metadata": {"lang": "en"}}\n')
        result = run_arkiv("detect", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "content" in data["fields_used"]
        assert "lang" in data["metadata_keys"]

    def test_detect_warns_on_invalid_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "ok"}\nnot json\n{"content": "fine"}\n')
        result = run_arkiv("detect", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_records"] == 2
        assert len(data["warnings"]) > 0

    def test_detect_empty_file(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("")
        result = run_arkiv("detect", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_records"] == 0

    # --- mcp subcommand ---

    def test_mcp_in_help(self):
        result = run_arkiv("--help")
        assert "mcp" in result.stdout

    def test_export(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        run_arkiv("import", str(f), "--db", str(db_path))
        out = tmp_path / "exported"
        result = run_arkiv("export", str(db_path), "--output", str(out))
        assert result.returncode == 0
        assert (out / "test.jsonl").exists()
        assert (out / "manifest.json").exists()
