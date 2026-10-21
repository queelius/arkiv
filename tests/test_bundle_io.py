"""Tests for the in-memory bundle API shared by the *-memex archives:
write_bundle / records_to_jsonl (export) and open_member / iter_jsonl /
peek_jsonl (import), plus pack_bundle determinism."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import time
import tracemalloc
import zipfile

import pytest

from arkiv import bundle
from arkiv import (
    bundle_format,
    iter_jsonl,
    open_member,
    pack_bundle,
    peek_jsonl,
    records_to_jsonl,
    unpack_bundle,
    write_bundle,
)

RECORDS = [{"uri": "x://a/1", "content": "héllo"}, {"uri": "x://a/2", "n": 2}]
MEMBERS = {
    "records.jsonl": records_to_jsonl(RECORDS),
    "README.md": b"---\nname: t\n---\n",
    "media/img.bin": b"\x00\x01",
}
WRITABLE = ["out", "out.zip", "out.tar.gz", "out.tgz"]


class TestBundleFormat:
    @pytest.mark.parametrize(
        "name, fmt",
        [
            ("a.zip", "zip"), ("a.ZIP", "zip"), ("a.tar.gz", "tar.gz"), ("a.tgz", "tar.gz"),
            ("a.jsonl", "jsonl"), ("a.jsonl.gz", "jsonl.gz"), ("a", "dir"), ("a.txt", "dir"),
        ],
    )
    def test_by_extension(self, tmp_path, name, fmt):
        assert bundle_format(tmp_path / name) == fmt

    def test_existing_directory_is_dir(self, tmp_path):
        (tmp_path / "looks.zip").mkdir()
        assert bundle_format(tmp_path / "looks.zip") == "dir"


class TestWriteAndRead:
    @pytest.mark.parametrize("name", WRITABLE)
    def test_round_trip(self, tmp_path, name):
        out = tmp_path / "nested" / name  # parent is created
        write_bundle(out, MEMBERS)
        assert list(iter_jsonl(out)) == RECORDS
        with open_member(out, "README.md") as f:
            assert f.read() == "---\nname: t\n---\n"

    @pytest.mark.parametrize("name", ["out.zip", "out.tar.gz"])
    def test_byte_reproducible(self, tmp_path, name):
        """Identical content -> identical bytes, regardless of when it is
        written or what the output file is called (gzip FNAME)."""
        a = tmp_path / "a" / name
        b = tmp_path / "b" / ("renamed-" + name)
        write_bundle(a, MEMBERS)
        time.sleep(1.1)  # cross a second boundary: timestamps must not leak
        write_bundle(b, dict(reversed(list(MEMBERS.items()))))
        assert a.read_bytes() == b.read_bytes()

    def test_zip_members_carry_fixed_date(self, tmp_path):
        """zip stores DOS time at 2s resolution, so a sleep-based check is
        weak; assert the stored timestamp directly."""
        out = tmp_path / "o.zip"
        write_bundle(out, MEMBERS)
        with zipfile.ZipFile(out) as zf:
            assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}

    def test_tar_members_carry_no_owner_or_time(self, tmp_path):
        out = tmp_path / "o.tar.gz"
        write_bundle(out, MEMBERS)
        with tarfile.open(out) as tf:
            for m in tf.getmembers():
                assert (m.mtime, m.uid, m.gid, m.uname, m.gname) == (0, 0, 0, "", "")

    @pytest.mark.parametrize("bad", ["../escape", "/abs", "a/../../b", "", "a\\b"])
    def test_rejects_unsafe_member_names(self, tmp_path, bad):
        with pytest.raises(ValueError):
            write_bundle(tmp_path / "o.zip", {bad: b"x"})

    @pytest.mark.parametrize("name", ["o.jsonl", "o.jsonl.gz"])
    def test_rejects_stream_targets(self, tmp_path, name):
        with pytest.raises(ValueError):
            write_bundle(tmp_path / name, MEMBERS)


class TestReadEdgeCases:
    @pytest.mark.parametrize("name", WRITABLE)
    def test_missing_member_is_file_not_found(self, tmp_path, name):
        out = tmp_path / name
        write_bundle(out, {"README.md": b"x"})
        with pytest.raises(FileNotFoundError):
            list(iter_jsonl(out))

    def test_tar_link_member_is_refused(self, tmp_path):
        out = tmp_path / "link.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            info = tarfile.TarInfo("records.jsonl")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        with pytest.raises(FileNotFoundError):
            list(iter_jsonl(out))

    def test_skips_blank_malformed_and_non_object_lines(self, tmp_path):
        out = tmp_path / "r.jsonl"
        out.write_text('{"a": 1}\n\n  \nnot json\n[1, 2]\n"str"\n{"b": 2}\n', encoding="utf-8")
        assert list(iter_jsonl(out)) == [{"a": 1}, {"b": 2}]

    def test_bare_jsonl_gz_ignores_member_name(self, tmp_path):
        out = tmp_path / "r.jsonl.gz"
        out.write_bytes(gzip.compress(records_to_jsonl(RECORDS)))
        assert list(iter_jsonl(out, member="anything.jsonl")) == RECORDS

    def test_peek(self, tmp_path):
        out = tmp_path / "o.zip"
        write_bundle(out, MEMBERS)
        assert peek_jsonl(out) == RECORDS[0]
        assert peek_jsonl(out, "absent.jsonl") is None

    @pytest.mark.parametrize("name", ["bad.zip", "bad.tar.gz", "bad.jsonl.gz"])
    def test_peek_corrupt_archive_is_none(self, tmp_path, name):
        out = tmp_path / name
        out.write_bytes(b"definitely not an archive")
        assert peek_jsonl(out) is None

    def test_peek_non_utf8_is_none(self, tmp_path):
        out = tmp_path / "r.jsonl"
        out.write_bytes(b"\xff\xfe\x00garbage\n")
        assert peek_jsonl(out) is None


def test_records_to_jsonl_handles_non_json_values():
    from datetime import datetime

    line = records_to_jsonl([{"t": datetime(2026, 1, 2, 3, 4, 5), "s": "é"}]).decode()
    assert json.loads(line) == {"t": "2026-01-02 03:04:05", "s": "é"}
    assert "é" in line  # not \\u-escaped


@pytest.mark.parametrize("ext", ["zip", "tar.gz"])
def test_pack_bundle_is_byte_reproducible(tmp_path, ext):
    src = tmp_path / "src"
    (src / "media").mkdir(parents=True)
    (src / "records.jsonl").write_bytes(records_to_jsonl(RECORDS))
    (src / "media" / "img.bin").write_bytes(b"\x00\x01")
    a, b = tmp_path / f"a.{ext}", tmp_path / f"b.{ext}"
    pack_bundle(src, a)
    time.sleep(1.1)
    (src / "records.jsonl").touch()  # a new mtime must not change the bytes
    pack_bundle(src, b)
    assert a.read_bytes() == b.read_bytes()
    assert list(iter_jsonl(b)) == RECORDS


class TestUntrustedInput:
    """Bundles can come from anywhere: reads are bounded and never follow
    links out of the archive."""

    def test_gzip_stream_over_limit_raises(self, tmp_path):
        out = tmp_path / "bomb.jsonl.gz"
        out.write_bytes(gzip.compress(b'{"a": 1}\n' * 200_000))  # ~1.8 MB from ~2 KB
        with pytest.raises(ValueError):
            list(iter_jsonl(out, max_bytes=100_000))

    @pytest.mark.parametrize("name", ["o.zip", "o.tar.gz"])
    def test_declared_size_over_limit_refused_upfront(self, tmp_path, name):
        out = tmp_path / name
        write_bundle(out, {"records.jsonl": b'{"a": 1}\n' * 1000})
        with pytest.raises(ValueError):
            list(iter_jsonl(out, max_bytes=100))

    def test_overlong_line_raises_not_buffers(self, tmp_path):
        out = tmp_path / "r.jsonl"
        out.write_text('{"a": "' + "x" * 5000 + '"}\n', encoding="utf-8")
        with pytest.raises(ValueError):
            list(iter_jsonl(out, max_line_chars=1000))
        assert list(iter_jsonl(out)) == [{"a": "x" * 5000}]

    def test_peek_of_bomb_is_none(self, tmp_path, monkeypatch):
        import arkiv.bundle as bundle

        monkeypatch.setattr(bundle, "_PEEK_MAX_BYTES", 1000)
        out = tmp_path / "bomb.jsonl.gz"
        out.write_bytes(gzip.compress(b" " * 100_000 + b'{"a": 1}\n'))
        assert peek_jsonl(out) is None

    def test_dir_member_symlink_out_of_archive_refused(self, tmp_path):
        secret = tmp_path / "secret.jsonl"
        secret.write_text('{"secret": true}\n', encoding="utf-8")
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "records.jsonl").symlink_to(secret)
        with pytest.raises(FileNotFoundError):
            list(iter_jsonl(archive))

    def test_write_bundle_will_not_write_through_symlink(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "media").symlink_to(outside)
        with pytest.raises(ValueError):
            write_bundle(archive, {"media/x.bin": b"x"})
        assert not (outside / "x.bin").exists()
        (archive / "records.jsonl").symlink_to(outside / "target")
        with pytest.raises(ValueError):
            write_bundle(archive, {"records.jsonl": b"{}"})
        assert not (outside / "target").exists()


@pytest.mark.parametrize("name", WRITABLE)
def test_str_paths_work_everywhere(tmp_path, name):
    """Callers pass plain strings as often as Paths."""
    out = str(tmp_path / name)
    write_bundle(out, MEMBERS)
    assert bundle_format(out) in ("dir", "zip", "tar.gz")
    assert list(iter_jsonl(out)) == RECORDS
    assert peek_jsonl(out) == RECORDS[0]
    with open_member(out, "README.md") as f:
        assert f.read().startswith("---")


class TestTarScanIsBounded:
    def test_many_entries_before_member_hits_entry_cap(self, tmp_path, monkeypatch):
        import arkiv.bundle as bundle

        monkeypatch.setattr(bundle, "_MAX_BUNDLE_ENTRIES", 50)
        out = tmp_path / "many.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            for i in range(100):
                info = tarfile.TarInfo(f"junk/{i}")
                tf.addfile(info, io.BytesIO(b""))
            data = records_to_jsonl(RECORDS)
            info = tarfile.TarInfo("records.jsonl")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        with pytest.raises(ValueError):
            list(iter_jsonl(out))

    def test_scan_bytes_count_against_limit(self, tmp_path):
        out = tmp_path / "big-prefix.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            filler = b"\0" * 200_000
            info = tarfile.TarInfo("filler.bin")
            info.size = len(filler)
            tf.addfile(info, io.BytesIO(filler))
            data = records_to_jsonl(RECORDS)
            info = tarfile.TarInfo("records.jsonl")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        with pytest.raises(ValueError):
            list(iter_jsonl(out, max_bytes=50_000))
        assert list(iter_jsonl(out)) == RECORDS

    def test_dot_slash_member_names_match(self, tmp_path):
        out = tmp_path / "dot.tar.gz"
        data = records_to_jsonl(RECORDS)
        with tarfile.open(out, "w:gz") as tf:
            info = tarfile.TarInfo("./records.jsonl")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        assert list(iter_jsonl(out)) == RECORDS


def test_only_the_root_database_is_derived(tmp_path):
    """arkiv.db beside README.md is the regenerable cache; a database file
    deeper in the tree (an EHR export's media/viewer.db) is content."""
    from arkiv.database import iter_source_files

    src = tmp_path / "src"
    (src / "media").mkdir(parents=True)
    (src / "records.jsonl").write_bytes(records_to_jsonl(RECORDS))
    (src / "arkiv.db").write_bytes(b"cache")
    (src / "media" / "viewer.db").write_bytes(b"content")
    (src / "media" / "scan.sqlite").write_bytes(b"content")
    out = tmp_path / "o.zip"
    pack_bundle(src, out)
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == ["media/scan.sqlite", "media/viewer.db", "records.jsonl"]
    assert [rel for rel, _ in iter_source_files(src)] == [
        "media/scan.sqlite", "media/viewer.db", "records.jsonl",
    ]


def tar_gz_with_long_name(tmp_path, name_len, fmt):
    """A tar.gz whose one member has a *name_len*-character name, which
    tarfile writes as a GNU long-name header or a pax header by *fmt*. A
    huge name compresses to a few KB but would decompress to a header that
    tarfile reads into memory whole."""
    out = tmp_path / f"longname-{fmt}.tar.gz"
    data = records_to_jsonl(RECORDS)
    with tarfile.open(out, "w:gz", format=fmt) as tf:
        info = tarfile.TarInfo("n" * name_len)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return out


class TestHostileTarHeaders:
    @pytest.mark.parametrize("fmt", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
    def test_iter_jsonl_rejects_huge_tar_header(self, tmp_path, fmt):
        path = tar_gz_with_long_name(tmp_path, 4 * 1024 * 1024, fmt)
        tracemalloc.start()
        try:
            with pytest.raises(ValueError, match="header"):
                list(iter_jsonl(path, "records.jsonl"))
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert peak < 3 * 1024 * 1024

    @pytest.mark.parametrize("fmt", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
    def test_ordinary_long_member_name_still_reads(self, tmp_path, fmt):
        # Several components, each under the OS's 255-byte limit.
        name = "/".join(["d" * 95, "e" * 95, "f" * 95, "records.jsonl"])
        assert len(name) >= 300
        out = tmp_path / "long.tar.gz"
        data = records_to_jsonl(RECORDS)
        with tarfile.open(out, "w:gz", format=fmt) as tf:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        assert list(iter_jsonl(out, name)) == RECORDS
        dst = tmp_path / "dst"
        unpack_bundle(out, dst)
        assert (dst / name).read_bytes() == data


# ── hand-built hostile tar streams ─────────────────────────────

_BLOCK = tarfile.BLOCKSIZE


def _pad(data):
    return data + b"\0" * (-len(data) % _BLOCK)


def _raw_header(name, size, typeflag):
    """One ustar header block with an arbitrary type flag (tarfile itself
    will not write, say, a GNU long-name header followed by another)."""
    info = tarfile.TarInfo(name)
    info.size = size
    block = bytearray(info.tobuf(format=tarfile.USTAR_FORMAT))
    block[156:157] = typeflag
    block[148:156] = b"        "
    block[148:156] = b"%06o\0 " % sum(block)
    return bytes(block)


def _pax_record(keyword, value):
    """A self-describing pax record: ``"<len> <keyword>=<value>\\n"``."""
    body = f" {keyword}={value}\n"
    length = len(body)
    while len(str(length)) + len(body) != length:
        length = len(str(length)) + len(body)
    return f"{length}{body}".encode()


def _tar_gz_stream(tmp_path, name, blocks):
    """Gzip raw tar *blocks*, end with records.jsonl and the end marker."""
    data = records_to_jsonl(RECORDS)
    raw = b"".join(blocks)
    raw += _raw_header("records.jsonl", len(data), tarfile.REGTYPE) + _pad(data)
    out = tmp_path / name
    out.write_bytes(gzip.compress(raw + b"\0" * (2 * _BLOCK)))
    return out


def tar_gz_header_chain(tmp_path, kind, n, each):
    """*n* chained extended headers of *each* bytes before one member: GNU
    long names, or pax records. Each is under the per-header cap."""
    if kind == "gnu":
        typeflag, payload = tarfile.GNUTYPE_LONGNAME, b"n" * each
    else:
        typeflag, payload = tarfile.XHDTYPE, _pax_record("comment", "v" * (each - 20))
    link = _raw_header("././@LongLink", len(payload), typeflag) + _pad(payload)
    return _tar_gz_stream(tmp_path, f"chain-{kind}.tar.gz", [link] * n)


def _old_gnu_sparse(tmp_path, n_blocks):
    """An old-GNU sparse member chaining *n_blocks* extension blocks of 21
    map entries each: a map of unbounded length, unknown upfront."""
    info = tarfile.TarInfo("records.jsonl")
    info.type = tarfile.GNUTYPE_SPARSE
    head = bytearray(info.tobuf(format=tarfile.GNU_FORMAT))
    head[482] = 1  # isextended
    head[148:156] = b"        "
    head[148:156] = b"%06o\0 " % sum(head[:_BLOCK])
    ext = bytearray(_BLOCK)
    for i in range(21):  # (offset, numbytes) = (1, 1), 12 octal bytes each
        ext[slice(i * 24, i * 24 + 24)] = b"%011o\0%011o\0" % (1, 1)
    ext[504] = 1
    out = tmp_path / "sparse-old.tar.gz"
    out.write_bytes(gzip.compress(bytes(head[:_BLOCK]) + bytes(ext) * n_blocks))
    return out


def _pax_sparse(tmp_path, version, map_entries=1):
    """A pax-format GNU sparse member of *version* ``"0.0"``, ``"0.1"`` or
    ``"1.0"`` (1.0 keeps its map, here *map_entries* long, in the data)."""
    info = tarfile.TarInfo("GNUSparseFile.0/records.jsonl")
    data = b""
    if version == "0.0":
        info.pax_headers = {"GNU.sparse.size": "1", "GNU.sparse.numbytes": "1"}
    elif version == "0.1":
        info.pax_headers = {"GNU.sparse.size": "1", "GNU.sparse.map": "0,1"}
    else:
        info.pax_headers = {
            "GNU.sparse.major": "1",
            "GNU.sparse.minor": "0",
            "GNU.sparse.name": "records.jsonl",
            "GNU.sparse.realsize": "3",
        }
        data = f"{map_entries}\n".encode() + b"1\n1\n" * map_entries
    info.size = len(data)
    out = tmp_path / f"sparse-{version}.tar.gz"
    with tarfile.open(out, "w:gz", format=tarfile.PAX_FORMAT) as tf:
        tf.addfile(info, io.BytesIO(data))
    return out


READERS = {
    "iter_jsonl": lambda path, tmp_path: list(iter_jsonl(path)),
    "unpack_bundle": lambda path, tmp_path: unpack_bundle(path, tmp_path / "dst"),
}
_PEAK_LIMIT = 8 * 1024 * 1024


def _refused_within_memory(read, path, tmp_path, match):
    """Run *read* on a prebuilt hostile *path*: it must raise a ValueError
    matching *match* while peak traced memory stays under _PEAK_LIMIT."""
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match=match):
            read(path, tmp_path)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < _PEAK_LIMIT


@pytest.mark.parametrize("reader", sorted(READERS))
class TestTarHeaderChainsAndSparse:
    """Extended headers are charged per member across a whole chain, and
    sparse members (which arkiv never writes) are refused outright."""

    @pytest.mark.parametrize("kind", ["gnu", "pax"])
    def test_chained_headers_share_one_budget(self, tmp_path, reader, kind):
        path = tar_gz_header_chain(tmp_path, kind, 20, 1_000_000)
        _refused_within_memory(READERS[reader], path, tmp_path, "header")

    def test_overlong_header_chain_refused(self, tmp_path, reader):
        path = tar_gz_header_chain(tmp_path, "gnu", 400, 100)
        _refused_within_memory(READERS[reader], path, tmp_path, "header")

    def test_short_header_chain_still_reads(self, tmp_path, reader):
        READERS[reader](tar_gz_header_chain(tmp_path, "pax", 8, 1000), tmp_path)

    def test_small_global_pax_header_still_reads(self, tmp_path, reader):
        # git archive writes one global header (the commit id).
        out = tmp_path / "global.tar.gz"
        data = records_to_jsonl(RECORDS)
        with tarfile.open(
            out, "w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": "abc"}
        ) as tf:
            info = tarfile.TarInfo("records.jsonl")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        with tarfile.open(out) as tf:
            tf.getmembers()
            assert tf.pax_headers == {"comment": "abc"}
        result = READERS[reader](out, tmp_path)
        if reader == "iter_jsonl":
            assert result == RECORDS
        else:
            assert (tmp_path / "dst" / "records.jsonl").read_bytes() == data

    def test_global_headers_have_an_archive_wide_budget(self, tmp_path, reader):
        record = _pax_record("comment", "g" * 500_000)
        glob = _raw_header("pax_global_header", len(record), tarfile.XGLTYPE)
        path = _tar_gz_stream(tmp_path, "globals.tar.gz", [glob + _pad(record)] * 3)
        _refused_within_memory(READERS[reader], path, tmp_path, "header")

    def test_old_gnu_sparse_refused(self, tmp_path, reader):
        path = _old_gnu_sparse(tmp_path, 120_000)
        _refused_within_memory(READERS[reader], path, tmp_path, "sparse")

    @pytest.mark.parametrize("version", ["0.0", "0.1", "1.0"])
    def test_pax_sparse_refused(self, tmp_path, reader, version):
        path = _pax_sparse(tmp_path, version, map_entries=200_000)
        _refused_within_memory(READERS[reader], path, tmp_path, "sparse")


def test_capped_tarinfo_hooks_exist_in_tarfile():
    """The caps override private tarfile hooks; if a Python release renames
    one, the override would silently stop applying. Fail loudly instead."""
    from arkiv.bundle import _CappedTarInfo

    hooks = [
        "_proc_gnulong",
        "_proc_pax",
        "_proc_sparse",
        "_proc_gnusparse_00",
        "_proc_gnusparse_01",
        "_proc_gnusparse_10",
    ]
    for name in hooks:
        assert callable(getattr(tarfile.TarInfo, name, None)), name
        assert name in vars(_CappedTarInfo), name


BOM = b"\xef\xbb\xbf"
BOM_JSONL = BOM + b'{"content":"first"}\n{"content":"second"}\n'


class TestByteOrderMark:
    """A UTF-8 BOM (Windows editors write one) must not hide record one."""

    @pytest.mark.parametrize("name", ["r.jsonl", "r.jsonl.gz", "r.zip", "r.tar.gz"])
    def test_iter_jsonl_keeps_first_record_after_bom(self, tmp_path, name):
        out = tmp_path / name
        if name.endswith(".jsonl"):
            out.write_bytes(BOM_JSONL)
        elif name.endswith(".jsonl.gz"):
            out.write_bytes(gzip.compress(BOM_JSONL))
        else:
            write_bundle(out, {"records.jsonl": BOM_JSONL})
        assert [r["content"] for r in iter_jsonl(out)] == ["first", "second"]

    def test_peek_sees_first_record_after_bom(self, tmp_path):
        out = tmp_path / "r.jsonl"
        out.write_bytes(BOM_JSONL)
        assert peek_jsonl(out) == {"content": "first"}


def make_corrupt(tmp_path, corruption):
    """A one-member bundle (records.jsonl) damaged in the named way."""
    body = records_to_jsonl({"uri": f"x://a/{i}", "n": i} for i in range(500))
    if corruption == "bad_gzip_body":
        # Truncated inside the first deflate block: nothing decodes at all.
        out = tmp_path / "r.jsonl.gz"
        out.write_bytes(gzip.compress(body)[:14])
        return out
    out = tmp_path / "r.zip"
    write_bundle(out, {"records.jsonl": body})
    data = bytearray(out.read_bytes())
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    if corruption == "flipped_deflate":
        start = local + 30 + len(b"records.jsonl")  # no extra field
        data[start : start + 8] = b"\xff" * 8  # reserved deflate block type
    elif corruption == "method_99":
        data[local + 8 : local + 10] = (99).to_bytes(2, "little")
        data[central + 10 : central + 12] = (99).to_bytes(2, "little")
    elif corruption == "encrypted_flag":
        data[local + 6] |= 1
        data[central + 8] |= 1
    else:
        raise AssertionError(corruption)
    out.write_bytes(bytes(data))
    return out


ZIP_CORRUPTIONS = ["flipped_deflate", "method_99", "encrypted_flag"]


class TestUnreadableMembers:
    """Corrupt or unsupported compressed data is a ValueError (which the CLI
    prints as an error), not a zlib/EOF/NotImplemented/Runtime traceback."""

    @pytest.mark.parametrize("corruption", ZIP_CORRUPTIONS + ["bad_gzip_body"])
    def test_peek_returns_none_on_unreadable_member(self, tmp_path, corruption):
        assert peek_jsonl(make_corrupt(tmp_path, corruption)) is None

    @pytest.mark.parametrize("corruption", ZIP_CORRUPTIONS + ["bad_gzip_body"])
    def test_iter_jsonl_raises_value_error(self, tmp_path, corruption):
        with pytest.raises(ValueError):
            list(iter_jsonl(make_corrupt(tmp_path, corruption)))

    def test_unsupported_and_encrypted_errors_name_the_bundle(self, tmp_path):
        for corruption in ("method_99", "encrypted_flag"):
            out = make_corrupt(tmp_path, corruption)
            with pytest.raises(ValueError, match="r.zip"):
                list(iter_jsonl(out))

    @pytest.mark.parametrize("corruption", ZIP_CORRUPTIONS)
    def test_unpack_bundle_raises_value_error(self, tmp_path, corruption):
        out = make_corrupt(tmp_path, corruption)
        with pytest.raises(ValueError, match="r.zip"):
            unpack_bundle(out, tmp_path / "dst")

    def test_bad_zip_crc_is_a_value_error_when_streamed(self, tmp_path):
        out = tmp_path / "crc.zip"
        write_bundle(out, {"records.jsonl": b'{"a": 1}\n' * 10})
        data = bytearray(out.read_bytes())
        central = data.find(b"PK\x01\x02")
        data[central + 16] ^= 0xFF  # the central directory's CRC-32 is checked
        out.write_bytes(bytes(data))
        with pytest.raises(ValueError):
            list(iter_jsonl(out))


def _reject_constant(name):
    raise AssertionError(f"non-standard JSON constant {name}")


def _archive(tmp_path, big=b"x" * 4096):
    archive = tmp_path / "archive"
    (archive / "media").mkdir(parents=True)
    (archive / "README.md").write_text("---\nname: t\n---\n")
    (archive / "media" / "big.bin").write_bytes(big)
    return archive


class TestAtomicAndZip64Packing:
    def test_pack_bundle_large_member_uses_zip64(self, tmp_path, monkeypatch):
        # Shrink the zip64 threshold so a 4 KiB member stands in for 2 GiB.
        monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 1024)
        data = bytes(range(256)) * 16
        out = tmp_path / "out.zip"
        pack_bundle(_archive(tmp_path, data), out)
        with zipfile.ZipFile(out) as zf:
            assert zf.read("media/big.bin") == data
            assert zf.getinfo("media/big.bin").extract_version >= 45  # zip64

    @pytest.mark.parametrize("ext", [".zip", ".tar.gz"])
    def test_failed_pack_leaves_no_partial_output(self, tmp_path, monkeypatch, ext):
        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(bundle.shutil, "copyfileobj", boom)
        monkeypatch.setattr(bundle.tarfile.TarFile, "addfile", boom)
        out = tmp_path / f"out{ext}"
        with pytest.raises(OSError):
            pack_bundle(_archive(tmp_path), out)
        assert not out.exists()
        assert not list(tmp_path.glob(".out*"))

    @pytest.mark.parametrize("ext", [".zip", ".tar.gz"])
    def test_failed_write_keeps_the_previous_bundle(self, tmp_path, ext):
        out = tmp_path / f"out{ext}"
        write_bundle(out, {"a.txt": b"old"})
        before = out.read_bytes()

        class Unwritable:
            def __len__(self):
                return 1

        with pytest.raises(Exception):
            write_bundle(out, {"a.txt": b"new", "b.txt": Unwritable()})  # type: ignore
        assert out.read_bytes() == before
        assert not list(tmp_path.glob(".out*"))

    @pytest.mark.parametrize("ext", [".zip", ".tar.gz"])
    def test_temp_name_does_not_leak_into_the_archive(self, tmp_path, ext):
        a, b = tmp_path / f"a{ext}", tmp_path / f"b{ext}"
        write_bundle(a, {"a.txt": b"1"})
        write_bundle(b, {"a.txt": b"1"})
        # Only the member names are in the bytes, never the output or temp name.
        assert a.read_bytes() == b.read_bytes()
        assert b".tmp" not in a.read_bytes()
        assert not any(p.name.startswith(".") for p in tmp_path.iterdir())

    def test_atomic_output_replaces_on_success_and_cleans_on_error(self, tmp_path):
        target = tmp_path / "t.bin"
        with bundle._atomic_output(target) as tmp:
            assert tmp.parent == tmp_path and tmp.name.startswith(".t.bin.")
            tmp.write_bytes(b"ok")
        assert target.read_bytes() == b"ok"
        with pytest.raises(RuntimeError):
            with bundle._atomic_output(target) as tmp:
                tmp.write_bytes(b"partial")
                raise RuntimeError("boom")
        assert target.read_bytes() == b"ok"
        assert [p.name for p in tmp_path.iterdir()] == ["t.bin"]


class TestWriteBundleNames:
    @pytest.mark.parametrize("name", ["out", "out.zip", "out.tar.gz"])
    def test_names_that_collide_after_normalization(self, tmp_path, name):
        with pytest.raises(ValueError, match="duplicate"):
            write_bundle(tmp_path / name, {"a/b": b"1", "./a/b": b"2"})
        assert not (tmp_path / name).exists()

    def test_slash_runs_collide_too(self, tmp_path):
        with pytest.raises(ValueError, match="duplicate"):
            write_bundle(tmp_path / "x.zip", {"a//b": b"1", "a/b": b"2"})

    @pytest.mark.parametrize("bad", ["../x", "/abs", "a/../b", "a\\b", ""])
    def test_names_unpack_would_refuse_are_refused_at_write(self, tmp_path, bad):
        with pytest.raises(ValueError, match="invalid bundle member name"):
            write_bundle(tmp_path / "x.zip", {bad: b"1"})
        assert not (tmp_path / "x.zip").exists()

    def test_normalized_names_are_what_is_written(self, tmp_path):
        out = tmp_path / "x.zip"
        write_bundle(out, {"./a//b": b"1"})
        assert zipfile.ZipFile(out).namelist() == ["a/b"]


class TestNonFiniteFloats:
    def test_records_to_jsonl_non_finite_floats(self):
        out = records_to_jsonl(
            [{"x": float("nan"), "y": [float("inf")], "z": {"w": (float("-inf"),)}}]
        )
        row = json.loads(out, parse_constant=_reject_constant)
        assert row == {"x": "nan", "y": ["inf"], "z": {"w": ["-inf"]}}

    def test_finite_floats_and_other_values_are_unchanged(self):
        out = records_to_jsonl([{"a": 1.5, "b": 2, "c": None, "d": "nan"}])
        assert json.loads(out) == {"a": 1.5, "b": 2, "c": None, "d": "nan"}
