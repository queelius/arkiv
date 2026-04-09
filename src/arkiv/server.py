"""arkiv MCP server."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .database import Database


class ArkivServer:
    """Server exposing 3 tools: get_manifest, get_schema, sql_query.

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
        for item in fm.get("contents", []):
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
        """Run read-only SQL query."""
        return self.db.query(query)

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
        """Run a read-only SQL query against the archive. The 'records' table has columns: id, collection, mimetype, uri, content, timestamp, metadata (JSON). Use json_extract(metadata, '$.key') to query metadata fields. Only SELECT statements are allowed."""
        results = arkiv.sql_query(query)
        return json.dumps(results, indent=2, default=str)

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
            # Parse and validate metadata
            meta_dict = None
            if metadata:
                try:
                    meta_dict = json.loads(metadata)
                except json.JSONDecodeError as e:
                    return json.dumps(
                        {"error": f"metadata is not valid JSON: {e}"}, indent=2
                    )
                if not isinstance(meta_dict, dict):
                    return json.dumps(
                        {
                            "error": (
                                "metadata must be a JSON object, "
                                f"got {type(meta_dict).__name__}"
                            )
                        },
                        indent=2,
                    )

            ts = timestamp if timestamp else None
            try:
                result = arkiv.db.insert_record(
                    collection=collection,
                    content=content,
                    mimetype=mimetype,
                    timestamp=ts,
                    metadata=meta_dict,
                )
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)
            return json.dumps(result, indent=2)

    mcp.run(transport="stdio")
