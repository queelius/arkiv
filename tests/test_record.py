"""Tests for arkiv.record."""

import json
import pytest
from arkiv.record import Record, parse_record, parse_jsonl


class TestRecord:
    def test_full_record(self):
        r = Record(
            mimetype="text/plain",
            uri="https://example.com",
            content="hello",
            timestamp="2024-01-15T10:00:00Z",
            metadata={"role": "user"},
        )
        assert r.mimetype == "text/plain"
        assert r.uri == "https://example.com"
        assert r.content == "hello"
        assert r.timestamp == "2024-01-15T10:00:00Z"
        assert r.metadata == {"role": "user"}

    def test_empty_record(self):
        r = Record()
        assert r.mimetype is None
        assert r.uri is None
        assert r.content is None
        assert r.timestamp is None
        assert r.metadata is None

    def test_content_only(self):
        r = Record(content="Trust the future.")
        assert r.content == "Trust the future."
        assert r.mimetype is None

    def test_metadata_only(self):
        r = Record(metadata={"relationship": "married"})
        assert r.metadata == {"relationship": "married"}

    def test_to_dict_excludes_none(self):
        r = Record(content="hello", mimetype="text/plain")
        d = r.to_dict()
        assert d == {"mimetype": "text/plain", "content": "hello"}
        assert "uri" not in d
        assert "metadata" not in d

    def test_to_dict_full(self):
        r = Record(
            mimetype="text/plain",
            content="hello",
            uri="file://test.txt",
            timestamp="2024-01-15",
            metadata={"key": "val"},
        )
        d = r.to_dict()
        assert len(d) == 5

    def test_to_json(self):
        r = Record(content="hello")
        line = r.to_json()
        parsed = json.loads(line)
        assert parsed == {"content": "hello"}

    def test_empty_record_to_dict(self):
        r = Record()
        assert r.to_dict() == {}


class TestParseRecord:
    def test_parse_full(self):
        data = {
            "mimetype": "text/plain",
            "content": "hello",
            "uri": "https://example.com",
            "timestamp": "2024-01-15",
            "metadata": {"role": "user"},
        }
        r = parse_record(data)
        assert r.mimetype == "text/plain"
        assert r.content == "hello"
        assert r.metadata == {"role": "user"}

    def test_parse_empty(self):
        r = parse_record({})
        assert r.mimetype is None

    def test_parse_unknown_fields_go_to_metadata(self):
        data = {"content": "hello", "custom_field": "value", "another": 42}
        r = parse_record(data)
        assert r.content == "hello"
        assert r.metadata["custom_field"] == "value"
        assert r.metadata["another"] == 42

    def test_parse_json_string(self):
        line = '{"content": "hello", "mimetype": "text/plain"}'
        r = parse_record(json.loads(line))
        assert r.content == "hello"


class TestParseJsonl:
    def test_parse_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"content": "one"}\n'
            '{"content": "two"}\n'
            '{"content": "three"}\n'
        )
        records = list(parse_jsonl(f))
        assert len(records) == 3
        assert records[0].content == "one"
        assert records[2].content == "three"

    def test_skip_blank_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "one"}\n\n{"content": "two"}\n')
        records = list(parse_jsonl(f))
        assert len(records) == 2

    def test_skip_invalid_json(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "one"}\nnot json\n{"content": "two"}\n')
        records = list(parse_jsonl(f))
        assert len(records) == 2
