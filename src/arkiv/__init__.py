"""arkiv: Universal personal data format."""

__version__ = "0.1.0"

from .record import Record, parse_record, parse_jsonl
from .schema import SchemaEntry, discover_schema
from .manifest import Manifest, Collection, load_manifest, save_manifest
from .database import Database

__all__ = [
    "Record",
    "parse_record",
    "parse_jsonl",
    "SchemaEntry",
    "discover_schema",
    "Manifest",
    "Collection",
    "load_manifest",
    "save_manifest",
    "Database",
]
