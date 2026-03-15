"""SQLite database for arkiv records."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from .record import Record, parse_jsonl
from .schema import SchemaEntry, CollectionSchema, discover_schema, merge_schema

_UNSAFE_NAMES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def _validate_collection_name(name):
    """Validate a collection name is safe for use as a directory name."""
    if "/" in name or "\\" in name:
        raise ValueError(f"Collection name contains path separator: {name!r}")
    if name.startswith("."):
        raise ValueError(f"Collection name starts with dot: {name!r}")
    if name.lower() in _UNSAFE_NAMES:
        raise ValueError(f"Collection name is OS-reserved: {name!r}")


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
        for key, entry in schema.items():
            if key in existing_desc:
                entry.description = existing_desc[key]
        self._save_schema_entries(collection, schema)

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

    def _save_schema_entries(
        self, collection: str, entries: Dict[str, SchemaEntry]
    ) -> None:
        """Replace _schema rows for a collection with the given entries."""
        self.conn.execute(
            "DELETE FROM _schema WHERE collection = ?", (collection,)
        )
        for key, entry in entries.items():
            sample = entry.values or ([entry.example] if entry.example else [])
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

    @staticmethod
    def _read_only_authorizer(action, *_args):
        """SQLite authorizer that allows only read operations."""
        allowed = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
        }
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """Run a read-only SQL query. Returns list of dicts."""
        normalized = sql.strip().upper()
        if not normalized.startswith(("SELECT", "WITH")):
            raise ValueError("Only SELECT queries are allowed")

        self.conn.set_authorizer(self._read_only_authorizer)
        try:
            cursor = self.conn.execute(sql)

            if cursor.description is None:
                raise ValueError("Only SELECT queries are allowed")

            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            raise ValueError(str(e)) from None
        finally:
            self.conn.set_authorizer(None)

    def get_info(self) -> Dict[str, Any]:
        """Get database info: total records, collections, counts."""
        total = self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

        collections = {}
        for row in self.conn.execute(
            "SELECT collection, COUNT(*) as cnt FROM records GROUP BY collection"
        ):
            collections[row[0]] = {"record_count": row[1]}

        return {"total_records": total, "collections": collections}

    def get_readme(self) -> Optional["Readme"]:
        """Get stored README metadata, or None if not present."""
        return self._load_readme_metadata()

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
        self._save_schema_entries(collection, merged)

    def _store_readme_metadata(self, readme: "Readme") -> None:
        """Store README frontmatter and body in _metadata KV table."""
        upsert = "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)"
        if readme.frontmatter:
            self.conn.execute(
                upsert,
                ("readme_frontmatter", yaml.dump(
                    readme.frontmatter,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )),
            )
        if readme.body:
            self.conn.execute(upsert, ("readme_body", readme.body))
        self.conn.commit()

    def _load_readme_metadata(self) -> Optional["Readme"]:
        """Load README data from _metadata table. Returns Readme or None."""
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

    def export(
        self,
        output_dir: Union[str, Path],
        nested: bool = False,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> None:
        """Export database to JSONL files + README.md + schema.yaml.

        Args:
            output_dir: Directory to write exported files.
            nested: Create a subdirectory per collection with its own README
                and schema.yaml.
            since: Include records with timestamp >= this ISO 8601 date.
            until: Include records through this ISO 8601 date.
        """
        from . import __version__
        from .readme import Readme, save_readme
        from .render import render_schema_detail, render_schema_summary, inject_schema_block, BEGIN_SENTINEL, END_SENTINEL
        from .schema import CollectionSchema, save_schema_yaml
        from .timefilter import build_time_filter

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        time_clause, time_params = build_time_filter(since, until)

        schemas = {}
        contents = []

        # Get stored README for collection ordering and descriptions
        stored_readme = self._load_readme_metadata()
        stored_contents_map = {}
        stored_order = []
        if stored_readme:
            for item in stored_readme.frontmatter.get("contents", []):
                if isinstance(item, dict) and "path" in item:
                    stored_contents_map[item["path"]] = item
                    # Extract collection name from stored path (strip .jsonl or trailing /)
                    p = item["path"]
                    if p.endswith(".jsonl"):
                        stored_order.append(p[:-6])
                    elif p.endswith("/"):
                        stored_order.append(p[:-1])

        for row in self.conn.execute(
            "SELECT DISTINCT collection FROM records"
        ):
            coll_name = row[0]

            if nested:
                _validate_collection_name(coll_name)
                coll_dir = output_dir / coll_name
                coll_dir.mkdir(parents=True, exist_ok=True)
                jsonl_path = coll_dir / f"{coll_name}.jsonl"
            else:
                jsonl_path = output_dir / f"{coll_name}.jsonl"

            base_sql = "SELECT mimetype, uri, content, timestamp, metadata FROM records WHERE collection = ?"
            params: list = [coll_name]
            if time_clause:
                base_sql += f" AND {time_clause}"
                params.extend(time_params)
            base_sql += " ORDER BY id"

            count = 0
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for rec_row in self.conn.execute(base_sql, params):
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

            # Skip empty collections after filtering
            if count == 0:
                jsonl_path.unlink()
                if nested:
                    try:
                        coll_dir.rmdir()
                    except OSError:
                        pass
                continue

            # Build collection schema
            if since or until:
                # Two-pass: recompute schema from the filtered JSONL
                auto_schema = discover_schema(jsonl_path)
                descs = self._load_schema_descriptions(coll_name)
                for key, entry in auto_schema.items():
                    if key in descs:
                        entry.description = descs[key]
                metadata_keys_dict = auto_schema
            else:
                # Existing behavior: read from _schema table
                schema_data = self.get_schema(coll_name)
                metadata_keys_dict = {
                    key_name: SchemaEntry(
                        type=key_info["type"],
                        count=key_info["count"],
                        values=key_info.get("values") or None,
                        description=key_info.get("description"),
                    )
                    for key_name, key_info in schema_data.get("metadata_keys", {}).items()
                }
            coll_schema = CollectionSchema(
                record_count=count,
                metadata_keys=metadata_keys_dict,
            )
            schemas[coll_name] = coll_schema

            if nested:
                # Write per-collection schema.yaml
                save_schema_yaml({coll_name: coll_schema}, coll_dir / "schema.yaml")

                # Write per-collection README
                coll_readme = Readme(
                    frontmatter={
                        "name": coll_name,
                        "record_count": count,
                        "generator": f"arkiv v{__version__}",
                        "arkiv_format": "0.2",
                        "contents": [{"path": f"{coll_name}.jsonl"}],
                    },
                )
                detail_block = render_schema_detail(coll_schema)
                coll_readme.body = inject_schema_block("", "## Metadata Keys\n\n" + detail_block)
                save_readme(coll_readme, coll_dir / "README.md")

                contents.append({"path": f"{coll_name}/"})
            else:
                contents.append({"path": f"{coll_name}.jsonl"})

        # Apply collection ordering from stored README
        if stored_order:
            def _sort_key(item):
                p = item["path"]
                name = p.rstrip("/").removesuffix(".jsonl")
                if name in stored_order:
                    return (0, stored_order.index(name))
                return (1, name)
            contents.sort(key=_sort_key)

        # Restore README metadata from _metadata table
        readme = stored_readme if stored_readme else Readme()

        # Ensure contents list in frontmatter reflects actual collections
        # Preserve existing descriptions from stored frontmatter
        updated_contents = []
        for item in contents:
            # Look up stored description using both flat and nested path forms
            coll_name = item["path"].rstrip("/").removesuffix(".jsonl")
            stored = stored_contents_map.get(f"{coll_name}.jsonl", {})
            if not stored.get("description"):
                stored = stored_contents_map.get(f"{coll_name}/", {})
            entry = {"path": item["path"]}
            if "description" in stored:
                entry["description"] = stored["description"]
            updated_contents.append(entry)

        readme.frontmatter["contents"] = updated_contents
        readme.frontmatter["arkiv_format"] = "0.2"

        raw_table = render_schema_summary(schemas)
        # Build a block with the heading inside sentinels so re-export replaces cleanly
        inner = raw_table[len(BEGIN_SENTINEL) + 1 : -(len(END_SENTINEL) + 1)]
        summary = BEGIN_SENTINEL + "\n## Collections\n\n" + inner + END_SENTINEL + "\n"
        readme.body = inject_schema_block(readme.body, summary)

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
