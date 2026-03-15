"""Tests for arkiv export (SQLite -> JSONL + README.md + schema.yaml)."""

import json
import pytest
from arkiv.database import Database
from arkiv.readme import parse_readme
from arkiv.schema import load_schema_yaml


class TestExport:
    def test_export_creates_jsonl_files(self, tmp_path):
        # Create and populate DB
        f = tmp_path / "input.jsonl"
        f.write_text('{"content": "hello", "metadata": {"role": "user"}}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="conversations")

        # Export
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        assert (out / "conversations.jsonl").exists()
        lines = (out / "conversations.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["content"] == "hello"

    def test_export_creates_readme(self, tmp_path):
        f = tmp_path / "input.jsonl"
        f.write_text('{"content": "a"}\n{"content": "b"}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="data")
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        assert (out / "README.md").exists()
        readme = parse_readme(out / "README.md")
        assert len(readme.frontmatter.get("contents", [])) == 1
        assert readme.frontmatter["contents"][0]["path"] == "data.jsonl"

    def test_export_creates_schema_yaml(self, tmp_path):
        f = tmp_path / "input.jsonl"
        f.write_text(
            '{"metadata": {"role": "user"}}\n'
            '{"metadata": {"role": "assistant"}}\n'
        )
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="data")
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        assert (out / "schema.yaml").exists()
        schemas = load_schema_yaml(out / "schema.yaml")
        assert "data" in schemas
        assert schemas["data"].record_count == 2
        assert "role" in schemas["data"].metadata_keys

    def test_export_multiple_collections(self, tmp_path):
        f1 = tmp_path / "a.jsonl"
        f1.write_text('{"content": "from a"}\n')
        f2 = tmp_path / "b.jsonl"
        f2.write_text('{"content": "from b"}\n')

        db = Database(tmp_path / "test.db")
        db.import_jsonl(f1, collection="alpha")
        db.import_jsonl(f2, collection="beta")
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        assert (out / "alpha.jsonl").exists()
        assert (out / "beta.jsonl").exists()
        readme = parse_readme(out / "README.md")
        paths = [c["path"] for c in readme.frontmatter.get("contents", [])]
        assert "alpha.jsonl" in paths
        assert "beta.jsonl" in paths

    def test_roundtrip_lossless(self, tmp_path):
        """Import JSONL -> SQLite -> Export JSONL. Content should be identical."""
        original = tmp_path / "original.jsonl"
        original.write_text(
            '{"mimetype": "text/plain", "uri": "https://example.com", "content": "hello", "timestamp": "2024-01-15", "metadata": {"role": "user", "id": 42}}\n'
        )

        db = Database(tmp_path / "test.db")
        db.import_jsonl(original, collection="test")
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        exported_line = (out / "test.jsonl").read_text().strip()
        exported = json.loads(exported_line)
        assert exported["mimetype"] == "text/plain"
        assert exported["uri"] == "https://example.com"
        assert exported["content"] == "hello"
        assert exported["timestamp"] == "2024-01-15"
        assert exported["metadata"]["role"] == "user"
        assert exported["metadata"]["id"] == 42

    def test_export_no_manifest_json(self, tmp_path):
        """Export should NOT create manifest.json anymore."""
        f = tmp_path / "input.jsonl"
        f.write_text('{"content": "hello"}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="test")
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        assert not (out / "manifest.json").exists()
        assert (out / "README.md").exists()
        assert (out / "schema.yaml").exists()


class TestSchemaInReadme:
    def test_export_readme_has_summary_table(self, tmp_path):
        """Flat export README body contains a collections summary table."""
        from arkiv.render import BEGIN_SENTINEL, END_SENTINEL

        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n{"metadata": {"role": "admin"}}\n')
        db.import_jsonl(f, collection="data")
        out = tmp_path / "out"
        db.export(out)
        db.close()
        readme_text = (out / "README.md").read_text()
        assert BEGIN_SENTINEL in readme_text
        assert END_SENTINEL in readme_text
        assert "| data |" in readme_text
        assert "## Collections" in readme_text

    def test_export_preserves_user_prose(self, tmp_path):
        """User-written body text outside sentinels survives re-export."""
        from arkiv.render import BEGIN_SENTINEL
        from arkiv.readme import Readme

        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection="data")
        readme = Readme(
            frontmatter={"name": "Test", "contents": [{"path": "data.jsonl"}]},
            body="My custom prose.\n",
        )
        db._store_readme_metadata(readme)
        out = tmp_path / "out"
        db.export(out)
        db.close()
        readme_text = (out / "README.md").read_text()
        assert "My custom prose." in readme_text
        assert BEGIN_SENTINEL in readme_text

    def test_export_sets_arkiv_format(self, tmp_path):
        """Exported README has arkiv_format: '0.2' in frontmatter."""
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection="data")
        out = tmp_path / "out"
        db.export(out)
        db.close()
        readme = parse_readme(out / "README.md")
        assert readme.frontmatter.get("arkiv_format") == "0.2"
