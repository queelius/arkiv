"""SQLite database for arkiv records."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .record import Record, parse_jsonl
from .schema import SchemaEntry, CollectionSchema, discover_schema, merge_schema


class Database:
    """SQLite query layer over arkiv records."""

    def __init__(self, path: Union[str, Path], read_only: bool = False):
        self.path = Path(path)
        if read_only:
            if not self.path.exists():
                raise FileNotFoundError(f"Database not found: {self.path}")
            self.conn = sqlite3.connect(
                f"file:{self.path}?mode=ro", uri=True
            )
        else:
            self.conn = sqlite3.connect(str(self.path))
            self._ensure_tables()
        self.conn.row_factory = sqlite3.Row

    def _ensure_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY,
                collection TEXT,
                mimetype TEXT,
                uri TEXT,
                content TEXT,
                timestamp TEXT,
                metadata JSON
            );

            CREATE TABLE IF NOT EXISTS _schema (
                collection TEXT,
                key_path TEXT,
                type TEXT,
                count INTEGER,
                sample_values TEXT,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS _metadata (
                key TEXT PRIMARY KEY,
                value TEXT
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

        Replaces any existing records in the same collection.
        Returns the number of records imported.
        """
        path = Path(path)
        if collection is None:
            collection = path.stem

        # Replace semantics: clear existing records for this collection
        self.conn.execute(
            "DELETE FROM records WHERE collection = ?", (collection,)
        )

        count = 0
        for record in parse_jsonl(path):
            self.conn.execute(
                "INSERT INTO records (collection, mimetype, uri, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    collection,
                    record.mimetype,
                    record.uri,
                    record.content,
                    record.timestamp,
                    json.dumps(record.metadata) if record.metadata else None,
                ),
            )
            count += 1
        self.conn.commit()

        # Pre-compute schema (preserve existing descriptions)
        schema = discover_schema(path)
        existing_desc = self._load_schema_descriptions(collection)
        self.conn.execute(
            "DELETE FROM _schema WHERE collection = ?", (collection,)
        )
        for key, entry in schema.items():
            sample = (
                entry.values
                if entry.values
                else ([entry.example] if entry.example else [])
            )
            desc = existing_desc.get(key)
            self.conn.execute(
                "INSERT INTO _schema (collection, key_path, type, count, sample_values, description) VALUES (?, ?, ?, ?, ?, ?)",
                (collection, key, entry.type, entry.count, json.dumps(sample), desc),
            )
        self.conn.commit()

        return count

    def _load_schema_descriptions(self, collection: str) -> Dict[str, str]:
        """Load existing schema descriptions for a collection."""
        try:
            rows = self.conn.execute(
                "SELECT key_path, description FROM _schema WHERE collection = ? AND description IS NOT NULL",
                (collection,),
            ).fetchall()
            return {row[0]: row[1] for row in rows}
        except sqlite3.OperationalError:
            return {}

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """Run a read-only SQL query. Returns list of dicts."""
        normalized = sql.strip().upper()
        if not normalized.startswith("SELECT") and not normalized.startswith(
            "WITH"
        ):
            raise ValueError("Only SELECT queries are allowed")

        try:
            cursor = self.conn.execute(sql)
        except sqlite3.OperationalError as e:
            raise ValueError(str(e)) from None

        if cursor.description is None:
            raise ValueError("Only SELECT queries are allowed")

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
                "SELECT key_path, type, count, sample_values, description FROM _schema WHERE collection = ?",
                (collection,),
            ).fetchall()
            result = {
                "collection": collection,
                "metadata_keys": {},
            }
            for row in rows:
                entry = {
                    "type": row[1],
                    "count": row[2],
                    "values": json.loads(row[3]) if row[3] else [],
                }
                if row[4] is not None:
                    entry["description"] = row[4]
                result["metadata_keys"][row[0]] = entry
            return result
        else:
            result = {}
            for row in self.conn.execute(
                "SELECT DISTINCT collection FROM _schema"
            ):
                result[row[0]] = self.get_schema(row[0])
            return result

    def merge_curated_schema(
        self, collection: str, curated_keys: Dict[str, SchemaEntry]
    ) -> None:
        """Update _schema rows with curated descriptions and values.

        Keys in curated but not in data are added with count=0.
        """
        existing = {}
        for row in self.conn.execute(
            "SELECT key_path, type, count, sample_values, description FROM _schema WHERE collection = ?",
            (collection,),
        ).fetchall():
            existing[row[0]] = SchemaEntry(
                type=row[1],
                count=row[2],
                values=json.loads(row[3]) if row[3] else None,
                description=row[4],
            )

        merged = merge_schema(existing, curated_keys)

        self.conn.execute(
            "DELETE FROM _schema WHERE collection = ?", (collection,)
        )
        for key, entry in merged.items():
            sample = (
                entry.values
                if entry.values
                else ([entry.example] if entry.example else [])
            )
            self.conn.execute(
                "INSERT INTO _schema (collection, key_path, type, count, sample_values, description) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    collection,
                    key,
                    entry.type,
                    entry.count,
                    json.dumps(sample) if sample else None,
                    entry.description,
                ),
            )
        self.conn.commit()

    def _store_readme_metadata(self, readme) -> None:
        """Store README frontmatter and body in _metadata KV table."""
        import yaml

        if readme.frontmatter:
            self.conn.execute(
                "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
                ("readme_frontmatter", yaml.dump(
                    readme.frontmatter,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )),
            )
        if readme.body:
            self.conn.execute(
                "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
                ("readme_body", readme.body),
            )
        self.conn.commit()

    def _load_readme_metadata(self):
        """Load README data from _metadata table. Returns Readme or None."""
        import yaml
        from .readme import Readme

        try:
            rows = self.conn.execute(
                "SELECT key, value FROM _metadata"
            ).fetchall()
        except sqlite3.OperationalError:
            return None

        meta = {row[0]: row[1] for row in rows}
        if not meta:
            return None

        frontmatter = {}
        if "readme_frontmatter" in meta:
            fm = yaml.safe_load(meta["readme_frontmatter"])
            if isinstance(fm, dict):
                frontmatter = fm

        return Readme(
            frontmatter=frontmatter,
            body=meta.get("readme_body", ""),
        )

    def export(self, output_dir: Union[str, Path]) -> None:
        """Export database to JSONL files + README.md + schema.yaml."""
        from .readme import Readme, save_readme
        from .schema import CollectionSchema, save_schema_yaml

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        schemas = {}
        contents = []

        for row in self.conn.execute(
            "SELECT DISTINCT collection FROM records"
        ):
            coll_name = row[0]
            jsonl_path = output_dir / f"{coll_name}.jsonl"

            count = 0
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for rec_row in self.conn.execute(
                    "SELECT mimetype, uri, content, timestamp, metadata FROM records WHERE collection = ? ORDER BY id",
                    (coll_name,),
                ):
                    record = Record(
                        mimetype=rec_row[0],
                        uri=rec_row[1],
                        content=rec_row[2],
                        timestamp=rec_row[3],
                        metadata=json.loads(rec_row[4])
                        if rec_row[4]
                        else None,
                    )
                    f.write(record.to_json() + "\n")
                    count += 1

            # Build collection schema
            schema_data = self.get_schema(coll_name)
            metadata_keys = {}
            for key_name, key_info in schema_data.get("metadata_keys", {}).items():
                metadata_keys[key_name] = SchemaEntry(
                    type=key_info["type"],
                    count=key_info["count"],
                    values=key_info.get("values") or None,
                    description=key_info.get("description"),
                )
            schemas[coll_name] = CollectionSchema(
                record_count=count,
                metadata_keys=metadata_keys,
            )

            contents.append({"path": f"{coll_name}.jsonl"})

        # Restore README metadata from _metadata table
        readme = self._load_readme_metadata()
        if readme is None:
            readme = Readme()

        # Ensure contents list in frontmatter reflects actual collections
        # Preserve existing descriptions from stored frontmatter
        stored_contents = {}
        for item in readme.frontmatter.get("contents", []):
            if isinstance(item, dict) and "path" in item:
                stored_contents[item["path"]] = item

        updated_contents = []
        for item in contents:
            stored = stored_contents.get(item["path"], {})
            entry = {"path": item["path"]}
            if "description" in stored:
                entry["description"] = stored["description"]
            updated_contents.append(entry)

        readme.frontmatter["contents"] = updated_contents
        save_readme(readme, output_dir / "README.md")

        # Write schema.yaml
        save_schema_yaml(schemas, output_dir / "schema.yaml")

    def import_readme(self, readme_path: Union[str, Path]) -> int:
        """Import all collections described in a README.md.

        1. Parse README.md frontmatter → store in _metadata
        2. For each contents entry, import the JSONL file
        3. If sibling schema.yaml exists, merge curated schema

        Returns total records imported.
        """
        from .readme import parse_readme
        from .schema import load_schema_yaml

        readme_path = Path(readme_path)
        readme = parse_readme(readme_path)
        base_dir = readme_path.parent

        # Store README metadata
        self._store_readme_metadata(readme)

        total = 0
        for item in readme.frontmatter.get("contents", []):
            if not isinstance(item, dict) or "path" not in item:
                continue
            jsonl_path = base_dir / item["path"]
            if jsonl_path.exists():
                count = self.import_jsonl(jsonl_path, collection=jsonl_path.stem)
                total += count

        # Merge curated schema if schema.yaml exists
        schema_yaml_path = base_dir / "schema.yaml"
        if schema_yaml_path.exists():
            curated = load_schema_yaml(schema_yaml_path)
            for coll_name, coll_schema in curated.items():
                self.merge_curated_schema(coll_name, coll_schema.metadata_keys)

        return total

    def close(self) -> None:
        self.conn.close()
