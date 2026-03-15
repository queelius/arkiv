# Export Enrichments Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich `arkiv export` with schema-in-README, nested collection directories, and temporal slicing.

**Architecture:** Three composable features added to `Database.export()` and `cmd_export()`. New `render.py` module for markdown rendering. New `timefilter.py` module for ISO 8601 prefix handling. `import_readme()` extended to handle directory entries in `contents`. All features are additive — existing flat export behavior unchanged.

**Tech Stack:** Python 3.8+, sqlite3, pyyaml (existing deps only)

**Spec:** `docs/specs/2026-03-15-export-enrichments-design.md`

---

## Chunk 1: Schema-in-README

### Task 1: Schema rendering functions

**Files:**
- Create: `src/arkiv/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write failing tests for `_render_schema_summary`**

```python
# tests/test_render.py
"""Tests for schema-to-markdown rendering."""

from arkiv.schema import SchemaEntry, CollectionSchema
from arkiv.render import render_schema_summary, render_schema_detail

SENTINEL_BEGIN = "<!-- arkiv:schema:begin -->"
SENTINEL_END = "<!-- arkiv:schema:end -->"


class TestRenderSchemaSummary:
    def test_single_collection(self):
        schemas = {
            "books": CollectionSchema(
                record_count=5,
                metadata_keys={
                    "title": SchemaEntry(type="string", count=5),
                    "year": SchemaEntry(type="number", count=5),
                },
            )
        }
        md = render_schema_summary(schemas)
        assert SENTINEL_BEGIN in md
        assert SENTINEL_END in md
        assert "| books | 5 | title, year |" in md
        assert "## Collections" in md

    def test_multiple_collections_sorted_by_input_order(self):
        schemas = {
            "zebra": CollectionSchema(record_count=1, metadata_keys={}),
            "alpha": CollectionSchema(record_count=2, metadata_keys={}),
        }
        md = render_schema_summary(schemas)
        lines = md.split("\n")
        zebra_line = next(i for i, l in enumerate(lines) if "zebra" in l)
        alpha_line = next(i for i, l in enumerate(lines) if "alpha" in l)
        assert zebra_line < alpha_line  # preserves dict order

    def test_empty_schemas(self):
        md = render_schema_summary({})
        assert SENTINEL_BEGIN in md
        assert "## Collections" in md
```

- [ ] **Step 2: Write failing tests for `render_schema_detail`**

```python
# append to tests/test_render.py

class TestRenderSchemaDetail:
    def test_low_cardinality_shows_values(self):
        schema = CollectionSchema(
            record_count=10,
            metadata_keys={
                "role": SchemaEntry(type="string", count=10, values=["user", "assistant"]),
            },
        )
        md = render_schema_detail(schema)
        assert "| role | string | 10 | user, assistant |" in md

    def test_high_cardinality_shows_example(self):
        schema = CollectionSchema(
            record_count=100,
            metadata_keys={
                "id": SchemaEntry(type="string", count=100, example="abc-123"),
            },
        )
        md = render_schema_detail(schema)
        assert '| id | string | 100 | *e.g., "abc-123"* |' in md

    def test_description_column_added_when_present(self):
        schema = CollectionSchema(
            record_count=5,
            metadata_keys={
                "role": SchemaEntry(type="string", count=5, values=["user"], description="Speaker"),
                "id": SchemaEntry(type="string", count=5),
            },
        )
        md = render_schema_detail(schema)
        assert "Description" in md
        assert "Speaker" in md

    def test_no_description_column_when_all_none(self):
        schema = CollectionSchema(
            record_count=5,
            metadata_keys={
                "role": SchemaEntry(type="string", count=5, values=["user"]),
            },
        )
        md = render_schema_detail(schema)
        assert "Description" not in md

    def test_sentinels_present(self):
        schema = CollectionSchema(record_count=1, metadata_keys={})
        md = render_schema_detail(schema)
        assert SENTINEL_BEGIN in md
        assert SENTINEL_END in md

    def test_count_with_no_values_or_example(self):
        schema = CollectionSchema(
            record_count=50,
            metadata_keys={
                "data": SchemaEntry(type="object", count=50),
            },
        )
        md = render_schema_detail(schema)
        assert "| data | object | 50 |" in md
```

- [ ] **Step 3: Run tests, verify they fail with `ModuleNotFoundError`**

Run: `pytest tests/test_render.py -v`
Expected: FAIL — `No module named 'arkiv.render'`

- [ ] **Step 4: Implement `render.py`**

```python
# src/arkiv/render.py
"""Render schema as markdown tables for README bodies."""

from typing import Dict
from .schema import CollectionSchema

SENTINEL_BEGIN = "<!-- arkiv:schema:begin -->"
SENTINEL_END = "<!-- arkiv:schema:end -->"


def render_schema_summary(schemas: Dict[str, CollectionSchema]) -> str:
    """Render a summary table of all collections.

    Produces a markdown section with collection name, record count,
    and comma-separated metadata key list.
    """
    lines = [SENTINEL_BEGIN, "## Collections", ""]
    lines.append("| Collection | Records | Metadata Keys |")
    lines.append("|------------|---------|---------------|")
    for name, schema in schemas.items():
        keys = ", ".join(schema.metadata_keys.keys())
        lines.append(f"| {name} | {schema.record_count:,} | {keys} |")
    lines.extend(["", SENTINEL_END])
    return "\n".join(lines)


def render_schema_detail(schema: CollectionSchema) -> str:
    """Render a full schema table for a single collection.

    Shows each metadata key with type, count, and values/example.
    Adds a Description column if any key has a description.
    """
    has_desc = any(e.description for e in schema.metadata_keys.values())

    lines = [SENTINEL_BEGIN, "## Metadata Keys", ""]
    if has_desc:
        lines.append("| Key | Type | Count | Values | Description |")
        lines.append("|-----|------|-------|--------|-------------|")
    else:
        lines.append("| Key | Type | Count | Values |")
        lines.append("|-----|------|-------|--------|")

    for key, entry in schema.metadata_keys.items():
        values_col = _format_values(entry)
        if has_desc:
            desc = entry.description or ""
            lines.append(f"| {key} | {entry.type} | {entry.count:,} | {values_col} | {desc} |")
        else:
            lines.append(f"| {key} | {entry.type} | {entry.count:,} | {values_col} |")

    lines.extend(["", SENTINEL_END])
    return "\n".join(lines)


def _format_values(entry) -> str:
    """Format the values column for a schema entry."""
    if entry.values:
        return ", ".join(str(v) for v in entry.values)
    if entry.example is not None:
        return f'*e.g., "{entry.example}"*'
    return ""


def inject_schema_block(body: str, schema_block: str) -> str:
    """Inject a schema block into a README body.

    If sentinel comments exist, replace the content between them.
    Otherwise, append the schema block at the end.
    """
    if SENTINEL_BEGIN in body and SENTINEL_END in body:
        before = body[: body.index(SENTINEL_BEGIN)]
        after = body[body.index(SENTINEL_END) + len(SENTINEL_END) :]
        return before.rstrip("\n") + "\n\n" + schema_block + after.lstrip("\n")
    else:
        separator = "\n\n" if body.strip() else ""
        return body.rstrip("\n") + separator + schema_block + "\n"
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `pytest tests/test_render.py -v`
Expected: all PASS

- [ ] **Step 6: Write tests for `inject_schema_block`**

```python
# append to tests/test_render.py
from arkiv.render import inject_schema_block, SENTINEL_BEGIN, SENTINEL_END


class TestInjectSchemaBlock:
    def test_append_to_empty_body(self):
        result = inject_schema_block("", "SCHEMA")
        assert result == "SCHEMA\n"

    def test_append_to_existing_body(self):
        result = inject_schema_block("Hello world.", "SCHEMA")
        assert result.startswith("Hello world.\n\nSCHEMA")

    def test_replace_existing_sentinels(self):
        body = f"Prose.\n\n{SENTINEL_BEGIN}\nOLD\n{SENTINEL_END}\n\nMore prose."
        result = inject_schema_block(body, "NEW")
        assert "OLD" not in result
        assert "NEW" in result
        assert "Prose." in result
        assert "More prose." in result

    def test_preserves_prose_outside_sentinels(self):
        body = f"Before.\n\n{SENTINEL_BEGIN}\nX\n{SENTINEL_END}\n\nAfter."
        result = inject_schema_block(body, "REPLACED")
        assert "Before." in result
        assert "After." in result
```

- [ ] **Step 7: Run all render tests**

Run: `pytest tests/test_render.py -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/arkiv/render.py tests/test_render.py
git commit -m "Add schema-to-markdown rendering with sentinel-based injection"
```

---

### Task 2: Wire schema-in-README into export

**Files:**
- Modify: `src/arkiv/database.py` (`export()` method)
- Test: `tests/test_export.py`

- [ ] **Step 1: Write failing test for schema-in-README on export**

```python
# append to tests/test_export.py
from arkiv.render import SENTINEL_BEGIN, SENTINEL_END


class TestSchemaInReadme:
    def test_export_readme_has_summary_table(self, tmp_path):
        """Flat export README body contains a collections summary table."""
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"metadata": {"role": "user"}}\n{"metadata": {"role": "admin"}}\n')
        db.import_jsonl(f, collection="data")

        out = tmp_path / "out"
        db.export(out)
        db.close()

        readme_text = (out / "README.md").read_text()
        assert SENTINEL_BEGIN in readme_text
        assert SENTINEL_END in readme_text
        assert "| data |" in readme_text
        assert "## Collections" in readme_text

    def test_export_preserves_user_prose(self, tmp_path):
        """User-written body text outside sentinels survives re-export."""
        from arkiv.readme import Readme

        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection="data")

        # Store README with custom body
        readme = Readme(
            frontmatter={"name": "Test", "contents": [{"path": "data.jsonl"}]},
            body="My custom prose.\n",
        )
        db._store_readme_metadata(readme)

        out = tmp_path / "out"
        db.export(out)
        db.close()

        readme_text = (out / "README.md").read_text()
        assert "My custom prose." in readme_text
        assert SENTINEL_BEGIN in readme_text
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_export.py::TestSchemaInReadme -v`
Expected: FAIL — no sentinel comments in current export output

- [ ] **Step 3: Write test for `arkiv_format` in exported frontmatter**

```python
    def test_export_sets_arkiv_format(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection="data")
        out = tmp_path / "out"
        db.export(out)
        db.close()

        from arkiv.readme import parse_readme
        readme = parse_readme(out / "README.md")
        assert readme.frontmatter.get("arkiv_format") == "0.2"
```

- [ ] **Step 4: Modify `export()` to inject schema summary and set `arkiv_format`**

In `src/arkiv/database.py`, import `render_schema_summary` and `inject_schema_block` from `.render`, then add before `save_readme()` (after line 352 in current code, between building `updated_contents` and calling `save_readme()`):

```python
from .render import render_schema_summary, inject_schema_block

# Set format version
readme.frontmatter["arkiv_format"] = "0.2"

# Inject schema summary into body
summary = render_schema_summary(schemas)
readme.body = inject_schema_block(readme.body, summary)
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `pytest tests/test_export.py -v`
Expected: all PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `pytest tests/ -q`
Expected: all pass (some existing tests may need sentinel awareness)

- [ ] **Step 7: Commit**

```bash
git add src/arkiv/database.py tests/test_export.py
git commit -m "Wire schema-in-README and arkiv_format into flat export"
```

---

## Chunk 2: Temporal Slicing

### Task 3: ISO 8601 prefix increment

**Files:**
- Create: `src/arkiv/timefilter.py`
- Test: `tests/test_timefilter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_timefilter.py
"""Tests for temporal filtering helpers."""

import pytest
from arkiv.timefilter import increment_iso_prefix, build_time_filter


class TestIncrementIsoPrefix:
    def test_year(self):
        assert increment_iso_prefix("2024") == "2025"

    def test_year_month(self):
        assert increment_iso_prefix("2024-12") == "2025-01"

    def test_year_month_day(self):
        assert increment_iso_prefix("2024-12-31") == "2025-01-01"

    def test_mid_year(self):
        assert increment_iso_prefix("2024-06") == "2024-07"

    def test_mid_month(self):
        assert increment_iso_prefix("2024-06-15") == "2024-06-16"

    def test_february_non_leap(self):
        assert increment_iso_prefix("2025-02-28") == "2025-03-01"

    def test_february_leap(self):
        assert increment_iso_prefix("2024-02-29") == "2024-03-01"


class TestBuildTimeFilter:
    def test_no_filters(self):
        clause, params = build_time_filter()
        assert clause == ""
        assert params == []

    def test_since_only(self):
        clause, params = build_time_filter(since="2024-01-01")
        assert "timestamp >= ?" in clause or "timestamp IS NULL" in clause
        assert "2024-01-01" in params

    def test_until_prefix(self):
        clause, params = build_time_filter(until="2024-12-31")
        assert "timestamp <" in clause
        assert "2025-01-01" in params

    def test_until_full_timestamp(self):
        clause, params = build_time_filter(until="2024-12-31T23:59:59Z")
        assert "timestamp <=" in clause
        assert "2024-12-31T23:59:59Z" in params

    def test_both(self):
        clause, params = build_time_filter(since="2024-01-01", until="2024-12-31")
        assert len(params) == 2
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_timefilter.py -v`
Expected: FAIL — `No module named 'arkiv.timefilter'`

- [ ] **Step 3: Implement `timefilter.py`**

```python
# src/arkiv/timefilter.py
"""Temporal filtering helpers for arkiv export."""

import calendar
from typing import List, Tuple


def increment_iso_prefix(value: str) -> str:
    """Increment the least-significant component of an ISO 8601 prefix.

    '2024' -> '2025'
    '2024-12' -> '2025-01'
    '2024-12-31' -> '2025-01-01'
    """
    parts = value.split("-")
    if len(parts) == 1:
        return str(int(parts[0]) + 1)
    elif len(parts) == 2:
        year, month = int(parts[0]), int(parts[1])
        month += 1
        if month > 12:
            year += 1
            month = 1
        return f"{year:04d}-{month:02d}"
    elif len(parts) >= 3:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        max_day = calendar.monthrange(year, month)[1]
        day += 1
        if day > max_day:
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
        return f"{year:04d}-{month:02d}-{day:02d}"
    return value


def build_time_filter(
    since: str = None, until: str = None
) -> Tuple[str, List[str]]:
    """Build a SQL WHERE clause for temporal filtering.

    Returns (clause_string, param_list). clause_string may be empty.
    NULL timestamps always pass the filter.
    """
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
            params.append(increment_iso_prefix(until))
    return " AND ".join(clauses), params
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_timefilter.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/arkiv/timefilter.py tests/test_timefilter.py
git commit -m "Add ISO 8601 prefix increment and temporal filter builder"
```

---

### Task 4: Wire temporal slicing into export

**Files:**
- Modify: `src/arkiv/database.py` (`export()` method)
- Modify: `src/arkiv/cli.py` (`cmd_export`, `p_export` argparse)
- Test: `tests/test_export.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_export.py

class TestTemporalSlicing:
    def _make_db(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"timestamp": "2023-06-01", "content": "old"}\n'
            '{"timestamp": "2024-03-15", "content": "mid"}\n'
            '{"timestamp": "2024-12-31T10:30:00Z", "content": "late"}\n'
            '{"content": "no timestamp"}\n'
        )
        db.import_jsonl(f, collection="data")
        return db

    def test_since_filters_old_records(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, since="2024-01-01")
        db.close()

        lines = (out / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3  # mid + late + no-timestamp

    def test_until_includes_full_timestamp(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, until="2024-12-31")
        db.close()

        lines = (out / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 4  # all records (2024-12-31T10:30:00Z included)

    def test_null_timestamps_always_pass(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, since="2099-01-01")
        db.close()

        lines = (out / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1  # only the null-timestamp record

    def test_empty_collection_excluded(self, tmp_path):
        """A collection with zero records after filtering is omitted entirely."""
        db = Database(tmp_path / "test.db")
        f1 = tmp_path / "old.jsonl"
        f1.write_text('{"timestamp": "2020-01-01", "content": "ancient"}\n')
        f2 = tmp_path / "new.jsonl"
        f2.write_text('{"timestamp": "2024-06-01", "content": "recent"}\n')
        db.import_jsonl(f1, collection="old")
        db.import_jsonl(f2, collection="new")

        out = tmp_path / "out"
        db.export(out, since="2024-01-01")
        db.close()

        assert not (out / "old.jsonl").exists()
        readme_text = (out / "README.md").read_text()
        assert "old" not in readme_text
        assert "new" in readme_text

    def test_until_excludes_future(self, tmp_path):
        """--until 2024 should exclude records from 2025."""
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"timestamp": "2024-06-01", "content": "in"}\n'
            '{"timestamp": "2025-01-01", "content": "out"}\n'
        )
        db.import_jsonl(f, collection="data")
        out = tmp_path / "out"
        db.export(out, until="2024")
        db.close()

        lines = (out / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1

    def test_slice_schema_reflects_filtered_data(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, since="2024-01-01")
        db.close()

        import yaml
        schema = yaml.safe_load((out / "schema.yaml").read_text())
        # Schema should reflect 3 records, not 4
        assert schema["data"]["record_count"] == 3
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_export.py::TestTemporalSlicing -v`
Expected: FAIL — `export()` doesn't accept `since`/`until` parameters

- [ ] **Step 3: Add `since`/`until` params to `export()` in `database.py`**

Modify the `export()` signature: `def export(self, output_dir, since=None, until=None)`. (The `nested` param is added later in Task 5.)

Key changes to `export()`:
1. Import `build_time_filter` from `.timefilter` at top of function
2. Build WHERE clause: `time_clause, time_params = build_time_filter(since, until)`
3. If `time_clause` is non-empty, append it to the records SELECT with `AND`
4. Use **two-pass schema** when temporal filters are active: after writing JSONL, call `discover_schema()` on the written file, then inject curated descriptions from `_load_schema_descriptions()`. When no temporal filter, continue using existing `get_schema()` from `_schema` table (preserves current behavior).
5. After writing all JSONL files, skip collections with `count == 0` — don't add them to `contents` or `schemas`

```python
# In the records query:
sql = "SELECT mimetype, uri, content, timestamp, metadata FROM records WHERE collection = ? ORDER BY id"
params = [coll_name]
if time_clause:
    sql = f"SELECT mimetype, uri, content, timestamp, metadata FROM records WHERE collection = ? AND {time_clause} ORDER BY id"
    params = [coll_name] + time_params

# After writing JSONL, schema computation:
if since or until:
    # Two-pass: recompute from written file
    auto_schema = discover_schema(jsonl_path)
    descs = self._load_schema_descriptions(coll_name)
    for key, entry in auto_schema.items():
        if key in descs:
            entry.description = descs[key]
    metadata_keys = auto_schema
else:
    # Unfiltered: use pre-computed schema from DB (existing behavior)
    schema_data = self.get_schema(coll_name)
    metadata_keys = {k: SchemaEntry(...) for k, v in schema_data["metadata_keys"].items()}
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_export.py::TestTemporalSlicing -v`
Expected: all PASS

- [ ] **Step 5: Add CLI flags for `--since` and `--until`**

In `src/arkiv/cli.py`, add arguments to `p_export`:

```python
p_export.add_argument("--since", help="Include records from this ISO 8601 date")
p_export.add_argument("--until", help="Include records through this ISO 8601 date")
```

Update `cmd_export()` to pass them:

```python
db.export(args.output, since=args.since, until=args.until)
```

- [ ] **Step 6: Write CLI-level test for temporal flags**

```python
# append to tests/test_cli.py or tests/test_export.py

class TestTemporalSlicingCLI:
    def test_since_flag(self, tmp_path):
        # Create DB with records, export with --since, verify filtered output
        ...
```

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/arkiv/database.py src/arkiv/cli.py tests/test_export.py
git commit -m "Add --since/--until temporal slicing to export"
```

---

## Chunk 3: Nested Collection Export

### Task 5: Nested export logic

**Files:**
- Modify: `src/arkiv/database.py` (`export()` method)
- Modify: `src/arkiv/cli.py` (`cmd_export`, `p_export` argparse)
- Test: `tests/test_export.py`

- [ ] **Step 1: Write failing tests for nested export**

```python
# append to tests/test_export.py

class TestNestedExport:
    def _make_db(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f1 = tmp_path / "convos.jsonl"
        f1.write_text('{"metadata": {"role": "user"}, "content": "hi"}\n')
        f2 = tmp_path / "books.jsonl"
        f2.write_text('{"metadata": {"title": "Moby Dick"}, "content": "Call me Ishmael"}\n')
        db.import_jsonl(f1, collection="convos")
        db.import_jsonl(f2, collection="books")
        return db

    def test_nested_creates_subdirectories(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()

        assert (out / "convos" / "convos.jsonl").exists()
        assert (out / "books" / "books.jsonl").exists()
        assert (out / "convos" / "README.md").exists()
        assert (out / "convos" / "schema.yaml").exists()

    def test_nested_top_readme_has_directory_contents(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()

        from arkiv.readme import parse_readme
        readme = parse_readme(out / "README.md")
        paths = [c["path"] for c in readme.frontmatter["contents"]]
        assert "convos/" in paths
        assert "books/" in paths

    def test_nested_per_collection_readme_has_detail_schema(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()

        readme_text = (out / "convos" / "README.md").read_text()
        assert "## Metadata Keys" in readme_text
        assert "role" in readme_text

    def test_nested_per_collection_schema_yaml_single_collection(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()

        import yaml
        schema = yaml.safe_load((out / "convos" / "schema.yaml").read_text())
        assert "convos" in schema
        assert "books" not in schema

    def test_nested_top_schema_yaml_has_all_collections(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()

        import yaml
        schema = yaml.safe_load((out / "schema.yaml").read_text())
        assert "convos" in schema
        assert "books" in schema

    def test_nested_per_collection_readme_frontmatter(self, tmp_path):
        db = self._make_db(tmp_path)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()

        from arkiv.readme import parse_readme
        readme = parse_readme(out / "convos" / "README.md")
        assert readme.frontmatter["name"] == "convos"
        assert readme.frontmatter["record_count"] == 1
        assert readme.frontmatter["arkiv_format"] == "0.2"
        assert readme.frontmatter["contents"] == [{"path": "convos.jsonl"}]

    def test_nested_collection_ordering_from_original(self, tmp_path):
        """Collections appear in order from original README contents."""
        from arkiv.readme import Readme
        db = self._make_db(tmp_path)
        # Store README with explicit ordering: books before convos
        readme = Readme(
            frontmatter={
                "name": "Test",
                "contents": [
                    {"path": "books.jsonl", "description": "Books"},
                    {"path": "convos.jsonl", "description": "Convos"},
                ],
            },
        )
        db._store_readme_metadata(readme)
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()

        from arkiv.readme import parse_readme
        top = parse_readme(out / "README.md")
        paths = [c["path"] for c in top.frontmatter["contents"]]
        assert paths.index("books/") < paths.index("convos/")

    def test_nested_rejects_unsafe_collection_name(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection="../evil")
        with pytest.raises(ValueError, match="path separator"):
            db.export(tmp_path / "out", nested=True)
        db.close()

    def test_nested_rejects_dot_prefix_name(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection=".hidden")
        with pytest.raises(ValueError, match="dot"):
            db.export(tmp_path / "out", nested=True)
        db.close()

    def test_nested_composable_with_since(self, tmp_path):
        db = Database(tmp_path / "test.db")
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"timestamp": "2023-01-01", "content": "old"}\n'
            '{"timestamp": "2024-06-01", "content": "new"}\n'
        )
        db.import_jsonl(f, collection="data")

        out = tmp_path / "out"
        db.export(out, nested=True, since="2024-01-01")
        db.close()

        lines = (out / "data" / "data.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_export.py::TestNestedExport -v`
Expected: FAIL — `export()` doesn't accept `nested` parameter

- [ ] **Step 3: Implement nested export in `export()`**

Extend `export()` to accept `nested=False`. When `nested=True`:
1. Create subdirectory per collection
2. Write JSONL into `collection_name/collection_name.jsonl`
3. Generate per-collection README with `render_schema_detail()`
4. Write per-collection schema.yaml (single collection)
5. Top-level `contents` lists directories (e.g., `"convos/"`) not JSONL files
6. Top-level README body gets `render_schema_summary()`
7. Top-level schema.yaml has all collections (convenience copy)

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_export.py::TestNestedExport -v`
Expected: all PASS

- [ ] **Step 5: Add `--nested` CLI flag**

In `src/arkiv/cli.py`, add to `p_export`:

```python
p_export.add_argument("--nested", action="store_true", help="Create subdirectory per collection")
```

Update `cmd_export()`:

```python
db.export(args.output, nested=args.nested, since=args.since, until=args.until)
```

- [ ] **Step 6: Add collection name safety check**

In `export()`, when `nested=True`, validate collection names before creating directories. Reject names with `/`, `\`, leading `.`, or OS-reserved names.

```python
_UNSAFE_NAMES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}

def _validate_collection_name(name: str) -> None:
    if "/" in name or "\\" in name:
        raise ValueError(f"Collection name contains path separator: {name!r}")
    if name.startswith("."):
        raise ValueError(f"Collection name starts with dot: {name!r}")
    if name.lower() in _UNSAFE_NAMES:
        raise ValueError(f"Collection name is OS-reserved: {name!r}")
```

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/arkiv/database.py src/arkiv/cli.py tests/test_export.py
git commit -m "Add --nested export with per-collection subdirectories"
```

---

### Task 6: Nested import roundtrip

**Files:**
- Modify: `src/arkiv/database.py` (`import_readme()` method)
- Test: `tests/test_readme_import.py`

- [ ] **Step 1: Write failing test for nested import**

```python
# append to tests/test_readme_import.py

class TestNestedImport:
    def test_import_nested_archive(self, tmp_path):
        """Import a nested archive (directory entries in contents)."""
        # Create nested structure
        (tmp_path / "convos").mkdir()
        (tmp_path / "convos" / "convos.jsonl").write_text(
            '{"content": "hello", "metadata": {"role": "user"}}\n'
        )
        (tmp_path / "convos" / "README.md").write_text(
            "---\nname: convos\ncontents:\n- path: convos.jsonl\n---\n"
        )
        (tmp_path / "README.md").write_text(
            "---\nname: Test\ncontents:\n- path: convos/\n---\n"
        )

        db = Database(tmp_path / "test.db")
        count = db.import_readme(tmp_path / "README.md")
        assert count == 1

        result = db.query("SELECT content FROM records WHERE collection = 'convos'")
        assert len(result) == 1
        assert result[0]["content"] == "hello"

        # Only top-level README stored
        readme = db.get_readme()
        assert readme.frontmatter["name"] == "Test"
        db.close()

    def test_roundtrip_nested_export_import(self, tmp_path):
        """Database -> nested export -> import -> database is lossless."""
        db1 = Database(tmp_path / "db1.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hello", "metadata": {"x": 1}}\n')
        db1.import_jsonl(f, collection="data")

        # Export nested
        out = tmp_path / "out"
        db1.export(out, nested=True)
        db1.close()

        # Import from nested export
        db2 = Database(tmp_path / "db2.db")
        db2.import_readme(out / "README.md")

        result = db2.query("SELECT content FROM records WHERE collection = 'data'")
        assert len(result) == 1
        assert result[0]["content"] == "hello"
        db2.close()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_readme_import.py::TestNestedImport -v`
Expected: FAIL — `import_readme()` doesn't handle directory paths

- [ ] **Step 3: Modify `import_readme()` to handle directory entries**

In `import_readme()`, when processing a `contents` entry:
1. Resolve the path relative to the README's directory
2. If it's a directory (or ends with `/`), look for `README.md` inside and recurse
3. If it's a `.jsonl` file, import directly (existing behavior)
4. Otherwise, skip with a warning to stderr

```python
for item in readme.frontmatter.get("contents", []):
    if not isinstance(item, dict) or "path" not in item:
        continue
    entry_path = base_dir / item["path"]
    if entry_path.is_dir():
        sub_readme = entry_path / "README.md"
        if sub_readme.exists():
            total += self._import_nested_readme(sub_readme)
    elif entry_path.suffix == ".jsonl" and entry_path.exists():
        count = self.import_jsonl(entry_path, collection=entry_path.stem)
        total += count
```

Add `_import_nested_readme()` helper that imports JSONL files and merges per-collection schema.yaml, but does NOT store the sub-README in `_metadata`.

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_readme_import.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/arkiv/database.py tests/test_readme_import.py
git commit -m "Support nested directory entries in import_readme"
```

---

## Chunk 4: Spec Update and Final Integration

### Task 7: Update SPEC.md and CLAUDE.md

**Files:**
- Modify: `SPEC.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update SPEC.md design principle #2**

Replace the canonicality language with:
> **The archive is the source of truth.** arkiv archives exist in two interconvertible forms — a directory (README.md + schema.yaml + *.jsonl) and a database (single SQLite file). Both represent the same data. In normal use they stay in sync via import/export. If they diverge, the directory form is authoritative.

- [ ] **Step 2: Add `--nested`, `--since`, `--until` to CLI section of SPEC.md**

- [ ] **Step 3: Add `arkiv_format` to SPEC.md frontmatter conventions table**

- [ ] **Step 4: Update CLAUDE.md to reflect new export capabilities**

Add `render.py` and `timefilter.py` to the Architecture section. Mention `--nested`, `--since`, `--until` in the CLI subcommands list. Update the `export()` description.

- [ ] **Step 5: Fix "ECHO" → "longecho" in SPEC.md**

Replace any remaining "ECHO" references with "longecho" (the settled branding).

- [ ] **Step 6: Run full test suite one final time**

Run: `pytest tests/ --cov=src/arkiv --cov-report=term-missing -q`
Expected: all pass, coverage ≥ 95%

- [ ] **Step 7: Commit**

```bash
git add SPEC.md CLAUDE.md
git commit -m "Update SPEC.md and CLAUDE.md for export enrichments"
```

---

## Summary

| Task | Feature | New files | Modified files |
|------|---------|-----------|----------------|
| 1 | Schema rendering | `render.py`, `test_render.py` | — |
| 2 | Schema-in-README wiring | — | `database.py`, `test_export.py` |
| 3 | ISO prefix + time filter | `timefilter.py`, `test_timefilter.py` | — |
| 4 | Temporal slicing wiring | — | `database.py`, `cli.py`, `test_export.py` |
| 5 | Nested export | — | `database.py`, `cli.py`, `test_export.py` |
| 6 | Nested import roundtrip | — | `database.py`, `test_readme_import.py` |
| 7 | Spec + doc updates | — | `SPEC.md`, `CLAUDE.md` |
