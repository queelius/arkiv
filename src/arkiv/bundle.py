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

    # Pack a database into a bundle (from arkiv CLI):
    #   arkiv convert archive.db bundle.zip
    # -> library writes the directory form to a tempdir, then packs it.

    # Unpack a bundle into a database (from arkiv CLI):
    #   arkiv convert bundle.zip archive.db
    # -> library extracts bundle.zip to a tempdir, then imports from it.
"""
from __future__ import annotations

import gzip
import io
import json
import shutil
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import IO, Any, Dict, Iterable, Iterator, Mapping, Optional, Tuple, Union


PathLike = Union[str, Path]


def _format_of(path: PathLike) -> Optional[str]:
    """Return ``'zip'``, ``'tar.gz'``, or None."""
    s = str(path).lower()
    if s.endswith(".zip"):
        return "zip"
    if s.endswith(".tar.gz") or s.endswith(".tgz"):
        return "tar.gz"
    return None


# Bundles may come from untrusted sources (a published SPA's arkiv export,
# a shared .zip), so every read is bounded: a cap on the decompressed size
# of what is read, and on the length of one JSONL line, which is otherwise
# read into memory whole.
_MAX_MEMBER_BYTES = 8 * 1024**3  # 8 GiB decompressed, as for unpack_bundle
_MAX_LINE_CHARS = 64 * 1024**2  # one record


class _BoundedReader(io.RawIOBase):
    """A binary stream that raises once more than *limit* bytes are read:
    a guard against decompression bombs in sources with no trustworthy
    declared size (gzip streams above all)."""

    def __init__(self, raw: IO[bytes], limit: int) -> None:
        self._raw = raw
        self._left = limit

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        n = self._raw.readinto(b)  # type: ignore[attr-defined]
        self._left -= n
        if self._left < 0:
            raise ValueError("bundle member exceeds the decompressed size limit")
        return n


def _text(raw: IO[bytes], limit: int) -> IO[str]:
    return io.TextIOWrapper(io.BufferedReader(_BoundedReader(raw, limit)), encoding="utf-8")


def bundle_format(path: PathLike) -> str:
    """Classify *path* as an arkiv container: ``"zip"``, ``"tar.gz"``,
    ``"jsonl.gz"``, ``"jsonl"``, or ``"dir"``.

    Decided by extension, except that an existing directory is always
    ``"dir"``. Any other path is ``"dir"`` too: the canonical, unpacked
    form, and the one a writer creates for an extension-less output path.
    ``"jsonl"``/``"jsonl.gz"`` are a bare record stream (one collection,
    no README or schema), readable but not a :func:`write_bundle` target.
    """
    if Path(path).is_dir():
        return "dir"
    fmt = _format_of(path)
    if fmt is not None:
        return fmt
    s = str(path).lower()
    if s.endswith(".jsonl.gz"):
        return "jsonl.gz"
    if s.endswith(".jsonl"):
        return "jsonl"
    return "dir"


def is_bundle(path: PathLike) -> bool:
    """True when *path* looks like a packed arkiv bundle by extension."""
    return _format_of(path) is not None


# The derived database form (arkiv.db, or any .db/.sqlite beside README.md)
# is regenerable from the directory and is not part of it: a bundle
# serializes the directory form, not its cache. Only the archive *root* holds
# that cache; a database file deeper down (media/viewer.db from an EHR
# export) is content and must be kept. Dot-prefixed entries (.git,
# .DS_Store, ...) are noise.
_DERIVED_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def is_source_path(rel: PurePosixPath) -> bool:
    """Whether an archive-relative path is part of the canonical directory
    form (and so belongs in a bundle and in the source fingerprint)."""
    if any(part.startswith(".") for part in rel.parts):
        return False
    return not (len(rel.parts) == 1 and rel.suffix.lower() in _DERIVED_SUFFIXES)


def _within(child: Path, root: Path) -> bool:
    """True if ``child`` resolves to a location inside ``root``.

    Fails closed: a path that cannot be resolved (symlink loop, over-long name,
    embedded NUL) is not within ``root``.
    """
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def iter_source_files(source_dir: PathLike) -> Iterator[Tuple[str, Path]]:
    """Yield ``(relposix, path)`` for each canonical source file.

    Walks *source_dir* recursively in sorted order, skipping the derived
    database at the root and dot-prefixed entries (:func:`is_source_path`).
    This is the set of files that constitute the authoritative directory
    form: README, schema.yaml, the JSONL collections, and the media/ subtree.
    It is the single walk shared by the source fingerprint, asset import, and
    :func:`pack_bundle`.

    Symlinks are never followed or yielded: an archive from an untrusted
    source could point a link at /dev/zero (DoS) or at a file outside the
    archive (information leak into the database and back out on export). A
    symlink is not part of the canonical directory form, so even a link that
    stays inside the archive is skipped (its real target is yielded in its
    own right). Each path is also resolved and contained, so the guarantee
    never depends on how ``rglob`` treats symlinked directories.
    """
    source_dir = Path(source_dir)
    for p in sorted(source_dir.rglob("*")):
        if p.is_symlink() or not _within(p, source_dir):
            continue
        if not p.is_file():
            continue
        rel = PurePosixPath(p.relative_to(source_dir).as_posix())
        if is_source_path(rel):
            yield rel.as_posix(), p


# Fixed member metadata, so packing identical content yields identical
# bytes: zip's earliest representable date (it cannot store 1970), tar's
# epoch, and no owner identity (which would also leak the packer's uid).
_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o644


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_ZIP_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = _FILE_MODE << 16
    return info


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = 0
    info.mode = _FILE_MODE
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


@contextmanager
def _open_tar_gz_for_write(output: Path) -> Iterator[tarfile.TarFile]:
    """A tar.gz writer whose gzip header is fixed too: ``tarfile.open(
    "w:gz")`` would stamp the wall-clock time and the output file name
    into it."""
    with open(output, "wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tf:
                yield tf


def _check_member_name(name: str) -> str:
    """Reject member names that are absolute or climb out of the archive."""
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name:
        raise ValueError(f"invalid bundle member name: {name!r}")
    return p.as_posix()


def write_bundle(path: PathLike, members: Mapping[str, bytes]) -> None:
    """Write *members* (archive-relative POSIX name -> content) as an arkiv
    archive at *path*: a directory, or a ``.zip`` / ``.tar.gz`` / ``.tgz``
    bundle chosen by extension (see :func:`bundle_format`).

    Bundles are byte-reproducible: members are written in sorted order with
    fixed timestamps, modes, and ownership, so exporting identical records
    twice yields identical files. Parent directories of *path* are created.
    """
    path = Path(path)
    fmt = bundle_format(path)
    if fmt not in ("dir", "zip", "tar.gz"):
        raise ValueError(f"write_bundle: cannot write a bundle as {fmt!r}: {path!s}")
    named = sorted((_check_member_name(n), data) for n, data in members.items())
    if fmt == "dir":
        for name, data in named:
            dest = path / name
            # Never write through a symlink: an existing link at the member
            # path, or a linked parent directory, could point outside *path*.
            if dest.is_symlink() or not _within(dest, path):
                raise ValueError(f"write_bundle: {name!r} would be written outside {path!s}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "zip":
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in named:
                zf.writestr(_zip_info(name), data)
    else:
        with _open_tar_gz_for_write(path) as tf:
            for name, data in named:
                tf.addfile(_tar_info(name, len(data)), io.BytesIO(data))


def records_to_jsonl(records: Iterable[Mapping[str, Any]]) -> bytes:
    """Serialize records as UTF-8 JSONL, one object per line.

    Non-ASCII text is kept as is, and values JSON cannot represent
    (datetimes, Decimals, ...) are written via ``str``.
    """
    return "".join(
        json.dumps(rec, ensure_ascii=False, default=str) + "\n" for rec in records
    ).encode("utf-8")


@contextmanager
def open_member(
    path: PathLike, member: str, *, max_bytes: int = _MAX_MEMBER_BYTES
) -> Iterator[IO[str]]:
    """Open one member of the arkiv archive at *path* for reading as text.

    Works on every :func:`bundle_format`: a directory, a zip, or a tar.gz
    is read in place (streamed, never extracted). A bare ``.jsonl`` or
    ``.jsonl.gz`` *is* its one member, so *member* is ignored for it.

    Raises :class:`FileNotFoundError` when the member is absent or is not a
    regular file inside the archive (a tar link, or a directory-bundle
    symlink, which could point anywhere), and :class:`ValueError` once more
    than *max_bytes* decompressed bytes are read (bomb protection; zip and
    tar members whose declared size is over the limit are refused upfront).
    """
    fmt = bundle_format(path)
    if fmt == "jsonl.gz":
        with open(path, "rb") as raw, gzip.GzipFile(fileobj=raw) as gz:
            with _text(gz, max_bytes) as f:
                yield f
        return
    if fmt in ("jsonl", "dir"):
        target = Path(path)
        if fmt == "dir":
            target = target / _check_member_name(member)
            if target.is_symlink() or not _within(target, Path(path)):
                raise FileNotFoundError(f"{member!r} is not a regular file in {path!s}")
        with open(target, "rb") as raw, _text(raw, max_bytes) as f:
            yield f
        return
    if fmt == "zip":
        with zipfile.ZipFile(path) as zf:
            try:
                info = zf.getinfo(_check_member_name(member))
            except KeyError:
                raise FileNotFoundError(f"{member!r} not in {path!s}") from None
            if info.file_size > max_bytes:
                raise ValueError(f"{member!r} in {path!s} exceeds the size limit")
            with zf.open(info) as raw, _text(raw, max_bytes) as f:
                yield f
        return
    # Stream the tar instead of tf.getmember(), which parses every header in
    # the archive before returning (unbounded for a crafted tar of millions
    # of tiny entries). The scan stops at the first match, counts entries,
    # and reads through a bounded stream, so headers and skipped members
    # alike are charged against max_bytes.
    wanted = _check_member_name(member)
    with open(path, "rb") as raw, gzip.GzipFile(fileobj=raw) as gz:
        bounded = io.BufferedReader(_BoundedReader(gz, max_bytes))
        with tarfile.open(fileobj=bounded, mode="r|") as tf:
            for count, tinfo in enumerate(tf, 1):
                if count > _MAX_BUNDLE_ENTRIES:
                    raise ValueError(f"{path!s} has too many entries; possible tar bomb")
                if PurePosixPath(tinfo.name).as_posix() != wanted:
                    continue
                raw_tar = tf.extractfile(tinfo) if tinfo.isfile() else None
                if raw_tar is None:
                    raise FileNotFoundError(f"{member!r} in {path!s} is not a regular file")
                if tinfo.size > max_bytes:
                    raise ValueError(f"{member!r} in {path!s} exceeds the size limit")
                with raw_tar, _text(raw_tar, max_bytes) as f:
                    yield f
                return
    raise FileNotFoundError(f"{member!r} not in {path!s}")


def iter_jsonl(
    path: PathLike,
    member: str = "records.jsonl",
    *,
    max_bytes: int = _MAX_MEMBER_BYTES,
    max_line_chars: int = _MAX_LINE_CHARS,
) -> Iterator[Dict[str, Any]]:
    """Yield the JSON objects in one JSONL member of an arkiv archive.

    Blank lines, lines that are not valid JSON, and JSON values that are
    not objects are skipped: a record is an object. Missing members raise
    :class:`FileNotFoundError`, and oversized input (more than *max_bytes*
    in all, or one line longer than *max_line_chars*) raises
    :class:`ValueError` rather than being read into memory (see
    :func:`open_member`).
    """
    with open_member(path, member, max_bytes=max_bytes) as f:
        while True:
            line = f.readline(max_line_chars + 1)
            if not line:
                return
            if len(line) > max_line_chars:
                raise ValueError(f"a line in {member!r} exceeds {max_line_chars} characters")
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


# Detection reads one record, so it gets a far smaller budget.
_PEEK_MAX_BYTES = 64 * 1024**2


def peek_jsonl(path: PathLike, member: str = "records.jsonl") -> Optional[Dict[str, Any]]:
    """The first record of a JSONL member, or None if there is none or the
    archive cannot be read at all (missing, corrupt, not UTF-8, or the first
    record lies beyond a small read budget). Meant for format detection,
    where unreadable input is simply "not ours"."""
    try:
        records = iter_jsonl(
            path, member, max_bytes=_PEEK_MAX_BYTES, max_line_chars=_PEEK_MAX_BYTES
        )
        return next(records, None)
    except (OSError, ValueError, EOFError, zipfile.BadZipFile, tarfile.TarError):
        return None


def pack_bundle(directory: PathLike, output: PathLike) -> None:
    """Pack an arkiv directory into a compressed bundle.

    The bundle format is chosen by the output extension:
    ``.zip``/``.tar.gz``/``.tgz``. Files in *directory* (recursively) are
    added with paths relative to the directory as archive names, EXCEPT
    derived database files (``.db``/``.sqlite``/``.sqlite3``) and
    dot-prefixed entries, which are regenerable or noise and do not belong
    in a transport container.

    Like :func:`write_bundle`, the result is byte-reproducible: members go
    in sorted order with fixed timestamps, modes, and ownership.
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

    def _members():
        for rel, p in iter_source_files(directory):
            yield p, rel

    if fmt == "zip":
        with zipfile.ZipFile(output, "w") as zf:
            for p, arcname in _members():
                with open(p, "rb") as src, zf.open(_zip_info(arcname), "w") as dst:
                    shutil.copyfileobj(src, dst)
    else:  # tar.gz
        with _open_tar_gz_for_write(output) as tf:
            for p, arcname in _members():
                with open(p, "rb") as src:
                    tf.addfile(_tar_info(arcname, p.stat().st_size), src)


# Bundles may come from untrusted sources, so extraction is bounded to
# resist zip/tar bombs: a cap on the number of entries and on the total
# uncompressed size (both read from archive metadata before extracting).
_MAX_BUNDLE_ENTRIES = 200_000
_MAX_BUNDLE_BYTES = 8 * 1024**3  # 8 GiB uncompressed


def unpack_bundle(
    bundle: PathLike,
    target_dir: PathLike,
    *,
    max_entries: int = _MAX_BUNDLE_ENTRIES,
    max_total_bytes: int = _MAX_BUNDLE_BYTES,
) -> None:
    """Extract a bundle (zip or tar.gz) into *target_dir*.

    Rejects entries that would escape *target_dir*, and refuses archives
    whose entry count or total uncompressed size exceed the given limits
    (bomb protection).
    """
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
            _safe_extract_zip(zf, target_dir, max_entries, max_total_bytes)
    else:
        with tarfile.open(bundle, "r:gz") as tf:
            _safe_extract_tar(tf, target_dir, max_entries, max_total_bytes)


def _safe_extract_zip(
    zf: zipfile.ZipFile,
    target_dir: Path,
    max_entries: int,
    max_total_bytes: int,
) -> None:
    """Extract a zip, rejecting path-escape entries and bombs."""
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ValueError(
            f"bundle has too many entries ({len(infos)} > {max_entries}); "
            f"possible zip bomb"
        )
    total = 0
    for info in infos:
        dest = target_dir / info.filename
        if not _within(dest, target_dir):
            raise ValueError(
                f"unsafe zip entry (path escape): {info.filename!r}"
            )
        total += info.file_size
        if total > max_total_bytes:
            raise ValueError(
                f"bundle uncompressed size exceeds limit "
                f"({max_total_bytes} bytes); possible zip bomb"
            )
    zf.extractall(target_dir)


def _safe_extract_tar(
    tf: tarfile.TarFile,
    target_dir: Path,
    max_entries: int,
    max_total_bytes: int,
) -> None:
    """Extract a tar, rejecting path-escape entries, escaping links, and bombs."""
    members = tf.getmembers()
    if len(members) > max_entries:
        raise ValueError(
            f"bundle has too many entries ({len(members)} > {max_entries}); "
            f"possible tar bomb"
        )
    total = 0
    for member in members:
        dest = target_dir / member.name
        if not _within(dest, target_dir):
            raise ValueError(
                f"unsafe tar entry (path escape): {member.name!r}"
            )
        # No symlinks escaping either
        if member.issym() or member.islnk():
            link = target_dir / member.linkname
            if not _within(link, target_dir):
                raise ValueError(
                    f"unsafe tar link target: {member.linkname!r}"
                )
        total += member.size
        if total > max_total_bytes:
            raise ValueError(
                f"bundle uncompressed size exceeds limit "
                f"({max_total_bytes} bytes); possible tar bomb"
            )
    # Python 3.12+ accepts filter="data" which also enforces safety; pass it
    # when available to silence the 3.14 deprecation warning and get native
    # protection. Our per-member checks above still run as belt-and-suspenders.
    try:
        tf.extractall(target_dir, filter="data")
    except TypeError:
        tf.extractall(target_dir)
