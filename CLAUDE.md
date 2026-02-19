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

## Archive Format

An arkiv archive directory contains:

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

## Expected CLI

```bash
arkiv import README.md --db archive.db        # import via README.md (resolves contents)
arkiv import conversations.jsonl --db archive.db  # import bare JSONL
arkiv import ./archive/ --db archive.db       # import directory (finds README.md)
arkiv export archive.db --output ./exported/  # exports JSONL + README.md + schema.yaml
arkiv schema conversations.jsonl
arkiv query archive.db "SELECT ..."
arkiv info archive.db
arkiv detect conversations.jsonl              # validate arkiv format + schema.yaml
arkiv fix conversations.jsonl                 # fix known field misspellings
arkiv mcp archive.db                          # start MCP server
```

## Tech Stack

- Python 3.8+, sqlite3 (stdlib), json (stdlib), pyyaml, MCP Python SDK

## Related Projects

- [longshade](../longshade/) -- Persona packaging convention (consumer of arkiv)
- [memex](../memex/), [mtk](../mtk/), [btk](../btk/), [ptk](../ptk/), [ebk](../ebk/), [repoindex](../repoindex/), [chartfold](../chartfold/) -- Source toolkits (producers of arkiv JSONL)
- [longecho](../longecho/) -- ECHO compliance validator
