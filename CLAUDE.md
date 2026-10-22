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
pytest --cov=src/arkiv --cov-report=term-missing    # coverage (needs coverage>=7.10)
black src/ tests/
flake8 src/ tests/
mypy src/
```

CLI is invoked as `python -m arkiv.cli` (or `arkiv` if installed). Tests use `subprocess.run([sys.executable, "-m", "arkiv.cli", ...])`.

Coverage: most CLI tests run `arkiv.cli` in a subprocess, so `.coveragerc` sets `patch = subprocess` and `parallel = true` (coverage 7.10 or newer, pinned in the `dev` extra). Each process writes its own `.coverage.*` file and pytest-cov combines them; without this `cli.py` reads as roughly 14%.

## Architecture

### Data Flow

The directory and database forms are isomorphic peers; `arkiv convert`
goes either direction:

```
README.md + schema.yaml + *.jsonl   ←→   SQLite database
   (archive directory form)               (records, _schema, _metadata tables)
```

`arkiv convert` auto-detects direction from the input type. Producing a
database goes through `build_database()` (a directory or `README.md`
source; see Database below), which builds from scratch via
`Database.import_directory()` / `import_readme()`; a bare `.jsonl` input
still uses `Database.import_jsonl()`. Producing a directory uses
`Database.export()`. Both directions are lossless. The directory form is
authoritative on divergence (see `docs/PHILOSOPHY.md`).

### Record Model (`record.py`)

All fields optional: `mimetype`, `uri`, `content`, `timestamp`, `metadata`. Unknown fields on input are merged into `metadata`, but an explicit `metadata` object wins over a colliding top-level field (the structured value is not clobbered). `KNOWN_FIELDS` is derived from the `Record` dataclass. Parsing is permissive: a known field with the wrong type (a non-object `metadata`, or a non-string `mimetype`/`uri`/`content`/`timestamp`) is moved into `metadata` under its own name and the record field stays `None`; `null` equals absent. `Record.to_json()` writes non-finite floats as the strings `"nan"`/`"inf"` (`_json_safe`, `allow_nan=False`) so output is strict JSON. `parse_jsonl` ignores a leading UTF-8 BOM. `normalize_timestamp()` converts zoned timestamps to canonical UTC (see Database).

### Schema System (`schema.py`)

Two-tier schema: auto-discovered from data and curated from `schema.yaml`.

- `discover_schema()` scans JSONL and produces `Dict[str, SchemaEntry]` with type, count, values/example
- `merge_schema(auto, curated)` combines them: **live fields** (type, count) from auto, **stable fields** (description, curated values) from curated. Keys in curated but not data preserved with `count=0`
- `CollectionSchema` bundles `record_count` + `metadata_keys`
- `load_schema_yaml()` / `save_schema_yaml()` handle YAML I/O. `load_schema_yaml()` raises `ValueError` on invalid YAML and drops wrongly typed fields as if absent (validators in `_CURATED_FIELDS`), so bad curated values never reach the database. `parse_readme()` also raises `ValueError` on invalid frontmatter YAML.

### Database (`database.py`)

SQLite tables:
- `records` -- (id, collection, mimetype, uri, content, timestamp, timestamp_original, metadata JSON). `timestamp` is normalized to canonical UTC (`...Z`) on import via `normalize_timestamp()` (record.py) so lexicographic order equals chronological order and `--since`/`--until` are correct; `timestamp_original` holds the exact input when it differed (NULL otherwise) and `export()` writes it back (`COALESCE(timestamp_original, timestamp)`) so the directory form is lossless. A migration in `_ensure_tables` adds `timestamp_original` to pre-existing databases.
- `_schema` -- (collection, key_path, type, count, sample_values, description, example). `sample_values` holds only enumerated `values` (JSON); `example` (JSON) holds a high-cardinality key's example (so an example is never written back as curated `values`), added to older databases by a migration in `_ensure_tables`. `_load_schema_entries()` is the one reader (selects NULL for `example` on an unmigrated read-only database).
- `_metadata` -- (key TEXT PRIMARY KEY, value TEXT): stores README frontmatter + body as KV pairs
- `_assets` -- (path TEXT PRIMARY KEY, content BLOB): the `media/` subtree stored as BLOBs, so the database form is a complete peer of the directory form (media survives a db roundtrip)

Key behaviors:
- `import_jsonl()` uses **replace semantics** (deletes existing records for same collection before inserting)
- `import_jsonl()` preserves existing schema descriptions across reimports via `_load_schema_descriptions()`
- `import_directory()` imports a whole archive directory: `README.md` via `import_readme()` when present, else every root-level `*.jsonl` (sorted) plus `media/`; a directory with neither raises `ValueError`.
- `import_readme()` parses README.md frontmatter, imports each JSONL from `contents` (resolves paths relative to README, so nested `collection/collection.jsonl` paths work), merges curated schema from sibling `schema.yaml`, and slurps the `media/` subtree into `_assets`. Two contents entries that resolve to the same collection name (the bare filename stem) raise a collision error rather than silently overwriting one another via replace semantics. `contents` entries come from untrusted frontmatter: `_resolve_contents_entry()` refuses non-string, absolute, `..`-containing, backslash, and NUL paths and anything that resolves outside the archive (even `..` that stays inside), and `_require_inside()` does the same for `schema.yaml`, nested README files, and the top-level `README.md` itself. `contents` itself must be a list (`_contents_entries()`; null is empty), and a `README.md` or `schema.yaml` that is not a regular file is ignored.
- `import_assets()` stores `dir/media/**` bytes into `_assets` (replace semantics) by walking `iter_source_files()`, so symlinks and dot-prefixed files are never stored; called by `import_directory()` and `import_readme()`
- `build_database(source, output, *, fingerprint)` is the one way to produce a database from a directory or `README.md` (used by `cmd_convert` for directory, README, and bundle inputs, and by `_resolve_db` for the auto-db). It calls `refuse_unexported_writes()`, then builds through `bundle._atomic_replace()` (into a dot-prefixed temp file beside the output, `os.replace`d over it only on success), so a failed build leaves the previous database untouched and no temp file behind. Nothing from the old database survives (removed collections, README text, schema descriptions are gone). The result keeps the replaced file's mode (a new file follows the umask), and a symlinked output has its target replaced and the link kept.
- `refuse_unexported_writes(db_path)` is the guard: it raises `ValueError` naming the export command when the database holds writes made by `insert_record()` since the last export, and also refuses an existing SQLite file with no `records` table (not an arkiv database). A missing or zero-byte file, or a database from an older arkiv without the counter, counts as zero writes. A full db-to-directory export (no `--since`/`--until`, not a bundle) calls `store_source_fingerprint()` on the output directory, which clears the counter; if the source database is read-only, the export still succeeds and prints a warning that the guard stays set.
- Read-only open builds the URI with `Path.as_uri()` (percent-encoded), so a path with `#`, `?`, `%`, spaces, or non-ASCII characters opens the file it names.
- `insert_record()` is the append-only write path used by the MCP `write_record` tool. By design, it does NOT update the `_schema` table; the pre-computed schema reflects the state at last `arkiv convert`.
- `refresh_schema()` recomputes and persists schema for a collection by scanning all records. Use after batches of `insert_record()` writes to bring the pre-computed schema back in sync.
- `_save_schema_entries()` is the shared helper for writing to `_schema` table (used by both `import_jsonl` and `merge_curated_schema`)
- `_store_readme_metadata()` / `_load_readme_metadata()` serialize README frontmatter + body to/from `_metadata` KV table
- `export()` writes JSONL files + README.md + schema.yaml, preserving stored frontmatter metadata, and reconstructs the `media/` subtree from `_assets` (via `_export_assets()`: only canonical paths under `media/` are written, checked structurally and then on the resolved path, so a crafted row cannot overwrite `README.md` or a JSONL file; pre-`_assets` databases still work). Supports `nested` (per-collection subdirectories with own README + schema.yaml), `since`/`until` (temporal slicing with two-pass schema recomputation from filtered data), and schema-in-README injection via `render.py` sentinels
- `get_readme()` is the public accessor for stored README metadata
- `query()` is read-only (SELECT/WITH prefix check + sqlite3 authorizer). `query_bounded(sql, max_rows, timeout_s)` additionally caps rows and aborts a statement past the deadline with `ValueError` (sqlite progress handler).

### README / Archive Identity (`readme.py`)

`Readme` dataclass with `frontmatter: dict` and `body: str`. Frontmatter is `---`-delimited YAML. Known frontmatter keys by convention: `name`, `description`, `datetime`, `generator`, `arkiv_format`, `contents`.

### CLI (`cli.py`)

Subcommands: `convert`, `schema`, `query`, `info`, `status`, `detect`, `fix`, `mcp`.

`status DIR` reports whether `DIR` and its `arkiv.db` are in sync (via `Database.sync_status()`): it recomputes the directory's content fingerprint and compares it to the one stored at the last conversion (`_metadata['source_fingerprint']`), and reads `_metadata['inserts_since_convert']` (bumped by `insert_record`). Directory-to-db conversions call `store_source_fingerprint()` (via `build_database(..., fingerprint=True)`). The auto-db used by `query`/`mcp` is built by `_resolve_db()` through the same `build_database()` when missing, and rebuilt when `_source_changed_since()` finds any source file newer than the cache (a cheap mtime check), so reads never return records contradicting the authoritative directory; the guard in `refuse_unexported_writes()` stops a rebuild from destroying `--writable` writes.

`convert` is bidirectional: auto-detects direction from the input type. A `.db`/`.sqlite`/`.sqlite3` input produces a directory (or bundle if the output ends in `.zip`/`.tar.gz`/`.tgz`); anything else (directory, `.jsonl`, `.md`, bundle) produces a database. Output is positional and optional: a directory input with no output writes `arkiv.db` inside the directory; a `.db` input with no output writes to `./exported/`. `query` and `mcp` accept directories and JSONL files too, auto-creating `arkiv.db` on demand.

Key flags:
- `convert`: `--nested` (per-collection subdirectories with own README/schema), `--since`/`--until` (temporal slicing). These only apply when producing a directory; using them with a database output is a hard error.
- `mcp`: `--writable` (enable `write_record` tool for append-only inserts)

Input routing inside `cmd_convert` (when producing a database): bundle → unpack to a tempdir then `build_database(tmp, ..., fingerprint=False)`; directory → `build_database(dir, ..., fingerprint=True)` (README.md if present, else root `*.jsonl`; neither is an error); `.md` → `build_database(readme, ..., fingerprint=False)`; else (a bare `.jsonl`) → `refuse_unexported_writes()` then `import_jsonl()`, which replaces only that collection. `build_database` rebuilds an existing output from scratch. The CLI uses lazy imports (`from .database import Database` inside functions) to keep startup fast.

Errors meant for the user must be `ValueError` or `FileNotFoundError`: `main()` prints those as `Error: ...` with exit 1, and anything else is a traceback.

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
`unpack_bundle(bundle, target_dir)`, plus the 0.4.0 library layer
(`write_bundle`, `records_to_jsonl`, `open_member`, `iter_jsonl`,
`peek_jsonl`, `bundle_format`). `iter_source_files(source_dir)` also lives
here (it was in `database.py`; `database` imports it): the one symlink-free,
contained walk of the canonical source files, shared by `pack_bundle`, the
source fingerprint, and `import_assets()`. The `cmd_convert` flow uses these
to pack/unpack through a tempdir transparently when the user-supplied
input or output is a bundle. `pack_bundle` excludes derived database
files (`.db`/`.sqlite`/`.sqlite3`) and dot-prefixed entries: a bundle
serializes the directory form, not its regenerable cache or hidden noise.

Stdlib-only: zip with DEFLATE, tar with gzip. Modern formats like zstd
or xz are deliberately excluded so bundles stay openable on any
machine for decades. Both extractors apply path-traversal protection
(rejects entries that resolve outside the target directory, via
`_within` containment, not a string prefix), bound the entry count and
total uncompressed size (`unpack_bundle(..., max_entries=, max_total_bytes=)`,
defaults `_MAX_BUNDLE_ENTRIES`/`_MAX_BUNDLE_BYTES`) to resist zip/tar
bombs, and on Python versions that have it (3.12+, and late 3.8-3.11
security releases) use the native `filter="data"` safe-extraction mode.
This matters because bundles may come from untrusted sources.

Extraction hardening, applied by both extractors (and by `open_member`
where noted):
- Every member name goes through `_check_member_name()`: names that are
  empty, absolute, contain a `..` part, or contain a backslash or NUL are
  refused, and the normalized name, NFC-normalized and case-folded
  (`_collision_key()`), is the duplicate key (`_check_unique()`), so
  `x/../records.jsonl`, a repeated member, or `Records.jsonl` beside
  `records.jsonl` (one file on APFS or NTFS) cannot make `convert` and
  `iter_jsonl` see different data. Only the key folds; names are written
  as given.
- Tar: link members (hard or symbolic, even inside the archive), FIFOs,
  devices, and every sparse variant are refused; only regular files and
  directories are extracted. Members stream in, so the entry cap applies
  before the rest of the archive is parsed.
- Tar headers are bounded by `_CappedTarInfo`: a header over
  `_MAX_TAR_HEADER_BYTES` (1 MiB) is refused before it is read, and
  extended headers (GNU long name, pax) are charged per member across the
  chain (`_HeaderBudget`, at most `_MAX_TAR_HEADER_CHAIN` = 8 deep).
- Corrupt, truncated, or unreadable bundles, and files that are not the
  archive their extension claims, surface as `ValueError`
  (`_extract_errors()`, `_ZIP_UNREADABLE_ERRORS`), on unpack and in
  `open_member` (which wraps the archive open and member scan, never its
  `yield`); a missing bundle stays `FileNotFoundError`. `peek_jsonl`
  returns `None` for any such input.
- `write_bundle` refuses the names unpack would refuse and names that
  collide after normalization, and writes atomically, so a failed write
  leaves no partial bundle. `_atomic_replace(output, suffix)` is the one
  replace policy for databases (`build_database`) and bundles
  (`write_bundle`, `pack_bundle`): it replaces a symlink's target and keeps
  the link, requires the target's directory to exist, writes a private
  `mkstemp` temp named `.arkiv-*<suffix>` (short, so it fits NAME_MAX, and
  dot-prefixed, so source walks skip it), then keeps the replaced file's
  mode or, for a new file, the mode `_new_file_mode()` measures with an
  empty probe file (the umask is never set to be read). `pack_bundle` declares each
  member's size up front so zipfile switches to zip64 for members over
  2 GiB. Output stays byte-reproducible.
- JSONL readers (and `arkiv detect` / `arkiv fix`) accept a leading
  UTF-8 BOM.

`arkiv query` and `arkiv mcp` deliberately do NOT auto-extract
bundles. They reject bundle input with a helpful error directing the
user to `arkiv convert` first. Bundles are transport containers, not
working formats. See `docs/PHILOSOPHY.md` for the rationale.

### MCP Server (`server.py`)

`ArkivServer` wraps a read-only `Database`. `run_mcp_server()` uses FastMCP (requires `pip install arkiv[mcp]`). All metadata is derived from the DB. No external files are needed at serve time. The MCP tool bodies live in testable `ArkivServer` methods (`get_manifest`, `get_schema`, `run_sql_capped`, `write_record`); the `@mcp.tool` closures are thin wrappers. `run_sql_capped` bounds what the LLM can pull at once: rows (`DEFAULT_MAX_ROWS`), execution time (`DEFAULT_QUERY_TIMEOUT_S`, 10 seconds; an over-long statement is aborted with `ValueError`), and text or blob cell size (`DEFAULT_MAX_CELL_CHARS`, 100000 characters), all via `Database.query_bounded`. It returns `{rows, row_count, truncated}`, plus `cells_truncated` (a count) and a `note` when any cell was cut, so the model knows to use `SUBSTR`; `get_schema` entries may carry `example`; `write_record` returns the inserted record or `{"error": ...}` (and refuses when the server is read-only).

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
