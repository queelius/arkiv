"""Tests for importing via README.md."""

import json
import pytest
from arkiv.database import Database
from arkiv.readme import Readme, save_readme


class TestReadmeImport:
    def test_import_from_readme(self, tmp_path):
        # Create JSONL files
        (tmp_path / "a.jsonl").write_text('{"content": "from a"}\n')
        (tmp_path / "b.jsonl").write_text('{"content": "from b"}\n')

        # Create README.md
        readme = Readme(
            frontmatter={
                "name": "Test archive",
                "contents": [
                    {"path": "a.jsonl"},
                    {"path": "b.jsonl"},
                ],
            },
        )
        save_readme(readme, tmp_path / "README.md")

        # Import
        db = Database(tmp_path / "test.db")
        db.import_readme(tmp_path / "README.md")

        info = db.get_info()
        assert info["total_records"] == 2
        assert "a" in info["collections"]
        assert "b" in info["collections"]
        db.close()

    def test_import_readme_resolves_relative_paths(self, tmp_path):
        subdir = tmp_path / "data"
        subdir.mkdir()
        (subdir / "test.jsonl").write_text('{"content": "hello"}\n')
        readme = Readme(
            frontmatter={"contents": [{"path": "test.jsonl"}]},
        )
        save_readme(readme, subdir / "README.md")

        db = Database(tmp_path / "test.db")
        db.import_readme(subdir / "README.md")

        results = db.query("SELECT content FROM records")
        assert results[0]["content"] == "hello"
        db.close()

    def test_import_readme_stores_frontmatter(self, tmp_path):
        (tmp_path / "data.jsonl").write_text('{"content": "hello"}\n')
        readme = Readme(
            frontmatter={
                "name": "My Archive",
                "description": "Personal data",
                "datetime": "2024-06-15",
                "contents": [{"path": "data.jsonl", "description": "Test data"}],
            },
            body="# My Archive\n\nDetails here.\n",
        )
        save_readme(readme, tmp_path / "README.md")

        db = Database(tmp_path / "test.db")
        db.import_readme(tmp_path / "README.md")

        loaded = db._load_readme_metadata()
        assert loaded.frontmatter["name"] == "My Archive"
        assert loaded.frontmatter["description"] == "Personal data"
        assert "# My Archive" in loaded.body
        db.close()

    def test_import_readme_with_schema_yaml(self, tmp_path):
        (tmp_path / "convos.jsonl").write_text(
            '{"metadata": {"role": "user"}}\n'
            '{"metadata": {"role": "assistant"}}\n'
        )
        readme = Readme(
            frontmatter={"contents": [{"path": "convos.jsonl"}]},
        )
        save_readme(readme, tmp_path / "README.md")

        schema_yaml = (
            "convos:\n  record_count: 2\n  metadata_keys:\n"
            "    role:\n      description: Speaker identity\n"
            "      type: string\n      count: 2\n"
            "      values: [user, assistant]\n"
        )
        (tmp_path / "schema.yaml").write_text(schema_yaml)

        db = Database(tmp_path / "test.db")
        db.import_readme(tmp_path / "README.md")

        schema = db.get_schema("convos")
        assert schema["metadata_keys"]["role"]["description"] == "Speaker identity"
        db.close()

    def test_import_readme_skips_missing_files(self, tmp_path):
        readme = Readme(
            frontmatter={
                "contents": [
                    {"path": "exists.jsonl"},
                    {"path": "missing.jsonl"},
                ],
            },
        )
        (tmp_path / "exists.jsonl").write_text('{"content": "hello"}\n')
        save_readme(readme, tmp_path / "README.md")

        db = Database(tmp_path / "test.db")
        count = db.import_readme(tmp_path / "README.md")
        assert count == 1
        db.close()

    def test_roundtrip_readme_import_export(self, tmp_path):
        """Import README.md → export → README.md metadata survives."""
        (tmp_path / "data.jsonl").write_text(
            '{"content": "hello", "metadata": {"role": "user"}}\n'
        )
        readme = Readme(
            frontmatter={
                "name": "Test Archive",
                "description": "A test",
                "contents": [{"path": "data.jsonl", "description": "Test data"}],
            },
            body="# Test Archive\n",
        )
        save_readme(readme, tmp_path / "README.md")

        # Import
        db = Database(tmp_path / "test.db")
        db.import_readme(tmp_path / "README.md")

        # Export
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        from arkiv.readme import parse_readme

        exported_readme = parse_readme(out / "README.md")
        assert exported_readme.frontmatter["name"] == "Test Archive"
        assert exported_readme.frontmatter["description"] == "A test"
        assert "# Test Archive" in exported_readme.body

        # Content descriptions survive
        coll_by_path = {
            c["path"]: c for c in exported_readme.frontmatter.get("contents", [])
        }
        assert coll_by_path["data.jsonl"]["description"] == "Test data"
