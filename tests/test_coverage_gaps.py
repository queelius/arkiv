"""Tests for coverage gaps and edge cases identified in regression analysis.

Covers uncovered lines and edge cases in:
- schema.py: _json_type, SchemaEntry.to_dict example, non-hashable values,
  load_schema_yaml edge cases, merge_schema edge cases
- database.py: export with no _metadata, query OperationalError path
- readme.py: non-dict frontmatter
- cli.py: _require_jsonl, detect curated values, fix blank/non-dict lines,
  unknown field without suggestion, non-JSON-object lines
- readme_import: README with no contents key, schema.yaml references
  collection not in data
"""

import json
import subprocess
import sys

import pytest

from arkiv.schema import (
    SchemaEntry,
    CollectionSchema,
    _json_type,
    discover_schema,
    load_schema_yaml,
    save_schema_yaml,
    merge_schema,
)
from arkiv.database import Database
from arkiv.readme import Readme, parse_readme, save_readme


# ---------------------------------------------------------------------------
# schema.py coverage gaps
# ---------------------------------------------------------------------------


class TestJsonType:
    """Covers schema.py _json_type for dict, None fallback."""

    def test_dict_type(self):
        assert _json_type({"a": 1}) == "object"

    def test_none_type_falls_back_to_string(self):
        assert _json_type(None) == "string"

    def test_bool_detected_before_int(self):
        """bool is a subclass of int; must detect boolean first."""
        assert _json_type(True) == "boolean"
        assert _json_type(False) == "boolean"

    def test_list_type(self):
        assert _json_type([1, 2, 3]) == "array"


class TestSchemaEntryToDictExample:
    """Covers SchemaEntry.to_dict example field."""

    def test_example_included_in_to_dict(self):
        e = SchemaEntry(type="string", count=100, example="hello")
        d = e.to_dict()
        assert d["example"] == "hello"

    def test_example_excluded_when_none(self):
        e = SchemaEntry(type="string", count=100)
        d = e.to_dict()
        assert "example" not in d


class TestDiscoverSchemaNonHashable:
    """Covers non-hashable metadata values (the critical bug fix)."""

    def test_dict_values_force_example_fallback(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"metadata": {"nested": {"a": 1}}}\n'
            '{"metadata": {"nested": {"b": 2}}}\n'
        )
        schema = discover_schema(f)
        assert schema["nested"].type == "object"
        assert schema["nested"].values is None
        assert schema["nested"].example is not None

    def test_unhashable_then_hashable_does_not_crash(self, tmp_path):
        """First record unhashable, second hashable -- must not crash."""
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"metadata": {"x": ["complex"]}}\n'
            '{"metadata": {"x": "simple"}}\n'
        )
        schema = discover_schema(f)
        # Once set to None, stays None (high cardinality)
        assert schema["x"].values is None
        assert schema["x"].example == ["complex"]

    def test_hashable_then_unhashable_forces_example(self, tmp_path):
        """First record hashable, second unhashable."""
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"metadata": {"x": "simple"}}\n'
            '{"metadata": {"x": ["complex"]}}\n'
        )
        schema = discover_schema(f)
        assert schema["x"].values is None
        assert schema["x"].example is not None


class TestLoadSchemaYamlEdgeCases:
    """Covers schema.yaml parsing edge cases."""

    def test_non_dict_collection_skipped(self, tmp_path):
        path = tmp_path / "schema.yaml"
        path.write_text("bad_collection: not_a_dict\n")
        result = load_schema_yaml(path)
        assert "bad_collection" not in result

    def test_non_dict_key_data_skipped(self, tmp_path):
        path = tmp_path / "schema.yaml"
        path.write_text(
            "coll:\n  record_count: 1\n  metadata_keys:\n    bad_key: not_a_dict\n"
        )
        result = load_schema_yaml(path)
        assert "bad_key" not in result["coll"].metadata_keys

    def test_non_dict_root_returns_empty(self, tmp_path):
        path = tmp_path / "schema.yaml"
        path.write_text("- a list\n- not a dict\n")
        result = load_schema_yaml(path)
        assert result == {}

    def test_missing_type_defaults_to_string(self, tmp_path):
        path = tmp_path / "schema.yaml"
        path.write_text(
            "coll:\n  record_count: 1\n  metadata_keys:\n"
            "    noType:\n      count: 5\n      description: No type given\n"
        )
        result = load_schema_yaml(path)
        assert result["coll"].metadata_keys["noType"].type == "string"


class TestMergeSchemaEdgeCases:
    def test_curated_only_with_none_type_defaults_to_string(self):
        """Curated key with type=None gets default 'string'."""
        curated = {
            "orphan": SchemaEntry(
                type=None, count=5, description="Key with no type"
            )
        }
        result = merge_schema({}, curated)
        assert result["orphan"].type == "string"
        assert result["orphan"].count == 0
        assert result["orphan"].description == "Key with no type"

    def test_auto_keys_passed_through_when_no_curated(self):
        auto = {
            "a": SchemaEntry(type="string", count=10, values=["x"]),
            "b": SchemaEntry(type="number", count=5),
        }
        result = merge_schema(auto, {})
        assert result["a"] is auto["a"]
        assert result["b"] is auto["b"]


# ---------------------------------------------------------------------------
# readme.py coverage gaps
# ---------------------------------------------------------------------------


class TestReadmeNonDictFrontmatter:
    """Covers non-dict frontmatter treated as empty dict."""

    def test_non_dict_frontmatter_becomes_empty(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("---\njust a string\n---\nBody here\n")
        readme = parse_readme(f)
        assert readme.frontmatter == {}
        assert "Body here" in readme.body


# ---------------------------------------------------------------------------
# database.py coverage gaps
# ---------------------------------------------------------------------------


class TestExportWithNoMetadata:
    """Covers export when _metadata table is empty."""

    def test_export_without_readme_metadata(self, tmp_path):
        """Bare JSONL import has no _metadata; export should still work."""
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="test")

        out = tmp_path / "exported"
        db.export(out)
        db.close()

        assert (out / "README.md").exists()
        assert (out / "schema.yaml").exists()
        assert (out / "test.jsonl").exists()

        readme = parse_readme(out / "README.md")
        assert len(readme.frontmatter.get("contents", [])) == 1
        assert readme.frontmatter["contents"][0]["path"] == "test.jsonl"


class TestQueryOperationalError:
    """Covers OperationalError -> ValueError wrapping."""

    def test_invalid_column_raises_value_error(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="test")

        with pytest.raises(ValueError):
            db.query("SELECT nonexistent_column FROM records")
        db.close()

    def test_bad_table_raises_value_error(self, tmp_path):
        db = Database(tmp_path / "test.db")
        with pytest.raises(ValueError):
            db.query("SELECT * FROM nonexistent_table")
        db.close()


class TestSaveSchemaEntries:
    """Covers the extracted _save_schema_entries helper."""

    def test_replaces_existing_entries(self, tmp_path):
        db = Database(tmp_path / "test.db")
        entries_v1 = {"key1": SchemaEntry(type="string", count=5, values=["a", "b"])}
        db._save_schema_entries("coll", entries_v1)

        entries_v2 = {"key2": SchemaEntry(type="number", count=10, description="new key")}
        db._save_schema_entries("coll", entries_v2)

        schema = db.get_schema("coll")
        assert "key1" not in schema["metadata_keys"]
        assert "key2" in schema["metadata_keys"]
        assert schema["metadata_keys"]["key2"]["description"] == "new key"
        db.close()

    def test_handles_empty_entries(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db._save_schema_entries("coll", {})
        schema = db.get_schema("coll")
        assert schema["metadata_keys"] == {}
        db.close()


# ---------------------------------------------------------------------------
# database.py: import_readme edge cases
# ---------------------------------------------------------------------------


class TestImportReadmeEdgeCases:
    def test_readme_with_no_contents_key(self, tmp_path):
        """README.md with frontmatter but no 'contents' key imports 0 records."""
        (tmp_path / "README.md").write_text(
            "---\nname: Empty archive\ndescription: No contents listed\n---\n# Empty\n"
        )
        db = Database(tmp_path / "test.db")
        count = db.import_readme(tmp_path / "README.md")
        assert count == 0

        loaded = db._load_readme_metadata()
        assert loaded.frontmatter["name"] == "Empty archive"
        db.close()

    def test_readme_with_non_dict_contents_items(self, tmp_path):
        """Contents items that are not dicts or lack 'path' are skipped."""
        (tmp_path / "data.jsonl").write_text('{"content": "hello"}\n')
        (tmp_path / "README.md").write_text(
            "---\ncontents:\n- just a string\n- path: data.jsonl\n- 42\n---\n"
        )
        db = Database(tmp_path / "test.db")
        count = db.import_readme(tmp_path / "README.md")
        assert count == 1
        db.close()

    def test_schema_yaml_references_collection_not_in_data(self, tmp_path):
        """schema.yaml with a collection not in README contents still merges."""
        (tmp_path / "data.jsonl").write_text(
            '{"metadata": {"role": "user"}}\n'
        )
        (tmp_path / "README.md").write_text(
            "---\ncontents:\n- path: data.jsonl\n---\n"
        )
        (tmp_path / "schema.yaml").write_text(
            "data:\n  record_count: 1\n  metadata_keys:\n"
            "    role:\n      type: string\n      count: 1\n"
            "      description: Speaker identity\n"
            "other:\n  record_count: 0\n  metadata_keys:\n"
            "    orphan_key:\n      type: string\n      count: 0\n"
            "      description: Key for missing collection\n"
        )
        db = Database(tmp_path / "test.db")
        db.import_readme(tmp_path / "README.md")

        schema = db.get_schema("data")
        assert schema["metadata_keys"]["role"]["description"] == "Speaker identity"

        schema_other = db.get_schema("other")
        assert "orphan_key" in schema_other["metadata_keys"]
        assert schema_other["metadata_keys"]["orphan_key"]["count"] == 0
        db.close()


# ---------------------------------------------------------------------------
# cli.py coverage gaps (via subprocess)
# ---------------------------------------------------------------------------


def run_arkiv(*args):
    result = subprocess.run(
        [sys.executable, "-m", "arkiv.cli", *args],
        capture_output=True,
        text=True,
    )
    return result


class TestCLIRequireJsonl:
    """Covers _require_jsonl guard."""

    def test_detect_rejects_db_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")
        result = run_arkiv("detect", str(db_path))
        assert result.returncode == 1
        assert "database" in result.stderr.lower()

    def test_fix_rejects_db_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"")
        result = run_arkiv("fix", str(db_path))
        assert result.returncode == 1
        assert "database" in result.stderr.lower()


class TestCLIDetectEdgeCases:
    def test_detect_non_json_object_line(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('[1, 2, 3]\n{"content": "ok"}\n')
        result = run_arkiv("detect", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valid_jsonl"] is False
        assert data["total_records"] == 1

    def test_detect_unknown_field_without_suggestion(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hi", "totally_custom": "val"}\n')
        result = run_arkiv("detect", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "totally_custom" in data["unknown_fields"]
        assert any(
            "totally_custom" in w and "metadata" in w for w in data["warnings"]
        )

    def test_detect_schema_curated_values_not_in_data(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n')
        schema_yaml = (
            "test:\n  record_count: 1\n  metadata_keys:\n"
            "    role:\n      type: string\n      count: 1\n"
            "      values: [user, assistant, system]\n"
        )
        (tmp_path / "schema.yaml").write_text(schema_yaml)

        result = run_arkiv("detect", str(f))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        schema_info = data.get("schema_info", [])
        assert any("Curated values" in s for s in schema_info)


class TestCLIFixEdgeCases:
    def test_fix_preserves_blank_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"url": "https://example.com"}\n\n{"content": "ok"}\n')
        result = run_arkiv("fix", str(f))
        assert result.returncode == 0
        lines = f.read_text().split("\n")
        assert "" in lines

    def test_fix_preserves_invalid_json_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('not valid json\n{"url": "https://example.com"}\n')
        result = run_arkiv("fix", str(f))
        assert result.returncode == 0
        lines = f.read_text().strip().split("\n")
        assert lines[0] == "not valid json"
        obj = json.loads(lines[1])
        assert "uri" in obj

    def test_fix_preserves_non_dict_json_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('[1, 2, 3]\n{"url": "https://example.com"}\n')
        result = run_arkiv("fix", str(f))
        assert result.returncode == 0
        lines = f.read_text().strip().split("\n")
        assert lines[0] == "[1, 2, 3]"


class TestCLINoCommandExits:
    def test_no_command_exits_1(self):
        result = run_arkiv()
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# server.py edge cases
# ---------------------------------------------------------------------------


class TestServerManifestWithoutReadme:
    """Covers get_manifest when no README data is stored."""

    def test_manifest_without_readme_has_collections(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello", "metadata": {"role": "user"}}\n')
        from arkiv.server import ArkivServer

        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="data")
        db.close()

        srv = ArkivServer(db_path=tmp_path / "test.db")
        result = srv.get_manifest()
        assert "name" not in result
        assert "description" not in result
        assert len(result["collections"]) == 1
        assert result["collections"][0]["file"] == "data.jsonl"
        assert result["collections"][0]["record_count"] == 1
        srv.close()
