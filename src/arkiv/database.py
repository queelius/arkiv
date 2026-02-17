"""SQLite database for arkiv records."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .record import Record, parse_jsonl
from .schema import discover_schema


class Database:
    """SQLite query layer over arkiv records."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY,
                collection TEXT,
                mimetype TEXT,
                url TEXT,
                content TEXT,
                timestamp TEXT,
                metadata JSON
            );

            CREATE TABLE IF NOT EXISTS _schema (
                collection TEXT,
                key_path TEXT,
                type TEXT,
                count INTEGER,
                sample_values TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_records_collection ON records(collection);
            CREATE INDEX IF NOT EXISTS idx_records_mimetype ON records(mimetype);
            CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);
        """
        )

    def import_jsonl(
        self, path: Union[str, Path], collection: Optional[str] = None
    ) -> int:
        """Import a JSONL file into the database.

        Returns the number of records imported.
        """
        path = Path(path)
        if collection is None:
            collection = path.stem

        count = 0
        for record in parse_jsonl(path):
            self.conn.execute(
                "INSERT INTO records (collection, mimetype, url, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    collection,
                    record.mimetype,
                    record.url,
                    record.content,
                    record.timestamp,
                    json.dumps(record.metadata) if record.metadata else None,
                ),
            )
            count += 1
        self.conn.commit()

        # Pre-compute schema
        schema = discover_schema(path)
        self.conn.execute(
            "DELETE FROM _schema WHERE collection = ?", (collection,)
        )
        for key, entry in schema.items():
            sample = (
                entry.values
                if entry.values
                else ([entry.example] if entry.example else [])
            )
            self.conn.execute(
                "INSERT INTO _schema (collection, key_path, type, count, sample_values) VALUES (?, ?, ?, ?, ?)",
                (collection, key, entry.type, entry.count, json.dumps(sample)),
            )
        self.conn.commit()

        return count

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """Run a read-only SQL query. Returns list of dicts."""
        normalized = sql.strip().upper()
        if not normalized.startswith("SELECT") and not normalized.startswith(
            "WITH"
        ):
            raise ValueError("Only SELECT queries are allowed")

        cursor = self.conn.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_info(self) -> Dict[str, Any]:
        """Get database info: total records, collections, counts."""
        total = self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

        collections = {}
        for row in self.conn.execute(
            "SELECT collection, COUNT(*) as cnt FROM records GROUP BY collection"
        ):
            collections[row[0]] = {"record_count": row[1]}

        return {"total_records": total, "collections": collections}

    def get_schema(self, collection: Optional[str] = None) -> Dict[str, Any]:
        """Get pre-computed schema for one or all collections."""
        if collection:
            rows = self.conn.execute(
                "SELECT key_path, type, count, sample_values FROM _schema WHERE collection = ?",
                (collection,),
            ).fetchall()
            return {
                "collection": collection,
                "metadata_keys": {
                    row[0]: {
                        "type": row[1],
                        "count": row[2],
                        "values": json.loads(row[3]) if row[3] else [],
                    }
                    for row in rows
                },
            }
        else:
            result = {}
            for row in self.conn.execute(
                "SELECT DISTINCT collection FROM _schema"
            ):
                result[row[0]] = self.get_schema(row[0])
            return result

    def export(self, output_dir: Union[str, Path]) -> None:
        """Export database to JSONL files + manifest."""
        from .manifest import Manifest, Collection, save_manifest

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        collections = []
        for row in self.conn.execute(
            "SELECT DISTINCT collection FROM records"
        ):
            coll_name = row[0]
            jsonl_path = output_dir / f"{coll_name}.jsonl"

            count = 0
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for rec_row in self.conn.execute(
                    "SELECT mimetype, url, content, timestamp, metadata FROM records WHERE collection = ? ORDER BY id",
                    (coll_name,),
                ):
                    record = Record(
                        mimetype=rec_row[0],
                        url=rec_row[1],
                        content=rec_row[2],
                        timestamp=rec_row[3],
                        metadata=json.loads(rec_row[4])
                        if rec_row[4]
                        else None,
                    )
                    f.write(record.to_json() + "\n")
                    count += 1

            # Get schema for this collection
            schema_data = self.get_schema(coll_name)
            collections.append(
                Collection(
                    file=f"{coll_name}.jsonl",
                    record_count=count,
                    schema=schema_data.get("metadata_keys")
                    if schema_data
                    else None,
                )
            )

        manifest = Manifest(collections=collections)
        save_manifest(manifest, output_dir / "manifest.json")

    def import_manifest(self, manifest_path: Union[str, Path]) -> int:
        """Import all collections described in a manifest.json.

        Returns total records imported.
        """
        from .manifest import load_manifest

        manifest_path = Path(manifest_path)
        manifest = load_manifest(manifest_path)
        base_dir = manifest_path.parent

        total = 0
        for coll in manifest.collections:
            jsonl_path = base_dir / coll.file
            if jsonl_path.exists():
                count = self.import_jsonl(jsonl_path, collection=jsonl_path.stem)
                total += count

        return total

    def close(self) -> None:
        self.conn.close()
