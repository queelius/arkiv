# arkiv review, 2026-10-21

Review of arkiv 0.4.0 (HEAD `2011bbe`, tag `v0.4.0`, on PyPI) across five
lenses: correctness and security, simplification and code quality, docs and
spec, producer conformance (the six `*-memex` exporters), and the
arkiv/longecho boundary contract (`../longecho/docs/ideas/arkiv-boundary.md`,
handoff `docs/handoffs/2026-10-19-from-longecho.md`).

Four reviewers worked in parallel, read-only, and had to attach a repro to
every claim. Every HIGH finding below was then reproduced a second time,
independently, before it went into this report. The column "Verified" says who
reproduced it: **both** (reviewer and the second pass), **reviewer** (repro by
the reviewer only), or **reading** (code reading, no repro).

This file is a record, not a change. Nothing here is fixed yet.

## Baseline

- 444 tests pass (Python 3.12, fresh venv).
- Coverage reads 74% overall. `cli.py` shows 14% only because the CLI tests
  run it through `subprocess`, which coverage does not follow. The 93% quoted
  in June was in effect "everything except the CLI". With
  `[run] patch = subprocess` (coverage 7.10+), `cli.py` measures 92% with no
  test changes.
- `black --check`: 23 of 30 files would be reformatted (the repo has never
  been black-clean). `flake8`: 236 issues, 195 of them line length.
  `mypy src`: 22 errors, and the config's `python_version = "3.8"` is rejected
  by current mypy.
- `Database.export()` output passes `longecho check` with zero warnings, flat
  and `--nested`. So "longecho-compliant by construction" holds for arkiv's
  own exporter; the gap is in the hand-rolled memex exporters.

---

## Verdict

The 0.3.0 fixes held, and the 0.4.0 bundle I/O is careful where it was aimed:
bounded streaming reads, symlink refusal in directory bundles, and
reproducible gzip headers all checked out. The read-only SQL layer could not
be written through.

But the review found **two input paths that bypass the containment the rest of
the code enforces** (README `contents` paths and `media/` symlinks), which
together let a hostile bundle copy arbitrary host files into a database that
then gets shared. It also found **several ways the database silently stops
matching the authoritative directory**: reconverting keeps removed
collections, `arkiv convert <dir>` destroys unexported writes, and exported
`schema.yaml` is wrong after one round trip and never recovers. These are
patch-release material.

On the ecosystem side, the handoff understated the drift: the memex
exporters write **three** `schema.yaml` shapes, not two, and a memex archive
round-tripped through `arkiv convert` can no longer be read by the tool that
made it. A producer function plus a normative schema shape is the right fix,
and the code is close to supporting it once `export()` is split into "build
members" and "write members".

### Strong parts (do not regress)

- `_BoundedReader` charging every header and skipped byte against the budget,
  the tar entry cap, and the upfront check of declared member sizes.
- Symlink refusal and `resolve()`-based containment in `write_bundle`
  (directory mode), `open_member`, `pack_bundle`, and `iter_source_files`.
- Fixed gzip headers (no file name, `mtime=0`): same content, same bytes.
- SELECT/WITH prefix gate plus the sqlite3 authorizer.
- Lossless `timestamp_original`, collection-collision detection,
  `filter="data"` extraction on 3.12+.

---

## Tier 1: security

| ID | Finding | Where | Verified |
|---|---|---|---|
| S1 | README `contents` paths are not contained: absolute paths and `..` are accepted, so a bundle can import any `.jsonl` on the host (Claude Code transcripts are `.jsonl`) | `database.py:851`, `:923` | both |
| S2 | `import_assets` follows symlinks, both a symlinked `media/` and symlinked files inside it, so host files land in `_assets` and then in exported bundles. `iter_source_files` guards against this; this path does not | `database.py:807-816` | both |
| S3 | Tar GNU long-name and pax headers are read whole into memory. Measured: a 65 KB `.tar.gz` peaks at 277 MiB in `iter_jsonl`; the reviewer's 600 KB file peaked at 1.3 GB (`iter_jsonl`) and 5.4 GB (`unpack_bundle`, which has no bound), the latter ending in an `OSError` traceback | `bundle.py:272-274`, `:424`, `:464` | both |
| S4 | The read-only open builds an unescaped `file:` URI, so a path containing `#`, `?`, or `%` opens a different file read-write and creates it (`notes#1.db` creates `notes`) | `database.py:118-120` | both |
| S5 | Duplicate tar members: `iter_jsonl` returns the first match, extraction keeps the last, so a tool that validates with `iter_jsonl` approves different data than `convert` imports | `bundle.py:275-287` | reviewer |
| S6 | `sql_query` has no time limit and no cell-size limit: an infinite recursive CTE hangs the MCP server; one 40 M-character cell returns with `truncated: False` | `database.py:415-438` | reviewer |
| S7 | Asset rows in a crafted database can overwrite exported non-media files (`README.md`, `*.jsonl`) | `database.py:783-791` | reviewer |

Fixes in brief: S1, require `_within(entry, archive_root)` and reject absolute
and `..` parts. S2, walk `media/` with the same walk as `iter_source_files`
(see Q5). S3, a small header cap (1 MiB) checked against `tinfo.size` before
tarfile reads the payload, stream `unpack_bundle` through `_BoundedReader`,
and map `OSError` to `ValueError`. S4, `self.path.resolve().as_uri() +
"?mode=ro"`. S5, refuse duplicate names in scan and extract. S6,
`set_progress_handler` with a deadline, and a per-cell cap. S7, accept asset
paths under `media/` only.

## Tier 2: data loss and broken core promises

| ID | Finding | Where | Verified |
|---|---|---|---|
| L1 | `arkiv convert <dir>` after `write_record` silently deletes the written records (exit 0, "1 records"). SPEC 3.2 tells users to run exactly this to refresh the schema. The unexported-writes guard exists only in `_resolve_db` | `cli.py:140-158`, SPEC 3.2 | both |
| L2 | Reconverting a directory into its existing database keeps collections the directory no longer has, and keeps the old README body; `status` then reports `in_sync: true` | `database.py:820-869` | both |
| L3 | Common malformed shapes crash the import with a raw traceback: `"metadata": null`, `"metadata": [..]`, object or array `content`, list `mimetype`. Boolean `content` is silently stored as `"1"`. Violates SPEC 1.1 "MUST NOT fail" | `record.py:84`, `database.py:192-203` | both |
| L4 | Export writes the stored `example` back out as a one-item `values` list. On reimport that list counts as curated, so it never recovers: after replacing all 30 ids, `schema.yaml` still says `values: [id-0]`. Cause: one `_schema.sample_values` column holds both `values` and `example` | `database.py:476`, `:505`, `:683`; `schema.py:246` | both |
| L5 | Fractional-second timestamps sort before whole-second ones (`...00.500000Z` < `...00Z` because `.` < `Z`), and `--since` drops them. The 0.3.0 CHANGELOG claim of chronological order across precisions is false | `record.py:43` | both |
| L6 | A README without `contents` imports 0 records and exits 0. The README.md library example builds exactly such a README | `database.py:848`, README.md:57-61 | both |
| L7 | Round trip overwrites the producer's `generator` (`llm-memex 0.13.0` becomes `arkiv v0.4.0`); nested sub-README frontmatter, `description`, and body are dropped | `database.py:751-754`, `:905` | both (generator), reviewer (nested) |
| L8 | Round trip moves top-level `kind` into `metadata.kind` (SPEC 1.1 behavior), and every memex importer branches on top-level `kind`, so a memex archive passed through `arkiv convert` imports zero records back into its own tool | memex importers, e.g. `mail_memex/importers/arkiv.py:188` | reviewer |

## Tier 3: other correctness

| ID | Finding | Where | Verified |
|---|---|---|---|
| C1 | Following the unlink guard's advice (`arkiv convert x.db x`) never clears it: the db-to-dir export opens read-only and never resets `inserts_since_convert` | `database.py:285-297`, `cli.py:240-246` | reviewer |
| C2 | Auto-db freshness misses deleted files and replacements with older mtimes; a bare `.jsonl` input has no freshness check at all (June M1 still open for JSONL) | `cli.py:19-38`, `:263-272` | reviewer |
| C3 | `FIXITY.sha256` and `site/` count as source files: adding fixity flips `status` to "directory modified", touching `site/README.md` rebuilds the auto-db (refused if writes are pending) | `bundle.py:118`, `database.py:43` | reviewer |
| C4 | Nested export of a collection named `site` overwrites a viewer's `site/README.md`; a nested collection named `media` is imported as assets | `database.py` export/import | reviewer |
| C5 | A UTF-8 BOM silently drops the first record | `record.py:105`, `bundle.py:78` | reviewer |
| C6 | Zip packing fails on any member of 2 GiB or more (`force_zip64` missing) and leaves a partial bundle on disk | `bundle.py:383` | reviewer |
| C7 | `peek_jsonl` raises `zlib.error`, `NotImplementedError`, `RuntimeError` on corrupt or encrypted input; its docstring promises `None` | `bundle.py:339` | reviewer |
| C8 | Nested per-collection `schema.yaml` is not authoritative as SPEC 1.2 says: the top-level file merges last, and a curated `description: None` wipes a real one | `database.py:859-864`, `schema.py:249` | reviewer |
| C9 | Re-export into an existing directory keeps stale JSONL files of collections that no longer exist | `database.py` export | reviewer |
| C10 | The same collection listed twice in `contents` is counted twice | import path | reviewer |
| C11 | `write_bundle` member names that normalize alike (`a/b`, `a//b`, `./a/b`) are written as duplicates | `bundle.py:191` | reviewer |
| C12 | `records_to_jsonl` and `Record.to_json` emit `NaN`, which is not JSON | `bundle.py:220` | reviewer |
| C13 | `pack_bundle` builds tar names with `str(rel)`, which would be backslashed on Windows | `bundle.py:378` | reading |

---

## Spec and docs

### SPEC.md as a format contract

| ID | Sev | Finding | Fix |
|---|---|---|---|
| D1 | MED | No RFC 2119 declaration and no statement of which parts are normative; MUST/SHOULD appear in Part 4 (4.2, 4.3) while Part 1 mixes in implementation detail | Declare RFC 2119; Parts 1-2 normative, Parts 3-4 informative; move the 4.2/4.3 rules into Part 1 |
| D2 | HIGH | What is a collection is contradictory: 1.2 says "each `.jsonl` file", 1.3 says `contents` decides (see L6) | One rule: `contents` file entries if present, else every root `*.jsonl` in name order |
| D3 | HIGH | `schema.yaml` shape is only an example: top-level non-collection keys, collection-level keys, nested scoping all unspecified (handoff task 2) | See the proposal under Producers |
| D4 | HIGH | Timestamp canonical form undefined; depends on Python version via `fromisoformat` (L5) | Define a fixed-width canonical form in 1.1 (decision Q4); move mechanics to Part 3 |
| D5 | HIGH | Behavior for a known field of the wrong type is unspecified (L3) | Say where a non-object `metadata` and non-string known fields go |
| D6 | MED | Database called "derived view" (1.2), "convenience only" (4.3), "isomorphic peer" (Principle 2, 4.2); `--writable` contradicts the 4.2 MUST that every layer is regenerable from the directory | Pick one framing and name `--writable` as the exception |
| D7 | MED | `contents` ambiguities: directory entries only described in Part 3; `sub/data.jsonl` loses its description and path on export; non-`.jsonl` and `.JSONL` silently ignored | Specify each |
| D8 | MED | Collection naming rules exist only in code (`_validate_collection_name`); case collisions are not rejected | Normative name rule, reserve `media` and `site` |
| D9 | MED | 0.4.0 library API (`write_bundle`, `iter_jsonl`, ...) absent from SPEC | Short 3.4 "Library API" |
| D10 | LOW | 2.2 "unique values" collapses `1`, `True`, `1.0`; "arbitrary order" makes `schema.yaml` diffs nondeterministic; 3.1 says three tables, lists four; `->>` needs SQLite 3.38 | Fix wording |
| D11 | LOW | 4.3 and README name retired tools (`memex`, `mtk`, `btk`, `ptk`, `ebk`, `chartfold`) | Use the `*-memex` names |

### Other documents

- **README.md (HIGH):** the library example omits `contents` (L6), and
  exporters copy it. The first paragraph is a tagline; it never says what an
  archive is. Suggested opening: "arkiv stores personal data as a plain
  directory: a README.md that says what it is, a schema.yaml data dictionary,
  and one JSONL file per collection. `arkiv convert` turns that directory into
  a single SQLite file and back. `arkiv mcp` lets an LLM query it. A .zip or
  .tar.gz of the directory is for shipping only." Also: `arkiv[mcp]` needs
  Python 3.10+, not stated.
- **PHILOSOPHY.md (MED):** line 33 copies a durable-format list (should point
  at `longecho formats`); lines 62 and 129 contradict each other and
  `--writable` (D6); line 178 says producers need only "valid JSONL and a
  README", false per L6.
- **CLAUDE.md (MED):** "Bundle form" contradicts PHILOSOPHY's "there is no
  bundle form"; the `pack_bundle` exclusion text is stale since 0.4.0 (root
  level only); the Public API list omits `normalize_timestamp` and the nine
  bundle exports; Related Projects paths are dead; JSONL input makes a sibling
  `{stem}.db`, not `arkiv.db` (same error in `query`/`mcp --help`).
- **CHANGELOG.md (LOW/MED):** release dates disagree with tags for 0.1.0
  through 0.2.0; 0.3.0 says `arkiv status` is "not yet implemented" in the
  same release that adds it; the fingerprint is said to cover README,
  schema.yaml, JSONL, `media/`, but it hashes every non-dot file. No GitHub
  Release page exists for v0.4.0.
- **Docstrings and help (LOW):** `_resolve_db` suggests
  `arkiv convert bundle.zip ./archive/`, which errors (there is no bundle to
  directory path); `write_bundle` should say it does not guarantee a
  compliant archive; subcommands have no `--help` description; `fix` copies
  `url` to `uri` but leaves `url`, and rewrites in place without a backup.
- **examples/ (LOW):** `inode/directory` is not an IANA type, URIs are
  absolute home paths, no `arkiv_format`, naive timestamps. It passes
  `check_compliance` cleanly.

### longecho contract gap table

| # | Contract item | Status | SPEC change |
|---|---|---|---|
| 1 | Unit of work is a directory; a bare bundle is not a source | partial (4.2 only) | 1.2: a bundle is durable but not self-describing; exporters SHOULD write the directory form |
| 2 | Frontmatter keys; name and description cascade; identity from own README | partial (cascade in 1.3 but unimplemented in `get_manifest`; "never a parent's" missing) | 1.3 plus implementation |
| 3 | `contents` split meaning | partial, contradicts (D2) | 1.3 and 4.4 |
| 4 | `site/` generator convention | missing | 4.4 |
| 5 | `schema.yaml` optional, read loosely by longecho | partial (4.3 says longecho does not understand it) | 4.3 |
| 5b | Normative `schema.yaml` shape | missing (D3) | 1.4 |
| 6 | Durable formats: point at longecho's registry, do not copy | missing, contradicts (4.4 and PHILOSOPHY copy partial lists) | 1.2 `media/` guidance |
| 7 | No runtime dependency; test-only allowed | partial (no longecho dev extra, no compliance tests) | 4.4 plus tests |
| 8 | `FIXITY.sha256` and `site/` are not collections and survive re-export | partial (they survive, but count in the fingerprint, C3) | 4.4; exclude from fingerprint |

The media mimetypes arkiv's docs recommend (`audio/wav`, `image/jpeg`,
`text/plain`) all pass `longecho.formats.is_durable_mimetype`.
`application/octet-stream` (health-memex's fallback) and `image/heic` do not.

---

## Producers (the six memex exporters)

| Exporter | Default form | schema.yaml shape | Records | Notes |
|---|---|---|---|---|
| llm-memex | path decides | collection-keyed | 5 known fields, no uri | README tells readers to run `arkiv import`, which does not exist; schema `values` contain Python tuple reprs, which then stick as curated |
| photo-memex | directory | **kind-keyed with typed `metadata_keys`** (a third shape) | extra top-level `kind`, `source_path` | photos not copied; `source_path` is an absolute `file://` |
| health-memex | directory | collection-keyed, own discovery (enum threshold `< 20` vs arkiv `<= 20`) | 5 fields, `uri` without `//` | copies `media/`; `--embed` puts base64 in `content` |
| mail-memex | path required | kind-keyed `{scheme, counts, kinds}` | extra top-level `kind` | mimetype `message/rfc822` but `content` is the plain-text body |
| book-memex | path required | kind-keyed plus `exported_at` (not reproducible) | no mimetype/timestamp/metadata; all top-level | |
| bookmark-memex | path required | kind-keyed plus `exported_at` | all top-level | `last_visited` written but undocumented |

None uses `discover_schema`, `save_schema_yaml`, `save_readme`, or `Database`.
None of the HTML viewers writes a `README.md` or `generator` stamp. A seventh
producer exists: the llm-memex SPA's `downloadArkiv()` writes a bare
`.jsonl.gz`.

### Proposed `write_archive`

Per-collection information in one structured value, not parallel mappings:

```python
@dataclass(frozen=True)
class Collection:
    records: Iterable[Mapping[str, Any]]
    description: Optional[str] = None
    uri: Optional[str] = None                     # URI template
    fields: Mapping[str, str] = field(default_factory=dict)   # docs for mimetype/uri/content/timestamp
    keys: Mapping[str, Union[str, SchemaEntry]] = field(default_factory=dict)  # metadata key docs

def write_archive(
    path: PathLike,
    collections: Mapping[str, Union[Collection, Iterable[Mapping[str, Any]]]],
    *,
    name: str,
    description: str,
    generator: str,
    readme_body: Optional[str] = None,
    frontmatter: Optional[Mapping[str, Any]] = None,   # extras such as uri_scheme
    media: Optional[Mapping[str, Union[bytes, PathLike]]] = None,  # paths are streamed
    nested: bool = False,
    datetime: Optional[str] = None,                    # reproducible output
) -> ArchiveResult: ...
```

It validates names (reserving `media` and `site`), normalizes each record with
`parse_record` in one pass that also feeds schema discovery, writes README
frontmatter (`name`, `description`, `datetime`, `generator`, `arkiv_format`,
`contents`) with a plain-language opening paragraph, writes `schema.yaml` in
the canonical shape, picks the output form by extension, and on re-export
deletes only files the previous `contents` listed, so `FIXITY.sha256` and
`site/` survive.

### Proposed canonical `schema.yaml`

Top level holds collections only. A kind becomes a collection, `counts`
becomes `record_count`, `scheme` moves to README frontmatter as `uri_scheme`,
`exported_at` is dropped (README `datetime` covers it), and `fields.metadata.x`
becomes `metadata_keys.x.description`.

```yaml
email:
  description: An RFC 2822 email message.
  uri: mail-memex://email/<message_id>
  record_count: 2
  fields:
    content: {description: Plain-text body., count: 2}
  metadata_keys:
    subject: {description: Subject line., type: string, count: 2}
```

What this needs elsewhere: the database has nowhere to keep collection-level
`description`, `uri`, `fields` (`_schema` is per key), so a `_collections`
table is required for a lossless db round trip; and a declared collection with
zero records only survives if an empty JSONL file is written.

---

## Simplification and code quality

### Do now (low risk, high value)

- **Q1** Coverage: `[run] patch = subprocess`, `parallel = true`; pin
  `coverage>=7.10`. `cli.py` goes from 14% to 92% measured.
- **Q2** Three copies of "import a directory" in `cli.py` (`:124-133`,
  `:141-158`, `:249-257`) already differ (only one stores a fingerprint, only
  one errors on empty). Add `Database.import_directory()`; also give `Database`
  `__enter__`/`__exit__` (about ten try/finally/close blocks).
- **Q3** Lazy imports do nothing: `from . import __version__` loads the whole
  package (93 of 97 ms). Move the function-local imports in `cli.py` and
  `database.py` to module level; this also clears flake8 F821/F811/F841 and
  the matching mypy errors.
- **Q4** The "carry curated descriptions over" loop is written three times
  (`database.py:208`, `:340`, `:670`), and `import_jsonl` reads its file twice.
- **Q5** `database._is_within` and `bundle._within` are identical;
  `iter_source_files` and `pack_bundle._members` are the same walk; and
  `import_assets` is a third, unsafe walk (S2). One walk in `bundle.py`, used
  by all three.
- **Q6** Vestigial: unused `has_fp` (`cli.py:322`), `get_readme` aliasing
  `_load_readme_metadata`, test-only `ArkivServer.sql_query`, two 8 GiB
  constants.
- **Q7** Two parametrized tests sleep 1.1 s each (`test_bundle_io.py:67`,
  `:159`); use `os.utime` or monkeypatch `time.time`.

### With `write_archive` (the seam)

- **Q8** `export()` is 200 lines mixing SQL, layout, rendering, stamping, and
  `open()`. Split into "build `members`" plus `write_bundle(output, members)`,
  and give `save_readme` / `save_schema_yaml` pure `render_*` counterparts.
  `write_archive` then shares the member builder, and `convert db -> bundle`
  no longer needs a tempdir. A new `archive.py` (directory-form concerns) leaves
  `database.py` doing only SQLite.
- **Q9** Export `discover_schema_from_metadata` (in-memory producers need it);
  pick one JSON serializer (`Record.to_json` vs `records_to_jsonl` differ on
  `default=str`); let `write_bundle` accept paths or streams so large media is
  not held in memory.

### When touching the code anyway

- **Q10** `main(argv=None)` and a single in-process `run_arkiv` fixture in
  `conftest.py` (the helper is copied three times; 103 subprocess calls
  dominate runtime). Keep two or three real subprocess smoke tests.
- **Q11** Parallel tables, against the project's own rules: `KNOWN_FIELDS`
  duplicates `Record`'s fields (derive with `dataclasses.fields`); db suffixes
  defined twice; two format classifiers returning bare strings (one
  `str`-subclass Enum keeps the public return values); misspelling aliases
  defined twice (`field_suggestions`, `fix_map`); repeated literals
  (`"0.2"`, `f"arkiv v{__version__}"`, UTC-now format, `"arkiv.db"`).
- **Q12** Three ways to map a `contents` path to a collection name, which
  disagree on `sub/conv.jsonl`; three ways to decode `_schema` rows; two README
  importers with an identical schema-merge block; duplicated zip/tar branches
  in `write_bundle`/`pack_bundle` and the two safe extractors.
- **Q13** Two public JSONL readers (`parse_jsonl`, `iter_jsonl`) plus loops in
  `cmd_detect`/`cmd_fix`; base all on one line iterator (gives `parse_jsonl`
  bounded reads for free). `timefilter.py` parses dates with regex where
  `strptime` would validate ranges.
- **Q14** Tooling: one black-only commit; set flake8 max-line-length to 88;
  mypy `python_version = "3.10"` plus `types-PyYAML`.
- **Q15** Tests: `_make_archive` copied three times; `test_coverage_gaps.py`
  is organized by covered lines, not behavior; about 15 tests read `_schema`
  and `_metadata` directly instead of the public accessors.

---

## Suggested release sequence

1. **0.4.1, patch: security and data loss.** S1-S7, L1-L4, C5-C7, C11-C12,
   plus Q1 and Q5 (the shared walk is the S2 fix). Every fix gets the missing
   regression test; none of these bug classes has one today.
2. **0.5.0, the producer contract.** `write_archive`, the normative
   `schema.yaml` shape with a `_collections` table, the SPEC contract work
   (D1-D9, gap table items 1-8), the timestamp canonical form (L5, D4), the
   collection rule (L6, D2), generator and nested-README preservation (L7),
   reserved names (C4), fixity/site out of the fingerprint (C3), longecho as a
   test-only dependency with compliance tests, the `export()` split (Q8-Q9),
   and `arkiv_format` "0.3". Then the memex migrations, in each memex repo.
3. **0.6.0, features.** FTS5 search, `arkiv redact`, and the remaining June
   items (enum cardinality marker, `write_record` uri). The name/description
   cascade moves up to 0.5.0, since contract item 2 needs it.

Simplification items Q2-Q4 and Q6-Q7 fit in 0.4.1 where they touch the same
code; Q10-Q15 ride along whenever a module is open.

## Decisions for the author

1. Ship a 0.4.1 security and data-loss patch before the producer work?
2. Canonical `schema.yaml`: one collection per kind (split `records.jsonl`
   into `email.jsonl`, `marginalia.jsonl`, ...), or keep one file with a
   discriminator key?
3. On re-export, keep the producer's `generator` (and record arkiv
   elsewhere), or stamp arkiv?
4. Canonical timestamp form. "Six-digit fraction only when present" does not
   fix L5 (`...00Z` still sorts after `...00.500000Z`), so the fraction must be
   always present or always absent. `timestamp_original` keeps the input
   either way, so the choice affects only the sortable column.
5. Should `write_archive` normalize records to the five known fields? (SPEC
   1.1 already says SHOULD; memex importers would then read `metadata.*`,
   which they must do anyway after a round trip, per L8.)
6. Default export form for memex tools: directory (recommended; every tool
   with a default already uses one).

### Decided 2026-10-21

1. Yes: 0.4.1 patch (security and data loss) ships before the producer work.
2. One collection per kind. `records.jsonl` splits into one JSONL per kind;
   memex importers accept the old `records.jsonl` during the transition.
3. Keep the producer's `generator`. arkiv stamps `generator` only when none
   exists, and records itself in a separate key (name settled in 0.5.0).
4. Canonical stored timestamp: always a six-digit fraction,
   `YYYY-MM-DDTHH:MM:SS.ffffffZ`. `timestamp_original` keeps the input.

Items 5 and 6 take the recommendation unless revisited: `write_archive`
normalizes to the five known fields, and memex tools default to the directory
form.
