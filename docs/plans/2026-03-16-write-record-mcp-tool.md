# write_record() MCP Tool — Implementation Plan

**Date:** 2026-03-16
**Scope:** Add a write path to arkiv's MCP server for eidola memory persistence
**Status:** Ready for implementation
**Motivation:** eidola simulacra need to persist conversation data to `memory/data.db` during conversations. The MCP server is currently read-only. This adds a controlled write path.

---

## Context

arkiv's MCP server (`src/arkiv/server.py`) exposes three read-only tools: `get_manifest()`, `get_schema()`, `sql_query()`. The server opens databases with `read_only=True` (`server.py:17`).

eidola's persona directories use two MCP servers:
- `arkiv` — person's immutable data (must stay read-only)
- `memory` — simulacrum's mutable experience (needs writes)

The solution: a `--writable` CLI flag that enables `write_record()` on the MCP server. The default remains read-only.

---

## Design

### CLI Change

```bash
# Read-only (default, existing behavior)
arkiv mcp archive.db

# Writable (enables write_record tool)
arkiv mcp --writable memory.db
```

The `--writable` flag causes the server to:
1. Open the database in read-write mode (not `read_only=True`)
2. Register the `write_record()` MCP tool (in addition to the three existing tools)
3. Auto-create tables if the database doesn't exist yet (`_ensure_tables()`)

### eidola .mcp.json

```json
{
  "mcpServers": {
    "arkiv":  { "command": "arkiv", "args": ["mcp", "arkiv/data.db"] },
    "memory": { "command": "arkiv", "args": ["mcp", "--writable", "memory/data.db"] }
  }
}
```

The `arkiv` server stays read-only. The `memory` server accepts writes. This enforces eidola's immutable/mutable boundary at the infrastructure level.

### write_record() Tool Spec

**Parameters:**
- `collection` (string, required) — which collection to write to (e.g., "conversations", "sessions")
- `content` (string, required) — the record content (text, JSON string, etc.)
- `mimetype` (string, optional, default: "text/plain") — MIME type of the content
- `timestamp` (string, optional, default: current UTC ISO 8601) — when this record was created
- `metadata` (string, optional) — JSON string of metadata key-value pairs

**Returns:** JSON with the inserted record's `id`, `collection`, and `timestamp`.

**Behavior:**
- Append semantics (NOT replace — unlike `import_jsonl()` which deletes first)
- Single INSERT into `records` table, immediate COMMIT
- Schema discovery is NOT run per-write (too expensive). Schema updates happen on next `arkiv import` or can be triggered manually.
- Collection name validated (no SQL injection, no path traversal — reuse `_validate_collection_name()` from `database.py:16-23`)

### Why Not Just Use sql_query() for Writes?

`sql_query()` intentionally rejects non-SELECT statements (`database.py:164-165`). This is correct — arbitrary SQL writes would bypass validation and could corrupt the database. `write_record()` provides a safe, structured write path that:
- Validates input
- Uses parameterized queries (no injection)
- Maintains the records table schema
- Returns confirmation

---

## Implementation

### Step 1: Add `insert_record()` to Database class

**File:** `src/arkiv/database.py`

Add a method after `import_jsonl()` (~line 116):

```python
def insert_record(
    self,
    collection: str,
    content: str,
    mimetype: str = "text/plain",
    timestamp: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Insert a single record. Append semantics (does not delete existing records)."""
    self._validate_collection_name(collection)
    if timestamp is None:
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata_json = json.dumps(metadata) if metadata else None
    cursor = self.conn.execute(
        "INSERT INTO records (collection, mimetype, uri, content, timestamp, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (collection, mimetype, None, content, timestamp, metadata_json),
    )
    self.conn.commit()
    return {
        "id": cursor.lastrowid,
        "collection": collection,
        "timestamp": timestamp,
    }
```

Import `datetime` at top of file if not already present.

### Step 2: Add `--writable` flag to CLI

**File:** `src/arkiv/cli.py`

In the MCP subparser registration (~line 370-373):

```python
p_mcp = subparsers.add_parser("mcp", help="Start MCP server")
p_mcp.add_argument("db", help="SQLite database path")
p_mcp.add_argument("--writable", action="store_true",
                    help="Enable write_record tool (default: read-only)")
p_mcp.set_defaults(func=cmd_mcp)
```

Update `cmd_mcp()` (~line 294-298):

```python
def cmd_mcp(args):
    """Start the MCP server."""
    from .server import run_mcp_server
    run_mcp_server(db_path=args.db, writable=getattr(args, 'writable', False))
```

### Step 3: Update ArkivServer and run_mcp_server()

**File:** `src/arkiv/server.py`

Update `ArkivServer.__init__()` (~line 17):

```python
def __init__(self, db_path: str, writable: bool = False):
    self.db = Database(db_path, read_only=not writable)
    self.writable = writable
```

Update `run_mcp_server()` signature and add the write tool conditionally:

```python
def run_mcp_server(db_path: str, writable: bool = False):
    arkiv = ArkivServer(db_path, writable=writable)
    mcp = FastMCP("arkiv")

    # ... existing tools (get_manifest, get_schema, sql_query) ...

    if writable:
        @mcp.tool()
        def write_record(
            collection: str,
            content: str,
            mimetype: str = "text/plain",
            timestamp: str = "",
            metadata: str = "",
        ) -> str:
            """Write a single record to a collection. Append semantics.

            Args:
                collection: Collection name (e.g., "conversations", "sessions")
                content: Record content (text or JSON string)
                mimetype: MIME type (default: text/plain)
                timestamp: ISO 8601 timestamp (default: current UTC time)
                metadata: JSON string of metadata key-value pairs (optional)
            """
            meta_dict = json.loads(metadata) if metadata else None
            ts = timestamp if timestamp else None
            result = arkiv.db.insert_record(
                collection=collection,
                content=content,
                mimetype=mimetype,
                timestamp=ts,
                metadata=meta_dict,
            )
            return json.dumps(result, indent=2)

    mcp.run(transport="stdio")
```

### Step 4: Update public API

**File:** `src/arkiv/__init__.py`

No changes needed — `Database.insert_record()` is accessible via the Database class which is already exported.

### Step 5: Update SPEC.md

Add `write_record()` to the MCP tools section. Note that it's only available when the server is started with `--writable`.

---

## Test Plan

### Database tests (`tests/test_database.py`)

```python
class TestInsertRecord:
    def test_basic_insert(self, db):
        """Insert a record and verify it's queryable."""
        result = db.insert_record("test", "hello world")
        assert result["id"] is not None
        assert result["collection"] == "test"
        rows = db.query("SELECT content FROM records WHERE collection = 'test'")
        assert len(rows) == 1
        assert rows[0]["content"] == "hello world"

    def test_insert_with_metadata(self, db):
        """Metadata dict is stored as JSON and queryable via json_extract."""
        db.insert_record("test", "msg", metadata={"role": "user", "session": "s1"})
        rows = db.query(
            "SELECT json_extract(metadata, '$.role') as role FROM records"
        )
        assert rows[0]["role"] == "user"

    def test_insert_default_timestamp(self, db):
        """Omitting timestamp auto-generates current UTC."""
        result = db.insert_record("test", "msg")
        assert result["timestamp"] is not None
        assert "T" in result["timestamp"]  # ISO 8601

    def test_insert_custom_timestamp(self, db):
        """Explicit timestamp is preserved."""
        result = db.insert_record("test", "msg", timestamp="2026-01-01T00:00:00Z")
        assert result["timestamp"] == "2026-01-01T00:00:00Z"

    def test_insert_append_semantics(self, db):
        """Multiple inserts to same collection append, not replace."""
        db.insert_record("test", "first")
        db.insert_record("test", "second")
        rows = db.query("SELECT content FROM records WHERE collection = 'test'")
        assert len(rows) == 2

    def test_insert_validates_collection_name(self, db):
        """Invalid collection names are rejected."""
        with pytest.raises(ValueError):
            db.insert_record("", "msg")
        with pytest.raises(ValueError):
            db.insert_record("../escape", "msg")

    def test_insert_with_mimetype(self, db):
        """Custom mimetype is stored."""
        db.insert_record("test", '{"key": "value"}', mimetype="application/json")
        rows = db.query("SELECT mimetype FROM records WHERE collection = 'test'")
        assert rows[0]["mimetype"] == "application/json"

    def test_insert_read_only_rejected(self):
        """insert_record raises on read-only database."""
        # Open db read-only, verify insert raises
```

### MCP server tests (`tests/test_server.py`)

```python
class TestWriteRecord:
    def test_write_record_available_when_writable(self):
        """write_record tool is registered when writable=True."""

    def test_write_record_not_available_when_readonly(self):
        """write_record tool is NOT registered when writable=False (default)."""

    def test_write_record_roundtrip(self):
        """Write via MCP tool, read back via sql_query."""

    def test_write_record_invalid_metadata_json(self):
        """Invalid JSON in metadata parameter returns error."""
```

---

## What This Does NOT Include

- **Schema discovery on write.** Per-write schema updates are too expensive. Schema is updated on `arkiv import` or manual `arkiv schema` refresh. This is a deliberate trade-off: writes are fast, schema accuracy is eventual.
- **Batch writes.** `write_record()` inserts one record at a time. For bulk operations, use `arkiv import`. This is correct for the eidola use case (conversation logging is low-throughput).
- **JSONL sync.** `write_record()` writes to SQLite only, not to companion JSONL files. The JSONL ↔ SQLite sync is handled by `arkiv export`. This matches arkiv's existing model: import/export are explicit operations, not automatic.
- **Authentication or authorization.** The `--writable` flag is a trust boundary: whoever starts the server decides if it's writable. eidola enforces the boundary by starting `arkiv` read-only and `memory` writable.
- **Delete or update operations.** Append-only. Records cannot be modified or deleted via MCP. This is correct for conversation logging.

---

## Downstream: eidola Changes After This Ships

Once arkiv has `write_record()`:

1. Update eidola `.mcp.json` template in SPEC.md and generate skill to use `--writable` flag on memory server
2. Update generated CLAUDE.md retrieval instructions to include `memory__write_record()` usage
3. Update generate skill Step 7: no need for `python3 -c "from arkiv import Database..."` — just start the writable server and it auto-creates tables
4. Consider adding conversation logging guidance to the simulacrum's behavioral core (when to write, what metadata to include)
