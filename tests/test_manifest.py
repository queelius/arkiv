"""Tests for arkiv.manifest."""

import json
import pytest
from arkiv.manifest import Manifest, Collection, load_manifest, save_manifest


class TestManifest:
    def test_empty_manifest(self):
        m = Manifest()
        assert m.collections == []

    def test_manifest_with_collections(self):
        c = Collection(file="test.jsonl", description="Test data", record_count=100)
        m = Manifest(description="My archive", collections=[c])
        assert len(m.collections) == 1
        assert m.collections[0].file == "test.jsonl"

    def test_to_dict(self):
        m = Manifest(description="My archive", collections=[])
        d = m.to_dict()
        assert d["description"] == "My archive"
        assert d["collections"] == []

    def test_collection_with_schema(self):
        c = Collection(
            file="test.jsonl",
            record_count=5,
            schema={"metadata_keys": {"role": {"type": "string", "count": 5}}},
        )
        d = c.to_dict()
        assert d["schema"]["metadata_keys"]["role"]["type"] == "string"


class TestLoadSaveManifest:
    def test_save_and_load(self, tmp_path):
        m = Manifest(
            description="Test",
            collections=[
                Collection(file="data.jsonl", description="Data", record_count=10)
            ],
        )
        save_manifest(m, tmp_path / "manifest.json")
        loaded = load_manifest(tmp_path / "manifest.json")
        assert loaded.description == "Test"
        assert len(loaded.collections) == 1
        assert loaded.collections[0].file == "data.jsonl"
        assert loaded.collections[0].record_count == 10

    def test_load_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path / "nope.json")

    def test_roundtrip_preserves_metadata(self, tmp_path):
        m = Manifest(
            description="Test",
            metadata={"author": "Alex", "version": "1.0"},
            collections=[],
        )
        save_manifest(m, tmp_path / "manifest.json")
        loaded = load_manifest(tmp_path / "manifest.json")
        assert loaded.metadata["author"] == "Alex"
