"""arkiv: Universal personal data format."""

__version__ = "0.1.0"

from .record import Record, parse_record, parse_jsonl
from .schema import (
    SchemaEntry,
    CollectionSchema,
    discover_schema,
    load_schema_yaml,
    save_schema_yaml,
)
from .readme import Readme, parse_readme, save_readme
from .database import Database

__all__ = [
    "Record",
    "parse_record",
    "parse_jsonl",
    "SchemaEntry",
    "CollectionSchema",
    "discover_schema",
    "load_schema_yaml",
    "save_schema_yaml",
    "Readme",
    "parse_readme",
    "save_readme",
    "Database",
]
