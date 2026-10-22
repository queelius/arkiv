"""Tests for zip / tar.gz bundle support.

Exercises both the library functions (arkiv.bundle) and the CLI export/import
round-trip through compressed bundles.
"""
from __future__ import annotations

import gzip
import io
import json
import subprocess
import sys
import sqlite3
import tarfile
import tracemalloc
import warnings
import zipfile
from pathlib import Path

import pytest

from arkiv.bundle import is_bundle, pack_bundle, unpack_bundle

from .test_bundle_io import tar_gz_with_long_name


def run_arkiv(*args):
    result = subprocess.run(
        [sys.executable, "-m", "arkiv.cli", *args],
        capture_output=True,
        text=True,
    )
    return result


# ── library-level tests ────────────────────────────────────────

class TestDetection:
    @pytest.mark.parametrize("name", [
        "archive.zip", "a.ZIP", "sub/path.Zip",
        "archive.tar.gz", "a.TAR.GZ", "archive.tgz", "a.TGZ",
    ])
    def test_detects_bundle_extensions(self, name):
        assert is_bundle(name)

    @pytest.mark.parametrize("name", [
        "archive", "archive.tar", "archive.gz", "archive.jsonl",
        "README.md", "data.db", "dir/",
    ])
    def test_rejects_non_bundle(self, name):
        assert not is_bundle(name)


class TestPackUnpackRoundTrip:
    def _make_dir(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        (d / "README.md").write_text("# arkiv\n\ncontents: []\n")
        (d / "schema.yaml").write_text("records: {}\n")
        (d / "records.jsonl").write_text('{"content": "hi"}\n')
        return d

    def test_zip_roundtrip(self, tmp_path):
        src = self._make_dir(tmp_path)
        bundle = tmp_path / "archive.zip"
        pack_bundle(src, bundle)
        assert bundle.exists()
        with zipfile.ZipFile(bundle) as zf:
            assert set(zf.namelist()) == {
                "README.md", "schema.yaml", "records.jsonl"
            }
        # unpack to a fresh dir
        dst = tmp_path / "dst"
        unpack_bundle(bundle, dst)
        assert (dst / "README.md").read_text() == (src / "README.md").read_text()
        assert (dst / "records.jsonl").read_text() == (src / "records.jsonl").read_text()

    def test_tar_gz_roundtrip(self, tmp_path):
        src = self._make_dir(tmp_path)
        bundle = tmp_path / "archive.tar.gz"
        pack_bundle(src, bundle)
        assert bundle.exists()
        with tarfile.open(bundle, "r:gz") as tf:
            names = {m.name for m in tf.getmembers()}
        assert {"README.md", "schema.yaml", "records.jsonl"} <= names
        dst = tmp_path / "dst"
        unpack_bundle(bundle, dst)
        assert (dst / "records.jsonl").read_text() == (src / "records.jsonl").read_text()

    def test_tgz_extension_treated_as_tar_gz(self, tmp_path):
        src = self._make_dir(tmp_path)
        bundle = tmp_path / "archive.tgz"
        pack_bundle(src, bundle)
        # Should open as tar.gz
        with tarfile.open(bundle, "r:gz") as tf:
            names = {m.name for m in tf.getmembers()}
        assert "records.jsonl" in names


class TestSafeExtraction:
    """Packed bundles should reject path-escape entries to avoid surprise
    writes outside the target directory."""

    def test_zip_rejects_parent_path_traversal(self, tmp_path):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../escape.txt", "escaped")
        with pytest.raises(ValueError, match="path escape"):
            unpack_bundle(bad, tmp_path / "dst")

    def test_tar_rejects_parent_path_traversal(self, tmp_path):
        import io

        bad = tmp_path / "bad.tar.gz"
        with tarfile.open(bad, "w:gz") as tf:
            info = tarfile.TarInfo(name="../escape.txt")
            payload = b"escaped"
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        with pytest.raises(ValueError, match="path escape"):
            unpack_bundle(bad, tmp_path / "dst")

    def test_zip_rejects_sibling_prefix_escape(self, tmp_path):
        # Classic startswith() flaw: target /tmp/out, entry resolving to
        # /tmp/out-evil/x. A string-prefix check accepts it; a proper
        # containment check rejects it.
        target = tmp_path / "out"
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../out-evil/x.txt", "pwn")
        with pytest.raises(ValueError, match="path escape"):
            unpack_bundle(bad, target)
        assert not (tmp_path / "out-evil").exists()


class TestDecompressionLimits:
    """Bundles may come from untrusted sources; extraction must bound the
    entry count and total uncompressed size to resist zip/tar bombs."""

    def _make_zip(self, tmp_path, n_files, size_each=1):
        src = tmp_path / "src"
        src.mkdir()
        for i in range(n_files):
            (src / f"f{i}.txt").write_text("x" * size_each)
        bundle = tmp_path / "a.zip"
        pack_bundle(src, bundle)
        return bundle

    def test_rejects_too_many_entries(self, tmp_path):
        bundle = self._make_zip(tmp_path, n_files=5)
        with pytest.raises(ValueError, match="entries|too many"):
            unpack_bundle(bundle, tmp_path / "dst", max_entries=2)

    def test_rejects_oversize_total(self, tmp_path):
        bundle = self._make_zip(tmp_path, n_files=1, size_each=1000)
        with pytest.raises(ValueError, match="size|large|bomb"):
            unpack_bundle(bundle, tmp_path / "dst", max_total_bytes=100)

    def test_within_limits_extracts_normally(self, tmp_path):
        bundle = self._make_zip(tmp_path, n_files=3, size_each=10)
        dst = tmp_path / "dst"
        unpack_bundle(bundle, dst, max_entries=100, max_total_bytes=10_000)
        assert (dst / "f0.txt").read_text() == "x" * 10

    def test_tar_rejects_oversize_total(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "big.txt").write_text("y" * 1000)
        bundle = tmp_path / "a.tar.gz"
        pack_bundle(src, bundle)
        with pytest.raises(ValueError, match="size|large|bomb"):
            unpack_bundle(bundle, tmp_path / "dst", max_total_bytes=100)


def _tar_gz(path, members):
    """Write a tar.gz of ``(TarInfo, payload-or-None)`` pairs."""
    with tarfile.open(path, "w:gz") as tf:
        for info, payload in members:
            if payload is None:
                tf.addfile(info)
            else:
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
    return path


class TestHostileTarMembers:
    """Tar headers and member types an attacker controls: oversized long-name
    and pax headers, duplicate names, links, and member counts."""

    @pytest.mark.parametrize("fmt", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
    def test_unpack_rejects_huge_tar_header(self, tmp_path, fmt):
        path = tar_gz_with_long_name(tmp_path, 4 * 1024 * 1024, fmt)
        tracemalloc.start()
        try:
            with pytest.raises(ValueError, match="header"):
                unpack_bundle(path, tmp_path / "dst")
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert peak < 3 * 1024 * 1024

    @pytest.mark.parametrize("second", ["records.jsonl", "./records.jsonl"])
    def test_unpack_refuses_duplicate_tar_members(self, tmp_path, second):
        bad = _tar_gz(
            tmp_path / "dup.tar.gz",
            [
                (tarfile.TarInfo("records.jsonl"), b'{"n": 1}\n'),
                (tarfile.TarInfo(second), b'{"n": 2}\n'),
            ],
        )
        dst = tmp_path / "dst"
        with pytest.raises(ValueError, match="duplicate"):
            unpack_bundle(bad, dst)
        assert not (dst / "records.jsonl").exists()

    def test_unpack_refuses_duplicate_zip_members(self, tmp_path):
        bad = tmp_path / "dup.zip"
        with zipfile.ZipFile(bad, "w") as zf, warnings.catch_warnings():
            warnings.simplefilter("ignore")  # zipfile warns on the duplicate
            zf.writestr("records.jsonl", '{"n": 1}\n')
            zf.writestr("records.jsonl", '{"n": 2}\n')
        dst = tmp_path / "dst"
        with pytest.raises(ValueError, match="duplicate"):
            unpack_bundle(bad, dst)
        assert not (dst / "records.jsonl").exists()

    def test_unpack_refuses_tar_members_differing_only_in_case(self, tmp_path):
        # On a case-insensitive filesystem (APFS, NTFS) the second would
        # overwrite the first, which iter_jsonl reads.
        bad = _tar_gz(
            tmp_path / "case.tar.gz",
            [
                (tarfile.TarInfo("records.jsonl"), b'{"n": "GOOD"}\n'),
                (tarfile.TarInfo("Records.jsonl"), b'{"n": "EVIL"}\n'),
            ],
        )
        dst = tmp_path / "dst"
        with pytest.raises(ValueError, match="duplicate"):
            unpack_bundle(bad, dst)
        assert not (dst / "records.jsonl").exists()

    def test_unpack_refuses_zip_members_differing_only_in_normalization(self, tmp_path):
        composed, decomposed = "caf\u00e9.jsonl", "cafe\u0301.jsonl"
        bad = tmp_path / "nfd.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr(composed, '{"n": 1}\n')
            zf.writestr(decomposed, '{"n": 2}\n')
        dst = tmp_path / "dst"
        with pytest.raises(ValueError, match="duplicate"):
            unpack_bundle(bad, dst)
        assert not (dst / composed).exists()

    @pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE])
    def test_unpack_refuses_tar_links(self, tmp_path, kind):
        # Even a link that stays inside the archive: links are not part of
        # the directory form.
        link = tarfile.TarInfo("media/latest.jpg")
        link.type = kind
        link.linkname = "media/2024.jpg"
        bad = _tar_gz(
            tmp_path / "link.tar.gz",
            [(tarfile.TarInfo("media/2024.jpg"), b"jpeg"), (link, None)],
        )
        dst = tmp_path / "dst"
        with pytest.raises(ValueError, match="link"):
            unpack_bundle(bad, dst)
        assert list(dst.iterdir()) == []

    def test_unpack_entry_cap_counts_while_streaming(self, tmp_path):
        # The fifth member's header is corrupt, so reading every header
        # upfront fails with a tar read error; a streaming count refuses the
        # archive at the fourth member and never reaches it.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
            for name in ["f0", "f1", "f2", "f3", "g" * 200]:
                info = tarfile.TarInfo(name)
                info.size = 1
                tf.addfile(info, io.BytesIO(b"x"))
        raw = bytearray(buf.getvalue())
        with tarfile.open(fileobj=io.BytesIO(bytes(raw))) as tf:
            header = tf.getmembers()[4].offset_data - tarfile.BLOCKSIZE
        checksum = slice(header + 148, header + 156)
        raw[checksum] = b"garbage!"
        bad = tmp_path / "many.tar.gz"
        bad.write_bytes(gzip.compress(bytes(raw)))
        with pytest.raises(ValueError, match="too many entries"):
            unpack_bundle(bad, tmp_path / "dst", max_entries=3)

    @pytest.mark.parametrize("ext", ["zip", "tar.gz"])
    def test_unpack_overlong_path_component_is_value_error(self, tmp_path, ext):
        name = "c" * 300  # one component, over the OS's 255-byte limit
        bad = tmp_path / f"long.{ext}"
        if ext == "zip":
            with zipfile.ZipFile(bad, "w") as zf:
                zf.writestr(name, "x")
        else:
            _tar_gz(bad, [(tarfile.TarInfo(name), b"x")])
        with pytest.raises(ValueError, match="cannot extract long"):
            unpack_bundle(bad, tmp_path / "dst")


class TestMemberNamesAndArchiveErrors:
    """Member names are checked as open_member checks them, and anything a
    corrupt or unextractable archive raises reaches the caller (and the CLI)
    as a ValueError."""

    def test_unpack_refuses_dotdot_alias_in_tar(self, tmp_path):
        bad = _tar_gz(
            tmp_path / "alias.tar.gz",
            [
                (tarfile.TarInfo("x/a"), b"a"),
                (tarfile.TarInfo("records.jsonl"), b'{"n": 1}\n'),
                (tarfile.TarInfo("x/../records.jsonl"), b'{"n": 2}\n'),
            ],
        )
        with pytest.raises(ValueError, match="invalid bundle member name"):
            unpack_bundle(bad, tmp_path / "dst")
        assert not (tmp_path / "dst" / "records.jsonl").exists()

    def test_unpack_refuses_dotdot_alias_in_zip(self, tmp_path):
        # zipfile would drop the '..' and write both to x/records.jsonl.
        bad = tmp_path / "alias.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("x/records.jsonl", '{"n": 1}\n')
            zf.writestr("x/../records.jsonl", '{"n": 2}\n')
        with pytest.raises(ValueError, match="invalid bundle member name"):
            unpack_bundle(bad, tmp_path / "dst")
        assert not (tmp_path / "dst" / "x").exists()

    def test_truncated_gzip_is_value_error(self, tmp_path):
        good = tmp_path / "good.tar.gz"
        _tar_gz(good, [(tarfile.TarInfo("a.jsonl"), b'{"n": 1}\n' * 2000)])
        bad = tmp_path / "trunc.tar.gz"
        bad.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
        with pytest.raises(ValueError, match="cannot extract trunc.tar.gz"):
            unpack_bundle(bad, tmp_path / "dst")

    @pytest.mark.parametrize("name", ["garbage.tar.gz", "garbage.zip"])
    def test_garbage_bundle_is_value_error(self, tmp_path, name):
        bad = tmp_path / name
        bad.write_bytes(b"not an archive at all" * 10)
        with pytest.raises(ValueError, match=f"cannot extract {name}"):
            unpack_bundle(bad, tmp_path / "dst")

    def test_missing_bundle_stays_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            unpack_bundle(tmp_path / "absent.tar.gz", tmp_path / "dst")

    @pytest.mark.parametrize("kind", [tarfile.FIFOTYPE, tarfile.CHRTYPE])
    def test_unpack_refuses_special_members(self, tmp_path, kind):
        special = tarfile.TarInfo("media/pipe")
        special.type = kind
        bad = _tar_gz(
            tmp_path / "special.tar.gz",
            [(tarfile.TarInfo("records.jsonl"), b"{}\n"), (special, None)],
        )
        dst = tmp_path / "dst"
        with pytest.raises(ValueError, match="special"):
            unpack_bundle(bad, dst)
        assert list(dst.iterdir()) == []

    def test_cli_convert_of_garbage_bundle_is_a_clean_error(self, tmp_path):
        bad = tmp_path / "garbage.tar.gz"
        bad.write_bytes(b"not an archive at all" * 10)
        result = run_arkiv("convert", str(bad), str(tmp_path / "out.db"))
        assert result.returncode == 1
        assert "Error:" in result.stderr
        assert "Traceback" not in result.stderr


# ── CLI integration tests ──────────────────────────────────────

def _seed_db(tmp_path):
    """Create a small arkiv DB from a JSONL file."""
    jsonl = tmp_path / "seed.jsonl"
    jsonl.write_text(
        '{"content": "one", "metadata": {"color": "red"}}\n'
        '{"content": "two", "metadata": {"color": "blue"}}\n'
    )
    db = tmp_path / "seed.db"
    run_arkiv("convert", str(jsonl), str(db))
    return db


class TestCliExportBundle:
    def test_convert_db_to_zip(self, tmp_path):
        db = _seed_db(tmp_path)
        out = tmp_path / "archive.zip"
        result = run_arkiv("convert", str(db), str(out))
        assert result.returncode == 0, result.stderr
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        assert "README.md" in names

    def test_convert_db_to_tar_gz(self, tmp_path):
        db = _seed_db(tmp_path)
        out = tmp_path / "archive.tar.gz"
        result = run_arkiv("convert", str(db), str(out))
        assert result.returncode == 0, result.stderr
        assert out.exists()
        with tarfile.open(out, "r:gz") as tf:
            names = {m.name for m in tf.getmembers()}
        assert "README.md" in names

    def test_convert_db_to_directory(self, tmp_path):
        """Non-bundle output still works as a plain directory."""
        db = _seed_db(tmp_path)
        out = tmp_path / "plain_dir"
        result = run_arkiv("convert", str(db), str(out))
        assert result.returncode == 0, result.stderr
        assert out.is_dir()
        assert (out / "README.md").is_file()


class TestCliImportBundle:
    def test_convert_zip_to_db(self, tmp_path):
        # Seed DB → convert to zip → re-convert into a fresh DB
        db_src = _seed_db(tmp_path)
        bundle = tmp_path / "round.zip"
        run_arkiv("convert", str(db_src), str(bundle))

        db_dst = tmp_path / "round.db"
        result = run_arkiv("convert", str(bundle), str(db_dst))
        assert result.returncode == 0, result.stderr
        assert db_dst.exists()

        # Content survived the round-trip
        conn = sqlite3.connect(str(db_dst))
        count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        conn.close()
        assert count == 2

    def test_convert_tar_gz_to_db(self, tmp_path):
        db_src = _seed_db(tmp_path)
        bundle = tmp_path / "round.tar.gz"
        run_arkiv("convert", str(db_src), str(bundle))

        db_dst = tmp_path / "round.db"
        result = run_arkiv("convert", str(bundle), str(db_dst))
        assert result.returncode == 0, result.stderr
        conn = sqlite3.connect(str(db_dst))
        count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        conn.close()
        assert count == 2


class TestPackHygiene:
    """pack_bundle must not sweep derived databases or dotfiles into a
    transport bundle (the bundle is a serialization of the directory form,
    not of regenerable or hidden artifacts)."""

    def _make_dir_with_cruft(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        (d / "README.md").write_text("# arkiv\n")
        (d / "data.jsonl").write_text('{"content": "hi"}\n')
        (d / "media").mkdir()
        (d / "media" / "pic.png").write_bytes(b"\x89PNG\r\n")
        # Cruft that must NOT be packed:
        (d / "arkiv.db").write_bytes(b"SQLite format 3\x00")
        (d / "notes.sqlite3").write_bytes(b"SQLite format 3\x00")
        (d / ".hidden").write_text("secret")
        (d / ".git").mkdir()
        (d / ".git" / "config").write_text("[core]\n")
        return d

    def test_zip_excludes_derived_db_and_dotfiles(self, tmp_path):
        src = self._make_dir_with_cruft(tmp_path)
        bundle = tmp_path / "archive.zip"
        pack_bundle(src, bundle)
        with zipfile.ZipFile(bundle) as zf:
            names = set(zf.namelist())
        # Canonical archive files (including media) are packed:
        assert "README.md" in names
        assert "data.jsonl" in names
        assert "media/pic.png" in names
        # Derived databases and dotfiles are not:
        assert "arkiv.db" not in names
        assert "notes.sqlite3" not in names
        assert ".hidden" not in names
        assert not any(n.startswith(".git") for n in names)

    def test_tar_excludes_derived_db_and_dotfiles(self, tmp_path):
        src = self._make_dir_with_cruft(tmp_path)
        bundle = tmp_path / "archive.tar.gz"
        pack_bundle(src, bundle)
        with tarfile.open(bundle, "r:gz") as tf:
            names = {m.name for m in tf.getmembers()}
        assert "data.jsonl" in names and "media/pic.png" in names
        assert "arkiv.db" not in names
        assert ".hidden" not in names


class TestCliBundleMediaRoundtrip:
    def test_media_survives_full_convert_chain_through_bundle(self, tmp_path):
        payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.jsonl").write_text(
            '{"uri": "file://media/pic.png", "mimetype": "image/png"}\n'
        )
        (src / "README.md").write_text(
            "---\ncontents:\n- path: data.jsonl\n---\n"
        )
        (src / "media").mkdir()
        (src / "media" / "pic.png").write_bytes(payload)

        a_db = tmp_path / "a.db"
        bundle = tmp_path / "archive.zip"
        b_db = tmp_path / "b.db"
        out = tmp_path / "out"

        assert run_arkiv("convert", str(src), str(a_db)).returncode == 0
        assert run_arkiv("convert", str(a_db), str(bundle)).returncode == 0
        assert run_arkiv("convert", str(bundle), str(b_db)).returncode == 0
        assert run_arkiv("convert", str(b_db), str(out)).returncode == 0

        assert (out / "media" / "pic.png").read_bytes() == payload
