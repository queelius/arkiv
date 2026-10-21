"""Tests for divergence detection between the directory and database forms.

The directory form is authoritative on divergence; these cover the
machinery that makes divergence *visible* (a stored content fingerprint
plus an insert-since-convert counter) and queryable via sync_status().
"""

import json
import subprocess
import sys

from arkiv.database import Database


def _make_archive(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.jsonl").write_text('{"content": "a"}\n')
    (d / "README.md").write_text("---\ncontents:\n- path: data.jsonl\n---\n")


class TestSyncStatus:
    def test_in_sync_after_convert(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        db.store_source_fingerprint(src)
        st = db.sync_status(src)
        db.close()
        assert st["has_fingerprint"] is True
        assert st["directory_changed"] is False
        assert st["unexported_writes"] == 0
        assert st["in_sync"] is True

    def test_directory_change_detected(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        db.store_source_fingerprint(src)
        (src / "data.jsonl").write_text('{"content": "a"}\n{"content": "b"}\n')
        st = db.sync_status(src)
        db.close()
        assert st["directory_changed"] is True
        assert st["in_sync"] is False

    def test_media_change_detected(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        (src / "media").mkdir()
        (src / "media" / "x.bin").write_bytes(b"one")
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        db.store_source_fingerprint(src)
        (src / "media" / "x.bin").write_bytes(b"two")  # same name, new bytes
        st = db.sync_status(src)
        db.close()
        assert st["directory_changed"] is True

    def test_derived_db_does_not_count_as_change(self, tmp_path):
        # An arkiv.db sitting inside the source directory must be excluded
        # from the fingerprint (it is derived), so its presence/rewrite does
        # not register as directory drift.
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(src / "arkiv.db")
        db.import_readme(src / "README.md")
        db.store_source_fingerprint(src)
        st = db.sync_status(src)
        db.close()
        assert st["directory_changed"] is False
        assert st["in_sync"] is True

    def test_unexported_writes_counted(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        db.store_source_fingerprint(src)
        db.insert_record("data", "new record")
        db.insert_record("data", "another")
        st = db.sync_status(src)
        db.close()
        assert st["unexported_writes"] == 2
        assert st["in_sync"] is False

    def test_storing_fingerprint_resets_counter(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        db.insert_record("data", "x")
        db.store_source_fingerprint(src)  # convert resets the counter
        st = db.sync_status(src)
        db.close()
        assert st["unexported_writes"] == 0

    def test_no_fingerprint_is_unknown(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")  # does NOT fingerprint on its own
        st = db.sync_status(src)
        db.close()
        assert st["has_fingerprint"] is False
        assert st["in_sync"] is False


def run_arkiv(*args):
    return subprocess.run(
        [sys.executable, "-m", "arkiv.cli", *[str(a) for a in args]],
        capture_output=True,
        text=True,
    )


def _collections_of(db_path):
    db = Database(db_path, read_only=True)
    try:
        rows = db.query("SELECT DISTINCT collection FROM records ORDER BY collection")
        return [r["collection"] for r in rows]
    finally:
        db.close()


class TestReconvertFromScratch:
    def test_reconvert_drops_removed_collection(self, tmp_path):
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "a.jsonl").write_text('{"content": "a"}\n')
        (archive / "b.jsonl").write_text('{"content": "b"}\n')
        (archive / "README.md").write_text(
            "---\ncontents:\n- path: a.jsonl\n- path: b.jsonl\n---\n"
        )
        assert run_arkiv("convert", archive).returncode == 0
        assert _collections_of(archive / "arkiv.db") == ["a", "b"]

        (archive / "b.jsonl").unlink()
        (archive / "README.md").write_text("---\ncontents:\n- path: a.jsonl\n---\n")
        r = run_arkiv("convert", archive)
        assert r.returncode == 0, r.stderr
        assert _collections_of(archive / "arkiv.db") == ["a"]
        assert json.loads(run_arkiv("status", archive).stdout)["in_sync"] is True

    def test_reconvert_drops_stale_readme_body(self, tmp_path):
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "a.jsonl").write_text('{"content": "a"}\n')
        (archive / "README.md").write_text(
            "---\ncontents:\n- path: a.jsonl\n---\nBody text\n"
        )
        assert run_arkiv("convert", archive).returncode == 0
        (archive / "README.md").write_text("---\ncontents:\n- path: a.jsonl\n---\n")
        r = run_arkiv("convert", archive)
        assert r.returncode == 0, r.stderr
        db = Database(archive / "arkiv.db", read_only=True)
        try:
            assert db.get_readme().body == ""
        finally:
            db.close()
