"""arkiv MCP server."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .database import Database


class ArkivServer:
    """Server exposing 3 tools: get_manifest, get_schema, sql_query.

    Derives all metadata from the database — no external manifest needed.
    """

    def __init__(self, db_path: Union[str, Path]):
        self.db = Database(db_path, read_only=True)

    def get_manifest(self) -> Dict[str, Any]:
        """Return archive overview from _metadata + DB info + schema."""
        result = {}

        # Load README metadata if present
        readme = self.db._load_readme_metadata()
        if readme and readme.frontmatter:
            fm = readme.frontmatter
            if "name" in fm:
                result["name"] = fm["name"]
            if "description" in fm:
                result["description"] = fm["description"]

        # Build collections from DB
        info = self.db.get_info()
        collections = []
        # Get content descriptions from README frontmatter
        content_desc = {}
        if readme and readme.frontmatter:
            for item in readme.frontmatter.get("contents", []):
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


def run_mcp_server(db_path: str):
    """Run the arkiv MCP server over stdio."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError(
            "MCP server requires 'mcp' package. Install with: pip install arkiv[mcp]"
        )

    mcp = FastMCP("arkiv")
    arkiv = ArkivServer(db_path)

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

    mcp.run(transport="stdio")
