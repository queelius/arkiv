"""Compressed bundle support for arkiv archives.

An arkiv directory (README.md + schema.yaml + *.jsonl) can be packed into a
single ``.zip`` or ``.tar.gz`` file for sharing. This module provides
symmetric ``pack_bundle`` / ``unpack_bundle`` helpers, plus an ``is_bundle``
detection function that the CLI uses to decide whether an input/output
path refers to a directory or a compressed bundle.

Compression choices are zip (DEFLATE) and tar.gz (gzip). Both are in the
Python standard library and supported by every OS; we avoid modern formats
like zstd/xz so bundles remain openable on any machine for decades.

Typical flow::

    # Export (from arkiv CLI):
    #   arkiv export archive.db bundle.zip
    # → library writes to a tempdir, then packs into bundle.zip.

    # Import (from arkiv CLI):
    #   arkiv import bundle.zip --db archive.db
    # → library extracts bundle.zip to a tempdir, then imports from it.
"""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path
from typing import Optional, Union


PathLike = Union[str, Path]


def _format_of(path: PathLike) -> Optional[str]:
    """Return ``'zip'``, ``'tar.gz'``, or None."""
    s = str(path).lower()
    if s.endswith(".zip"):
        return "zip"
    if s.endswith(".tar.gz") or s.endswith(".tgz"):
        return "tar.gz"
    return None


def is_bundle(path: PathLike) -> bool:
    """True when *path* looks like a packed arkiv bundle by extension."""
    return _format_of(path) is not None


def pack_bundle(directory: PathLike, output: PathLike) -> None:
    """Pack an arkiv directory into a compressed bundle.

    The bundle format is chosen by the output extension:
    ``.zip``/``.tar.gz``/``.tgz``. All files in *directory* (recursively)
    are added, with paths relative to the directory as archive names.
    """
    directory = Path(directory)
    output = Path(output)
    fmt = _format_of(output)
    if fmt is None:
        raise ValueError(
            f"pack_bundle: {output!s} has no recognized bundle extension "
            f"(want .zip, .tar.gz, or .tgz)"
        )
    if not directory.is_dir():
        raise NotADirectoryError(str(directory))

    if fmt == "zip":
        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            for p in sorted(directory.rglob("*")):
                if p.is_file():
                    zf.write(p, arcname=str(p.relative_to(directory)))
    else:  # tar.gz
        with tarfile.open(output, "w:gz") as tf:
            for p in sorted(directory.rglob("*")):
                if p.is_file():
                    tf.add(p, arcname=str(p.relative_to(directory)))


def unpack_bundle(bundle: PathLike, target_dir: PathLike) -> None:
    """Extract a bundle (zip or tar.gz) into *target_dir*."""
    bundle = Path(bundle)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    fmt = _format_of(bundle)
    if fmt is None:
        raise ValueError(
            f"unpack_bundle: {bundle!s} has no recognized bundle extension"
        )
    if fmt == "zip":
        with zipfile.ZipFile(bundle) as zf:
            _safe_extract_zip(zf, target_dir)
    else:
        with tarfile.open(bundle, "r:gz") as tf:
            _safe_extract_tar(tf, target_dir)


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract a zip, rejecting entries that would escape target_dir
    (e.g. absolute paths or ``..`` traversal)."""
    root = target_dir.resolve()
    for info in zf.infolist():
        dest = (target_dir / info.filename).resolve()
        if not str(dest).startswith(str(root)):
            raise ValueError(
                f"unsafe zip entry (path escape): {info.filename!r}"
            )
    zf.extractall(target_dir)


def _safe_extract_tar(tf: tarfile.TarFile, target_dir: Path) -> None:
    """Extract a tar, rejecting entries that would escape target_dir."""
    root = target_dir.resolve()
    for member in tf.getmembers():
        dest = (target_dir / member.name).resolve()
        if not str(dest).startswith(str(root)):
            raise ValueError(
                f"unsafe tar entry (path escape): {member.name!r}"
            )
        # No symlinks escaping either
        if member.issym() or member.islnk():
            link = (target_dir / member.linkname).resolve()
            if not str(link).startswith(str(root)):
                raise ValueError(
                    f"unsafe tar link target: {member.linkname!r}"
                )
    # Python 3.12+ accepts filter="data" which also enforces safety; pass it
    # when available to silence the 3.14 deprecation warning and get native
    # protection. Our per-member checks above still run as belt-and-suspenders.
    try:
        tf.extractall(target_dir, filter="data")
    except TypeError:
        tf.extractall(target_dir)
