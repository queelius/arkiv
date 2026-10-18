"""Tests for the in-memory bundle API shared by the *-memex archives:
write_bundle / records_to_jsonl (export) and open_member / iter_jsonl /
peek_jsonl (import), plus pack_bundle determinism."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import time
import zipfile

import pytest

from arkiv import (
    bundle_format,
    iter_jsonl,
    open_member,
    pack_bundle,
    peek_jsonl,
    records_to_jsonl,
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
