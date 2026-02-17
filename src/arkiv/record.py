"""Universal record format."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union


KNOWN_FIELDS = {"mimetype", "url", "content", "timestamp", "metadata"}


@dataclass
class Record:
    """A single arkiv record.

    All fields optional. Any valid JSON object is a valid record.
    """

    mimetype: Optional[str] = None
    url: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict, excluding None fields."""
        d = {}
        if self.mimetype is not None:
            d["mimetype"] = self.mimetype
        if self.url is not None:
            d["url"] = self.url
        if self.content is not None:
            d["content"] = self.content
        if self.timestamp is not None:
            d["timestamp"] = self.timestamp
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


def parse_record(data: Dict[str, Any]) -> Record:
    """Parse a dict into a Record.

    Known fields (mimetype, url, content, timestamp, metadata) are
    extracted. Unknown fields are merged into metadata.
    """
    metadata = data.get("metadata")
    if metadata is not None:
        metadata = dict(metadata)
    else:
        metadata = None

    # Collect unknown fields into metadata
    unknown = {k: v for k, v in data.items() if k not in KNOWN_FIELDS}
    if unknown:
        if metadata is None:
            metadata = {}
        metadata.update(unknown)

    return Record(
        mimetype=data.get("mimetype"),
        url=data.get("url"),
        content=data.get("content"),
        timestamp=data.get("timestamp"),
        metadata=metadata if metadata else None,
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
