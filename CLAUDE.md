# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What arkiv Is

Universal personal data format with two interconvertible forms (directory and database) plus an MCP server.

- **Directory form** is README.md + schema.yaml + *.jsonl (human-readable, portable, git-friendly)
- **Database form** is a single SQLite file (queryable, efficient, JSON1 extension)
- **Bundle form** is the directory packed as `.zip` or `.tar.gz`: a shipping container, not a working format. `arkiv convert` auto-detects and transparently packs or unpacks bundles through a tempdir. `arkiv query` and `arkiv mcp` reject bundles with a clear error (unpack first).
- The directory and database forms are isomorphic peers. In normal use they stay in sync via `arkiv convert`. If they diverge, the directory form is authoritative.
- **MCP server** exposes 3 read-only tools by default (`get_manifest`, `get_schema`, `sql_query`), plus `write_record` when started with `--writable`

## What arkiv Is NOT

- Not a database -- it's a format with tooling
- Not specific to personas -- longshade is one consumer, but arkiv is general-purpose
- Not a replacement for SQL databases -- it's an interchange format that converts between directory and SQLite forms

## Development Commands

```bash
pip install -e ".[dev]"
pytest                                              # all tests
pytest tests/test_database.py -v                    # one test file
pytest tests/test_cli.py::TestCLI::test_convert_db_to_dir -v   # single test
pytest --cov=src/arkiv --cov-report=term-missing    # coverage
black src/ tests/
flake8 src/ tests/
mypy src/
```

CLI is invoked as `python -m arkiv.cli` (or `arkiv` if installed). Tests use `subprocess.run([sys.executable, "-m", "arkiv.cli", ...])`.

## Architecture

### Data Flow

The directory and database forms are isomorphic peers; `arkiv convert`
goes either direction:

```
README.md + schema.yaml + *.jsonl   ←→   SQLite database
   (archive directory form)               (records, _schema, _metadata tables)
```

`arkiv convert` auto-detects direction from the input type. Internally
this delegates to `Database.import_readme()` / `Database.import_jsonl()`
when producing a database, and `Database.export()` when producing a
directory. Both directions are lossless. The directory form is
authoritative on divergence (see `docs/PHILOSOPHY.md`).

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
- `import_jsonl()` preserves existing schema descriptions across reimports via `_load_schema_descriptions()`
- `import_readme()` parses README.md frontmatter, imports each JSONL from `contents` (resolves paths relative to README, so nested `collection/collection.jsonl` paths work), merges curated schema from sibling `schema.yaml`
- `insert_record()` is the append-only write path used by the MCP `write_record` tool. By design, it does NOT update the `_schema` table; the pre-computed schema reflects the state at last `arkiv convert`.
- `refresh_schema()` recomputes and persists schema for a collection by scanning all records. Use after batches of `insert_record()` writes to bring the pre-computed schema back in sync.
- `_save_schema_entries()` is the shared helper for writing to `_schema` table (used by both `import_jsonl` and `merge_curated_schema`)
- `_store_readme_metadata()` / `_load_readme_metadata()` serialize README frontmatter + body to/from `_metadata` KV table
- `export()` writes JSONL files + README.md + schema.yaml, preserving stored frontmatter metadata. Supports `nested` (per-collection subdirectories with own README + schema.yaml), `since`/`until` (temporal slicing with two-pass schema recomputation from filtered data), and schema-in-README injection via `render.py` sentinels
- `get_readme()` is the public accessor for stored README metadata
- `query()` is read-only (SELECT/WITH prefix check + sqlite3 authorizer)

### README / Archive Identity (`readme.py`)

`Readme` dataclass with `frontmatter: dict` and `body: str`. Frontmatter is `---`-delimited YAML. Known frontmatter keys by convention: `name`, `description`, `datetime`, `generator`, `arkiv_format`, `contents`.

### CLI (`cli.py`)

Subcommands: `convert`, `schema`, `query`, `info`, `detect`, `fix`, `mcp`.

`convert` is bidirectional: auto-detects direction from the input type. A `.db`/`.sqlite`/`.sqlite3` input produces a directory (or bundle if the output ends in `.zip`/`.tar.gz`/`.tgz`); anything else (directory, `.jsonl`, `.md`, bundle) produces a database. Output is positional and optional: a directory input with no output writes `arkiv.db` inside the directory; a `.db` input with no output writes to `./exported/`. `query` and `mcp` accept directories and JSONL files too, auto-creating `arkiv.db` on demand.

Key flags:
- `convert`: `--nested` (per-collection subdirectories with own README/schema), `--since`/`--until` (temporal slicing). These only apply when producing a directory; using them with a database output is a hard error.
- `mcp`: `--writable` (enable `write_record` tool for append-only inserts)

Input routing inside `cmd_convert` (when producing a database): `.md` → `import_readme()`, directory → looks for `README.md`, bundle → unpack to tempdir then import, else → `import_jsonl()`. The CLI uses lazy imports (`from .database import Database` inside functions) to keep startup fast.

### Export (`database.py` export method)

The `export()` method writes a full archive directory (JSONL + README.md + schema.yaml):
- Schema-in-README injection: auto-generated schema tables are wrapped in HTML sentinels (`<!-- arkiv:schema:begin/end -->`). On re-export, the region between sentinels is replaced; prose outside is preserved.
- Flat vs. nested modes: `nested=False` (default) writes all JSONL files at top level; `nested=True` creates a subdirectory per collection with its own README and schema.yaml.
- Temporal slicing: `since` and `until` parameters filter records by timestamp; uses a two-pass approach where JSONL is written first, then schema is recomputed from the filtered output.
- Empty collection skipping: collections that have zero records after filtering are not written to the output directory.

### Schema Rendering (`render.py`)

`render_schema_summary()` and `render_schema_detail()` produce markdown tables from `CollectionSchema`. `inject_schema_block()` handles sentinel-based injection into README bodies (`<!-- arkiv:schema:begin/end -->`). Used by `export()`.

### Temporal Filtering (`timefilter.py`)

`increment_iso_prefix()` handles ISO 8601 date arithmetic. `build_time_filter()` constructs SQL WHERE clauses for `--since`/`--until`. Used by `export()`.

### Bundle Support (`bundle.py`)

Self-contained module for `.zip` and `.tar.gz` archives. Public API:
`is_bundle(path)`, `pack_bundle(directory, output)`,
`unpack_bundle(bundle, target_dir)`. The `cmd_convert` flow uses these
to pack/unpack through a tempdir transparently when the user-supplied
input or output is a bundle.

Stdlib-only: zip with DEFLATE, tar with gzip. Modern formats like zstd
or xz are deliberately excluded so bundles stay openable on any
machine for decades. Both extractors apply path-traversal protection
(rejects entries that resolve outside the target directory) plus, on
Python 3.12+, the native `filter="data"` safe-extraction mode. This
matters because bundles may come from untrusted sources.

`arkiv query` and `arkiv mcp` deliberately do NOT auto-extract
bundles. They reject bundle input with a helpful error directing the
user to `arkiv convert` first. Bundles are transport containers, not
working formats. See `docs/PHILOSOPHY.md` for the rationale.

### MCP Server (`server.py`)

`ArkivServer` wraps a read-only `Database`. `run_mcp_server()` uses FastMCP (requires `pip install arkiv[mcp]`). All metadata is derived from the DB. No external files are needed at serve time.

### Public API

The `arkiv` package re-exports these symbols for use by consumers:

- Record model: `Record`, `parse_record`, `parse_jsonl`
- Schema: `SchemaEntry`, `CollectionSchema`, `discover_schema`, `load_schema_yaml`, `save_schema_yaml`
- README: `Readme`, `parse_readme`, `save_readme`
- Database: `Database`

## Archive Format

```
archive/
├── README.md           # Self-description (YAML frontmatter + markdown)
├── schema.yaml         # Structured metadata schema (auto-generated, curatable)
├── conversations.jsonl
└── bookmarks.jsonl
```

With `--nested` export:

```
archive/
├── README.md
├── schema.yaml
├── conversations/
│   ├── README.md
│   ├── schema.yaml
│   └── conversations.jsonl
└── bookmarks/
    ├── README.md
    ├── schema.yaml
    └── bookmarks.jsonl
```

- **README.md** -- YAML frontmatter (`name`, `description`, `datetime`, `generator`, `arkiv_format`, `contents`) + markdown body
- **schema.yaml** -- per-collection metadata keys with type, count, values, description
- **Merge-on-import** -- live fields (type, count) recomputed from data; stable fields (description, curated values) preserved

A curated example archive lives at `examples/repos/` and is verified by `test_integration.py::test_example_archive_roundtrip`.

## Key Principles

1. All record fields optional -- permissive input, best-effort processing
2. Two interconvertible forms (directory and database). Directory is authoritative on divergence.
3. Standards-based -- MIME types, URIs, ISO 8601, SQL
4. Document-oriented, not relational

## Tech Stack

- Python 3.8+, sqlite3 (stdlib), json (stdlib), pyyaml, MCP Python SDK

## Releases

`pyproject.toml` and `src/arkiv/__init__.py` both carry the version
string and must be bumped together. Each release also updates
`CHANGELOG.md` (Keep-a-Changelog format) and gets a git tag
`v<version>`. The `arkiv_format` field in exported READMEs is a
separate version (currently `"0.2"`) tracking the on-disk format
spec, not the package release.

## Further Reading

- `docs/PHILOSOPHY.md` -- two-axis durability model, why bundles are
  transport not a third form, the regenerability principle. Read this
  before making design decisions; the language used in code comments
  and commits assumes this framing.
- `SPEC.md` -- the format spec (Parts 1-2 normative, Part 3 reference
  implementation notes, Part 4 ecosystem context).
- `CHANGELOG.md` -- per-release summary of breaking changes, additions,
  fixes.

## Related Projects

- [longshade](../longshade/) -- Persona packaging convention (consumer of arkiv)
- [memex](../memex/), [mtk](../mtk/), [btk](../btk/), [ptk](../ptk/), [ebk](../ebk/), [repoindex](../repoindex/), [chartfold](../chartfold/) -- Source toolkits (producers of arkiv archives)
- [longecho](../longecho/) -- longecho compliance validator. arkiv archives are longecho-compliant by construction; the two projects compose without code coupling.
