"""Tests for zip / tar.gz bundle support.

Exercises both the library functions (arkiv.bundle) and the CLI export/import
round-trip through compressed bundles.
"""
from __future__ import annotations

import json
import subprocess
import sys
import sqlite3
import tarfile
import zipfile
from pathlib import Path

import pytest

from arkiv.bundle import is_bundle, pack_bundle, unpack_bundle


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


# ── CLI integration tests ──────────────────────────────────────

def _seed_db(tmp_path):
    """Create a small arkiv DB from a JSONL file."""
    jsonl = tmp_path / "seed.jsonl"
    jsonl.write_text(
        '{"content": "one", "metadata": {"color": "red"}}\n'
        '{"content": "two", "metadata": {"color": "blue"}}\n'
    )
    db = tmp_path / "seed.db"
    run_arkiv("import", str(jsonl), "--db", str(db))
    return db


class TestCliExportBundle:
    def test_export_to_zip(self, tmp_path):
        db = _seed_db(tmp_path)
        out = tmp_path / "archive.zip"
        result = run_arkiv("export", str(db), "--output", str(out))
        assert result.returncode == 0, result.stderr
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        assert "README.md" in names

    def test_export_to_tar_gz(self, tmp_path):
        db = _seed_db(tmp_path)
        out = tmp_path / "archive.tar.gz"
        result = run_arkiv("export", str(db), "--output", str(out))
        assert result.returncode == 0, result.stderr
        assert out.exists()
        with tarfile.open(out, "r:gz") as tf:
            names = {m.name for m in tf.getmembers()}
        assert "README.md" in names

    def test_export_directory_unchanged(self, tmp_path):
        """Non-bundle output still works as a plain directory."""
        db = _seed_db(tmp_path)
        out = tmp_path / "plain_dir"
        result = run_arkiv("export", str(db), "--output", str(out))
        assert result.returncode == 0, result.stderr
        assert out.is_dir()
        assert (out / "README.md").is_file()


class TestCliImportBundle:
    def test_import_zip(self, tmp_path):
        # Seed DB → export to zip → re-import into a fresh DB
        db_src = _seed_db(tmp_path)
        bundle = tmp_path / "round.zip"
        run_arkiv("export", str(db_src), "--output", str(bundle))

        db_dst = tmp_path / "round.db"
        result = run_arkiv("import", str(bundle), "--db", str(db_dst))
        assert result.returncode == 0, result.stderr
        assert db_dst.exists()

        # Content survived the round-trip
        conn = sqlite3.connect(str(db_dst))
        count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        conn.close()
        assert count == 2

    def test_import_tar_gz(self, tmp_path):
        db_src = _seed_db(tmp_path)
        bundle = tmp_path / "round.tar.gz"
        run_arkiv("export", str(db_src), "--output", str(bundle))

        db_dst = tmp_path / "round.db"
        result = run_arkiv("import", str(bundle), "--db", str(db_dst))
        assert result.returncode == 0, result.stderr
        conn = sqlite3.connect(str(db_dst))
        count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        conn.close()
        assert count == 2
