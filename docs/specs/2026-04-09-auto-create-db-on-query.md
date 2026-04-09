# Auto-Create Database on Query/MCP

**Date:** 2026-04-09
**Status:** Draft

---

## Problem

The current workflow requires an explicit import step before querying:

```bash
arkiv import ./archive/ --db archive.db   # step 1: create database
arkiv query archive.db "SELECT ..."        # step 2: query it
```

Most users just want to ask questions about their JSONL files. The import step is friction.

## Solution

`arkiv query` and `arkiv mcp` accept a directory (or single JSONL file) as input. If no `arkiv.db` exists, one is created automatically from the directory contents. If it already exists, it is used as-is.

```bash
arkiv query ./archive/ "SELECT ..."    # creates arkiv.db if needed, then queries
arkiv mcp ./archive/                    # creates arkiv.db if needed, then serves
```

## Behavior

### When input is a directory

1. Check for `arkiv.db` inside the directory
2. If missing: create it by running the equivalent of `import_readme()` (if README.md exists) or importing all `.jsonl` files found in the directory
3. If present: open it
4. Proceed with the query or MCP server

The database file is named `arkiv.db` (visible, not hidden). It sits inside the archive directory alongside the JSONL files.

### When input is a single JSONL file

1. Check for `{stem}.db` in the same directory (e.g., `conversations.db` for `conversations.jsonl`)
2. If missing: create it by importing that one JSONL file
3. If present: open it
4. Proceed with the query

### No staleness detection

If the user modifies JSONL files after the database was created, the database is not automatically refreshed. The user can delete `arkiv.db` and re-run, or run `arkiv import` explicitly. This is a deliberate choice: no hashing, no mtime checks, no magic.

### What does NOT change

- `arkiv import` and `arkiv export` continue to work exactly as they do today
- `arkiv query archive.db "..."` (passing a .db file directly) continues to work
- `arkiv mcp archive.db` continues to work
- `--writable` on mcp works with directory input (creates DB in read-write mode)
- All other subcommands (`schema`, `info`, `detect`, `fix`) are unchanged

## Implementation

The changes are confined to `cli.py`:

### `cmd_query(args)`

Currently requires `args.db` to be a database file. Change: if `args.db` is a directory, auto-create and use `arkiv.db` inside it. If `args.db` is a `.jsonl` file, auto-create and use `{stem}.db` alongside it.

### `cmd_mcp(args)`

Currently requires `args.db` to be a database file. Same auto-create logic as `cmd_query`.

### Shared helper

```python
def _resolve_db(path_str: str, writable: bool = False) -> Database:
    """Resolve a path to a Database, auto-creating if the input is a directory or JSONL file."""
    path = Path(path_str)
    if path.is_dir():
        db_path = path / "arkiv.db"
        if not db_path.exists():
            db = Database(db_path)
            readme = path / "README.md"
            if readme.exists():
                db.import_readme(readme)
            else:
                for jsonl in sorted(path.glob("*.jsonl")):
                    db.import_jsonl(jsonl)
            return db
        return Database(db_path, read_only=not writable)
    elif path.suffix == ".jsonl":
        db_path = path.with_suffix(".db")
        if not db_path.exists():
            db = Database(db_path)
            db.import_jsonl(path)
            return db
        return Database(db_path, read_only=not writable)
    else:
        return Database(path, read_only=not writable)
```

Note: when auto-creating, the Database is opened read-write for the import, then the caller uses it. For `cmd_query`, the database should be read-only after creation. For `cmd_mcp --writable`, it stays read-write. The helper handles this via the `writable` parameter.

## Test plan

1. `arkiv query ./dir/ "SELECT ..."` with no existing arkiv.db: creates it, returns results
2. `arkiv query ./dir/ "SELECT ..."` with existing arkiv.db: uses it without reimporting
3. `arkiv query file.jsonl "SELECT ..."` with no existing file.db: creates it
4. `arkiv mcp ./dir/` with no existing arkiv.db: creates it, serves
5. `arkiv mcp --writable ./dir/` with no existing arkiv.db: creates it in writable mode
6. `arkiv query existing.db "SELECT ..."` still works (no behavioral change)
7. Verify the auto-created arkiv.db contains correct records and schema
