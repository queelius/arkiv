"""arkiv CLI."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__


_DB_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}


def _is_db_path(path: Path) -> bool:
    """A path points at a database form if its extension says so."""
    return path.suffix.lower() in _DB_EXTENSIONS


def cmd_convert(args):
    """Convert between the two arkiv archive forms.

    Direction is auto-detected from the input:
      - ``.db`` / ``.sqlite`` / ``.sqlite3``   → produce a directory
      - directory, ``.jsonl``, ``.md``, bundle → produce a database

    Output is optional:
      - input directory, no output  → writes ``arkiv.db`` inside it
      - input .db, no output        → writes directory at ``./exported/``

    Output may be a bundle (``.zip`` / ``.tar.gz`` / ``.tgz``) when
    producing a directory; the directory is built then packed.

    Flags ``--nested`` / ``--since`` / ``--until`` apply only when
    producing a directory.
    """
    import tempfile

    from .bundle import is_bundle, pack_bundle, unpack_bundle
    from .database import Database

    input_path = Path(args.input)

    nested = getattr(args, "nested", False)
    since = getattr(args, "since", None)
    until = getattr(args, "until", None)

    # DB → directory
    if _is_db_path(input_path):
        if not input_path.exists():
            raise FileNotFoundError(f"Database not found: {input_path}")
        output = Path(args.output) if args.output else Path("./exported")

        if is_bundle(output):
            with tempfile.TemporaryDirectory(prefix="arkiv-convert-") as tmp:
                db = Database(input_path, read_only=True)
                try:
                    db.export(tmp, nested=nested, since=since, until=until)
                finally:
                    db.close()
                pack_bundle(Path(tmp), output)
            print(f"Converted {input_path.name} → {output}")
            return

        db = Database(input_path, read_only=True)
        try:
            db.export(output, nested=nested, since=since, until=until)
        finally:
            db.close()
        print(f"Converted {input_path.name} → {output}")
        return

    # Directory / JSONL / README / bundle → DB
    if any([nested, since, until]):
        raise ValueError(
            "--nested, --since, --until apply only when producing a "
            "directory (converting a database to directory form). They "
            "cannot be used when converting into a database."
        )

    # Decide output path
    if args.output:
        output = Path(args.output)
        if not _is_db_path(output):
            raise ValueError(
                f"When converting into a database, output must be a "
                f"database path (.db/.sqlite/.sqlite3), got: {output}"
            )
    elif input_path.is_dir():
        output = input_path / "arkiv.db"
    else:
        raise ValueError(
            "Output path is required when converting a file (JSONL, "
            "README.md, or bundle) into a database. Usage: "
            "arkiv convert INPUT OUTPUT.db"
        )

    # Bundle input: unpack to tempdir, import from there
    if is_bundle(input_path):
        with tempfile.TemporaryDirectory(prefix="arkiv-unpack-") as tmp:
            unpack_bundle(input_path, Path(tmp))
            db = Database(output)
            try:
                readme = Path(tmp) / "README.md"
                if readme.exists():
                    count = db.import_readme(readme)
                else:
                    count = sum(
                        db.import_jsonl(j)
                        for j in sorted(Path(tmp).glob("*.jsonl"))
                    )
            finally:
                db.close()
        print(f"Converted {input_path.name} → {output} ({count} records)")
        return

    # Directory input
    if input_path.is_dir():
        readme = input_path / "README.md"
        db = Database(output)
        try:
            if readme.exists():
                count = db.import_readme(readme)
            else:
                count = sum(
                    db.import_jsonl(j)
                    for j in sorted(input_path.glob("*.jsonl"))
                )
                if count == 0:
                    raise ValueError(
                        f"Directory has no README.md and no .jsonl files: "
                        f"{input_path}"
                    )
        finally:
            db.close()
        print(f"Converted {input_path} → {output} ({count} records)")
        return

    # Single file: README.md or JSONL
    if input_path.suffix == ".md":
        db = Database(output)
        try:
            count = db.import_readme(input_path)
        finally:
            db.close()
        print(f"Converted {input_path.name} → {output} ({count} records)")
        return

    # Treat as JSONL
    db = Database(output)
    try:
        count = db.import_jsonl(input_path)
    finally:
        db.close()
    print(f"Converted {input_path.name} → {output} ({count} records)")



def cmd_schema(args):
    """Show schema from a JSONL file or SQLite database."""
    input_path = Path(args.input)

    if input_path.suffix == ".db":
        from .database import Database

        db = Database(input_path, read_only=True)
        output = db.get_schema()
        db.close()
    else:
        from .schema import discover_schema

        schema = discover_schema(input_path)
        output = {key: entry.to_dict() for key, entry in schema.items()}

    print(json.dumps(output, indent=2))


def _resolve_db(path_str, writable=False):
    """Resolve a path to a Database.

    - ``.db``         → open directly
    - directory       → auto-create ``arkiv.db`` by importing README.md or
      any ``*.jsonl`` found inside
    - ``.jsonl``      → auto-create sibling ``.db`` importing from the file

    Bundles (``.zip`` / ``.tar.gz`` / ``.tgz``) are NOT auto-extracted.
    Bundles are transport containers; to operate on them, unpack first via
    ``arkiv convert bundle.zip ./archive/`` (or ``arkiv convert bundle.zip
    archive.db`` to go straight to a database).
    """
    from .bundle import is_bundle
    from .database import Database

    path = Path(path_str)

    if is_bundle(path):
        raise ValueError(
            f"{path.name} is a packed bundle, not a working archive.\n"
            f"Bundles are transport containers. To work with the contents, unpack first:\n"
            f"  arkiv convert {path.name} archive.db\n"
            f"Then query archive.db, or convert to a directory and work with that."
        )

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
            if not writable:
                db.close()
                return Database(db_path, read_only=True)
            return db
        return Database(db_path, read_only=not writable)
    elif path.suffix == ".jsonl":
        db_path = path.with_suffix(".db")
        if not db_path.exists():
            db = Database(db_path)
            db.import_jsonl(path)
            if not writable:
                db.close()
                return Database(db_path, read_only=True)
            return db
        return Database(db_path, read_only=not writable)
    else:
        return Database(path, read_only=not writable)


def cmd_query(args):
    """Run a SQL query against the database."""
    db = _resolve_db(args.db)
    results = db.query(args.sql)
    db.close()
    print(json.dumps(results, indent=2, default=str))


def cmd_info(args):
    """Print info about a JSONL file or SQLite database."""
    input_path = Path(args.input)

    if input_path.suffix == ".db":
        from .database import Database

        db = Database(input_path, read_only=True)
        info = db.get_info()
        db.close()
    else:
        from .record import parse_jsonl
        from .schema import discover_schema

        collection = input_path.stem
        records = list(parse_jsonl(input_path))
        schema = discover_schema(input_path)
        metadata_keys = {key: entry.to_dict() for key, entry in schema.items()}

        coll_info = {"record_count": len(records)}
        if metadata_keys:
            coll_info["metadata_keys"] = metadata_keys

        info = {
            "total_records": len(records),
            "collections": {collection: coll_info},
        }

    print(json.dumps(info, indent=2))


def _require_jsonl(path, suggestion):
    """Check that path is a JSONL file, not a database."""
    p = Path(path)
    if p.suffix == ".db":
        print(
            f"Error: {p.name} is a SQLite database, not a JSONL file.\n"
            f"Try: arkiv {suggestion} {p.name}",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_detect(args):
    """Check if a JSONL file is valid arkiv format."""
    from .record import KNOWN_FIELDS

    input_path = Path(args.input)
    _require_jsonl(input_path, "info")
    field_suggestions = {
        "url": "uri", "link": "uri", "href": "uri",
        "type": "mimetype", "mime": "mimetype",
    }

    total = 0
    errors = 0
    fields_used = set()
    unknown_fields = set()
    metadata_keys = set()
    warnings = []

    with open(input_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                warnings.append(f"Line {lineno}: invalid JSON")
                errors += 1
                continue
            if not isinstance(obj, dict):
                warnings.append(f"Line {lineno}: not a JSON object")
                errors += 1
                continue

            total += 1
            for key in obj:
                if key in KNOWN_FIELDS:
                    fields_used.add(key)
                else:
                    unknown_fields.add(key)
            if isinstance(obj.get("metadata"), dict):
                metadata_keys.update(obj["metadata"].keys())

    for field in sorted(unknown_fields):
        suggestion = field_suggestions.get(field)
        if suggestion:
            warnings.append(
                f"Unknown field '{field}' — did you mean '{suggestion}'?"
            )
        else:
            warnings.append(
                f"Unknown field '{field}' (will be merged into metadata on import)"
            )

    # Schema validation: check sibling schema.yaml if present
    schema_checks = []
    schema_yaml_path = input_path.parent / "schema.yaml"
    if schema_yaml_path.exists():
        from .schema import discover_schema, load_schema_yaml

        curated = load_schema_yaml(schema_yaml_path)
        collection = input_path.stem
        if collection in curated:
            coll_schema = curated[collection]
            curated_key_names = set(coll_schema.metadata_keys.keys())

            # Keys in schema.yaml but not in data
            for key in sorted(curated_key_names - metadata_keys):
                warnings.append(
                    f"Schema key '{key}' not found in data"
                )

            # Keys in data but not in schema.yaml
            for key in sorted(metadata_keys - curated_key_names):
                schema_checks.append(
                    f"Undocumented key '{key}' (in data but not schema.yaml)"
                )

            # Type and value mismatches
            auto_schema = discover_schema(input_path)
            for key in sorted(curated_key_names & metadata_keys):
                curated_entry = coll_schema.metadata_keys[key]
                if key in auto_schema and auto_schema[key].type != curated_entry.type:
                    warnings.append(
                        f"Type mismatch for '{key}': schema says {curated_entry.type}, data has {auto_schema[key].type}"
                    )

                if curated_entry.values and key in auto_schema and auto_schema[key].values:
                    missing_vals = set(str(v) for v in curated_entry.values) - set(
                        str(v) for v in auto_schema[key].values
                    )
                    if missing_vals:
                        schema_checks.append(
                            f"Curated values for '{key}' not in data: {sorted(missing_vals)}"
                        )

    result = {
        "valid_jsonl": errors == 0,
        "total_records": total,
        "collection": input_path.stem,
        "fields_used": sorted(fields_used),
        "unknown_fields": sorted(unknown_fields),
        "metadata_keys": sorted(metadata_keys),
        "warnings": warnings,
    }
    if schema_checks:
        result["schema_info"] = schema_checks
    print(json.dumps(result, indent=2))

    if args.strict and warnings:
        sys.exit(1)


def cmd_fix(args):
    """Fix known field misspellings in a JSONL file."""
    input_path = Path(args.input)
    _require_jsonl(input_path, "info")
    fix_map = {"url": "uri", "link": "uri", "href": "uri"}

    lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    fixed_count = 0
    out_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            out_lines.append(line)
            continue
        if not isinstance(obj, dict):
            out_lines.append(line)
            continue

        changed = False
        for unknown_field, target_field in fix_map.items():
            if unknown_field in obj and target_field not in obj:
                obj[target_field] = obj[unknown_field]
                changed = True
                fixed_count += 1

        if changed:
            out_lines.append(json.dumps(obj, ensure_ascii=False) + "\n")
        else:
            out_lines.append(line)

    input_path.write_text("".join(out_lines), encoding="utf-8")
    print(json.dumps({"fixed": fixed_count, "file": str(input_path)}, indent=2))


def cmd_mcp(args):
    """Start the MCP server."""
    from .server import run_mcp_server

    writable = getattr(args, 'writable', False)
    db = _resolve_db(args.db, writable=writable)
    run_mcp_server(db_path=str(db.path), writable=writable)
    db.close()


def main():
    parser = argparse.ArgumentParser(
        prog="arkiv",
        description="Universal personal data format. JSONL in, SQL out, MCP to LLMs.",
    )
    parser.add_argument(
        "--version", action="version", version=f"arkiv {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command")

    # convert
    p_convert = subparsers.add_parser(
        "convert",
        help=(
            "Convert between arkiv forms. Direction is auto-detected: "
            ".db input produces a directory (or bundle); any other input "
            "produces a database."
        ),
    )
    p_convert.add_argument(
        "input",
        help=(
            "Input path: directory, .jsonl, README.md, "
            ".db/.sqlite/.sqlite3, or .zip/.tar.gz/.tgz bundle"
        ),
    )
    p_convert.add_argument(
        "output",
        nargs="?",
        help=(
            "Output path. Defaults: input dir → INPUT/arkiv.db; "
            "input .db → ./exported/"
        ),
    )
    p_convert.add_argument(
        "--nested",
        action="store_true",
        help="When producing a directory: one subdirectory per collection",
    )
    p_convert.add_argument(
        "--since",
        help="When producing a directory: include records from this ISO 8601 date",
    )
    p_convert.add_argument(
        "--until",
        help="When producing a directory: include records through this ISO 8601 date",
    )
    p_convert.set_defaults(func=cmd_convert)

    # schema
    p_schema = subparsers.add_parser(
        "schema", help="Show schema from JSONL file or database"
    )
    p_schema.add_argument("input", help="JSONL file or SQLite database")
    p_schema.set_defaults(func=cmd_schema)

    # query
    p_query = subparsers.add_parser("query", help="Run SQL query")
    p_query.add_argument("db", help="SQLite database path")
    p_query.add_argument("sql", help="SQL query")
    p_query.set_defaults(func=cmd_query)

    # info
    p_info = subparsers.add_parser(
        "info", help="Show info about JSONL file or database"
    )
    p_info.add_argument("input", help="JSONL file or SQLite database")
    p_info.set_defaults(func=cmd_info)

    # detect
    p_detect = subparsers.add_parser(
        "detect", help="Check if a JSONL file is valid arkiv format"
    )
    p_detect.add_argument("input", help="JSONL file to check")
    p_detect.add_argument(
        "--strict", action="store_true", help="Exit 1 if any warnings"
    )
    p_detect.set_defaults(func=cmd_detect)

    # fix
    p_fix = subparsers.add_parser(
        "fix", help="Fix known field misspellings in JSONL (e.g. url -> uri)"
    )
    p_fix.add_argument("input", help="JSONL file to fix")
    p_fix.set_defaults(func=cmd_fix)

    # mcp
    p_mcp = subparsers.add_parser("mcp", help="Start MCP server")
    p_mcp.add_argument("db", help="SQLite database path")
    p_mcp.add_argument("--writable", action="store_true",
                        help="Enable write_record tool (default: read-only)")
    p_mcp.set_defaults(func=cmd_mcp)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except UnicodeDecodeError:
        print("Error: File is not valid UTF-8 text (is it a binary file?)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
