"""Tests for arkiv.readme."""

import pytest
from arkiv.readme import Readme, split_frontmatter, parse_readme, save_readme


class TestSplitFrontmatter:
    def test_with_frontmatter(self):
        text = "---\nname: Test\n---\n# Hello\n"
        fm, body = split_frontmatter(text)
        assert fm == "name: Test"
        assert body == "# Hello\n"

    def test_no_frontmatter(self):
        text = "# Just markdown\nSome content\n"
        fm, body = split_frontmatter(text)
        assert fm == ""
        assert body == text

    def test_empty_string(self):
        fm, body = split_frontmatter("")
        assert fm == ""
        assert body == ""

    def test_no_closing_delimiter(self):
        text = "---\nname: Test\nno closing\n"
        fm, body = split_frontmatter(text)
        assert fm == ""
        assert body == text

    def test_multiline_frontmatter(self):
        text = "---\nname: Test\ndescription: A test archive\n---\nBody here\n"
        fm, body = split_frontmatter(text)
        assert "name: Test" in fm
        assert "description: A test archive" in fm
        assert body == "Body here\n"

    def test_frontmatter_with_empty_body(self):
        text = "---\nname: Test\n---\n"
        fm, body = split_frontmatter(text)
        assert fm == "name: Test"
        assert body == ""


class TestReadme:
    def test_default_readme(self):
        r = Readme()
        assert r.frontmatter == {}
        assert r.body == ""

    def test_readme_with_data(self):
        r = Readme(
            frontmatter={"name": "My Archive", "description": "Test"},
            body="# My Archive\n\nSome content.\n",
        )
        assert r.frontmatter["name"] == "My Archive"
        assert "Some content" in r.body


class TestParseReadme:
    def test_parse_full(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text(
            "---\nname: Test Archive\ndescription: A test\n---\n\n# Test Archive\n\nDetails here.\n"
        )
        readme = parse_readme(f)
        assert readme.frontmatter["name"] == "Test Archive"
        assert readme.frontmatter["description"] == "A test"
        assert "# Test Archive" in readme.body

    def test_parse_no_frontmatter(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("# Just Markdown\n\nNo frontmatter.\n")
        readme = parse_readme(f)
        assert readme.frontmatter == {}
        assert "# Just Markdown" in readme.body

    def test_parse_preserves_unknown_keys(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("---\nname: Test\ncustom_field: value\ntags: [a, b]\n---\n")
        readme = parse_readme(f)
        assert readme.frontmatter["name"] == "Test"
        assert readme.frontmatter["custom_field"] == "value"
        assert readme.frontmatter["tags"] == ["a", "b"]

    def test_parse_with_contents_list(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text(
            "---\nname: Archive\ncontents:\n- path: conversations.jsonl\n  description: AI chats\n- path: bookmarks.jsonl\n---\nBody\n"
        )
        readme = parse_readme(f)
        assert len(readme.frontmatter["contents"]) == 2
        assert readme.frontmatter["contents"][0]["path"] == "conversations.jsonl"
        assert readme.frontmatter["contents"][0]["description"] == "AI chats"
        assert readme.frontmatter["contents"][1]["path"] == "bookmarks.jsonl"

    def test_parse_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_readme(tmp_path / "nope.md")

    def test_parse_empty_frontmatter(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("---\n---\nJust body\n")
        readme = parse_readme(f)
        assert readme.frontmatter == {}
        assert "Just body" in readme.body


class TestSaveReadme:
    def test_save_full(self, tmp_path):
        r = Readme(
            frontmatter={"name": "Test", "description": "A test archive"},
            body="# Test\n\nDetails.\n",
        )
        path = tmp_path / "README.md"
        save_readme(r, path)
        text = path.read_text()
        assert text.startswith("---\n")
        assert "name: Test" in text
        assert "description: A test archive" in text
        assert "---" in text
        assert "# Test" in text
        assert "Details." in text

    def test_save_no_frontmatter(self, tmp_path):
        r = Readme(body="# Just markdown\n")
        path = tmp_path / "README.md"
        save_readme(r, path)
        text = path.read_text()
        assert not text.startswith("---")
        assert "# Just markdown" in text

    def test_save_no_body(self, tmp_path):
        r = Readme(frontmatter={"name": "Test"})
        path = tmp_path / "README.md"
        save_readme(r, path)
        text = path.read_text()
        assert "---" in text
        assert "name: Test" in text

    def test_roundtrip(self, tmp_path):
        original = Readme(
            frontmatter={
                "name": "My Archive",
                "description": "Personal data",
                "datetime": "2024-06-15",
                "generator": "arkiv v0.1.0",
                "contents": [
                    {"path": "conversations.jsonl", "description": "AI chats"},
                    {"path": "bookmarks.jsonl"},
                ],
            },
            body="# My Archive\n\nPersonal data archive.\n",
        )
        path = tmp_path / "README.md"
        save_readme(original, path)
        loaded = parse_readme(path)
        assert loaded.frontmatter["name"] == original.frontmatter["name"]
        assert loaded.frontmatter["description"] == original.frontmatter["description"]
        assert loaded.frontmatter["datetime"] == original.frontmatter["datetime"]
        assert loaded.frontmatter["contents"] == original.frontmatter["contents"]
        assert "# My Archive" in loaded.body
        assert "Personal data archive." in loaded.body

    def test_roundtrip_preserves_unknown_keys(self, tmp_path):
        original = Readme(
            frontmatter={"name": "Test", "custom": "value", "tags": [1, 2, 3]},
            body="Body\n",
        )
        path = tmp_path / "README.md"
        save_readme(original, path)
        loaded = parse_readme(path)
        assert loaded.frontmatter["custom"] == "value"
        assert loaded.frontmatter["tags"] == [1, 2, 3]

    def test_ends_with_newline(self, tmp_path):
        r = Readme(frontmatter={"name": "Test"}, body="Content")
        path = tmp_path / "README.md"
        save_readme(r, path)
        assert path.read_text().endswith("\n")
