"""Schema-to-markdown rendering with sentinel-based injection."""

import re
from typing import Dict, Optional

from .schema import CollectionSchema, SchemaEntry

BEGIN_SENTINEL = "<!-- arkiv:schema:begin -->"
END_SENTINEL = "<!-- arkiv:schema:end -->"


def _format_values(entry: SchemaEntry) -> str:
    """Format the values/example column for a schema entry.

    Low-cardinality (values list): comma-joined values.
    High-cardinality (example only): *e.g., "example"*.
    Neither: empty string.
    """
    if entry.values is not None:
        return ", ".join(str(v) for v in entry.values)
    if entry.example is not None:
        return f'*e.g., "{entry.example}"*'
    return ""


def render_schema_summary(
    schemas: Dict[str, CollectionSchema],
    heading: Optional[str] = None,
) -> str:
    """Render a summary table of collections with record counts and key lists.

    Returns markdown wrapped in sentinel comments. If `heading` is provided,
    it is inserted as a markdown heading between the opening sentinel and
    the table.
    """
    lines = [BEGIN_SENTINEL]
    if heading:
        lines.append(heading)
        lines.append("")
    lines.append("| Collection | Records | Keys |")
    lines.append("| --- | --- | --- |")
    for name, schema in schemas.items():
        keys = ", ".join(schema.metadata_keys.keys())
        lines.append(f"| {name} | {schema.record_count} | {keys} |")
    lines.append(END_SENTINEL)
    return "\n".join(lines) + "\n"


def render_schema_detail(
    schema: CollectionSchema,
    heading: Optional[str] = None,
) -> str:
    """Render a detailed table of metadata keys for one collection.

    Includes a Description column only if any key has a description.
    Returns markdown wrapped in sentinel comments. If `heading` is provided,
    it is inserted as a markdown heading between the opening sentinel and
    the table.
    """
    has_description = any(
        e.description is not None for e in schema.metadata_keys.values()
    )

    lines = [BEGIN_SENTINEL]
    if heading:
        lines.append(heading)
        lines.append("")
    if has_description:
        lines.append("| Key | Type | Count | Values | Description |")
        lines.append("| --- | --- | --- | --- | --- |")
    else:
        lines.append("| Key | Type | Count | Values |")
        lines.append("| --- | --- | --- | --- |")

    for key, entry in schema.metadata_keys.items():
        values_str = _format_values(entry)
        if has_description:
            desc = entry.description or ""
            lines.append(f"| {key} | {entry.type} | {entry.count} | {values_str} | {desc} |")
        else:
            lines.append(f"| {key} | {entry.type} | {entry.count} | {values_str} |")

    lines.append(END_SENTINEL)
    return "\n".join(lines) + "\n"


def inject_schema_block(body: str, schema_block: str) -> str:
    """Inject a schema block into a markdown body.

    If a matched sentinel pair is found (each sentinel on its own line),
    replace the region between them (inclusive). Otherwise, append the
    block to the body. Prose outside the sentinels is preserved.

    Sentinels must appear on their own line (possibly with surrounding
    whitespace) to be recognized. This prevents stray sentinels in user
    prose (e.g., inside a code fence discussing arkiv) from being matched.
    """
    # Line-anchored: sentinels must be on their own line, possibly with
    # surrounding whitespace. MULTILINE makes ^ and $ match line boundaries.
    pattern = re.compile(
        r"^[ \t]*"
        + re.escape(BEGIN_SENTINEL)
        + r"[ \t]*$"
        + r".*?"
        + r"^[ \t]*"
        + re.escape(END_SENTINEL)
        + r"[ \t]*$",
        re.DOTALL | re.MULTILINE,
    )
    if pattern.search(body):
        # Use a lambda so schema_block is treated literally, not as a
        # regex replacement template (otherwise \1, \g<x>, etc. crash).
        replacement = schema_block.strip()
        return pattern.sub(lambda _m: replacement, body, count=1)
    # Append
    if body and not body.endswith("\n"):
        return body + "\n\n" + schema_block
    if body:
        return body + "\n" + schema_block
    return schema_block
