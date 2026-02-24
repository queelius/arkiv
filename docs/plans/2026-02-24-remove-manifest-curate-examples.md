# Remove manifest.py + Curate examples/ Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove all manifest.json support (clean break) and replace the bloated examples/ with a small curated archive that doubles as a living test fixture.

**Architecture:** Delete manifest.py and all references, then build a 5-record example archive in the new README.md + schema.yaml format with a smoke test that imports and roundtrips it.

**Tech Stack:** Python, pytest, pyyaml

---

### Task 1: Delete manifest.py and its tests

**Files:**
- Delete: `src/arkiv/manifest.py`
- Delete: `tests/test_manifest.py`
- Delete: `tests/test_manifest_import.py`

**Step 1: Delete the files**

```bash
rm src/arkiv/manifest.py tests/test_manifest.py tests/test_manifest_import.py
```

**Step 2: Run tests to confirm expected failures**

Run: `pytest tests/ -q 2>&1 | tail -5`
Expected: Import errors in files that reference manifest

**Step 3: Commit**

```bash
git add -u src/arkiv/manifest.py tests/test_manifest.py tests/test_manifest_import.py
git commit -m "Remove manifest.py and its tests"
```

---

### Task 2: Remove manifest references from __init__.py

**Files:**
- Modify: `src/arkiv/__init__.py:14,29-32`

**Step 1: Remove the manifest import line and __all__ entries**

In `src/arkiv/__init__.py`, delete line 14:
```python
from .manifest import Manifest, Collection, load_manifest, save_manifest
```

And remove these entries from `__all__` (lines 29-32):
```python
    "Manifest",
    "Collection",
    "load_manifest",
    "save_manifest",
```

**Step 2: Run tests to verify import errors are gone for __init__**

Run: `python -c "import arkiv; print(dir(arkiv))"`
Expected: No error, no Manifest/Collection in output

**Step 3: Commit**

```bash
git add src/arkiv/__init__.py
git commit -m "Remove manifest symbols from public API"
```

---

### Task 3: Remove import_manifest from database.py

**Files:**
- Modify: `src/arkiv/database.py:392-430` (delete `import_manifest` method)

**Step 1: Delete the `import_manifest` method**

Remove the entire method at lines 392-430:
```python
    def import_manifest(self, manifest_path: Union[str, Path]) -> int:
        ...
        return total
```

Also remove `_store_manifest_metadata` and `_load_manifest_metadata` if they exist and are only used by `import_manifest`. Check with grep first.

**Step 2: Run tests to see which tests now fail**

Run: `pytest tests/ -q 2>&1 | tail -10`
Expected: Failures in test_cli (test_import_manifest, test_import_directory_fallback_manifest), test_database (test_import_manifest_stores_as_readme_metadata), test_integration (test_manifest_import_still_works)

**Step 3: Commit**

```bash
git add src/arkiv/database.py
git commit -m "Remove import_manifest from Database"
```

---

### Task 4: Remove manifest references from CLI and tests

**Files:**
- Modify: `src/arkiv/cli.py:11-46`
- Modify: `tests/test_cli.py` (delete test_import_manifest at :38, test_import_directory_fallback_manifest at :303)
- Modify: `tests/test_database.py` (delete test_import_manifest_stores_as_readme_metadata at :364)
- Modify: `tests/test_integration.py` (delete test_manifest_import_still_works at :91, update test_public_api_imports at :116)

**Step 1: Update cmd_import in cli.py**

Replace the directory import block to remove manifest.json fallback:
```python
    if input_path.is_dir():
        readme_path = input_path / "README.md"
        if readme_path.exists():
            count = db.import_readme(readme_path)
            print(f"Imported {count} records from README.md")
        else:
            print(f"Error: No README.md found in {input_path}", file=sys.stderr)
            db.close()
            sys.exit(1)
```

Remove the `.json` routing (lines 40-42). After `.md` check, fall through to JSONL:
```python
    elif input_path.suffix == ".md":
        count = db.import_readme(input_path)
        print(f"Imported {count} records from {input_path.name}")
    else:
        count = db.import_jsonl(input_path)
        print(f"Imported {count} records from {input_path.name}")
```

Update the docstring to remove "manifest.json":
```python
def cmd_import(args):
    """Import JSONL, README.md, or directory into a SQLite database."""
```

**Step 2: Delete manifest-related tests**

In `tests/test_cli.py`:
- Delete `test_import_manifest` (lines 38-46)
- Delete `test_import_directory_fallback_manifest` (lines 303-313)
- Update `test_import_empty_directory` error message: change `"No README.md or manifest.json"` to `"No README.md"`

In `tests/test_database.py`:
- Delete `test_import_manifest_stores_as_readme_metadata` (lines 364-383)

In `tests/test_integration.py`:
- Delete `test_manifest_import_still_works` (lines 91-114)
- In `test_public_api_imports`, remove `Manifest`, `Collection`, `load_manifest`, `save_manifest` from the import (they no longer exist)

**Step 3: Run tests**

Run: `pytest tests/ -q`
Expected: All pass (count will be lower — we removed ~5 manifest tests)

**Step 4: Commit**

```bash
git add src/arkiv/cli.py tests/test_cli.py tests/test_database.py tests/test_integration.py
git commit -m "Remove all manifest.json references from CLI and tests"
```

---

### Task 5: Clean up examples/ directory

**Files:**
- Delete: `examples/archive.db`, `examples/repos.jsonl`, `examples/exported/` (entire directory)
- Create: `examples/repos/README.md`
- Create: `examples/repos/schema.yaml`
- Create: `examples/repos/repos.jsonl`

**Step 1: Remove old examples**

```bash
rm -rf examples/
```

**Step 2: Create examples/repos/repos.jsonl**

Extract 5 diverse records from the original data (Python, R, C++, JavaScript, Go). Each record should be a valid arkiv record with `mimetype`, `uri` (not `url`), `timestamp`, `content`, and `metadata`. Trim metadata to essential keys: `name`, `description`, `language`, `languages`, `is_clean`, `has_ci`, `has_readme`, `has_license`, `owner`.

5 records, one per line, valid JSONL.

**Step 3: Create examples/repos/README.md**

```markdown
---
name: repos
description: Sample repository metadata from repoindex
datetime: "2026-02-24"
generator: repoindex
contents:
  - path: repos.jsonl
    description: Git repository metadata records
---

# repos

A small sample of git repository metadata exported by [repoindex](https://github.com/queelius/repoindex).

Each record describes a single repository with language, CI status, and other metadata.
```

**Step 4: Create examples/repos/schema.yaml**

```yaml
# schema.yaml — curated metadata schema for repos archive
repos:
  record_count: 5
  metadata_keys:
    name:
      type: string
      count: 5
      description: Repository name
    description:
      type: string
      count: 4
      description: Repository description from README or GitHub
    language:
      type: string
      count: 5
      values: [C++, Go, JavaScript, Python, R]
      description: Primary programming language
    languages:
      type: array
      count: 5
      description: All detected programming languages
    owner:
      type: string
      count: 5
      description: Repository owner (GitHub username)
    is_clean:
      type: boolean
      count: 5
      description: Whether the working tree is clean
    has_ci:
      type: boolean
      count: 5
      description: Whether CI/CD is configured
    has_readme:
      type: boolean
      count: 5
      description: Whether a README file exists
    has_license:
      type: boolean
      count: 5
      description: Whether a LICENSE file exists
```

**Step 5: Verify the example is valid**

```bash
python -m arkiv.cli detect examples/repos/repos.jsonl
```
Expected: valid arkiv JSONL

**Step 6: Commit**

```bash
git add examples/
git commit -m "Add curated 5-record example archive in README.md + schema.yaml format"
```

---

### Task 6: Add example archive smoke test

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Write the smoke test**

Add to `TestEndToEnd` in `tests/test_integration.py`:

```python
    def test_example_archive_roundtrip(self, tmp_path):
        """The examples/repos/ archive imports and roundtrips cleanly."""
        import os
        example_dir = Path(os.path.dirname(__file__)).parent / "examples" / "repos"
        assert example_dir.exists(), f"Example archive not found at {example_dir}"

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        count = db.import_readme(example_dir / "README.md")
        assert count == 5

        # Verify schema descriptions survived import
        schema = db.get_schema("repos")
        assert "language" in schema["metadata_keys"]
        assert schema["metadata_keys"]["language"]["description"] == "Primary programming language"

        # Export and verify roundtrip
        out = tmp_path / "exported"
        db.export(out)
        db.close()

        assert (out / "README.md").exists()
        assert (out / "schema.yaml").exists()
        assert (out / "repos.jsonl").exists()

        # Re-import exported data
        db2 = Database(tmp_path / "test2.db")
        count2 = db2.import_readme(out / "README.md")
        assert count2 == 5
        db2.close()
```

**Step 2: Run the test**

Run: `pytest tests/test_integration.py::TestEndToEnd::test_example_archive_roundtrip -v`
Expected: PASS

**Step 3: Run full suite + coverage**

Run: `pytest tests/ --cov=src/arkiv --cov-report=term-missing -q`
Expected: All pass

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "Add smoke test for example archive roundtrip"
```

---

### Task 7: Drop stale stash and final cleanup

**Step 1: Drop the stash**

```bash
git stash drop stash@{0}
```

**Step 2: Verify final state**

```bash
git status
git log --oneline -10
pytest tests/ -q
```

Expected: Clean working tree, all tests pass, no manifest references remain.

**Step 3: Verify no stale manifest references**

```bash
grep -r "manifest" src/ tests/ --include="*.py" -l
```

Expected: No files returned (or only comments/docstrings if any remain — clean those up).
