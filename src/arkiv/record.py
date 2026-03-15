"""Universal record format."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union


KNOWN_FIELDS = {"mimetype", "uri", "content", "timestamp", "metadata"}


@dataclass
class Record:
    """A single arkiv record.

    All fields optional. Any valid JSON object is a valid record.
    """

    mimetype: Optional[str] = None
    uri: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict, excluding None fields."""
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name) is not None
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


def parse_record(data: Dict[str, Any]) -> Record:
    """Parse a dict into a Record.

    Known fields (mimetype, uri, content, timestamp, metadata) are
    extracted. Unknown fields are merged into metadata.
    """
    metadata = dict(data["metadata"]) if "metadata" in data else None

    # Collect unknown fields into metadata
    unknown = {k: v for k, v in data.items() if k not in KNOWN_FIELDS}
    if unknown:
        metadata = {**(metadata or {}), **unknown}

    return Record(
        mimetype=data.get("mimetype"),
        uri=data.get("uri"),
        content=data.get("content"),
        timestamp=data.get("timestamp"),
        metadata=metadata or None,
    )


def parse_jsonl(path: Union[str, Path]) -> Iterator[Record]:
    """Parse a JSONL file, yielding Records.

    Skips blank lines and invalid JSON.
    """
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield parse_record(data)
