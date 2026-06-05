"""Universal record format."""

import json
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple, Union


KNOWN_FIELDS = {"mimetype", "uri", "content", "timestamp", "metadata"}


def normalize_timestamp(ts: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Normalize a zoned ISO 8601 timestamp to canonical UTC.

    Returns ``(canonical, original_if_changed)``:

    - A timestamp carrying a timezone (an offset like ``+05:00`` or a
      trailing ``Z``) is converted to UTC and rendered with a ``Z`` suffix;
      the exact original string is returned alongside it so callers can
      preserve it losslessly.
    - A naive (zoneless) timestamp cannot be normalized without assuming a
      zone, so it is returned unchanged with ``original = None``.
    - A timestamp already in canonical ``...Z`` form, an empty/None value,
      or an unparseable string is returned unchanged with ``original =
      None``.

    Normalizing the stored timestamp is what makes lexicographic ordering
    equal chronological ordering and makes ``--since``/``--until`` slices
    correct across timezone offsets.
    """
    if not ts or not isinstance(ts, str):
        return ts, None
    # datetime.fromisoformat (3.8) does not accept a trailing 'Z'; it does
    # accept explicit numeric offsets. Translate 'Z' to '+00:00' first.
    parse_src = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
    try:
        dt = datetime.fromisoformat(parse_src)
    except ValueError:
        return ts, None
    if dt.tzinfo is None:
        return ts, None
    canonical = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if canonical == ts:
        return ts, None
    return canonical, ts


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
