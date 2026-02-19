"""Tests for arkiv.schema."""

import json
import pytest
from arkiv.schema import (
    discover_schema,
    SchemaEntry,
    CollectionSchema,
    load_schema_yaml,
    save_schema_yaml,
    merge_schema,
)


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


class TestSchemaEntryDescription:
    def test_description_default_none(self):
        e = SchemaEntry(type="string", count=1)
        assert e.description is None

    def test_description_in_to_dict(self):
        e = SchemaEntry(type="string", count=1, description="Speaker identity")
        d = e.to_dict()
        assert d["description"] == "Speaker identity"

    def test_description_excluded_when_none(self):
        e = SchemaEntry(type="string", count=1)
        d = e.to_dict()
        assert "description" not in d


class TestCollectionSchema:
    def test_default(self):
        cs = CollectionSchema()
        assert cs.record_count == 0
        assert cs.metadata_keys == {}

    def test_with_data(self):
        cs = CollectionSchema(
            record_count=100,
            metadata_keys={
                "role": SchemaEntry(type="string", count=100, values=["user", "assistant"])
            },
        )
        assert cs.record_count == 100
        assert cs.metadata_keys["role"].count == 100


class TestSchemaYamlIO:
    def test_save_and_load_roundtrip(self, tmp_path):
        schemas = {
            "conversations": CollectionSchema(
                record_count=150,
                metadata_keys={
                    "role": SchemaEntry(
                        type="string",
                        count=150,
                        values=["user", "assistant"],
                        description="Speaker identity",
                    ),
                    "source": SchemaEntry(
                        type="string",
                        count=150,
                        values=["chatgpt", "claude"],
                    ),
                },
            ),
        }
        path = tmp_path / "schema.yaml"
        save_schema_yaml(schemas, path)
        loaded = load_schema_yaml(path)

        assert "conversations" in loaded
        cs = loaded["conversations"]
        assert cs.record_count == 150
        assert cs.metadata_keys["role"].description == "Speaker identity"
        assert cs.metadata_keys["role"].type == "string"
        assert cs.metadata_keys["role"].values == ["user", "assistant"]
        assert cs.metadata_keys["source"].description is None

    def test_save_includes_header_comment(self, tmp_path):
        schemas = {"test": CollectionSchema(record_count=1)}
        path = tmp_path / "schema.yaml"
        save_schema_yaml(schemas, path)
        text = path.read_text()
        assert text.startswith("# Auto-generated by arkiv")

    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "schema.yaml"
        path.write_text("")
        result = load_schema_yaml(path)
        assert result == {}

    def test_load_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_schema_yaml(tmp_path / "nope.yaml")

    def test_description_preserved_in_yaml(self, tmp_path):
        schemas = {
            "data": CollectionSchema(
                record_count=10,
                metadata_keys={
                    "lang": SchemaEntry(
                        type="string",
                        count=10,
                        description="Language code",
                    ),
                },
            ),
        }
        path = tmp_path / "schema.yaml"
        save_schema_yaml(schemas, path)
        text = path.read_text()
        assert "description: Language code" in text

        loaded = load_schema_yaml(path)
        assert loaded["data"].metadata_keys["lang"].description == "Language code"

    def test_multiple_collections(self, tmp_path):
        schemas = {
            "convos": CollectionSchema(record_count=10),
            "bookmarks": CollectionSchema(record_count=5),
        }
        path = tmp_path / "schema.yaml"
        save_schema_yaml(schemas, path)
        loaded = load_schema_yaml(path)
        assert "convos" in loaded
        assert "bookmarks" in loaded


class TestMergeSchema:
    def test_auto_only(self):
        auto = {"role": SchemaEntry(type="string", count=100, values=["user"])}
        result = merge_schema(auto, {})
        assert result["role"].type == "string"
        assert result["role"].count == 100

    def test_curated_description_applied(self):
        auto = {"role": SchemaEntry(type="string", count=100)}
        curated = {
            "role": SchemaEntry(
                type="string", count=0, description="Speaker identity"
            )
        }
        result = merge_schema(auto, curated)
        assert result["role"].description == "Speaker identity"
        # Live fields from auto
        assert result["role"].count == 100
        assert result["role"].type == "string"

    def test_curated_values_override_auto(self):
        auto = {
            "role": SchemaEntry(
                type="string", count=100, values=["user", "assistant", "system"]
            )
        }
        curated = {
            "role": SchemaEntry(
                type="string", count=0, values=["user", "assistant"]
            )
        }
        result = merge_schema(auto, curated)
        # Curated values take precedence
        assert result["role"].values == ["user", "assistant"]

    def test_auto_values_used_when_curated_has_none(self):
        auto = {"role": SchemaEntry(type="string", count=100, values=["user"])}
        curated = {
            "role": SchemaEntry(type="string", count=0, description="Speaker")
        }
        result = merge_schema(auto, curated)
        assert result["role"].values == ["user"]

    def test_curated_only_keys_preserved(self):
        auto = {"role": SchemaEntry(type="string", count=100)}
        curated = {
            "old_key": SchemaEntry(
                type="string", count=50, description="Deprecated key"
            )
        }
        result = merge_schema(auto, curated)
        assert "old_key" in result
        assert result["old_key"].count == 0
        assert result["old_key"].description == "Deprecated key"

    def test_merge_empty(self):
        result = merge_schema({}, {})
        assert result == {}
