# arkiv Export Enrichments — Design Spec

**Date:** 2026-03-15
**Scope:** Sub-project A of the arkiv + longecho evolution
**Status:** Draft

---

## Context

arkiv archives exist in two forms:

- **Directory form**: README.md + schema.yaml + *.jsonl (human-optimized, git-friendly, durable)
- **Database form**: single .db file with records + _schema + _metadata tables (query-optimized, portable)

These are losslessly interconvertible. `arkiv import` converts directory → database. `arkiv export` converts database → directory. The MCP server is a read-only access layer over the database form.

Both forms represent the same data. In normal use they stay in sync via import/export. If they diverge (e.g., someone edits a JSONL file without reimporting), the **directory form is authoritative** — it is human-readable, inspectable, and does not require tooling to verify.

This design enriches the **directory form** to be more self-describing, more composable with longecho, and more flexible for time-bounded exports.

---

## Feature 1: Schema-in-README

### Summary

`arkiv export` auto-renders a human-readable schema summary in the README body. The archive becomes self-describing without any tooling — a human reading the README understands the data structure.

### Behavior

**Flat export** (default): the single README.md gets a "Collections" summary table:

```markdown
<!-- arkiv:schema:begin -->
## Collections

| Collection | Records | Metadata Keys |
|------------|---------|---------------|
| conversations | 12,847 | role, source, conversation_id, topic |
| bookmarks | 342 | tags, annotation, domain |
<!-- arkiv:schema:end -->
```

**Nested export** (`--nested`): the top-level README gets the summary table above. Each per-collection README gets a full schema table:

```markdown
<!-- arkiv:schema:begin -->
## Metadata Keys

| Key | Type | Count | Values |
|-----|------|-------|--------|
| role | string | 12,847 | user, assistant |
| source | string | 12,847 | chatgpt, claude |
| conversation_id | string | 12,847 | *(12,847 unique)* |
| topic | string | 8,432 | *e.g., "category theory"* |
<!-- arkiv:schema:end -->
```

Column rules:
- Low-cardinality keys (with `values`): show the values list
- High-cardinality keys (with `example`): show count + italicized example
- If any key has a `description`, add a Description column

### Roundtrip behavior

The rendered tables are in the README **body**, not frontmatter. On reimport, the body is preserved as-is in `_metadata`. On re-export, the body is **regenerated** from current data.

Schema tables are delimited by `<!-- arkiv:schema:begin -->` and `<!-- arkiv:schema:end -->` sentinel comments (invisible in rendered markdown). On re-export:
- If sentinels are found in the existing body, replace the content between them
- If no sentinels are found, append the schema block at the end of the body

User prose outside the sentinel block is preserved across re-exports. Schema curation belongs in schema.yaml, not the README body.

### Implementation

Two internal functions:

`_render_schema_summary(schemas: Dict[str, CollectionSchema]) -> str`
- Produces the summary table (collection name, count, key list)
- Used for top-level README in both flat and nested modes

`_render_schema_detail(schema: CollectionSchema) -> str`
- Produces the full schema table for a single collection
- Used for per-collection READMEs in nested mode

Both wrap output in sentinel comments. Called from `Database.export()` when building the README body.

---

## Feature 2: Nested Collection Export

### Summary

`arkiv export archive.db --output ./out/ --nested` creates a subdirectory per collection, each with its own README.md and schema.yaml. This makes each collection an independent, self-describing unit compatible with longecho's fractal source model.

### Output structure

```
out/
├── README.md              # archive identity + summary table
├── schema.yaml            # full schema (all collections, convenience copy)
├── conversations/
│   ├── README.md          # collection identity + full schema table
│   ├── schema.yaml        # this collection's schema only (authoritative)
│   └── conversations.jsonl
└── bookmarks/
    ├── README.md
    ├── schema.yaml
    └── bookmarks.jsonl
```

The top-level `schema.yaml` is a convenience copy containing all collections. The per-collection `schema.yaml` files are authoritative. On reimport of a nested archive, the per-collection files are used.

### Top-level README

Frontmatter `contents` lists subdirectories (not JSONL files):

```yaml
contents:
  - path: conversations/
    description: ChatGPT and Claude conversations
  - path: bookmarks/
    description: Browser bookmarks
```

Body contains the summary table (Feature 1). Collection ordering in `contents` preserves the order from the original README frontmatter where available, falling back to alphabetical.

### Per-collection README

Frontmatter:

```yaml
name: conversations
description: ChatGPT and Claude conversations
record_count: 12847
generator: arkiv v0.2.0
arkiv_format: "0.2"
contents:
  - path: conversations.jsonl
```

Body contains the full schema table (Feature 1).

The `description` is pulled from the top-level README's `contents` entry for this collection (if it exists), or left absent. The `record_count` field is a new frontmatter convention (not required on import, informational only).

### Per-collection schema.yaml

Contains only the single collection's schema. Same format as the full schema.yaml but with one top-level key.

### Import roundtrip

`arkiv import` must handle nested archives. When a `contents` entry's `path` is a directory (or ends with `/`), recurse: look for a README.md in that subdirectory, and import its contents. The per-collection schema.yaml is merged during this recursive import.

Only the **top-level README** is stored in the `_metadata` table. Per-collection READMEs are used only to resolve their `contents` entries during import — they are not stored separately.

This is a change to `import_readme()`: currently it only resolves `path` entries as JSONL files relative to the README's directory. The new behavior:
1. If `path` ends with `/` or resolves to a directory → recurse into it, import its README
2. If `path` ends with `.jsonl` → import directly (existing behavior)
3. Otherwise → skip with warning

### Collection name safety

Collection names become directory names in nested mode. Names containing path separators (`/`, `\`), starting with `.`, or that are OS-reserved (e.g., `con`, `nul` on Windows) are rejected with an error during nested export. In practice, collection names come from JSONL filename stems, which are already filesystem-safe.

### CLI

```bash
arkiv export archive.db --output ./out/                  # flat (default)
arkiv export archive.db --output ./out/ --nested         # nested
```

No changes to `arkiv import` CLI — it already accepts directories.

---

## Feature 3: Temporal Slicing

### Summary

`arkiv export` accepts `--since` and `--until` flags to export a time-bounded subset of the archive.

### CLI

```bash
arkiv export archive.db --output 2024/ --since 2024-01-01 --until 2024-12-31
arkiv export archive.db --output recent/ --since 2024-06-01
arkiv export archive.db --output ./out/ --nested --since 2024-01-01
```

### Filtering behavior

- Filter by `timestamp` column using SQL string comparison (ISO 8601 sorts lexicographically)
- `--since` is inclusive: `timestamp >= since_value`
- `--until` is exclusive of the next period: `--until 2024-12-31` means `timestamp < 2025-01-01`. This ensures records with full timestamps like `2024-12-31T10:30:00Z` are correctly included. Implementation: increment the least-significant component of the ISO 8601 prefix (`2024` → `2025`, `2024-12` → `2025-01`, `2024-12-31` → `2025-01-01`). If the value already contains a `T` (full timestamp), use `<=` directly.
- Records with `NULL` timestamp always pass (permissive — never exclude data for lacking a timestamp)
- Accepts any ISO 8601 prefix: `2024`, `2024-01`, `2024-01-15`, `2024-01-15T10:30:00Z`
- Both flags are optional and independent

### Schema recomputation

The exported schema.yaml reflects the **filtered** data, not the full database. The export uses a two-pass approach:

1. **Pass 1**: query filtered records from SQLite, write JSONL files to disk
2. **Pass 2**: call `discover_schema()` on the written JSONL files to compute schema from the sliced data

This reuses the existing `discover_schema()` function (which takes a file path) without modification. Curated descriptions from the database's `_schema` table are preserved by loading them before export and injecting them into the discovered schema entries.

Record counts, values, and examples all reflect the sliced data.

### Empty collections

If a collection has zero records after filtering, it is excluded from the export:
- No JSONL file (or subdirectory in nested mode)
- No entry in `contents` frontmatter
- No entry in schema.yaml

### README metadata

The exported README preserves the original archive's `name` and `description`. The `datetime` field reflects the export time, not the original. No automatic renaming or annotation of the slice parameters.

### Implementation

```python
def _increment_iso_prefix(value: str) -> str:
    """Increment the least-significant component of an ISO 8601 prefix.

    '2024' -> '2025', '2024-12' -> '2025-01', '2024-12-31' -> '2025-01-01'
    """
    ...

def _build_time_filter(since=None, until=None):
    clauses = []
    params = []
    if since:
        clauses.append("(timestamp IS NULL OR timestamp >= ?)")
        params.append(since)
    if until:
        if "T" in until:
            clauses.append("(timestamp IS NULL OR timestamp <= ?)")
            params.append(until)
        else:
            clauses.append("(timestamp IS NULL OR timestamp < ?)")
            params.append(_increment_iso_prefix(until))
    return " AND ".join(clauses), params
```

Export opens the DB in read-only mode (as today). The two-pass approach means all writes go to the output directory, not the database.

---

## Format version

The `arkiv_format` field in README frontmatter is set to `"0.2"` on all exports. This is informational — implementations SHOULD NOT reject archives based on version. The format is forward-compatible by convention: unknown frontmatter keys and unknown record fields are preserved, not rejected. Version `"0.2"` indicates support for nested archives and schema-in-README; older implementations that encounter these will degrade gracefully (treating directory `contents` entries as unknown, ignoring sentinel comments in the body).

---

## Spec update

SPEC.md design principle #2 should be updated from "JSONL is canonical" to:

> **The archive is the source of truth.** arkiv archives exist in two interconvertible forms — a directory (README.md + schema.yaml + *.jsonl) and a database (single SQLite file). Both represent the same data. In normal use they stay in sync via import/export. If they diverge, the directory form is authoritative.

This preserves a clear conflict-resolution rule while acknowledging that both forms are complete representations.

---

## What this does NOT include

- **arkiv merge** (Sub-project B) — separate spec
- **Multi-DB MCP** (Sub-project C) — separate spec
- **Embedded SQL in SFA** (Sub-project D) — separate spec, longecho project
- **Dotted schema paths** (Sub-project E) — separate spec
- **longecho schema.yaml awareness** — longecho project, no arkiv changes needed

---

## Test plan

1. **Schema-in-README**: export, verify README body contains markdown tables with correct counts/values/examples. Verify description column appears only when descriptions exist. Verify sentinel comments present. Verify body regeneration preserves user prose outside sentinels.
2. **Nested export**: export with `--nested`, verify directory structure, per-collection READMEs, per-collection schema.yaml. Verify collection ordering matches original `contents` order. Verify per-collection schema is single-collection only.
3. **Temporal slicing**: export with `--since`/`--until`, verify correct record filtering. Verify `--until 2024-12-31` includes `2024-12-31T10:30:00Z`. Verify NULL timestamps pass. Verify schema recomputation reflects slice. Verify empty collections excluded.
4. **Composition**: `--nested --since 2024-01-01` produces nested time-sliced archive.
5. **Roundtrip**: database → nested export → import → database produces equivalent state. Only top-level README stored in `_metadata`.
6. **Collection name safety**: nested export rejects collections with unsafe names.
7. **longecho compatibility**: nested export directory has README.md + durable formats at each level. Each subdirectory is independently self-describing.
