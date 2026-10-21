# Handoff from longecho: making "longecho-compliant by construction" true for every producer

**Written:** 2026-10-19, from a Claude Code session in `~/github/beta/longecho`.
**Read first:** `~/github/beta/longecho/docs/ideas/arkiv-boundary.md` (the shared contract), then this file. For longecho itself: its `README.md` and `CLAUDE.md`.

## Why this matters

The author plans to use arkiv as the way to make many of their projects longecho-compliant. arkiv's `SPEC.md` (4.4) already claims arkiv archives are "longecho-compliant by construction". Today that holds only for `arkiv convert` / `Database.export()`. The six memex exporters call arkiv's low-level bundle functions and assemble their own README and `schema.yaml` by hand, so compliance is a habit, not a guarantee, and the `schema.yaml` convention has already split in two.

A live test in the longecho session confirmed: llm-memex and mail-memex arkiv exports (directory form) pass `longecho check`. Their bare `.zip` bundles are not sources, and the memex HTML viewers have no README.

## Verified current state (paths relative to `~/github`)

- `beta/arkiv/src/arkiv/bundle.py:178` `write_bundle(path, members)` writes whatever members it is given. Nothing requires a README or `schema.yaml`.
- `beta/arkiv/src/arkiv/schema.py:159` `load_schema_yaml` treats every top-level mapping as a collection and silently skips what it does not understand. A kind-keyed file would yield phantom collections `counts` and `kinds` with no warning (not yet run to confirm).
- Hand-rolled README and `schema.yaml` writers, one per tool:
  - `memex/llm-memex/llm_memex/exporters/arkiv_export.py` (collection-keyed schema, around lines 222-245)
  - `memex/photo-memex/photo_memex/exports/arkiv.py` (collection-keyed)
  - `memex/health-memex/src/health_memex/export_arkiv.py` (collection-keyed, plus `media/`)
  - `memex/mail-memex/src/mail_memex/export/arkiv_export.py` (kind-keyed `{scheme, counts, kinds}`, around lines 141-166)
  - `memex/book-memex/book_memex/exports/arkiv.py` (kind-keyed)
  - `memex/bookmark-memex/bookmark_memex/exporters/arkiv.py` (kind-keyed)
- Nothing in memex uses arkiv's `Database`, `discover_schema`, or schema rendering.

## Tasks, in order

### 1. One producer function that guarantees a compliant archive

Add a public function (name and exact signature are yours to decide; a starting point):

```python
def write_archive(
    path: PathLike,
    collections: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    name: str,
    description: str,
    generator: str,
    readme_body: str | None = None,
    collection_descriptions: Mapping[str, str] | None = None,
    media: Mapping[str, bytes] | None = None,
    nested: bool = False,
) -> None: ...
```

It always writes README frontmatter (`name`, `description`, `datetime`, `generator`, `arkiv_format`, `contents`), a `schema.yaml` in the canonical shape (task 2), one JSONL file per collection, and `media/`. It reuses `write_bundle` for the dir/zip/tar.gz choice and the existing schema discovery for counts and keys, so there is one implementation, not seven. Keep `write_bundle` as the low-level primitive and say in its docstring that it does not guarantee compliance.

Done when: the six memex exporters can each replace their `_readme_bytes` / `_schema_yaml_bytes` code with one call (migrating them is follow-on work in each memex repo, task 7).

### 2. Make the `schema.yaml` shape normative

Pick the canonical shape and write it into `SPEC.md` 1.4 as normative. A suggestion, not a decision:

- Keep the collection-keyed shape. Import merging and `load_schema_yaml` already depend on it.
- Add optional per-collection keys that carry what the kind-keyed files have: `description`, `uri` (URI template such as `mail-memex://email/<message_id>`), and per-field `description` inside `metadata_keys` (which replaces `fields`).
- Move the top-level `scheme` to README frontmatter, where identity already lives, so `schema.yaml` has no non-collection top-level keys.
- Make `load_schema_yaml` warn (or error, your call) on a top-level entry that is not a collection mapping, instead of silently creating phantom collections. Add a test with a kind-keyed file.
- Decide whether this needs an `arkiv_format` bump. Optional keys are backward compatible; a reserved top-level key would not be.

longecho will then display `schema.yaml` loosely (its plan, task C1). It will never require or validate it.

### 3. Bundles are transport, not archives

Say in `SPEC.md` 1.2 that a bare `.zip` / `.tar.gz` is a durable artifact but not a self-describing source: tools that read directories (longecho, file browsers, people) cannot see inside it. Then pick one: exporters default to the directory form, or `write_archive` to a bundle path also documents that the bundle should sit in a directory with a README. Do not make longecho read inside archives; that boundary is deliberate on both sides.

### 4. Write the shared contract into `SPEC.md` section 4.4

Add, briefly: the split meaning of `contents` file entries (arkiv: import list; longecho: informational); the `site/` generator convention (viewers write `site/README.md` with `generator: <tool> <version>`; from longecho 0.5.0 an unstamped `site/` is protected from `longecho build`); that `FIXITY.sha256` and `site/` may appear in an archive root and are not collections, and should survive a re-export into the same directory.

### 5. Media formats: check against longecho's registry, do not copy it

Updated 2026-10-21. longecho now keeps durable formats as one registry, `longecho.formats.FORMATS`: each entry has its extensions, a media type, the readers that can open it (standard tool, web browser, text editor), and a one-line reason judged against the Library of Congress sustainability factors. The list now includes `.pdf`, `.epub`, `.eml`, `.mbox`, `.svg`, `.tif`/`.tiff`, `.wav`, `.flac`, `.mp3`, `.ogg`, `.opus`, `.mp4`, `.webm`. HEIC and office formats are deliberately off it; longecho warns about them instead of failing.

- SPEC.md's `media/` guidance should say "prefer formats on longecho's durable list" and point at `longecho formats` (or https://queelius.github.io/longecho/spec/), not restate the list. A second copy would drift.
- Because arkiv records carry a `mimetype`, alignment can be tested instead of maintained: in arkiv's tests (test-only longecho dependency, task 6), assert that every mimetype arkiv's docs, examples, and `write_archive` defaults recommend for `media/` passes `longecho.formats.is_durable_mimetype(mt)`. It accepts each format's canonical type and its common aliases (`audio/x-wav`, `application/x-ndjson`, `image/jpg`, and so on), ignoring case and parameters, so arkiv need not normalize first. `longecho formats --json` exposes the same data (`mimetype`, `mimetype_aliases`) for non-Python callers.
- If arkiv needs a format longecho lacks, propose it upstream with a reason against the criteria; do not add it on arkiv's side.

### 6. Prove compliance in tests

Add `longecho` as a test-only dependency (a dev extra, never a runtime dependency) and assert, for `Database.export()` and `write_archive` in directory form, both flat and `--nested`:

```python
from longecho import check_compliance
result = check_compliance(out_dir)
assert result.compliant
assert result.warnings == []  # longecho >= 0.6.0: nothing unreadable, no SQLite sidecar at risk, nothing too deep to inspect
```

This turns the SPEC's claim into a guarantee in one place, so the memex repos inherit it.

### 7. Follow-on in the memex repos (not this repo)

- Migrate each exporter to `write_archive`; mail, book, and bookmark move to the canonical `schema.yaml` shape.
- Every HTML viewer export writes `README.md` with `generator: <tool> <version>` (so `longecho build` never overwrites it, and so it is a source in its own right).
- book-memex: `book_memex/cli.py:4032` and `book_memex/exports/echo_export.py:274` link to `github.com/alextowell/longecho`; the correct repo is `github.com/queelius/longecho`. Consider retiring the ECHO export in favor of arkiv.

## What arkiv should not do

- Depend on longecho at runtime, or add longecho-specific branches.
- Generate the archive-of-archives site (longecho's `build` does that; arkiv's universal viewer is the per-archive fallback reader).
- Turn `schema.yaml` into validation. It stays a data dictionary (SPEC "Why a data dictionary, not a validation schema?").

## Open questions for the author

- Canonical `schema.yaml` shape: the suggestion above, or adopt the richer kind-keyed shape?
- Default export form for memex tools: directory, or bundle plus README?
- ~~Should `write_archive` write an optional `START_HERE.txt`?~~ Decided 2026-10-21: no. The README is the start-here note, and longecho's spec now says so. What `write_archive` should do instead: open the generated README body with a plain-language paragraph (what this is, where it came from, that the `.jsonl` files open in any text editor), so the README works for a reader with none of our tools.
