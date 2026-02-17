# arkiv Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement arkiv -- universal personal data format with JSONL storage, SQLite query layer, and MCP server.

**Architecture:** JSONL files are the canonical source of truth. A `Database` class imports JSONL → SQLite with schema pre-computation. A `Manifest` class reads/writes manifest.json. The CLI exposes import, export, schema, query, info, serve. The MCP server exposes 3 tools: get_manifest, get_schema, sql_query. All stdlib except MCP SDK.

**Tech Stack:** Python 3.8+, sqlite3 (stdlib), json (stdlib), argparse (stdlib), mcp Python SDK

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/arkiv/__init__.py`
- Create: `.gitignore`
- Create: `.coveragerc`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "arkiv"
version = "0.1.0"
description = "Universal personal data format. JSONL in, SQL out, MCP to LLMs."
requires-python = ">=3.8"
license = {text = "MIT"}
dependencies = []

[project.optional-dependencies]
mcp = ["mcp[cli]"]
dev = [
    "pytest",
    "pytest-cov",
    "black",
    "flake8",
    "mypy",
    "mcp[cli]",
]

[project.scripts]
arkiv = "arkiv.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.8"
warn_return_any = true
warn_unused_configs = true

[tool.black]
line-length = 88
target-version = ["py38"]
```

**Step 2: Create src/arkiv/__init__.py**

```python
"""arkiv: Universal personal data format."""

__version__ = "0.1.0"
```

**Step 3: Create .gitignore**

Standard Python .gitignore (pycache, dist, eggs, .coverage, venv, IDE files, *.db).

**Step 4: Create .coveragerc**

```ini
[run]
source = src/arkiv
omit = src/arkiv/__pycache__/*

[report]
exclude_lines =
    pragma: no cover
    if __name__ == .__main__
    if TYPE_CHECKING
show_missing = true
```

**Step 5: Create tests/__init__.py**

Empty file.

**Step 6: Install and verify**

Run: `pip install -e ".[dev]"`
Run: `python -c "import arkiv; print(arkiv.__version__)"`
Expected: `0.1.0`

**Step 7: Commit**

```bash
git add pyproject.toml src/ tests/__init__.py .gitignore .coveragerc
git commit -m "Project scaffolding"
```

---

### Task 2: Record Model

**Files:**
- Create: `src/arkiv/record.py`
- Create: `tests/test_record.py`

**Step 1: Write failing tests**

```python
"""Tests for arkiv.record."""

import json
import pytest
from arkiv.record import Record, parse_record, parse_jsonl


class TestRecord:
    def test_full_record(self):
        r = Record(
            mimetype="text/plain",
            url="https://example.com",
            content="hello",
            timestamp="2024-01-15T10:00:00Z",
            metadata={"role": "user"},
        )
        assert r.mimetype == "text/plain"
        assert r.url == "https://example.com"
        assert r.content == "hello"
        assert r.timestamp == "2024-01-15T10:00:00Z"
        assert r.metadata == {"role": "user"}

    def test_empty_record(self):
        r = Record()
        assert r.mimetype is None
        assert r.url is None
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
        assert "url" not in d
        assert "metadata" not in d

    def test_to_dict_full(self):
        r = Record(
            mimetype="text/plain",
            content="hello",
            url="file://test.txt",
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
            "url": "https://example.com",
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_record.py -v`
Expected: FAIL (import error)

**Step 3: Implement Record**

```python
"""Universal record format."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union


KNOWN_FIELDS = {"mimetype", "url", "content", "timestamp", "metadata"}


@dataclass
class Record:
    """A single arkiv record.

    All fields optional. Any valid JSON object is a valid record.
    """

    mimetype: Optional[str] = None
    url: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict, excluding None fields."""
        d = {}
        if self.mimetype is not None:
            d["mimetype"] = self.mimetype
        if self.url is not None:
            d["url"] = self.url
        if self.content is not None:
            d["content"] = self.content
        if self.timestamp is not None:
            d["timestamp"] = self.timestamp
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


def parse_record(data: Dict[str, Any]) -> Record:
    """Parse a dict into a Record.

    Known fields (mimetype, url, content, timestamp, metadata) are
    extracted. Unknown fields are merged into metadata.
    """
    metadata = data.get("metadata")
    if metadata is not None:
        metadata = dict(metadata)
    else:
        metadata = None

    # Collect unknown fields into metadata
    unknown = {k: v for k, v in data.items() if k not in KNOWN_FIELDS}
    if unknown:
        if metadata is None:
            metadata = {}
        metadata.update(unknown)

    return Record(
        mimetype=data.get("mimetype"),
        url=data.get("url"),
        content=data.get("content"),
        timestamp=data.get("timestamp"),
        metadata=metadata if metadata else None,
    )


def parse_jsonl(path: Union[str, Path]) -> Iterator[Record]:
    """Parse a JSONL file, yielding Records.

    Skips blank lines and invalid JSON.
    """
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield parse_record(data)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_record.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/arkiv/record.py tests/test_record.py
git commit -m "Add Record model with JSONL parsing"
```

---

### Task 3: Schema Discovery

**Files:**
- Create: `src/arkiv/schema.py`
- Create: `tests/test_schema.py`

**Step 1: Write failing tests**

```python
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
            '{"metadata": {"count": 5}}\n'
            '{"metadata": {"count": 10}}\n'
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schema.py -v`
Expected: FAIL

**Step 3: Implement schema discovery**

```python
"""Schema discovery for JSONL metadata."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .record import parse_jsonl

MAX_ENUM_VALUES = 20


@dataclass
class SchemaEntry:
    """Discovered schema for a single metadata key."""

    type: str
    count: int
    values: Optional[List[Any]] = None
    example: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"type": self.type, "count": self.count}
        if self.values is not None:
            d["values"] = self.values
        if self.example is not None:
            d["example"] = self.example
        return d


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def discover_schema(path: Union[str, Path]) -> Dict[str, SchemaEntry]:
    """Scan a JSONL file and discover metadata key schemas."""
    key_counts: Dict[str, int] = {}
    key_types: Dict[str, str] = {}
    key_values: Dict[str, set] = {}
    key_example: Dict[str, Any] = {}

    for record in parse_jsonl(path):
        if not record.metadata:
            continue
        for key, value in record.metadata.items():
            key_counts[key] = key_counts.get(key, 0) + 1
            key_types[key] = _json_type(value)

            if key not in key_example:
                key_example[key] = value

            if key not in key_values:
                key_values[key] = set()
            try:
                if isinstance(value, (str, int, float, bool)):
                    key_values[key].add(value)
                else:
                    # Non-hashable types force high cardinality
                    key_values[key] = None
            except TypeError:
                key_values[key] = None

    result = {}
    for key in key_counts:
        values_set = key_values.get(key)
        if values_set is not None and len(values_set) <= MAX_ENUM_VALUES:
            entry = SchemaEntry(
                type=key_types[key],
                count=key_counts[key],
                values=sorted(str(v) for v in values_set) if all(isinstance(v, str) for v in values_set) else list(values_set),
            )
        else:
            entry = SchemaEntry(
                type=key_types[key],
                count=key_counts[key],
                example=key_example[key],
            )
        result[key] = entry

    return result
```

**Step 4: Run tests**

Run: `pytest tests/test_schema.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/arkiv/schema.py tests/test_schema.py
git commit -m "Add schema discovery for JSONL metadata"
```

---

### Task 4: Manifest Model

**Files:**
- Create: `src/arkiv/manifest.py`
- Create: `tests/test_manifest.py`

**Step 1: Write failing tests**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_manifest.py -v`
Expected: FAIL

**Step 3: Implement Manifest**

```python
"""Manifest for arkiv collections."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class Collection:
    """A single collection entry in a manifest."""

    file: str = ""
    description: Optional[str] = None
    record_count: Optional[int] = None
    schema: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"file": self.file}
        if self.description is not None:
            d["description"] = self.description
        if self.record_count is not None:
            d["record_count"] = self.record_count
        if self.schema is not None:
            d["schema"] = self.schema
        return d


@dataclass
class Manifest:
    """Describes a collection of JSONL files."""

    description: Optional[str] = None
    created: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    collections: List[Collection] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {}
        if self.description is not None:
            d["description"] = self.description
        if self.created is not None:
            d["created"] = self.created
        if self.metadata is not None:
            d["metadata"] = self.metadata
        d["collections"] = [c.to_dict() for c in self.collections]
        return d


def save_manifest(manifest: Manifest, path: Union[str, Path]) -> None:
    """Write manifest to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)


def load_manifest(path: Union[str, Path]) -> Manifest:
    """Load manifest from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    collections = []
    for c in data.get("collections", []):
        collections.append(
            Collection(
                file=c.get("file", ""),
                description=c.get("description"),
                record_count=c.get("record_count"),
                schema=c.get("schema"),
            )
        )

    return Manifest(
        description=data.get("description"),
        created=data.get("created"),
        metadata=data.get("metadata"),
        collections=collections,
    )
```

**Step 4: Run tests**

Run: `pytest tests/test_manifest.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/arkiv/manifest.py tests/test_manifest.py
git commit -m "Add Manifest model with load/save"
```

---

### Task 5: SQLite Database (Import)

**Files:**
- Create: `src/arkiv/database.py`
- Create: `tests/test_database.py`

**Step 1: Write failing tests**

```python
"""Tests for arkiv.database."""

import json
import sqlite3
import pytest
from arkiv.database import Database


class TestImport:
    def test_import_jsonl(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"mimetype": "text/plain", "content": "hello", "metadata": {"role": "user"}}\n'
            '{"mimetype": "text/plain", "content": "world", "metadata": {"role": "assistant"}}\n'
        )
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM records").fetchone()
        assert rows[0] == 2
        conn.close()

    def test_import_preserves_fields(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"mimetype": "text/plain", "url": "https://example.com", "content": "hello", "timestamp": "2024-01-15", "metadata": {"key": "val"}}\n'
        )
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT mimetype, url, content, timestamp, metadata FROM records").fetchone()
        assert row[0] == "text/plain"
        assert row[1] == "https://example.com"
        assert row[2] == "hello"
        assert row[3] == "2024-01-15"
        assert json.loads(row[4]) == {"key": "val"}
        conn.close()

    def test_import_empty_record(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("{}\n")
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT mimetype, content FROM records").fetchone()
        assert row[0] is None
        assert row[1] is None
        conn.close()

    def test_import_computes_schema(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"metadata": {"role": "user"}}\n'
            '{"metadata": {"role": "assistant"}}\n'
        )
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")
        db.close()

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT key_path, type, count FROM _schema WHERE collection = 'test'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "role"
        assert rows[0][1] == "string"
        assert rows[0][2] == 2
        conn.close()

    def test_collection_name_from_filename(self, tmp_path):
        f = tmp_path / "conversations.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f)
        db.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT collection FROM records").fetchone()
        assert row[0] == "conversations"
        conn.close()


class TestQuery:
    def test_sql_query(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"content": "hello", "metadata": {"role": "user"}}\n'
            '{"content": "world", "metadata": {"role": "assistant"}}\n'
        )
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")

        results = db.query("SELECT content FROM records WHERE metadata->>'role' = 'user'")
        assert len(results) == 1
        assert results[0]["content"] == "hello"
        db.close()

    def test_query_returns_dicts(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello", "mimetype": "text/plain"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")

        results = db.query("SELECT content, mimetype FROM records")
        assert results[0]["content"] == "hello"
        assert results[0]["mimetype"] == "text/plain"
        db.close()

    def test_query_rejects_writes(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        with pytest.raises(ValueError):
            db.query("DROP TABLE records")
        db.close()


class TestInfo:
    def test_get_info(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "a"}\n{"content": "b"}\n')
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.import_jsonl(f, collection="test")

        info = db.get_info()
        assert info["total_records"] == 2
        assert "test" in info["collections"]
        assert info["collections"]["test"]["record_count"] == 2
        db.close()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_database.py -v`
Expected: FAIL

**Step 3: Implement Database**

```python
"""SQLite database for arkiv records."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .record import Record, parse_jsonl
from .schema import discover_schema


class Database:
    """SQLite query layer over arkiv records."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY,
                collection TEXT,
                mimetype TEXT,
                url TEXT,
                content TEXT,
                timestamp TEXT,
                metadata JSON
            );

            CREATE TABLE IF NOT EXISTS _schema (
                collection TEXT,
                key_path TEXT,
                type TEXT,
                count INTEGER,
                sample_values TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_records_collection ON records(collection);
            CREATE INDEX IF NOT EXISTS idx_records_mimetype ON records(mimetype);
            CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);
        """)

    def import_jsonl(
        self, path: Union[str, Path], collection: Optional[str] = None
    ) -> int:
        """Import a JSONL file into the database.

        Returns the number of records imported.
        """
        path = Path(path)
        if collection is None:
            collection = path.stem

        count = 0
        for record in parse_jsonl(path):
            self.conn.execute(
                "INSERT INTO records (collection, mimetype, url, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    collection,
                    record.mimetype,
                    record.url,
                    record.content,
                    record.timestamp,
                    json.dumps(record.metadata) if record.metadata else None,
                ),
            )
            count += 1
        self.conn.commit()

        # Pre-compute schema
        schema = discover_schema(path)
        self.conn.execute(
            "DELETE FROM _schema WHERE collection = ?", (collection,)
        )
        for key, entry in schema.items():
            sample = entry.values if entry.values else ([entry.example] if entry.example else [])
            self.conn.execute(
                "INSERT INTO _schema (collection, key_path, type, count, sample_values) VALUES (?, ?, ?, ?, ?)",
                (collection, key, entry.type, entry.count, json.dumps(sample)),
            )
        self.conn.commit()

        return count

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """Run a read-only SQL query. Returns list of dicts."""
        normalized = sql.strip().upper()
        if not normalized.startswith("SELECT") and not normalized.startswith("WITH"):
            raise ValueError("Only SELECT queries are allowed")

        cursor = self.conn.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_info(self) -> Dict[str, Any]:
        """Get database info: total records, collections, counts."""
        total = self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

        collections = {}
        for row in self.conn.execute(
            "SELECT collection, COUNT(*) as cnt FROM records GROUP BY collection"
        ):
            collections[row[0]] = {"record_count": row[1]}

        return {"total_records": total, "collections": collections}

    def get_schema(self, collection: Optional[str] = None) -> Dict[str, Any]:
        """Get pre-computed schema for one or all collections."""
        if collection:
            rows = self.conn.execute(
                "SELECT key_path, type, count, sample_values FROM _schema WHERE collection = ?",
                (collection,),
            ).fetchall()
            return {
                "collection": collection,
                "metadata_keys": {
                    row[0]: {
                        "type": row[1],
                        "count": row[2],
                        "values": json.loads(row[3]) if row[3] else [],
                    }
                    for row in rows
                },
            }
        else:
            result = {}
            for row in self.conn.execute(
                "SELECT DISTINCT collection FROM _schema"
            ):
                result[row[0]] = self.get_schema(row[0])
            return result

    def close(self) -> None:
        self.conn.close()
```

**Step 4: Run tests**

Run: `pytest tests/test_database.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/arkiv/database.py tests/test_database.py
git commit -m "Add SQLite database with import, query, schema"
```

---

### Task 6: SQLite Export

**Files:**
- Modify: `src/arkiv/database.py`
- Create: `tests/test_export.py`

**Step 1: Write failing tests**

```python
"""Tests for arkiv export (SQLite → JSONL + manifest)."""

import json
import pytest
from arkiv.database import Database
from arkiv.manifest import load_manifest


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

    def test_export_creates_manifest(self, tmp_path):
        f = tmp_path / "input.jsonl"
        f.write_text('{"content": "a"}\n{"content": "b"}\n')
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="data")
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        manifest = load_manifest(out / "manifest.json")
        assert len(manifest.collections) == 1
        assert manifest.collections[0].file == "data.jsonl"
        assert manifest.collections[0].record_count == 2

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
        manifest = load_manifest(out / "manifest.json")
        assert len(manifest.collections) == 2

    def test_roundtrip_lossless(self, tmp_path):
        """Import JSONL → SQLite → Export JSONL. Content should be identical."""
        original = tmp_path / "original.jsonl"
        original.write_text(
            '{"mimetype": "text/plain", "url": "https://example.com", "content": "hello", "timestamp": "2024-01-15", "metadata": {"role": "user", "id": 42}}\n'
        )

        db = Database(tmp_path / "test.db")
        db.import_jsonl(original, collection="test")
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        exported_line = (out / "test.jsonl").read_text().strip()
        exported = json.loads(exported_line)
        assert exported["mimetype"] == "text/plain"
        assert exported["url"] == "https://example.com"
        assert exported["content"] == "hello"
        assert exported["timestamp"] == "2024-01-15"
        assert exported["metadata"]["role"] == "user"
        assert exported["metadata"]["id"] == 42
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export.py -v`
Expected: FAIL (no `export` method)

**Step 3: Add export method to Database**

Add to `src/arkiv/database.py`:

```python
def export(self, output_dir: Union[str, Path]) -> None:
    """Export database to JSONL files + manifest."""
    from .manifest import Manifest, Collection, save_manifest
    from .record import Record

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    collections = []
    for row in self.conn.execute("SELECT DISTINCT collection FROM records"):
        coll_name = row[0]
        jsonl_path = output_dir / f"{coll_name}.jsonl"

        count = 0
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for rec_row in self.conn.execute(
                "SELECT mimetype, url, content, timestamp, metadata FROM records WHERE collection = ? ORDER BY id",
                (coll_name,),
            ):
                record = Record(
                    mimetype=rec_row[0],
                    url=rec_row[1],
                    content=rec_row[2],
                    timestamp=rec_row[3],
                    metadata=json.loads(rec_row[4]) if rec_row[4] else None,
                )
                f.write(record.to_json() + "\n")
                count += 1

        # Get schema for this collection
        schema_data = self.get_schema(coll_name)
        collections.append(
            Collection(
                file=f"{coll_name}.jsonl",
                record_count=count,
                schema=schema_data.get("metadata_keys") if schema_data else None,
            )
        )

    manifest = Manifest(collections=collections)
    save_manifest(manifest, output_dir / "manifest.json")
```

**Step 4: Run tests**

Run: `pytest tests/test_export.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/arkiv/database.py tests/test_export.py
git commit -m "Add SQLite → JSONL export with manifest generation"
```

---

### Task 7: Manifest Import (import from manifest.json)

**Files:**
- Modify: `src/arkiv/database.py`
- Create: `tests/test_manifest_import.py`

**Step 1: Write failing tests**

```python
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
```

**Step 2: Run tests, verify fail**

Run: `pytest tests/test_manifest_import.py -v`
Expected: FAIL

**Step 3: Add import_manifest method**

Add to `src/arkiv/database.py`:

```python
def import_manifest(self, manifest_path: Union[str, Path]) -> int:
    """Import all collections described in a manifest.json.

    Returns total records imported.
    """
    from .manifest import load_manifest

    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    base_dir = manifest_path.parent

    total = 0
    for coll in manifest.collections:
        jsonl_path = base_dir / coll.file
        if jsonl_path.exists():
            count = self.import_jsonl(jsonl_path, collection=jsonl_path.stem)
            total += count

    return total
```

**Step 4: Run tests**

Run: `pytest tests/test_manifest_import.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/arkiv/database.py tests/test_manifest_import.py
git commit -m "Add manifest-based import for multiple collections"
```

---

### Task 8: CLI

**Files:**
- Create: `src/arkiv/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write failing tests**

```python
"""Tests for arkiv CLI."""

import json
import subprocess
import sys
import pytest


def run_arkiv(*args):
    result = subprocess.run(
        [sys.executable, "-m", "arkiv.cli", *args],
        capture_output=True,
        text=True,
    )
    return result


class TestCLI:
    def test_version(self):
        result = run_arkiv("--version")
        assert "0.1.0" in result.stdout

    def test_help(self):
        result = run_arkiv("--help")
        assert "import" in result.stdout
        assert "export" in result.stdout

    def test_import_jsonl(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        result = run_arkiv("import", str(f), "--db", str(db_path))
        assert result.returncode == 0
        assert db_path.exists()

    def test_import_manifest(self, tmp_path):
        (tmp_path / "data.jsonl").write_text('{"content": "hello"}\n')
        manifest = {"collections": [{"file": "data.jsonl"}]}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        db_path = tmp_path / "test.db"
        result = run_arkiv("import", str(tmp_path / "manifest.json"), "--db", str(db_path))
        assert result.returncode == 0

    def test_query(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        run_arkiv("import", str(f), "--db", str(db_path))
        result = run_arkiv("query", str(db_path), "SELECT content FROM records")
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_schema(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n')
        result = run_arkiv("schema", str(f))
        assert result.returncode == 0
        assert "role" in result.stdout

    def test_info(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "a"}\n{"content": "b"}\n')
        db_path = tmp_path / "test.db"
        run_arkiv("import", str(f), "--db", str(db_path))
        result = run_arkiv("info", str(db_path))
        assert result.returncode == 0
        assert "2" in result.stdout

    def test_export(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"content": "hello"}\n')
        db_path = tmp_path / "test.db"
        run_arkiv("import", str(f), "--db", str(db_path))
        out = tmp_path / "exported"
        result = run_arkiv("export", str(db_path), "--output", str(out))
        assert result.returncode == 0
        assert (out / "test.jsonl").exists()
        assert (out / "manifest.json").exists()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL

**Step 3: Implement CLI**

Create `src/arkiv/cli.py` with argparse subcommands: import, export, schema, query, info, serve. Also create `src/arkiv/__main__.py` for `python -m arkiv.cli` support.

The CLI implementation should:
- `import`: detect .json (manifest) vs .jsonl (single file), call Database.import_jsonl or import_manifest
- `export`: call Database.export
- `schema`: call discover_schema and print JSON
- `query`: call Database.query and print results as JSON
- `info`: call Database.get_info and print summary
- `serve`: placeholder for MCP server (Task 9)

**Step 4: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/arkiv/cli.py src/arkiv/__main__.py tests/test_cli.py
git commit -m "Add CLI with import, export, schema, query, info commands"
```

---

### Task 9: MCP Server

**Files:**
- Create: `src/arkiv/server.py`
- Create: `tests/test_server.py`

**Step 1: Write failing tests**

```python
"""Tests for arkiv MCP server tools (unit tests, no MCP transport)."""

import json
import pytest
from arkiv.server import ArkivServer


class TestArkivServer:
    @pytest.fixture
    def server(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"content": "hello", "metadata": {"role": "user"}}\n'
            '{"content": "world", "metadata": {"role": "assistant"}}\n'
        )
        from arkiv.database import Database
        db = Database(tmp_path / "test.db")
        db.import_jsonl(f, collection="conversations")

        # Write manifest
        from arkiv.manifest import Manifest, Collection, save_manifest
        m = Manifest(
            description="Test archive",
            collections=[Collection(file="test.jsonl", record_count=2)],
        )
        save_manifest(m, tmp_path / "manifest.json")

        srv = ArkivServer(
            db_path=tmp_path / "test.db",
            manifest_path=tmp_path / "manifest.json",
        )
        yield srv
        srv.close()

    def test_get_manifest(self, server):
        result = server.get_manifest()
        assert result["description"] == "Test archive"
        assert len(result["collections"]) == 1

    def test_get_schema(self, server):
        result = server.get_schema("conversations")
        assert "metadata_keys" in result
        assert "role" in result["metadata_keys"]

    def test_get_schema_all(self, server):
        result = server.get_schema()
        assert "conversations" in result

    def test_sql_query(self, server):
        results = server.sql_query("SELECT content FROM records WHERE metadata->>'role' = 'user'")
        assert len(results) == 1
        assert results[0]["content"] == "hello"

    def test_sql_query_rejects_writes(self, server):
        with pytest.raises(ValueError):
            server.sql_query("DELETE FROM records")
```

**Step 2: Run tests, verify fail**

Run: `pytest tests/test_server.py -v`
Expected: FAIL

**Step 3: Implement ArkivServer**

```python
"""arkiv MCP server."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .database import Database
from .manifest import load_manifest


class ArkivServer:
    """Server exposing 3 tools: get_manifest, get_schema, sql_query."""

    def __init__(
        self,
        db_path: Union[str, Path],
        manifest_path: Optional[Union[str, Path]] = None,
    ):
        self.db = Database(db_path)
        self.manifest = None
        if manifest_path and Path(manifest_path).exists():
            self.manifest = load_manifest(manifest_path)

    def get_manifest(self) -> Dict[str, Any]:
        """Return manifest with collection descriptions and schemas."""
        if self.manifest:
            result = self.manifest.to_dict()
            # Enrich with schema from DB
            for coll in result.get("collections", []):
                name = Path(coll["file"]).stem
                schema = self.db.get_schema(name)
                if schema and "metadata_keys" in schema:
                    coll["schema"] = {"metadata_keys": schema["metadata_keys"]}
            return result
        else:
            # Generate from database info
            info = self.db.get_info()
            return {
                "collections": [
                    {"file": f"{name}.jsonl", "record_count": data["record_count"]}
                    for name, data in info["collections"].items()
                ]
            }

    def get_schema(self, collection: Optional[str] = None) -> Dict[str, Any]:
        """Return pre-computed metadata schema."""
        return self.db.get_schema(collection)

    def sql_query(self, query: str) -> List[Dict[str, Any]]:
        """Run read-only SQL query."""
        return self.db.query(query)

    def close(self) -> None:
        self.db.close()
```

Then add the MCP transport wiring (using mcp SDK) in a `serve()` function that registers the 3 tools. This can be a separate step if the mcp SDK is not yet installed.

**Step 4: Run tests**

Run: `pytest tests/test_server.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/arkiv/server.py tests/test_server.py
git commit -m "Add MCP server with get_manifest, get_schema, sql_query"
```

---

### Task 10: MCP Transport Wiring

**Files:**
- Modify: `src/arkiv/server.py` (add `run_mcp_server` function)
- Modify: `src/arkiv/cli.py` (wire `serve` command)

**Step 1: Add MCP transport**

Add to `src/arkiv/server.py`:

```python
def run_mcp_server(db_path: str, manifest_path: Optional[str] = None, port: int = 8002):
    """Run the arkiv MCP server."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError:
        raise ImportError("MCP server requires 'mcp' package. Install with: pip install arkiv[mcp]")

    server = Server("arkiv")
    arkiv = ArkivServer(db_path, manifest_path)

    @server.tool()
    async def get_manifest() -> str:
        """Get manifest with collection descriptions and pre-computed schemas."""
        return json.dumps(arkiv.get_manifest(), indent=2)

    @server.tool()
    async def get_schema(collection: Optional[str] = None) -> str:
        """Get metadata schema for one or all collections."""
        return json.dumps(arkiv.get_schema(collection), indent=2)

    @server.tool()
    async def sql_query(query: str) -> str:
        """Run read-only SQL query against the archive."""
        results = arkiv.sql_query(query)
        return json.dumps(results, indent=2, default=str)

    import asyncio
    asyncio.run(stdio_server(server))
```

**Step 2: Wire serve command in CLI**

Add `serve` subcommand that calls `run_mcp_server`.

**Step 3: Test manually**

Run: `arkiv serve test.db`
Expected: MCP server starts (or prints error if mcp not installed)

**Step 4: Commit**

```bash
git add src/arkiv/server.py src/arkiv/cli.py
git commit -m "Wire MCP transport for serve command"
```

---

### Task 11: Package Exports and Final Polish

**Files:**
- Modify: `src/arkiv/__init__.py`
- Create: `tests/test_integration.py`

**Step 1: Update __init__.py exports**

```python
"""arkiv: Universal personal data format."""

__version__ = "0.1.0"

from .record import Record, parse_record, parse_jsonl
from .schema import SchemaEntry, discover_schema
from .manifest import Manifest, Collection, load_manifest, save_manifest
from .database import Database

__all__ = [
    "Record",
    "parse_record",
    "parse_jsonl",
    "SchemaEntry",
    "discover_schema",
    "Manifest",
    "Collection",
    "load_manifest",
    "save_manifest",
    "Database",
]
```

**Step 2: Write integration test**

```python
"""End-to-end integration test."""

import json
import pytest
from arkiv import Database, Manifest, Collection, save_manifest, load_manifest, parse_jsonl


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        """JSONL → import → query → export → verify roundtrip."""
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
                Collection(file="conversations.jsonl", description="AI convos"),
                Collection(file="bookmarks.jsonl", description="Saved links"),
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
            "SELECT content FROM records WHERE metadata->>'role' = 'user'"
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
        assert exported_convos[0].content == "I think category theory is beautiful"
```

**Step 3: Run full test suite**

Run: `pytest tests/ -v --cov=src/arkiv --cov-report=term-missing`
Expected: all tests PASS, good coverage

**Step 4: Commit**

```bash
git add src/arkiv/__init__.py tests/test_integration.py
git commit -m "Add package exports and end-to-end integration test"
```

---

## Task Summary

| Task | Component | Tests |
|------|-----------|-------|
| 1 | Project scaffolding | - |
| 2 | Record model + JSONL parsing | ~15 tests |
| 3 | Schema discovery | ~9 tests |
| 4 | Manifest model | ~6 tests |
| 5 | SQLite import + query | ~9 tests |
| 6 | SQLite export | ~4 tests |
| 7 | Manifest import | ~2 tests |
| 8 | CLI | ~8 tests |
| 9 | MCP server (unit) | ~5 tests |
| 10 | MCP transport wiring | manual |
| 11 | Package exports + integration | ~1 test |

**Total: ~60 tests across 11 tasks**

**Build order:** Tasks 1-7 are the core. Task 8 (CLI) wraps it. Tasks 9-10 (MCP) add the LLM interface. Task 11 ties it together.
