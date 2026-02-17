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
