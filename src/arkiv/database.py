"""SQLite database for arkiv records."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import yaml

from .record import Record, parse_jsonl
from .schema import (
    SchemaEntry,
    CollectionSchema,
    discover_schema,
    discover_schema_from_metadata,
    merge_schema,
)

_UNSAFE_NAMES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}

# Conventional subdirectory for binary assets referenced by file://media/...
# URIs (SPEC 1.2). Its contents are carried through the database form as
# BLOBs in the _assets table so the two forms stay isomorphic.
_MEDIA_DIRNAME = "media"


def _is_within(child: Path, root: Path) -> bool:
    """True if ``child`` is ``root`` or lives under it (both resolved).

    Python 3.8 lacks ``Path.is_relative_to``; this is the portable form.
    """
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# Derived database forms are regenerable, so they are excluded from the
# source fingerprint and from pack_bundle. Dot-prefixed entries are noise.
_DERIVED_DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def iter_source_files(source_dir: Union[str, Path]) -> Iterator[Tuple[str, Path]]:
    """Yield ``(relposix, path)`` for each canonical source file.

    Walks *source_dir* recursively, skipping derived database files
    (``.db``/``.sqlite``/``.sqlite3``) and dot-prefixed entries. This is the
    set of files that constitute the authoritative directory form: README,
    schema.yaml, the JSONL collections, and the media/ subtree.
    """
    source_dir = Path(source_dir)
    for p in sorted(source_dir.rglob("*")):
        # Never follow symlinks: arkiv archives are plain files, and an
        # archive from an untrusted source could point a symlink at
        # /dev/zero (DoS) or a file outside the archive (info leak into the
        # fingerprint). A symlink is not part of the canonical directory form.
        if p.is_symlink():
            continue
        if not p.is_file():
            continue
        rel = p.relative_to(source_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if p.suffix.lower() in _DERIVED_DB_SUFFIXES:
            continue
        yield rel.as_posix(), p


def _source_fingerprint(source_dir: Union[str, Path]) -> str:
    """A content hash of the directory form, stable across re-conversions.

    SHA-256 over each source file's relative path and its own content hash,
    in sorted path order. Two directories with identical canonical files
    (regardless of the derived .db) produce the same fingerprint.
    """
    h = hashlib.sha256()
    for relposix, p in iter_source_files(source_dir):
        h.update(relposix.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def _collection_name_from_path(path: str) -> str:
    """Extract collection name from a contents entry path.

    Handles both flat form ("conversations.jsonl") and nested form
    ("conversations/"). Python 3.8 compatible (no str.removesuffix).
    """
    name = path.rstrip("/")
    if name.endswith(".jsonl"):
        name = name[: -len(".jsonl")]
    return name


def _validate_collection_name(name):
    """Validate a collection name is safe for use as a file/directory name."""
    if not isinstance(name, str) or not name or not name.strip():
        raise ValueError(f"Collection name must be a non-empty string: {name!r}")
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

            CREATE TABLE IF NOT EXISTS _assets (
                path TEXT PRIMARY KEY,
                content BLOB
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
        _validate_collection_name(collection)

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

    def insert_record(
        self,
        collection: str,
        content: str,
        mimetype: str = "text/plain",
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Insert a single record. Append semantics (does not delete existing records).

        Returns dict with id, collection, and timestamp of the inserted record.

        Note: the pre-computed schema in `_schema` is NOT updated by this
        method. New metadata keys from inserted records are invisible to
        `get_schema()` until `refresh_schema(collection)` is called or
        the collection is reimported. This is a deliberate trade-off:
        per-insert schema recomputation would make the write path O(n).
        """
        _validate_collection_name(collection)
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError(
                f"metadata must be a dict or None, got {type(metadata).__name__}"
            )
        if timestamp is None:
            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        metadata_json = json.dumps(metadata) if metadata else None
        cursor = self.conn.execute(
            "INSERT INTO records (collection, mimetype, uri, content, timestamp, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (collection, mimetype, None, content, timestamp, metadata_json),
        )
        # Track that the database has diverged from the directory form since
        # the last conversion, so `arkiv status` can surface unexported writes.
        self._bump_inserts_counter()
        self.conn.commit()
        return {
            "id": cursor.lastrowid,
            "collection": collection,
            "timestamp": timestamp,
        }

    def get_metadata_value(self, key: str) -> Optional[str]:
        """Read a single value from the _metadata KV table, or None."""
        try:
            row = self.conn.execute(
                "SELECT value FROM _metadata WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return row[0] if row else None

    def get_unexported_writes(self) -> int:
        """How many records were inserted since the last conversion."""
        try:
            return int(self.get_metadata_value("inserts_since_convert") or 0)
        except (TypeError, ValueError):
            return 0

    def _bump_inserts_counter(self) -> None:
        """Increment the insert-since-convert counter (caller commits)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO _metadata (key, value) "
            "VALUES ('inserts_since_convert', ?)",
            (str(self.get_unexported_writes() + 1),),
        )

    def store_source_fingerprint(self, source_dir: Union[str, Path]) -> str:
        """Record a content fingerprint of the source directory.

        Called when converting a directory into this database. Stores the
        fingerprint in _metadata and resets the insert-since-convert counter,
        marking the two forms as in sync as of now. Returns the fingerprint.
        """
        fp = _source_fingerprint(Path(source_dir))
        upsert = "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)"
        self.conn.execute(upsert, ("source_fingerprint", fp))
        self.conn.execute(upsert, ("inserts_since_convert", "0"))
        self.conn.commit()
        return fp

    def sync_status(self, source_dir: Union[str, Path]) -> Dict[str, Any]:
        """Report whether this database is in sync with *source_dir*.

        Compares the directory's current content fingerprint against the one
        stored at the last conversion, and reads the insert-since-convert
        counter. ``in_sync`` is true only when a fingerprint was recorded, the
        directory is unchanged, and no records were written since.
        """
        stored = self.get_metadata_value("source_fingerprint")
        inserts = self.get_unexported_writes()
        has_fp = stored is not None
        directory_changed = bool(
            has_fp and _source_fingerprint(Path(source_dir)) != stored
        )
        in_sync = bool(has_fp and not directory_changed and inserts == 0)
        return {
            "has_fingerprint": has_fp,
            "directory_changed": directory_changed,
            "unexported_writes": inserts,
            "in_sync": in_sync,
        }

    def refresh_schema(self, collection: str) -> None:
        """Recompute and persist the schema for a collection.

        Scans all records in the given collection, rebuilds the `_schema`
        rows from scratch, and preserves existing curated descriptions.
        Call this after a batch of `insert_record()` writes to bring the
        pre-computed schema back in sync with the data.
        """
        _validate_collection_name(collection)

        def _metadata_iter():
            for row in self.conn.execute(
                "SELECT metadata FROM records WHERE collection = ?",
                (collection,),
            ):
                if row[0] is None:
                    continue
                yield json.loads(row[0])

        schema = discover_schema_from_metadata(_metadata_iter())
        existing_desc = self._load_schema_descriptions(collection)
        for key, entry in schema.items():
            if key in existing_desc:
                entry.description = existing_desc[key]
        self._save_schema_entries(collection, schema)

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
            sample = entry.values or (
                [entry.example] if entry.example is not None else []
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

    @staticmethod
    def _read_only_authorizer(action, *_args):
        """SQLite authorizer that allows only read operations."""
        allowed = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            # SQLITE_RECURSIVE (action 33): authorizes the recursion step
            # inside a WITH RECURSIVE CTE. It is a read-only operation, and
            # query() already admits the WITH prefix, so without this the
            # authorizer would deny every recursive CTE. getattr keeps the
            # 3.8 floor honest in case the constant name is unavailable; the
            # numeric action code is stable across SQLite versions.
            getattr(sqlite3, "SQLITE_RECURSIVE", 33),
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
        from .render import render_schema_detail, render_schema_summary, inject_schema_block
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
            _validate_collection_name(coll_name)

            if nested:
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
                detail_block = render_schema_detail(
                    coll_schema, heading="## Metadata Keys"
                )
                coll_readme.body = inject_schema_block("", detail_block)
                save_readme(coll_readme, coll_dir / "README.md")

                contents.append({"path": f"{coll_name}/"})
            else:
                contents.append({"path": f"{coll_name}.jsonl"})

        # Apply collection ordering from stored README
        if stored_order:
            def _sort_key(item):
                name = _collection_name_from_path(item["path"])
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
            coll_name = _collection_name_from_path(item["path"])
            stored = stored_contents_map.get(f"{coll_name}.jsonl", {})
            if not stored.get("description"):
                stored = stored_contents_map.get(f"{coll_name}/", {})
            entry = {"path": item["path"]}
            if "description" in stored:
                entry["description"] = stored["description"]
            updated_contents.append(entry)

        readme.frontmatter["contents"] = updated_contents
        readme.frontmatter["arkiv_format"] = "0.2"

        summary = render_schema_summary(schemas, heading="## Collections")
        readme.body = inject_schema_block(readme.body, summary)

        save_readme(readme, output_dir / "README.md")

        # Write schema.yaml
        save_schema_yaml(schemas, output_dir / "schema.yaml")

        # Reconstruct binary assets (media/) from the _assets table. Assets
        # are not timestamped, so a temporal slice still writes all of them
        # rather than risk leaving a referenced resource dangling.
        self._export_assets(output_dir)

    def _export_assets(self, output_dir: Path) -> None:
        """Write every row of _assets back to ``output_dir/<path>``.

        Each path is validated to stay within ``output_dir`` (defending
        against a crafted database with an escaping asset path). Databases
        created before the _assets table existed simply have nothing to
        write.
        """
        try:
            rows = self.conn.execute("SELECT path, content FROM _assets").fetchall()
        except sqlite3.OperationalError:
            return  # pre-_assets database: no assets to reconstruct

        out_root = output_dir.resolve()
        for row in rows:
            rel, content = row[0], row[1]
            dest = output_dir / rel
            if not _is_within(dest, out_root):
                raise ValueError(
                    f"unsafe asset path (escapes the output directory): {rel!r}"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content if content is not None else b"")

    def import_assets(self, source_dir: Union[str, Path]) -> int:
        """Slurp an archive's ``media/`` subtree into the ``_assets`` table.

        Binary assets referenced by ``file://media/...`` URIs are stored as
        BLOBs keyed by their archive-relative POSIX path, so the database
        form is a complete peer of the directory form and a db -> dir export
        can reconstruct them byte-for-byte. Replace semantics: existing rows
        are cleared first, keeping re-import idempotent. Returns the number
        of asset files stored.
        """
        source_dir = Path(source_dir)
        media_dir = source_dir / _MEDIA_DIRNAME
        self.conn.execute("DELETE FROM _assets")
        count = 0
        if media_dir.is_dir():
            for p in sorted(media_dir.rglob("*")):
                if p.is_file():
                    rel = p.relative_to(source_dir).as_posix()
                    self.conn.execute(
                        "INSERT OR REPLACE INTO _assets (path, content) "
                        "VALUES (?, ?)",
                        (rel, p.read_bytes()),
                    )
                    count += 1
        self.conn.commit()
        return count

    def import_readme(self, readme_path: Union[str, Path]) -> int:
        """Import all collections described in a README.md.

        1. Parse README.md frontmatter → store in _metadata
        2. For each contents entry, import the JSONL file
        3. If sibling schema.yaml exists, merge curated schema
        4. Slurp the media/ subtree into _assets

        Returns total records imported.
        """
        from .readme import parse_readme
        from .schema import load_schema_yaml

        readme_path = Path(readme_path)
        readme = parse_readme(readme_path)
        base_dir = readme_path.parent

        # Store README metadata
        self._store_readme_metadata(readme)

        # Track which collection each source path claims, so two contents
        # entries that resolve to the same collection name raise instead of
        # silently destroying the first via import_jsonl's replace semantics.
        # A fresh map per top-level import keeps legitimate re-imports (the
        # same archive converted twice) idempotent rather than self-colliding.
        seen: Dict[str, Path] = {}

        total = 0
        for item in readme.frontmatter.get("contents", []):
            if not isinstance(item, dict) or "path" not in item:
                continue
            entry_path = base_dir / item["path"]
            if entry_path.is_dir():
                sub_readme = entry_path / "README.md"
                if sub_readme.exists():
                    total += self._import_nested_readme(sub_readme, seen, base_dir)
            elif entry_path.suffix == ".jsonl" and entry_path.exists():
                total += self._import_collection_checked(entry_path, seen, base_dir)

        # Merge curated schema if schema.yaml exists
        schema_yaml_path = base_dir / "schema.yaml"
        if schema_yaml_path.exists():
            curated = load_schema_yaml(schema_yaml_path)
            for coll_name, coll_schema in curated.items():
                self.merge_curated_schema(coll_name, coll_schema.metadata_keys)

        # Carry binary assets (media/) into the database form.
        self.import_assets(base_dir)

        return total

    def _import_collection_checked(
        self,
        entry_path: Path,
        seen: Dict[str, Path],
        archive_root: Path,
    ) -> int:
        """Import one JSONL collection, raising on a name collision.

        Collection identity is the filename stem (SPEC 1.2), so two contents
        entries at different paths can resolve to the same collection. Because
        import_jsonl uses replace semantics, importing the second would
        silently delete the first. Detect that here and raise a clear error
        naming both sources (relative to the archive root) so the user can
        rename one.
        """
        name = entry_path.stem
        resolved = entry_path.resolve()
        if name in seen and seen[name] != resolved:

            def _rel(p: Path) -> Path:
                try:
                    return p.relative_to(archive_root.resolve())
                except ValueError:
                    return p

            raise ValueError(
                f"collection name collision: {name!r}\n"
                f"  {_rel(seen[name])}  and  {_rel(resolved)}\n"
                f"  both map to collection {name!r}. Rename one so each "
                f"collection is unique within the archive."
            )
        seen[name] = resolved
        return self.import_jsonl(entry_path, collection=name)

    def _import_nested_readme(
        self,
        readme_path: Union[str, Path],
        seen: Dict[str, Path],
        archive_root: Path,
    ) -> int:
        """Import contents of a nested README without storing its metadata."""
        from .readme import parse_readme
        from .schema import load_schema_yaml

        readme_path = Path(readme_path)
        sub_readme = parse_readme(readme_path)
        base_dir = readme_path.parent
        total = 0

        for item in sub_readme.frontmatter.get("contents", []):
            if not isinstance(item, dict) or "path" not in item:
                continue
            entry_path = base_dir / item["path"]
            if entry_path.suffix == ".jsonl" and entry_path.exists():
                total += self._import_collection_checked(entry_path, seen, archive_root)

        # Merge per-collection schema.yaml if present
        schema_yaml_path = base_dir / "schema.yaml"
        if schema_yaml_path.exists():
            curated = load_schema_yaml(schema_yaml_path)
            for coll_name, coll_schema in curated.items():
                self.merge_curated_schema(coll_name, coll_schema.metadata_keys)

        return total

    def close(self) -> None:
        self.conn.close()
