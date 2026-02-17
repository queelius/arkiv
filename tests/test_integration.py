"""End-to-end integration test."""

import json
import pytest
from arkiv import (
    Database,
    Manifest,
    Collection,
    save_manifest,
    load_manifest,
    parse_jsonl,
)


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        """JSONL -> import -> query -> export -> verify roundtrip."""
        # 1. Create JSONL files
        convos = tmp_path / "conversations.jsonl"
        convos.write_text(
            '{"mimetype": "text/plain", "content": "I think category theory is beautiful", "timestamp": "2023-05-14", "metadata": {"role": "user", "source": "chatgpt"}}\n'
            '{"mimetype": "text/plain", "content": "That is an interesting perspective", "timestamp": "2023-05-14", "metadata": {"role": "assistant", "source": "chatgpt"}}\n'
        )

        bookmarks = tmp_path / "bookmarks.jsonl"
        bookmarks.write_text(
            '{"mimetype": "application/json", "url": "https://arxiv.org/abs/2301.00001", "metadata": {"annotation": "Great paper", "tags": ["math"]}}\n'
        )

        # 2. Create manifest
        m = Manifest(
            description="Test archive",
            collections=[
                Collection(
                    file="conversations.jsonl", description="AI convos"
                ),
                Collection(
                    file="bookmarks.jsonl", description="Saved links"
                ),
            ],
        )
        save_manifest(m, tmp_path / "manifest.json")

        # 3. Import
        db = Database(tmp_path / "archive.db")
        db.import_manifest(tmp_path / "manifest.json")

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

        # 7. Verify roundtrip
        exported_manifest = load_manifest(out / "manifest.json")
        assert len(exported_manifest.collections) == 2

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
            Manifest,
            Collection,
            load_manifest,
            save_manifest,
            Database,
        )

        # Smoke test: create a record via public API
        r = Record(content="hello", mimetype="text/plain")
        assert r.to_dict() == {"mimetype": "text/plain", "content": "hello"}
