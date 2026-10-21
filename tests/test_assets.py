"""Tests for binary asset (media/) preservation through the database form.

The directory and database forms are isomorphic peers, so binary assets
referenced by ``file://media/...`` URIs must survive a
directory -> db -> directory roundtrip. They are carried as BLOBs in the
``_assets`` table.
"""

import sqlite3

import pytest

from arkiv.database import Database

# Arbitrary non-UTF-8 binary payload (a PNG signature plus raw bytes).
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


def _make_archive(d, with_media=True):
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.jsonl").write_text(
        '{"mimetype": "image/png", "uri": "file://media/pic.png", '
        '"metadata": {"caption": "talk"}}\n'
    )
    (d / "README.md").write_text("---\ncontents:\n- path: data.jsonl\n---\n")
    if with_media:
        (d / "media").mkdir()
        (d / "media" / "pic.png").write_bytes(PNG_BYTES)


class TestAssetImport:
    def test_media_stored_in_assets_table(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        row = db.conn.execute(
            "SELECT path, content FROM _assets"
        ).fetchone()
        db.close()
        assert row["path"] == "media/pic.png"
        assert bytes(row["content"]) == PNG_BYTES

    def test_nested_media_paths_preserved(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        (src / "media" / "sub").mkdir()
        (src / "media" / "sub" / "clip.wav").write_bytes(b"RIFF\x00\x01")
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        paths = {
            r["path"]
            for r in db.conn.execute("SELECT path FROM _assets")
        }
        db.close()
        assert paths == {"media/pic.png", "media/sub/clip.wav"}

    def test_reimport_is_idempotent(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        db.import_readme(src / "README.md")
        n = db.conn.execute("SELECT COUNT(*) FROM _assets").fetchone()[0]
        db.close()
        assert n == 1


class TestAssetRoundtrip:
    def test_dir_db_dir_preserves_media_bytes(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        out = tmp_path / "out"
        db.export(out)
        db.close()
        assert (out / "media" / "pic.png").read_bytes() == PNG_BYTES

    def test_nested_export_preserves_media(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        out = tmp_path / "out"
        db.export(out, nested=True)
        db.close()
        assert (out / "media" / "pic.png").read_bytes() == PNG_BYTES

    def test_no_media_dir_is_fine(self, tmp_path):
        src = tmp_path / "src"
        _make_archive(src, with_media=False)
        db = Database(tmp_path / "a.db")
        db.import_readme(src / "README.md")
        out = tmp_path / "out"
        db.export(out)
        n = db.conn.execute("SELECT COUNT(*) FROM _assets").fetchone()[0]
        db.close()
        assert n == 0
        assert not (out / "media").exists()


class TestAssetSafety:
    def test_legacy_db_without_assets_table_exports(self, tmp_path):
        # A database created before the _assets table existed must still
        # export (backward compatibility), just without media.
        db = Database(tmp_path / "a.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection="data")
        db.conn.execute("DROP TABLE _assets")
        db.conn.commit()
        out = tmp_path / "out"
        db.export(out)  # must not raise
        db.close()
        assert (out / "data.jsonl").exists()

    def test_asset_path_escape_rejected_on_export(self, tmp_path):
        # A malicious asset path that escapes the output directory must be
        # rejected rather than written outside it.
        db = Database(tmp_path / "a.db")
        f = tmp_path / "data.jsonl"
        f.write_text('{"content": "hi"}\n')
        db.import_jsonl(f, collection="data")
        db.conn.execute(
            "INSERT INTO _assets (path, content) VALUES (?, ?)",
            ("../escaped.bin", b"pwned"),
        )
        db.conn.commit()
        with pytest.raises(ValueError, match="escape"):
            db.export(tmp_path / "out")
        db.close()
        assert not (tmp_path / "escaped.bin").exists()

    def test_export_refuses_asset_rows_outside_media(self, tmp_path):
        # Only rows under media/ are reconstructed on export; a crafted row
        # naming a file elsewhere in the archive must not overwrite it.
        db = Database(tmp_path / "x.db")
        db.conn.execute("INSERT INTO _assets VALUES ('README.md', ?)", (b"pwned",))
        db.conn.commit()
        with pytest.raises(ValueError, match="unsafe asset path"):
            db.export(tmp_path / "out")
        db.close()
        assert (tmp_path / "out" / "README.md").read_bytes() != b"pwned"

    @pytest.mark.parametrize(
        "rel",
        [
            "data.jsonl",
            "schema.yaml",
            "media",
            "media/",
            "media/..",
            "media/../README.md",
            "media/a/../../schema.yaml",
            "media/x/../../data.jsonl",
            "/media/x",
            "media\\..\\README.md",
            "media/x\0.bin",
            "./media/x",
            "media//x",
            "",
        ],
    )
    def test_export_refuses_asset_paths_not_under_media(self, tmp_path, rel):
        db = Database(tmp_path / "x.db")
        db.conn.execute("INSERT INTO _assets VALUES (?, ?)", (rel, b"pwned"))
        db.conn.commit()
        out = tmp_path / "out"
        with pytest.raises(ValueError, match="unsafe asset path"):
            db.export(out)
        db.close()
        # The crafted bytes must not be written anywhere under the output.
        assert not any(
            b"pwned" in p.read_bytes() for p in out.rglob("*") if p.is_file()
        )

    def test_export_refuses_media_path_resolving_outside_media(self, tmp_path):
        # The row is canonical, but a symlink inside media/ points back at the
        # archive root. The resolved target is inside the output directory yet
        # outside media/, so it must be refused.
        db = Database(tmp_path / "x.db")
        db.conn.execute(
            "INSERT INTO _assets VALUES ('media/up/README.md', ?)", (b"pwned",)
        )
        db.conn.commit()
        out = tmp_path / "out"
        (out / "media").mkdir(parents=True)
        (out / "media" / "up").symlink_to(out, target_is_directory=True)
        with pytest.raises(ValueError, match="unsafe asset path"):
            db.export(out)
        db.close()
        assert (out / "README.md").read_bytes() != b"pwned"

    def test_export_refuses_media_path_through_symlink_out_of_archive(self, tmp_path):
        db = Database(tmp_path / "x.db")
        db.conn.execute(
            "INSERT INTO _assets VALUES ('media/link/x.bin', ?)", (b"pwned",)
        )
        db.conn.commit()
        out = tmp_path / "out"
        outside = tmp_path / "outside"
        outside.mkdir()
        (out / "media").mkdir(parents=True)
        (out / "media" / "link").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError, match="unsafe asset path"):
            db.export(out)
        db.close()
        assert not (outside / "x.bin").exists()

    def test_canonical_media_path_exported_under_media(self, tmp_path):
        db = Database(tmp_path / "x.db")
        db.conn.execute("INSERT INTO _assets VALUES ('media/a/b.bin', ?)", (b"ok",))
        db.conn.commit()
        out = tmp_path / "out"
        db.export(out)
        db.close()
        assert (out / "media" / "a" / "b.bin").read_bytes() == b"ok"
