"""Universal record format."""

import json
import math
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple, Union


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


def _json_safe(value: Any) -> Any:
    """A copy of *value* that strict JSON can represent.

    Every non-finite float (``nan``, ``inf``, ``-inf``) inside dicts, lists,
    and tuples is replaced by ``str(value)``: ``json.dumps`` would otherwise
    write the non-standard ``NaN``/``Infinity`` tokens, which strict readers
    (JavaScript's ``JSON.parse``, jq, most other languages) reject. Callers
    serialize the result with ``allow_nan=False`` so nothing slips through.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


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
        return json.dumps(
            _json_safe(self.to_dict()), ensure_ascii=False, allow_nan=False
        )


KNOWN_FIELDS = {f.name for f in fields(Record)}

# The known fields that must be strings: every Record field but ``metadata``.
_STRING_FIELDS = tuple(f.name for f in fields(Record) if f.name != "metadata")


def parse_record(data: Dict[str, Any]) -> Record:
    """Parse a dict into a Record.

    Known fields (mimetype, uri, content, timestamp, metadata) are
    extracted. Unknown fields are merged into metadata, but an explicit
    ``metadata`` object wins over a colliding top-level field: the
    structured value is authoritative and is never silently clobbered by a
    stray field of the same name. (Use ``arkiv detect`` to surface such
    collisions.)

    Input is permissive: a known field with the wrong type is kept, never
    fatal. A ``null`` known field is the same as an absent one. A
    ``metadata`` that is not an object, or a string field (mimetype, uri,
    content, timestamp) that is not a string, is treated as an unknown
    field: it is moved into metadata under its own name and the record
    field is left ``None``. The same precedence applies to these moved
    fields.
    """
    explicit: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    raw_metadata = data.get("metadata")
    if isinstance(raw_metadata, dict):
        explicit = dict(raw_metadata)
    elif raw_metadata is not None:
        extra["metadata"] = raw_metadata

    strings: Dict[str, Optional[str]] = {}
    for name in _STRING_FIELDS:
        value = data.get(name)
        if value is None or isinstance(value, str):
            strings[name] = value
        else:
            strings[name] = None
            extra[name] = value

    # Collect unknown fields too; explicit metadata keys take precedence.
    unknown = {k: v for k, v in data.items() if k not in KNOWN_FIELDS}
    metadata = {**unknown, **extra, **explicit}

    return Record(metadata=metadata or None, **strings)


def parse_jsonl(path: Union[str, Path]) -> Iterator[Record]:
    """Parse a JSONL file, yielding Records.

    Skips blank lines and invalid JSON. A leading UTF-8 byte order mark
    (written by some Windows editors) is ignored, not read as part of the
    first record.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
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
