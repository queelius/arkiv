"""Tests for arkiv.schema."""

import json
import pytest
from arkiv.schema import discover_schema, SchemaEntry


class TestDiscoverSchema:
    def test_simple_metadata(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"content": "a", "metadata": {"role": "user"}}\n'
            '{"content": "b", "metadata": {"role": "assistant"}}\n'
            '{"content": "c", "metadata": {"role": "user"}}\n'
        )
        schema = discover_schema(f)
        assert "role" in schema
        assert schema["role"].type == "string"
        assert schema["role"].count == 3
        assert set(schema["role"].values) == {"user", "assistant"}

    def test_mixed_types(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"metadata": {"count": 5}}\n' '{"metadata": {"count": 10}}\n'
        )
        schema = discover_schema(f)
        assert schema["count"].type == "number"
        assert schema["count"].count == 2

    def test_high_cardinality_uses_example(self, tmp_path):
        f = tmp_path / "test.jsonl"
        lines = [
            json.dumps({"metadata": {"id": f"id-{i}"}}) for i in range(30)
        ]
        f.write_text("\n".join(lines) + "\n")
        schema = discover_schema(f)
        assert schema["id"].values is None
        assert schema["id"].example is not None

    def test_array_type(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"tags": ["a", "b"]}}\n')
        schema = discover_schema(f)
        assert schema["tags"].type == "array"

    def test_boolean_type(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"active": true}}\n')
        schema = discover_schema(f)
        assert schema["active"].type == "boolean"

    def test_no_metadata(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        schema = discover_schema(f)
        assert schema == {}

    def test_empty_file(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("")
        schema = discover_schema(f)
        assert schema == {}

    def test_to_dict(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n')
        schema = discover_schema(f)
        d = schema["role"].to_dict()
        assert d["type"] == "string"
        assert d["count"] == 1
        assert d["values"] == ["user"]
