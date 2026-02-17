"""Manifest for arkiv collections."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class Collection:
    """A single collection entry in a manifest."""

    file: str = ""
    description: Optional[str] = None
    record_count: Optional[int] = None
    schema: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"file": self.file}
        if self.description is not None:
            d["description"] = self.description
        if self.record_count is not None:
            d["record_count"] = self.record_count
        if self.schema is not None:
            d["schema"] = self.schema
        return d


@dataclass
class Manifest:
    """Describes a collection of JSONL files."""

    description: Optional[str] = None
    created: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    collections: List[Collection] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {}
        if self.description is not None:
            d["description"] = self.description
        if self.created is not None:
            d["created"] = self.created
        if self.metadata is not None:
            d["metadata"] = self.metadata
        d["collections"] = [c.to_dict() for c in self.collections]
        return d


def save_manifest(manifest: Manifest, path: Union[str, Path]) -> None:
    """Write manifest to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)


def load_manifest(path: Union[str, Path]) -> Manifest:
    """Load manifest from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    collections = []
    for c in data.get("collections", []):
        collections.append(
            Collection(
                file=c.get("file", ""),
                description=c.get("description"),
                record_count=c.get("record_count"),
                schema=c.get("schema"),
            )
        )

    return Manifest(
        description=data.get("description"),
        created=data.get("created"),
        metadata=data.get("metadata"),
        collections=collections,
    )
