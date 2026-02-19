"""README.md with YAML frontmatter for arkiv archives."""

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union


@dataclass
class Readme:
    """ECHO-compliant README with YAML frontmatter + markdown body.

    Frontmatter is a plain dict — all keys are preserved on roundtrip.
    Known keys by convention: name, description, datetime, generator, contents.
    """

    frontmatter: Dict[str, Any] = field(default_factory=dict)
    body: str = ""


def split_frontmatter(text: str) -> tuple:
    """Split text into (frontmatter_str, body_str).

    Frontmatter is delimited by --- on its own line at the start.
    Returns ("", text) if no frontmatter found.
    """
    lines = text.split("\n")

    # Must start with ---
    if not lines or lines[0].strip() != "---":
        return ("", text)

    # Find closing ---
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            # Strip leading newline from body
            if body.startswith("\n"):
                body = body[1:]
            return (fm, body)

    # No closing delimiter — treat entire content as body
    return ("", text)


def parse_readme(path: Union[str, Path]) -> Readme:
    """Parse a README.md with YAML frontmatter."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    fm_str, body = split_frontmatter(text)

    if fm_str:
        frontmatter = yaml.safe_load(fm_str)
        if not isinstance(frontmatter, dict):
            frontmatter = {}
    else:
        frontmatter = {}

    return Readme(frontmatter=frontmatter, body=body)


def save_readme(readme: Readme, path: Union[str, Path]) -> None:
    """Write README.md with YAML frontmatter."""
    path = Path(path)
    parts = []

    if readme.frontmatter:
        parts.append("---")
        parts.append(
            yaml.dump(
                readme.frontmatter,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            ).rstrip()
        )
        parts.append("---")
        if readme.body:
            parts.append("")

    if readme.body:
        parts.append(readme.body)

    text = "\n".join(parts)
    if not text.endswith("\n"):
        text += "\n"

    path.write_text(text, encoding="utf-8")
