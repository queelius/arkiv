"""Security hardening regressions.

1. The auto-db rebuild must not destroy a database that holds unexported
   `--writable` writes.
2. Source-directory walks (fingerprint, pack) must not follow symlinks out
   of the archive (arbitrary read / decompression-style DoS).
"""

import os
import subprocess
import sys

import pytest

from arkiv.database import Database, _source_fingerprint


def run_arkiv(*args):
    return subprocess.run(
        [sys.executable, "-m", "arkiv.cli", *args],
        capture_output=True,
        text=True,
    )


def _symlink_or_skip(target, link):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")


class TestRebuildPreservesWrites:
    def test_rebuild_refuses_to_destroy_unexported_writes(self, tmp_path):
        from arkiv.cli import _resolve_db

        d = tmp_path / "arch"
        d.mkdir()
        (d / "data.jsonl").write_text('{"content": "a"}\n')
        (d / "README.md").write_text(
            "---\ncontents:\n- path: data.jsonl\n---\n"
        )

        # Build the writable auto-db and add an unexported write.
        db = _resolve_db(str(d), writable=True)
        db.insert_record("data", "live write")
        db.close()

        # The directory now looks changed (edit + bump mtime past the db).
        (d / "data.jsonl").write_text('{"content": "a"}\n{"content": "b"}\n')
        db_file = d / "arkiv.db"
        future = db_file.stat().st_mtime + 100
        os.utime(d / "data.jsonl", (future, future))

        # A read-path resolve must NOT silently destroy the pending writes.
        with pytest.raises(ValueError, match="unexported"):
            _resolve_db(str(d))

        assert db_file.exists()
        probe = Database(db_file, read_only=True)
        rows = probe.query(
            "SELECT content FROM records WHERE content = 'live write'"
        )
        probe.close()
        assert len(rows) == 1

    def test_rebuild_still_happens_without_pending_writes(self, tmp_path):
        from arkiv.cli import _resolve_db

        d = tmp_path / "arch"
        d.mkdir()
        (d / "data.jsonl").write_text('{"content": "first"}\n')
        (d / "README.md").write_text(
            "---\ncontents:\n- path: data.jsonl\n---\n"
        )
        db = _resolve_db(str(d))  # read-only auto-db, no writes
        db.close()

        (d / "data.jsonl").write_text('{"content": "second"}\n')
        db_file = d / "arkiv.db"
        future = db_file.stat().st_mtime + 100
        os.utime(d / "data.jsonl", (future, future))

        db = _resolve_db(str(d))  # no pending writes -> rebuild is fine
        rows = db.query("SELECT content FROM records")
        db.close()
        assert [r["content"] for r in rows] == ["second"]


class TestSymlinkSafety:
    def test_fingerprint_skips_symlinks(self, tmp_path):
        d = tmp_path / "arch"
        d.mkdir()
        (d / "data.jsonl").write_text('{"content": "a"}\n')
        fp_before = _source_fingerprint(d)

        secret = tmp_path / "secret.txt"
        secret.write_text("SECRET OUTSIDE THE ARCHIVE")
        _symlink_or_skip(secret, d / "leak.txt")

        # The symlink is ignored: the out-of-archive file is never read in.
        assert _source_fingerprint(d) == fp_before

    def test_pack_excludes_symlinks(self, tmp_path):
        import zipfile

        from arkiv.bundle import pack_bundle

        d = tmp_path / "src"
        d.mkdir()
        (d / "data.jsonl").write_text('{"content": "a"}\n')
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"x" * 100)
        _symlink_or_skip(outside, d / "link.jsonl")

        out = tmp_path / "archive.zip"
        pack_bundle(d, out)
        names = set(zipfile.ZipFile(out).namelist())
        assert "data.jsonl" in names
        assert "link.jsonl" not in names

    def test_fingerprint_ignores_files_under_symlinked_dir(self, tmp_path):
        # A *directory* symlink: the leaf file is not itself a symlink, so a
        # leaf-only check would still read it. rglob follows directory
        # symlinks; the walk must not.
        d = tmp_path / "arch"
        d.mkdir()
        (d / "data.jsonl").write_text('{"content": "a"}\n')
        fp_before = _source_fingerprint(d)

        secret_dir = tmp_path / "secretdir"
        secret_dir.mkdir()
        (secret_dir / "passwd").write_text("SECRET OUTSIDE THE ARCHIVE")
        _symlink_or_skip(secret_dir, d / "sub")  # directory symlink

        assert _source_fingerprint(d) == fp_before

    def test_pack_ignores_files_under_symlinked_dir(self, tmp_path):
        import zipfile

        from arkiv.bundle import pack_bundle

        d = tmp_path / "src"
        d.mkdir()
        (d / "data.jsonl").write_text('{"content": "a"}\n')
        secret_dir = tmp_path / "secretdir"
        secret_dir.mkdir()
        (secret_dir / "passwd").write_text("SECRET")
        _symlink_or_skip(secret_dir, d / "sub")  # directory symlink

        out = tmp_path / "archive.zip"
        pack_bundle(d, out)
        names = set(zipfile.ZipFile(out).namelist())
        assert "data.jsonl" in names
        assert not any("passwd" in n for n in names)
        assert not any(n.startswith("sub/") for n in names)


def _make_archive(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "c.jsonl").write_text('{"content": "x"}\n')
    (archive / "README.md").write_text("---\ncontents:\n- path: c.jsonl\n---\n")
    return archive


def _roundtrip(archive, out):
    r = run_arkiv("convert", str(archive))
    assert r.returncode == 0, r.stderr
    r = run_arkiv("convert", str(archive / "arkiv.db"), str(out))
    assert r.returncode == 0, r.stderr


class TestMediaSymlinksNotImported:
    def test_symlinked_media_dir_is_not_imported(self, tmp_path):
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "key").write_bytes(b"TOP SECRET")
        archive = _make_archive(tmp_path)
        _symlink_or_skip(secret, archive / "media")
        out = tmp_path / "out"
        _roundtrip(archive, out)
        assert not (out / "media").exists()

    def test_symlinked_media_file_is_not_imported(self, tmp_path):
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "key").write_bytes(b"TOP SECRET")
        archive = _make_archive(tmp_path)
        (archive / "media").mkdir()
        _symlink_or_skip(secret / "key", archive / "media" / "pic.png")
        out = tmp_path / "out"
        _roundtrip(archive, out)
        assert not (out / "media" / "pic.png").exists()

    def test_internal_symlink_skipped_real_file_kept(self, tmp_path):
        archive = _make_archive(tmp_path)
        (archive / "media").mkdir()
        original = b"\xff\xd8 jpeg bytes"
        (archive / "media" / "2024.jpg").write_bytes(original)
        _symlink_or_skip("2024.jpg", archive / "media" / "latest.jpg")
        out = tmp_path / "out"
        _roundtrip(archive, out)
        assert (out / "media" / "2024.jpg").read_bytes() == original
        assert not (out / "media" / "latest.jpg").exists()


class TestPackBundleMemberNames:
    def test_tar_and_zip_member_names_are_posix(self, tmp_path):
        import tarfile
        import zipfile

        from arkiv.bundle import pack_bundle

        archive = _make_archive(tmp_path)
        (archive / "media" / "sub").mkdir(parents=True)
        (archive / "media" / "sub" / "a.bin").write_bytes(b"a")
        pack_bundle(archive, tmp_path / "b.tar.gz")
        pack_bundle(archive, tmp_path / "b.zip")
        with tarfile.open(tmp_path / "b.tar.gz") as tf:
            tnames = tf.getnames()
        with zipfile.ZipFile(tmp_path / "b.zip") as zf:
            znames = zf.namelist()
        assert tnames == znames == sorted(tnames)
        assert "media/sub/a.bin" in tnames
        assert all("\\" not in n for n in tnames)
