"""Schema-to-markdown rendering with sentinel-based injection."""

import re
from typing import Dict

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


def render_schema_summary(schemas: Dict[str, CollectionSchema]) -> str:
    """Render a summary table of collections with record counts and key lists.

    Returns markdown wrapped in sentinel comments.
    """
    lines = [BEGIN_SENTINEL]
    lines.append("| Collection | Records | Keys |")
    lines.append("| --- | --- | --- |")
    for name, schema in schemas.items():
        keys = ", ".join(schema.metadata_keys.keys())
        lines.append(f"| {name} | {schema.record_count} | {keys} |")
    lines.append(END_SENTINEL)
    return "\n".join(lines) + "\n"


def render_schema_detail(schema: CollectionSchema) -> str:
    """Render a detailed table of metadata keys for one collection.

    Includes a Description column only if any key has a description.
    Returns markdown wrapped in sentinel comments.
    """
    has_description = any(
        e.description is not None for e in schema.metadata_keys.values()
    )

    lines = [BEGIN_SENTINEL]
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

    If sentinel comments are found, replace the region between them (inclusive).
    Otherwise, append the block to the body.
    Prose outside sentinels is preserved.
    """
    pattern = re.compile(
        re.escape(BEGIN_SENTINEL) + r".*?" + re.escape(END_SENTINEL),
        re.DOTALL,
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
