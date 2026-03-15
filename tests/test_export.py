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


class TestTemporalSlicing:
    def _make_db(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"timestamp": "2023-06-01", "content": "old"}\n'
            '{"timestamp": "2024-03-15", "content": "mid"}\n'
            '{"timestamp": "2024-12-31T10:30:00Z", "content": "late"}\n'
            '{"content": "no timestamp"}\n'
        )
        db.import_jsonl(f, collection="data")
        return db

    def test_since_filters_old_records(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, since="2024-01-01")
        db.close()
        lines = (out / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3  # mid + late + no-timestamp

    def test_until_includes_full_timestamp(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, until="2024-12-31")
        db.close()
        lines = (out / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 4  # all records (2024-12-31T10:30:00Z < 2025-01-01)

    def test_null_timestamps_always_pass(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, since="2099-01-01")
        db.close()
        lines = (out / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1  # only the null-timestamp record

    def test_empty_collection_excluded(self, tmp_path):
        """Collection with zero records after filtering is omitted entirely."""
        db = Database(tmp_path / "test.db")
        f1 = tmp_path / "old.jsonl"
        f1.write_text('{"timestamp": "2020-01-01", "content": "ancient"}\n')
        f2 = tmp_path / "new.jsonl"
        f2.write_text('{"timestamp": "2024-06-01", "content": "recent"}\n')
        db.import_jsonl(f1, collection="old")
        db.import_jsonl(f2, collection="new")
        out = tmp_path / "out"
        db.export(out, since="2024-01-01")
        db.close()
        assert not (out / "old.jsonl").exists()
        readme = parse_readme(out / "README.md")
        paths = [c["path"] for c in readme.frontmatter.get("contents", [])]
        assert "old.jsonl" not in paths
        assert "new.jsonl" in paths

    def test_until_excludes_future(self, tmp_path):
        """--until 2024 should exclude records from 2025."""
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"timestamp": "2024-06-01", "content": "in"}\n'
            '{"timestamp": "2025-01-01", "content": "out"}\n'
        )
        db.import_jsonl(f, collection="data")
        out = tmp_path / "out"
        db.export(out, until="2024")
        db.close()
        lines = (out / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1

    def test_slice_schema_reflects_filtered_data(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, since="2024-01-01")
        db.close()
        import yaml
        schema = yaml.safe_load((out / "schema.yaml").read_text())
        assert schema["data"]["record_count"] == 3


class TestNestedExport:
    def _make_db(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f1 = tmp_path / "convos.jsonl"
        f1.write_text('{"metadata": {"role": "user"}, "content": "hi"}\n')
        f2 = tmp_path / "books.jsonl"
        f2.write_text('{"metadata": {"title": "Moby Dick"}, "content": "Call me Ishmael"}\n')
        db.import_jsonl(f1, collection="convos")
        db.import_jsonl(f2, collection="books")
        return db

    def test_nested_creates_subdirectories(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()
        assert (out / "convos" / "convos.jsonl").exists()
        assert (out / "books" / "books.jsonl").exists()
        assert (out / "convos" / "README.md").exists()
        assert (out / "convos" / "schema.yaml").exists()

    def test_nested_top_readme_has_directory_contents(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()
        from arkiv.readme import parse_readme
        readme = parse_readme(out / "README.md")
        paths = [c["path"] for c in readme.frontmatter["contents"]]
        assert "convos/" in paths
        assert "books/" in paths

    def test_nested_per_collection_readme_has_detail_schema(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()
        readme_text = (out / "convos" / "README.md").read_text()
        assert "## Metadata Keys" in readme_text
        assert "role" in readme_text

    def test_nested_per_collection_schema_yaml_single_collection(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()
        import yaml
        schema = yaml.safe_load((out / "convos" / "schema.yaml").read_text())
        assert "convos" in schema
        assert "books" not in schema

    def test_nested_top_schema_yaml_has_all_collections(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()
        import yaml
        schema = yaml.safe_load((out / "schema.yaml").read_text())
        assert "convos" in schema
        assert "books" in schema

    def test_nested_per_collection_readme_frontmatter(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()
        from arkiv.readme import parse_readme
        readme = parse_readme(out / "convos" / "README.md")
        assert readme.frontmatter["name"] == "convos"
        assert readme.frontmatter["record_count"] == 1
        assert readme.frontmatter["arkiv_format"] == "0.2"
        assert readme.frontmatter["contents"] == [{"path": "convos.jsonl"}]

    def test_nested_collection_ordering_from_original(self, tmp_path):
        """Collections appear in order from original README contents."""
        from arkiv.readme import Readme
        db = self._make_db(tmp_path)
        readme = Readme(
            frontmatter={
                "name": "Test",
                "contents": [
                    {"path": "books.jsonl", "description": "Books"},
                    {"path": "convos.jsonl", "description": "Convos"},
                ],
            },
        )
        db._store_readme_metadata(readme)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()
        from arkiv.readme import parse_readme
        top = parse_readme(out / "README.md")
        paths = [c["path"] for c in top.frontmatter["contents"]]
        assert paths.index("books/") < paths.index("convos/")

    def test_nested_rejects_unsafe_collection_name(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection="../evil")
        with pytest.raises(ValueError, match="path separator"):
            db.export(tmp_path / "out", nested=True)
        db.close()

    def test_nested_rejects_dot_prefix_name(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection=".hidden")
        with pytest.raises(ValueError, match="dot"):
            db.export(tmp_path / "out", nested=True)
        db.close()

    def test_nested_composable_with_since(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"timestamp": "2023-01-01", "content": "old"}\n'
            '{"timestamp": "2024-06-01", "content": "new"}\n'
        )
        db.import_jsonl(f, collection="data")
        out = tmp_path / "out"
        db.export(out, nested=True, since="2024-01-01")
        db.close()
        lines = (out / "data" / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
