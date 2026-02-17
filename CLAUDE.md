# CLAUDE.md

## What arkiv Is

Universal personal data format with JSONL canonical storage, SQLite query layer, and MCP server.

- **JSONL** is the source of truth (human-readable, portable, mergeable)
- **SQLite** is the derived query layer (efficient, standard SQL, JSON1 extension)
- **MCP server** exposes 3 tools: `get_manifest()`, `get_schema()`, `sql_query()`

## What arkiv Is NOT

- Not a database -- it's a format with tooling
- Not specific to personas -- longshade is one consumer, but arkiv is general-purpose
- Not a replacement for SQL databases -- it's an interchange format that imports/exports to SQLite

## Record Fields

`mimetype`, `uri`, `content`, `timestamp`, `metadata` -- all optional. Unknown fields go to `metadata`.

## Key Principles

1. All record fields optional -- permissive input, best-effort processing
2. JSONL canonical, SQLite derived -- can always regenerate the DB from JSONL
3. Standards-based -- MIME types, URIs, ISO 8601, SQL
4. Document-oriented, not relational

## Development Commands

```bash
pip install -e ".[dev]"
pytest
pytest --cov=src/arkiv --cov-report=term-missing
black src/ tests/
flake8 src/ tests/
mypy src/
```

## Expected CLI

```bash
arkiv import conversations.jsonl --db archive.db
arkiv import manifest.json --db archive.db
arkiv export archive.db --output ./exported/
arkiv schema conversations.jsonl
arkiv query archive.db "SELECT ..."
arkiv serve archive.db --port 8002
arkiv info archive.db
```

## Tech Stack

- Python 3.8+, sqlite3 (stdlib), json (stdlib), MCP Python SDK

## Related Projects

- [longshade](../longshade/) -- Persona packaging convention (consumer of arkiv)
- [memex](../memex/), [mtk](../mtk/), [btk](../btk/), [ptk](../ptk/), [ebk](../ebk/), [repoindex](../repoindex/), [chartfold](../chartfold/) -- Source toolkits (producers of arkiv JSONL)
- [longecho](../longecho/) -- ECHO compliance validator
