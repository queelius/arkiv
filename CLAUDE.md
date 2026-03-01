# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What arkiv Is

Universal personal data format with JSONL canonical storage, SQLite query layer, and MCP server.

- **JSONL** is the source of truth (human-readable, portable, mergeable)
- **SQLite** is the derived query layer (efficient, standard SQL, JSON1 extension)
- **MCP server** exposes 3 tools: `get_manifest()`, `get_schema()`, `sql_query()`

## What arkiv Is NOT

- Not a database -- it's a format with tooling
- Not specific to personas -- longshade is one consumer, but arkiv is general-purpose
- Not a replacement for SQL databases -- it's an interchange format that imports/exports to SQLite

## Development Commands

```bash
pip install -e ".[dev]"
pytest                                              # all tests
pytest tests/test_database.py -v                    # one test file
pytest tests/test_cli.py::TestCLI::test_export -v   # single test
pytest --cov=src/arkiv --cov-report=term-missing    # coverage
black src/ tests/
flake8 src/ tests/
mypy src/
```

CLI is invoked as `python -m arkiv.cli` (or `arkiv` if installed). Tests use `subprocess.run([sys.executable, "-m", "arkiv.cli", ...])`.

## Architecture

### Data Flow

```
README.md + schema.yaml + *.jsonl   (archive directory)
        ↓ import_readme()
    SQLite database                 (3 tables: records, _schema, _metadata)
        ↓ export()
README.md + schema.yaml + *.jsonl   (roundtrip-safe)
```

### Record Model (`record.py`)

All fields optional: `mimetype`, `uri`, `content`, `timestamp`, `metadata`. Unknown fields on input are merged into `metadata`. Defined in `KNOWN_FIELDS`.

### Schema System (`schema.py`)

Two-tier schema: auto-discovered from data and curated from `schema.yaml`.

- `discover_schema()` scans JSONL and produces `Dict[str, SchemaEntry]` with type, count, values/example
- `merge_schema(auto, curated)` combines them: **live fields** (type, count) from auto, **stable fields** (description, curated values) from curated. Keys in curated but not data preserved with `count=0`
- `CollectionSchema` bundles `record_count` + `metadata_keys`
- `load_schema_yaml()` / `save_schema_yaml()` handle YAML I/O

### Database (`database.py`)

SQLite tables:
- `records` -- (id, collection, mimetype, uri, content, timestamp, metadata JSON)
- `_schema` -- (collection, key_path, type, count, sample_values, description)
- `_metadata` -- (key TEXT PRIMARY KEY, value TEXT) — stores README frontmatter + body as KV pairs

Key behaviors:
- `import_jsonl()` uses **replace semantics** (deletes existing records for same collection before inserting)
- `import_jsonl()` preserves existing schema descriptions across reimports
- `import_readme()` parses README.md frontmatter, imports each JSONL from `contents`, merges curated schema from sibling `schema.yaml`
- `export()` writes JSONL files + README.md + schema.yaml, preserving stored frontmatter metadata
- `query()` is read-only (SELECT/WITH only)

### README / Archive Identity (`readme.py`)

`Readme` dataclass with `frontmatter: dict` and `body: str`. Frontmatter is `---`-delimited YAML. Known frontmatter keys by convention: `name`, `description`, `datetime`, `generator`, `contents`.

### CLI (`cli.py`)

Import routing: `.md` → `import_readme()`, directory → looks for `README.md`, everything else → `import_jsonl()`. The CLI uses lazy imports (`from .database import Database` inside functions) to keep startup fast.

### MCP Server (`server.py`)

`ArkivServer` wraps a read-only `Database`. `run_mcp_server()` uses FastMCP (requires `pip install arkiv[mcp]`). All metadata is derived from the DB — no external files needed at serve time.

## Archive Format

```
archive/
├── README.md           # ECHO self-description (YAML frontmatter + markdown)
├── schema.yaml         # Structured metadata schema (auto-generated, curatable)
├── conversations.jsonl
└── bookmarks.jsonl
```

- **README.md** -- YAML frontmatter (`name`, `description`, `datetime`, `generator`, `contents`) + markdown body
- **schema.yaml** -- per-collection metadata keys with type, count, values, description
- **Merge-on-import** -- live fields (type, count) recomputed from data; stable fields (description, curated values) preserved

A curated example archive lives at `examples/repos/` and is verified by `test_integration.py::test_example_archive_roundtrip`.

## Key Principles

1. All record fields optional -- permissive input, best-effort processing
2. JSONL canonical, SQLite derived -- can always regenerate the DB from JSONL
3. Standards-based -- MIME types, URIs, ISO 8601, SQL
4. Document-oriented, not relational

## Tech Stack

- Python 3.8+, sqlite3 (stdlib), json (stdlib), pyyaml, MCP Python SDK

## Related Projects

- [longshade](../longshade/) -- Persona packaging convention (consumer of arkiv)
- [memex](../memex/), [mtk](../mtk/), [btk](../btk/), [ptk](../ptk/), [ebk](../ebk/), [repoindex](../repoindex/), [chartfold](../chartfold/) -- Source toolkits (producers of arkiv JSONL)
- [longecho](../longecho/) -- ECHO compliance validator
