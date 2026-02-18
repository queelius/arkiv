"""arkiv CLI."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def cmd_import(args):
    """Import JSONL or manifest into a SQLite database."""
    from .database import Database

    input_path = Path(args.input)

    if input_path.suffix == ".db":
        print(f"Error: {input_path} is a database file, not a JSONL or manifest file", file=sys.stderr)
        sys.exit(1)

    db = Database(args.db)

    if input_path.suffix == ".json":
        count = db.import_manifest(input_path)
        print(f"Imported {count} records from manifest")
    else:
        count = db.import_jsonl(input_path)
        print(f"Imported {count} records from {input_path.name}")

    db.close()


def _require_db(path, command):
    """Check that path looks like a database, not JSONL."""
    p = Path(path)
    if p.suffix in (".jsonl", ".json"):
        name = p.name
        print(
            f"Error: {name} is a JSONL file, not a SQLite database.\n"
            f"Import it first:\n"
            f"  arkiv import {name} --db archive.db\n"
            f"  arkiv {command} archive.db ...",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_export(args):
    """Export SQLite database to JSONL files + manifest."""
    from .database import Database

    _require_db(args.db, "export")
    db = Database(args.db, read_only=True)
    db.export(args.output)
    db.close()
    print(f"Exported to {args.output}")


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


def cmd_query(args):
    """Run a SQL query against the database."""
    from .database import Database

    _require_db(args.db, "query")
    db = Database(args.db, read_only=True)
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


def cmd_detect(args):
    """Check if a JSONL file is valid arkiv format."""
    import json as json_mod

    input_path = Path(args.input)
    known_fields = {"mimetype", "uri", "content", "timestamp", "metadata"}
    # Unambiguous fixes: unknown field -> arkiv field to duplicate into
    fix_map = {"url": "uri", "link": "uri", "href": "uri"}
    # Broader suggestions for warnings (includes ambiguous ones)
    field_suggestions = {**fix_map, "type": "mimetype", "mime": "mimetype"}

    if args.fix:
        _detect_fix(input_path, known_fields, fix_map)
        return

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
                obj = json_mod.loads(line)
            except json_mod.JSONDecodeError:
                warnings.append(f"Line {lineno}: invalid JSON")
                errors += 1
                continue
            if not isinstance(obj, dict):
                warnings.append(f"Line {lineno}: not a JSON object")
                errors += 1
                continue

            total += 1
            for key in obj:
                if key in known_fields:
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

    result = {
        "valid": errors == 0,
        "total_records": total,
        "collection": input_path.stem,
        "fields_used": sorted(fields_used),
        "unknown_fields": sorted(unknown_fields),
        "metadata_keys": sorted(metadata_keys),
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))

    if args.strict and warnings:
        sys.exit(1)


def _detect_fix(input_path, known_fields, fix_map):
    """Rewrite a JSONL file, duplicating fixable unknown fields into known ones."""
    import json as json_mod

    lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    fixed_count = 0
    out_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        try:
            obj = json_mod.loads(stripped)
        except json_mod.JSONDecodeError:
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
            out_lines.append(json_mod.dumps(obj, ensure_ascii=False) + "\n")
        else:
            out_lines.append(line)

    input_path.write_text("".join(out_lines), encoding="utf-8")
    print(json.dumps({"fixed": fixed_count, "file": str(input_path)}, indent=2))


def cmd_mcp(args):
    """Start the MCP server."""
    from .server import run_mcp_server

    run_mcp_server(
        db_path=args.db,
        manifest_path=args.manifest,
    )


def main():
    parser = argparse.ArgumentParser(
        prog="arkiv",
        description="Universal personal data format. JSONL in, SQL out, MCP to LLMs.",
    )
    parser.add_argument(
        "--version", action="version", version=f"arkiv {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command")

    # import
    p_import = subparsers.add_parser("import", help="Import JSONL or manifest")
    p_import.add_argument("input", help="JSONL file or manifest.json")
    p_import.add_argument(
        "--db", default="archive.db", help="SQLite database path"
    )
    p_import.set_defaults(func=cmd_import)

    # export
    p_export = subparsers.add_parser(
        "export", help="Export database to JSONL + manifest"
    )
    p_export.add_argument("db", help="SQLite database path")
    p_export.add_argument(
        "--output", default="./exported", help="Output directory"
    )
    p_export.set_defaults(func=cmd_export)

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
    p_detect.add_argument(
        "--fix",
        action="store_true",
        help="Fix known field misspellings by duplicating (e.g. url -> uri)",
    )
    p_detect.set_defaults(func=cmd_detect)

    # mcp
    p_mcp = subparsers.add_parser("mcp", help="Start MCP server")
    p_mcp.add_argument("db", help="SQLite database path")
    p_mcp.add_argument("--manifest", help="Manifest JSON path")
    p_mcp.set_defaults(func=cmd_mcp)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except UnicodeDecodeError:
        print("Error: File is not valid UTF-8 text (is it a binary file?)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
