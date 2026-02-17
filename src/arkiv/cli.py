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


def cmd_export(args):
    """Export SQLite database to JSONL files + manifest."""
    from .database import Database

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

    db = Database(args.db, read_only=True)
    results = db.query(args.sql)
    db.close()
    print(json.dumps(results, indent=2, default=str))


def cmd_info(args):
    """Print database info."""
    from .database import Database

    db = Database(args.db, read_only=True)
    info = db.get_info()
    db.close()
    print(json.dumps(info, indent=2))


def cmd_serve(args):
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
    p_info = subparsers.add_parser("info", help="Show database info")
    p_info.add_argument("db", help="SQLite database path")
    p_info.set_defaults(func=cmd_info)

    # serve
    p_serve = subparsers.add_parser("serve", help="Start MCP server")
    p_serve.add_argument("db", help="SQLite database path")
    p_serve.add_argument("--manifest", help="Manifest JSON path")
    p_serve.set_defaults(func=cmd_serve)

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
