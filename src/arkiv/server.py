"""arkiv MCP server."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .database import Database

# Default cap on rows returned to the LLM by the sql_query tool, so a broad
# query cannot pull (or OOM on) the whole archive in one call.
DEFAULT_MAX_ROWS = 1000

# A statement still running after this many seconds is aborted, so a
# pathological query (e.g. an unbounded recursive CTE) cannot hang the server.
DEFAULT_QUERY_TIMEOUT_S = 10.0

# A text or blob cell longer than this is cut, so one huge value cannot flood
# the model's context regardless of the row cap.
DEFAULT_MAX_CELL_CHARS = 100_000


class ArkivServer:
    """Server exposing read-only tools (get_manifest, get_schema, sql_query)
    plus write_record when started writable.

    Derives all metadata from the database — no external manifest needed.
    """

    def __init__(self, db_path: Union[str, Path], writable: bool = False):
        self.db = Database(db_path, read_only=not writable)
        self.writable = writable

    def get_manifest(self) -> Dict[str, Any]:
        """Return archive overview from _metadata + DB info + schema."""
        readme = self.db.get_readme()
        fm = readme.frontmatter if readme else {}
        result = {k: fm[k] for k in ("name", "description") if k in fm}

        # Build collections from DB
        info = self.db.get_info()
        collections = []
        content_desc = {}
        for item in fm.get("contents") or []:
            if isinstance(item, dict) and "path" in item:
                content_desc[Path(item["path"]).stem] = item.get("description")

        for name, data in info["collections"].items():
            coll = {
                "file": f"{name}.jsonl",
                "record_count": data["record_count"],
            }
            if name in content_desc and content_desc[name]:
                coll["description"] = content_desc[name]
            schema = self.db.get_schema(name)
            if schema and "metadata_keys" in schema:
                coll["schema"] = {"metadata_keys": schema["metadata_keys"]}
            collections.append(coll)

        result["collections"] = collections
        return result

    def get_schema(self, collection: Optional[str] = None) -> Dict[str, Any]:
        """Return pre-computed metadata schema."""
        return self.db.get_schema(collection)

    def sql_query(self, query: str) -> List[Dict[str, Any]]:
        """Run read-only SQL query (unbounded; used by tests/consumers)."""
        return self.db.query(query)

    def run_sql_capped(
        self,
        query: str,
        max_rows: int = DEFAULT_MAX_ROWS,
        timeout_s: float = DEFAULT_QUERY_TIMEOUT_S,
        max_cell_chars: int = DEFAULT_MAX_CELL_CHARS,
    ) -> Dict[str, Any]:
        """Run a read-only query for the MCP surface with bounded output.

        Rows are capped at *max_rows*, execution at *timeout_s* seconds
        (``ValueError`` when exceeded), and each ``str``/``bytes`` cell at
        *max_cell_chars*. Returns ``{rows, row_count, truncated}``, plus
        ``cells_truncated`` (a count) when any cell was cut, plus a ``note``
        explaining each kind of truncation so the LLM knows to add
        LIMIT/OFFSET or SUBSTR rather than assuming it saw everything.
        """
        rows, truncated = self.db.query_bounded(query, max_rows, timeout_s)
        cells_truncated = 0
        for row in rows:
            for key, value in row.items():
                if isinstance(value, (str, bytes)) and len(value) > max_cell_chars:
                    row[key] = value[:max_cell_chars]
                    cells_truncated += 1
        result: Dict[str, Any] = {
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }
        notes = []
        if truncated:
            notes.append(
                f"Result truncated to {max_rows} rows. Add LIMIT/OFFSET to "
                f"your query to page through the rest."
            )
        if cells_truncated:
            result["cells_truncated"] = cells_truncated
            notes.append(
                f"{cells_truncated} cell(s) were cut to {max_cell_chars} "
                f"characters. Use SUBSTR to read other parts of a long value."
            )
        if notes:
            result["note"] = " ".join(notes)
        return result

    def write_record(
        self,
        collection: str,
        content: str,
        mimetype: str = "text/plain",
        timestamp: str = "",
        metadata: str = "",
    ) -> Dict[str, Any]:
        """Append a single record. Returns the inserted record or
        ``{'error': ...}``. Holds the MCP write tool's logic so its error
        paths are testable without the FastMCP wiring."""
        if not self.writable:
            return {"error": "server is read-only; start it with --writable"}
        meta_dict = None
        if metadata:
            try:
                meta_dict = json.loads(metadata)
            except json.JSONDecodeError as e:
                return {"error": f"metadata is not valid JSON: {e}"}
            if not isinstance(meta_dict, dict):
                return {
                    "error": (
                        "metadata must be a JSON object, "
                        f"got {type(meta_dict).__name__}"
                    )
                }
        ts = timestamp if timestamp else None
        try:
            return self.db.insert_record(
                collection=collection,
                content=content,
                mimetype=mimetype,
                timestamp=ts,
                metadata=meta_dict,
            )
        except ValueError as e:
            return {"error": str(e)}

    def close(self) -> None:
        self.db.close()


def run_mcp_server(db_path: str, writable: bool = False) -> None:
    """Run the arkiv MCP server over stdio."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError(
            "MCP server requires 'mcp' package. Install with: pip install arkiv[mcp]"
        )

    mcp = FastMCP("arkiv")
    arkiv = ArkivServer(db_path, writable=writable)

    @mcp.tool()
    def get_manifest() -> str:
        """Get the archive manifest: lists all collections with record counts and pre-computed metadata schemas. Call this first to understand what data is available."""
        return json.dumps(arkiv.get_manifest(), indent=2)

    @mcp.tool()
    def get_schema(collection: Optional[str] = None) -> str:
        """Get metadata schema for a collection. Shows all metadata keys, their types, counts, and sample values. Use this to understand what fields are queryable via json_extract(metadata, '$.key')."""
        return json.dumps(arkiv.get_schema(collection), indent=2)

    @mcp.tool()
    def sql_query(query: str) -> str:
        """Run a read-only SQL query against the archive. The 'records' table has columns: id, collection, mimetype, uri, content, timestamp, metadata (JSON). Use json_extract(metadata, '$.key') to query metadata fields. Only SELECT statements are allowed. Returns an object {rows, row_count, truncated}; results are capped, so if 'truncated' is true add LIMIT/OFFSET to page. Queries are aborted after 10 seconds, and any text or blob cell longer than 100000 characters is cut (reported as 'cells_truncated'; use SUBSTR to read other parts)."""
        return json.dumps(arkiv.run_sql_capped(query), indent=2, default=str)

    if writable:
        @mcp.tool()
        def write_record(
            collection: str,
            content: str,
            mimetype: str = "text/plain",
            timestamp: str = "",
            metadata: str = "",
        ) -> str:
            """Write a single record to a collection. Append semantics: does not delete existing records.

            Args:
                collection: Collection name (e.g., "conversations", "sessions")
                content: Record content (text or JSON string)
                mimetype: MIME type (default: text/plain)
                timestamp: ISO 8601 timestamp (default: current UTC time)
                metadata: JSON string of metadata key-value pairs (optional, must be a JSON object)
            """
            return json.dumps(
                arkiv.write_record(collection, content, mimetype, timestamp, metadata),
                indent=2,
            )

    mcp.run(transport="stdio")
