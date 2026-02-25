"""End-to-end integration test."""

import json
import pytest
from arkiv import (
    Database,
    Readme,
    parse_readme,
    save_readme,
    parse_jsonl,
)
from arkiv.schema import load_schema_yaml


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        """JSONL -> import via README.md -> query -> export -> verify roundtrip."""
        # 1. Create JSONL files
        convos = tmp_path / "conversations.jsonl"
        convos.write_text(
            '{"mimetype": "text/plain", "content": "I think category theory is beautiful", "timestamp": "2023-05-14", "metadata": {"role": "user", "source": "chatgpt"}}\n'
            '{"mimetype": "text/plain", "content": "That is an interesting perspective", "timestamp": "2023-05-14", "metadata": {"role": "assistant", "source": "chatgpt"}}\n'
        )

        bookmarks = tmp_path / "bookmarks.jsonl"
        bookmarks.write_text(
            '{"mimetype": "application/json", "uri": "https://arxiv.org/abs/2301.00001", "metadata": {"annotation": "Great paper", "tags": ["math"]}}\n'
        )

        # 2. Create README.md
        readme = Readme(
            frontmatter={
                "name": "Test archive",
                "description": "Test archive",
                "contents": [
                    {"path": "conversations.jsonl", "description": "AI convos"},
                    {"path": "bookmarks.jsonl", "description": "Saved links"},
                ],
            },
            body="# Test archive\n\nPersonal data.\n",
        )
        save_readme(readme, tmp_path / "README.md")

        # 3. Import
        db = Database(tmp_path / "archive.db")
        db.import_readme(tmp_path / "README.md")

        # 4. Query
        info = db.get_info()
        assert info["total_records"] == 3

        user_msgs = db.query(
            "SELECT content FROM records WHERE json_extract(metadata, '$.role') = 'user'"
        )
        assert len(user_msgs) == 1
        assert "category theory" in user_msgs[0]["content"]

        # 5. Schema discovery
        schema = db.get_schema("conversations")
        assert "role" in schema["metadata_keys"]

        # 6. Export
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        # 7. Verify roundtrip — README.md
        exported_readme = parse_readme(out / "README.md")
        assert exported_readme.frontmatter["name"] == "Test archive"
        contents = exported_readme.frontmatter.get("contents", [])
        assert len(contents) == 2

        # 7a. Verify content descriptions survived
        coll_by_path = {c["path"]: c for c in contents}
        assert coll_by_path["conversations.jsonl"]["description"] == "AI convos"
        assert coll_by_path["bookmarks.jsonl"]["description"] == "Saved links"

        # 7b. Verify schema.yaml
        schemas = load_schema_yaml(out / "schema.yaml")
        assert "conversations" in schemas
        assert "role" in schemas["conversations"].metadata_keys

        # 7c. Verify JSONL content
        exported_convos = list(parse_jsonl(out / "conversations.jsonl"))
        assert len(exported_convos) == 2
        assert (
            exported_convos[0].content
            == "I think category theory is beautiful"
        )

    def test_public_api_imports(self):
        """Verify all public API symbols are importable."""
        from arkiv import (
            Record,
            parse_record,
            parse_jsonl,
            SchemaEntry,
            discover_schema,
            Readme,
            parse_readme,
            save_readme,
            CollectionSchema,
            load_schema_yaml,
            save_schema_yaml,
            Database,
        )

        # Smoke test: create a record via public API
        r = Record(content="hello", mimetype="text/plain")
        assert r.to_dict() == {"mimetype": "text/plain", "content": "hello"}
