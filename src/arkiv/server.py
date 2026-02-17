"""arkiv MCP server."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .database import Database
from .manifest import load_manifest


class ArkivServer:
    """Server exposing 3 tools: get_manifest, get_schema, sql_query."""

    def __init__(
        self,
        db_path: Union[str, Path],
        manifest_path: Optional[Union[str, Path]] = None,
    ):
        self.db = Database(db_path)
        self.manifest = None
        if manifest_path and Path(manifest_path).exists():
            self.manifest = load_manifest(manifest_path)

    def get_manifest(self) -> Dict[str, Any]:
        """Return manifest with collection descriptions and schemas."""
        if self.manifest:
            result = self.manifest.to_dict()
            # Enrich with schema from DB
            for coll in result.get("collections", []):
                name = Path(coll["file"]).stem
                schema = self.db.get_schema(name)
                if schema and "metadata_keys" in schema:
                    coll["schema"] = {"metadata_keys": schema["metadata_keys"]}
            return result
        else:
            # Generate from database info
            info = self.db.get_info()
            return {
                "collections": [
                    {
                        "file": f"{name}.jsonl",
                        "record_count": data["record_count"],
                    }
                    for name, data in info["collections"].items()
                ]
            }

    def get_schema(self, collection: Optional[str] = None) -> Dict[str, Any]:
        """Return pre-computed metadata schema."""
        return self.db.get_schema(collection)

    def sql_query(self, query: str) -> List[Dict[str, Any]]:
        """Run read-only SQL query."""
        return self.db.query(query)

    def close(self) -> None:
        self.db.close()


def run_mcp_server(
    db_path: str,
    manifest_path: Optional[str] = None,
):
    """Run the arkiv MCP server."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError:
        raise ImportError(
            "MCP server requires 'mcp' package. Install with: pip install arkiv[mcp]"
        )

    import asyncio

    server = Server("arkiv")
    arkiv = ArkivServer(db_path, manifest_path)

    @server.tool()
    async def get_manifest() -> str:
        """Get manifest with collection descriptions and pre-computed schemas."""
        return json.dumps(arkiv.get_manifest(), indent=2)

    @server.tool()
    async def get_schema(collection: Optional[str] = None) -> str:
        """Get metadata schema for one or all collections."""
        return json.dumps(arkiv.get_schema(collection), indent=2)

    @server.tool()
    async def sql_query(query: str) -> str:
        """Run read-only SQL query against the archive."""
        results = arkiv.sql_query(query)
        return json.dumps(results, indent=2, default=str)

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)

    asyncio.run(_run())
