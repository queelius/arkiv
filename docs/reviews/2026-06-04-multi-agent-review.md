# arkiv review, 2026-06-04

Multi-agent review of arkiv v0.2.0 across seven lenses (format design,
implementation correctness, longecho-ethos consistency, missing features,
doc/spec drift, security/privacy, test quality). Every concrete claim below was
adversarially re-verified against the actual code with a repro; subjective
judgments are marked. 305 tests pass, 93% coverage at time of review.

This file is a record, not a change. Nothing here is fixed yet.

---

## Verdict

arkiv is a genuinely well-built, principled format with an unusually clear
philosophy and a *real* (not aspirational) composition with longecho: an arkiv
export passes `longecho check` out of the box, neither project imports the
other (zero code coupling, verified), and the graceful-degradation stack mostly
holds. The repoindex example proves the format is general-purpose, not secretly
conversation-shaped.

The review found **one structural problem that breaks the load-bearing promise**
("isomorphic peers, lossless conversion, directory authoritative") plus a
cluster of correctness bugs and an under-built operational surface. The headline
issues are not sloppiness. They are the seams that only show under the
30-year-durable-contract framing the project sets for itself.

### What's strong (don't regress these)
- Read-only SQL enforcement is well-layered (read-only URI connection,
  single-statement execution, SELECT/WITH prefix gate, sqlite3 authorizer).
  Under adversarial testing it blocks ATTACH, load_extension, readfile/writefile.
- Input validation in `timefilter.py` and `bundle.py` is careful (ISO prefix
  validation, path-traversal rejection, `filter="data"` on 3.12+).
- Clean module separation; explicit trade-off documentation in docstrings
  (e.g. the O(1) write path / stale-schema trade-off is stated, not hidden).
- The two-axis durability philosophy is coherent and the longecho composition
  is real and decoupled.

---

## Priority findings (deduped across dimensions)

Severity: **HIGH** breaks a core promise or loses data. **MED** meaningful
weakness/gap. **LOW** polish. "Corroboration" = how many independent reviewers
hit it.

### HIGH

**H1, `directory -> db -> directory` silently drops `media/` and all non-core files.**
*(corroborated by 5 reviewers, each with a repro)*
`export()` (`database.py:377-553`) rebuilds the directory purely from the three
DB tables, writing only `*.jsonl` + `README.md` + `schema.yaml`. There is no
media-handling code anywhere (`grep -niE 'media|shutil|copytree|copyfile' src/`
finds only `bundle.py` whole-dir packing). But `media/` is documented as canonical
archive structure (`SPEC.md:96-101`), used in record examples (`SPEC.md:73`,
`README.md:11-12`: `uri: file://media/...`), and tarred in the encryption
example (`SPEC.md:604`). So a roundtrip drops every binary asset and leaves the
surviving `uri` dangling. Also dropped: the `.db` itself and any sibling file
not in the three categories. This directly contradicts "lossless in both
directions" (`PHILOSOPHY.md:129`, `SPEC.md:523`) and is the central promise of
the whole two-form model.
**Fix:** teach `export()` to copy a sibling `media/` (and ideally any
`contents`-referenced asset dirs) through the DB form, or record asset
directories in `_metadata` so they survive. At minimum, document loudly that the
DB form is records-only and binary assets live only in the directory form, and
have `convert db->dir` warn when records reference `file://` assets it cannot
reproduce.

**H2, collection identity = filename stem + replace-on-import = silent data loss.**
*(corroborated by 2 reviewers, repro)*
Collection identity is the bare filename stem (`SPEC.md:124`); `import_jsonl`
uses replace semantics (`DELETE FROM records WHERE collection = ?`,
`database.py:109-111`). An archive whose README lists both `data.jsonl` (flat)
and `data/` (nested `data/data.jsonl`) maps both to collection `data`: the
second import's DELETE wipes the first. Repro reported "imported: 2" but the DB
held **one** record. Same collision for case-insensitive filesystems
(`Notes.jsonl` vs `notes.jsonl`) on the flat path too. `_validate_collection_name`
only rejects separators/dots/reserved names, not stem aliasing.
**Fix:** qualify nested collections by path (e.g. collection key `data/data`),
detect stem collisions in `import_readme` and raise rather than DELETE+overwrite,
and state in the spec that collection identity must be unique within an archive.

**H3, read-only authorizer denies all `WITH RECURSIVE` queries.**
*(verified firsthand)*
`query()` advertises `WITH` (prefix gate at `database.py:250`), but the
authorizer (`database.py:238-245`) allows only `SQLITE_SELECT/READ/FUNCTION`, so
recursive CTEs trip `SQLITE_RECURSIVE` and return `not authorized`. Repro: plain
`WITH` and `SELECT` work; `WITH RECURSIVE cnt(x) AS (...) ...` errors. Recursive
CTEs are exactly how an LLM would walk a thread/tree, so a documented capability
is broken for the primary consumer.
**Fix:** add `sqlite3.SQLITE_RECURSIVE` to the allowed set. (Stays read-only;
recursion is not a write.)

**H4, live docs present removed `arkiv import` / `arkiv export` as working commands.**
*(corroborated by 4 reviewers)*
0.2.0 replaced `import`/`export` with a single `convert` (no aliases;
`python -m arkiv.cli import ...` exits 2). Yet `PHILOSOPHY.md:62,129,141,153,154`
show them as working invocations (plus a `--db` flag that never existed and an
`arkiv status` that doesn't exist), `SPEC.md:25,375,525,559` use the removed
verbs in user-facing prose, and the shipped `bundle.py:13-22` module docstring's
"Typical flow" still shows `arkiv import bundle.zip --db archive.db`. PHILOSOPHY
is flagged in CLAUDE.md as "read before deciding," so this is the most
misleading drift for a new reader.
**Fix:** rewrite these to `arkiv convert` (keep CHANGELOG history intact; those
references are correct as a historical record).

### MEDIUM

**M1, auto-created `arkiv.db` is reused with no freshness check, returning stale results.**
`_resolve_db` (`cli.py:203-227`) creates `arkiv.db` (or sibling `{stem}.db`) on
`query`/`mcp` and reuses it if present. Edit the authoritative JSONL, re-query,
get stale rows, directly contradicting "directory is authoritative on
divergence." **Fix:** compare source mtime/hash against a stored fingerprint and
rebuild when stale, or document that auto-db is a cache and add `--refresh`.

**M2, timestamps compared lexicographically are chronologically wrong.**
Stored as opaque TEXT with an index that invites `ORDER BY timestamp`
(`database.py:71,91`), but `2024-01-01T08:00:00-05:00` (13:00Z) sorts *before*
`...T08:00:00Z` (08:00Z). Mixed precision compounds it (`2024-01-01` < `...T00:00:00Z`).
**M3, `--since`/`--until` slices are wrong near offset boundaries** (same root):
`2023-12-31T20:00:00-05:00` (= 2024-01-01T01:00Z) is excluded by `--since 2024-01-01`
(`timefilter.py:116-128`). **Fix:** RECOMMEND UTC-normalized timestamps in the
spec, have `detect` warn on mixed offsets/precision, and compare normalized
values for slicing.

**M4, schema `type` rule: spec says first occurrence, code uses last.**
`schema.py:107` assigns `key_types[key]` every iteration; `example` is locked to
the *first* value (`schema.py:109`). So for a string-then-number key, `type=number`
(last) while `example="..."` (first): they describe different records, and both
contradict `SPEC.md:224,313`. **Fix:** pick one rule (most-common type is most
useful for a data dictionary) and make spec + code + example agree.

**M5, a falsy first example (`0`, `""`, `false`) is dropped from the data dictionary.**
`database.py:223`: `sample = entry.values or ([entry.example] if entry.example else [])`,
where the truthiness test drops `0`/`""`/`false`, storing NULL. A high-cardinality
numeric key whose first value is `0` shows no example at all. (`render.py` already
uses `is not None`.) **Fix:** `if entry.example is not None`. Bonus bug surfaced:
a key whose first value is `null` ends with both `values=None` and `example=None`
even after 24 real values follow (null poisons the value set and locks the example).

**M6, unknown top-level field silently overwrites a colliding `metadata` key.**
`record.py:49`: `{**(metadata or {}), **unknown}`, so `{"role":"user","metadata":{"role":"system"}}`
yields `metadata.role == "user"`, destroying the inner value with no signal,
against "preserve everything" (`SPEC.md:24,50`). **Fix:** on collision, keep the
existing `metadata` value (or namespace the unknown field) and have `detect` warn.

**M7, divergence detection is specified but unimplemented, while `--writable` creates divergence.**
`PHILOSOPHY.md:141` describes a content fingerprint + insert-since-import counter
+ `arkiv status`. None exists (`grep -niE 'fingerprint|hashlib|status' src/` finds 0).
`insert_record` mutates only the DB and leaves `_schema` stale by design, and
**`refresh_schema()` exists but is exposed by no CLI/MCP surface**, so after
writes, `get_schema`/`get_manifest` silently lie until a full reconvert. **Fix:**
implement `arkiv status` (even just mtime/hash compare) and expose `refresh_schema`
as an MCP tool / `arkiv refresh`.

**M8, no full-text search.** Listed under "Future" (`SPEC.md:658`), but the
primary corpus is conversations/email where `content LIKE '%...%'` full scans are
the only option. SQLite FTS5 ships in CPython's bundled sqlite3 on mainstream
builds and is cheap to add as a regenerable virtual table. **Fix:** optional FTS5
table built during convert; keep it regenerable so the durability axis is untouched.

**M9, no archive merge; same-named collections collide destructively.**
No `arkiv merge`; importing two `conversations.jsonl` into one DB keeps only the
second (REPLACE). The docs tout "cat them together," which is true only at the
JSONL/directory level, not DB conversion. **Fix:** an `--append`/`merge` mode, or
at least warn on collision instead of silently replacing.

**M10, no record update/delete/redaction.** Only append + whole-collection
replace. A personal-data tool needs correction and right-to-be-forgotten. The
JSONL-first workaround (edit file, reconvert) is principled but has no affordance
and no MCP tool. **Fix:** `arkiv redact`/`delete` operating on the directory form.

**M11, MCP `sql_query` returns unbounded rows and cell sizes to the LLM.**
`database.py:261` `fetchall()` + `server.py:83-87` `json.dumps` of everything; no
LIMIT injection, no pagination, no cap. An LLM issuing `SELECT content FROM records`
gets the whole archive (cost/OOM/exfiltration surface). **Fix:** default cap +
pagination (`fetchmany`/`LIMIT`/`OFFSET`), and tell the tool to paginate.

**M12, bundle extraction has no decompression-size / ratio / entry-count guard.**
Path traversal is handled, but a zip/tar bomb fills disk. **Fix:** cap total
extracted bytes and entry count; abort past a ratio threshold.

**M13, `pack_bundle` sweeps `arkiv.db` and stray dotfiles into the bundle.**
`bundle.py:71-78` `rglob("*")` adds everything, including the derived `arkiv.db`
the default `convert ./dir/` drops into the canonical directory, leaking more
than intended and undercutting "directory is canonical." **Fix:** exclude derived
`*.db` and dotfiles by default (or pack only `contents`-listed files + `media/`).

**M14, `SPEC.md:411` `get_schema` return shape is wrong.** Spec says returns
`record_count` + `metadata_keys`; code returns `collection` + `metadata_keys`
(`database.py:283-303`), no `record_count`. **Fix:** correct the spec (or add
`record_count`).

**M15, `.sqlite` / `.sqlite3` crash `schema`/`info`/`detect`/`fix`.** These use
`suffix == ".db"` (`cli.py:162,244,274`) while `_is_db_path` accepts all three.
`arkiv schema x.sqlite` reads a SQLite binary as JSONL and emits a cryptic UTF-8
error. (`query`/`mcp` are fine: `_resolve_db`'s final branch opens any path as a
DB.) **Fix:** use `_is_db_path` everywhere.

**M16, `arkiv_format` version is write-only; no negotiation.** Written as literal
`"0.2"` twice (`database.py:504,545`), never read/compared; `SPEC.md:250-254`
describes negotiation semantics no code implements. **Fix:** either implement a
read/compat path or soften the spec to "informational only."

**M17, `datetime` never refreshed on export; `generator` never set on flat export.**
`export()` copies stored frontmatter verbatim; `datetime` is never stamped
(`SPEC.md:159` calls it "most recent export"), and the **flat** top-level README
gets only `contents` + `arkiv_format`, no `name`/`description`/`generator`/body,
contradicting `PHILOSOPHY.md:74`'s enumeration. **Fix:** stamp `datetime`/`generator`
on export; emit a fuller top-level README (and pass timestamps in, since the
exact time is environment-derived).

### LOW (polish, see per-finding notes below)
- Bundle path-escape uses `str.startswith` (sibling-prefix flaw); real safety is
  accidental via zipfile/tarfile sanitization. Switch to `Path.is_relative_to`/`os.path.commonpath`.
- Authorizer blanket-allows every SQL function instead of allow-listing safe ones.
- Enum threshold (20) is a hard cliff with no cardinality fallback; add a
  `distinct_count`/`truncated` marker.
- Empty `{}` metadata and field order are not byte-preserved; clarify the spec to
  "value-lossless," not "equivalent files."
- Name/description resolution cascade (`SPEC.md:166-170`: fall back to `# Heading`
  / first paragraph) is unimplemented.
- `readme.py:11` says "ECHO-compliant" (legacy) and omits `arkiv_format` from
  known keys; `server.py:11` "exposing 3 tools" omits the writable 4th tool;
  `get_manifest` can never emit the nested `conversations/` `file` form
  (`SPEC.md:401`); `query`/`mcp` arg help says "SQLite database path" but accepts
  dirs/JSONL.
- MCP `write_record` cannot set `uri` (`insert_record` hardcodes `uri=None`).
- No archive-wide `validate` (detect is single-file); no reference-integrity /
  `file://` link-checking; no encryption affordance (manual gpg/age only); no
  CSV/Parquet export for analytics consumers.
- No documented warning that record content/metadata flows verbatim into MCP tool
  results (prompt-injection surface).
- Denormalization of relational sources (conversation to messages) is asserted but
  the linkage/ordering conventions are unspecified; producers will each invent
  their own.
- Auto-generated `schema.yaml` carries structure (keys/types/values) but no
  semantics; "an LLM knows what they mean" (`PHILOSOPHY.md:58`) is true only for
  hand-curated archives.

---

## Longecho-ethos consistency

**Composition is real and well-executed:** zero code coupling (verified both
directions), `longecho check` passes on an arkiv export, the durability stack's
layers are genuinely independent.

**Where the ethos is overreached by the implementation:**
1. **Losslessness is record-only, not archive-level** (H1): binary resources are
   not durable through the DB form, a direct hit on the time axis.
2. **"Directory authoritative" is contradicted by the auto-db cache** (M1) and by
   **unimplemented divergence detection** under an active write path (M7).
3. **Self-description under-delivers**: the flat-export README passes `longecho
   check` only via the directory-name fallback (M17), mechanically compliant but
   qualitatively thin.
4. **Hygiene wart**: the default `convert ./dir/` drops a derived `arkiv.db` into
   the canonical directory, which `pack_bundle` then ships (M13).

None of these break the *composition* (longecho still passes); they erode the
*spirit* (durability, authoritativeness, self-description) the project sets for
itself.

---

## Suggested fix order

1. **H3** (one-line: allow `SQLITE_RECURSIVE`) and **M5/M15**: trivial, high-value.
2. **H4 / doc-drift cluster**: propagate the import/export to convert rename through
   PHILOSOPHY.md, SPEC.md, bundle.py docstring, server.py docstring, readme.py.
3. **H2 + M9**: collection-identity uniqueness + collision detection (one design,
   two payoffs: stops data loss and enables safe merge).
4. **H1 + M13**: media/asset handling through the DB form (the headline promise),
   plus stop bundling the derived db.
5. **M2/M3**: timestamp normalization convention + `detect` warning.
6. **M7 + M1**: `arkiv status`/fingerprint and expose `refresh_schema`; freshness
   check on the auto-db.
7. **M4/M6**: schema type rule + metadata-collision policy (spec + code).
8. **M8/M10/M11**: FTS5, redaction, MCP result caps (each a self-contained feature).

The first two batches are an afternoon and remove most of the "30-year-contract"
embarrassment; batches 3 and 4 are the real engineering and restore the lossless
claim the whole design rests on.
