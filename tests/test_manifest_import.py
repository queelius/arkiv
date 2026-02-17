"""Tests for importing via manifest.json."""

import json
import pytest
from arkiv.database import Database
from arkiv.manifest import Manifest, Collection, save_manifest


class TestManifestImport:
    def test_import_from_manifest(self, tmp_path):
        # Create JSONL files
        (tmp_path / "a.jsonl").write_text('{"content": "from a"}\n')
        (tmp_path / "b.jsonl").write_text('{"content": "from b"}\n')

        # Create manifest
        m = Manifest(
            description="Test archive",
            collections=[
                Collection(file="a.jsonl"),
                Collection(file="b.jsonl"),
            ],
        )
        save_manifest(m, tmp_path / "manifest.json")

        # Import
        db = Database(tmp_path / "test.db")
        db.import_manifest(tmp_path / "manifest.json")

        info = db.get_info()
        assert info["total_records"] == 2
        assert "a" in info["collections"]
        assert "b" in info["collections"]
        db.close()

    def test_import_manifest_resolves_relative_paths(self, tmp_path):
        subdir = tmp_path / "data"
        subdir.mkdir()
        (subdir / "test.jsonl").write_text('{"content": "hello"}\n')
        m = Manifest(collections=[Collection(file="test.jsonl")])
        save_manifest(m, subdir / "manifest.json")

        db = Database(tmp_path / "test.db")
        db.import_manifest(subdir / "manifest.json")

        results = db.query("SELECT content FROM records")
        assert results[0]["content"] == "hello"
        db.close()
