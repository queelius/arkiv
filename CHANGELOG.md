# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-04-09

This release unifies the CLI mental model around a single `convert`
subcommand. The two forms (directory and database) are isomorphic
peers, and the CLI now reflects that.

### Removed

- **Breaking:** `arkiv import` and `arkiv export` subcommands are gone.
  Both are replaced by `arkiv convert`, which auto-detects direction
  from the input type. There are no backwards-compat aliases.

### Added

- `arkiv convert INPUT [OUTPUT]` subcommand with auto-detected direction:
  `.db` / `.sqlite` / `.sqlite3` input produces a directory (or bundle if
  the output ends in `.zip` / `.tar.gz` / `.tgz`); any other input
  (directory, `.jsonl`, `.md`, bundle) produces a database.
- Smart output defaults: `arkiv convert ./archive/` writes `arkiv.db`
  inside the directory (refresh in place); `arkiv convert archive.db`
  writes a directory at `./exported/`.
- `arkiv query` and `arkiv mcp` accept a directory or `.jsonl` file as
  input, auto-creating an `arkiv.db` (or sibling `{stem}.db`) on first
  use. Removes the friction of explicit conversion before querying.
- Bundle support throughout `convert`: pack a directory into `.zip` or
  `.tar.gz`, unpack a bundle into a database, all in one command.
- Schema discovery now flattens nested metadata objects into dotted leaf
  keys. `{"conv": {"model": "gpt-4"}}` produces a schema entry
  `conv.model` rather than a single `conv` entry of type `object`. Arrays
  stay opaque (no `tags.0` synthesis). Empty nested dicts produce no
  entries. Documented in SPEC.md 2.1.1.
- `docs/PHILOSOPHY.md`: companion document articulating the two-axis
  durability model (longecho for time, arkiv for complexity), the
  durability stack, and why bundles are transport rather than a third
  form.
- `--nested`, `--since`, `--until` flags on `convert` (apply only when
  producing a directory; using them with database output is a hard error).

### Changed

- `arkiv query bundle.zip` and `arkiv mcp bundle.zip` now reject bundle
  input with a clear error directing the user to `arkiv convert` first.
  Bundles are transport containers, not working formats. This matches
  longecho's stance: archives are recognized as durable but not
  traversed in place.
- SPEC.md Part 4 restructured around the ecosystem-roles model:
  producers (toolkits), arkiv (interchange), longecho (compliance),
  consumers. Includes the durability stack diagram and the
  regenerability principle.
- README.md Quick Start now leads with `arkiv query ./my-archive/`
  rather than the import-then-query workflow.

### Documentation

- `arkiv_format` field in README frontmatter is now bumped to `"0.2"`
  on every export, signaling support for nested archives,
  schema-in-README sentinels, and dotted schema paths.
- `arkiv_format` is informational; older readers degrade gracefully
  by ignoring unknown frontmatter and unknown sentinel comments.

## [0.1.2] - 2026-04-08

Hardening release. Addresses important findings from a code review of
the 0.1.1 export pipeline.

### Added

- `Database.refresh_schema(collection)` recomputes the `_schema` table
  from current records. `insert_record` does not update the schema by
  design (the write path stays O(1)); call `refresh_schema` after a
  batch of writes to bring the pre-computed schema back in sync.
- `_validate_collection_name` now rejects empty and whitespace-only
  names (would have produced a file literally named `.jsonl`).
- New `heading` parameter on `render_schema_summary` and
  `render_schema_detail`. Replaces the brittle index-arithmetic that
  was chopping sentinels off the rendered output and re-wrapping with a
  heading.
- `discover_schema_from_metadata(iter)` shared core, with
  `discover_schema(path)` as a thin wrapper. Lets `refresh_schema`
  reuse the discovery logic without writing a temp JSONL file.

### Changed

- `insert_record` and the `write_record` MCP tool now reject non-dict
  metadata. Previously a list, string, or number would be silently
  stored as JSON, producing records that crash `discover_schema` on
  re-import. The MCP tool returns structured JSON errors instead of
  raising.
- `build_time_filter` and `increment_iso_prefix` validate their input.
  A regex-based parser rejects malformed prefixes (`"garbage"`,
  `"2024-13"`, `"2024-02-30"`) before dispatching to the increment
  logic. Full timestamps with `T` bypass strict date validation and
  are compared lexicographically by SQLite.
- `inject_schema_block` now requires sentinels on their own line
  (line-anchored with `re.MULTILINE`). A sentinel-looking string
  embedded in prose (e.g., inside backticks discussing arkiv) is no
  longer matched as a real sentinel, so documentation READMEs are not
  corrupted on export.

### Documentation

- 13 doc drift items fixed across SPEC.md, README.md, and CLAUDE.md.
  `import_readme` nested archive recursion documented; `export()`
  parameters described; `arkiv_format` clarified relative to package
  version; `get_manifest` return shape documented; "Why JSONL as
  canonical?" renamed to "Why JSONL as the durable layer?" to align
  with the two-interconvertible-forms principle.

## [0.1.1] - 2026-04-08

Hotfix release for three critical bugs in the 0.1.0 export pipeline.

### Fixed

- `inject_schema_block` no longer crashes on backslash-digit sequences
  in schema content (e.g., `\1` in a description). `re.sub` treats the
  replacement string as a regex template; any backref reference raised
  `re.error`. Fixed by passing a callable replacement. Also added
  `count=1` to defend against stray sentinels in user prose.
- Flat export now validates collection names. Previously
  `_validate_collection_name` was only called in the nested branch, so
  a collection named `"../pwn"` or `"/tmp/x"` could write files outside
  the output directory. Validation is now called in `import_jsonl` (so
  bad names can't reach the DB) and unconditionally in `export()` (so
  bad names that did reach the DB are caught before any file write).
- `str.removesuffix()` was used in `database.py` but is Python 3.9+,
  while `pyproject.toml` declared `requires-python = ">=3.8"`. Replaced
  with a `_collection_name_from_path` helper that uses `endswith` +
  slicing. The 3.8 floor is now honest.

### Documentation

- 4 documentation blockers fixed: SPEC.md and CLAUDE.md now correctly
  describe `write_record()` as a 4th MCP tool available with
  `--writable`, README.md MCP tools table includes the writable mode,
  and the "MCP server exposes 3 tools" claim has been updated.

## [0.1.0] - 2026-04-07

Initial PyPI release.

### Added

- Universal record format: JSONL files where each line is a JSON object
  with five optional conventional fields (`mimetype`, `uri`, `content`,
  `timestamp`, `metadata`). Unknown top-level fields are merged into
  `metadata` on import.
- Archive directory format: `README.md` (YAML frontmatter +
  human-readable body) plus `schema.yaml` (auto-generated data
  dictionary) plus one or more `.jsonl` files (collections).
- SQLite query layer: `arkiv import` converts a directory into a single
  `.db` file with `records`, `_schema`, and `_metadata` tables. Lossless
  roundtrip via `arkiv export`.
- MCP server: three read-only tools (`get_manifest`, `get_schema`,
  `sql_query`) over stdio. `--writable` flag adds a fourth tool,
  `write_record`, for append-only inserts.
- CLI: `import`, `export`, `schema`, `query`, `info`, `detect`, `fix`,
  `mcp`. Full reference in SPEC.md 3.3.
- Schema-in-README: exported READMEs include auto-generated markdown
  tables describing each collection's metadata keys, wrapped in
  `<!-- arkiv:schema:begin -->` / `<!-- arkiv:schema:end -->` sentinel
  comments. User prose outside sentinels is preserved across re-exports.
- Nested export (`--nested`): one subdirectory per collection, each
  with its own README.md and schema.yaml. Each subdirectory is
  independently longecho-compliant.
- Temporal slicing (`--since`, `--until`): time-bounded exports with
  two-pass schema recomputation. Records without timestamps always
  pass (permissive).
- SQLite read-only enforcement: prefix check (`SELECT` / `WITH` only)
  plus `sqlite3.set_authorizer` for engine-level write rejection.
  Defends against multi-statement injection.
- Durable formats throughout: stdlib JSON / YAML / SQLite, no exotic
  dependencies.
