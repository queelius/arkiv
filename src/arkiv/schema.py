"""Schema discovery for JSONL metadata."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .record import parse_jsonl

MAX_ENUM_VALUES = 20


@dataclass
class SchemaEntry:
    """Discovered schema for a single metadata key."""

    type: str
    count: int
    values: Optional[List[Any]] = None
    example: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"type": self.type, "count": self.count}
        if self.values is not None:
            d["values"] = self.values
        if self.example is not None:
            d["example"] = self.example
        return d


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def discover_schema(path: Union[str, Path]) -> Dict[str, SchemaEntry]:
    """Scan a JSONL file and discover metadata key schemas."""
    key_counts: Dict[str, int] = {}
    key_types: Dict[str, str] = {}
    key_values: Dict[str, set] = {}
    key_example: Dict[str, Any] = {}

    for record in parse_jsonl(path):
        if not record.metadata:
            continue
        for key, value in record.metadata.items():
            key_counts[key] = key_counts.get(key, 0) + 1
            key_types[key] = _json_type(value)

            if key not in key_example:
                key_example[key] = value

            if key not in key_values:
                key_values[key] = set()
            try:
                if isinstance(value, (str, int, float, bool)):
                    key_values[key].add(value)
                else:
                    # Non-hashable types force high cardinality
                    key_values[key] = None
            except TypeError:
                key_values[key] = None

    result = {}
    for key in key_counts:
        values_set = key_values.get(key)
        if values_set is not None and len(values_set) <= MAX_ENUM_VALUES:
            entry = SchemaEntry(
                type=key_types[key],
                count=key_counts[key],
                values=sorted(str(v) for v in values_set)
                if all(isinstance(v, str) for v in values_set)
                else list(values_set),
            )
        else:
            entry = SchemaEntry(
                type=key_types[key],
                count=key_counts[key],
                example=key_example[key],
            )
        result[key] = entry

    return result
