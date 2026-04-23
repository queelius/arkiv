# arkiv and longecho: Two Axes of Durability

**Status:** Reflective companion to [SPEC.md](../SPEC.md)
**Audience:** Anyone trying to understand *why* arkiv exists and how it relates to longecho.

---

## The problem

Personal data is fragile in several different ways at once. We tend to conflate them.

A photograph is fragile because the disk it lives on will fail, the format might stop being readable, the cloud service might close, the person who knew the context might die. That is **fragility across time**: the artifact degrades, the tooling decays, the human knowledge that contextualized the artifact disappears. The enemy is entropy, and the timescale is decades.

The same photograph is fragile in a different way: you cannot easily ask "which photos from 2014 have Sarah in them, sorted by the location tag, with captions that mention Boston." Not because the data is gone, but because there is no structured access to it. That is **fragility across complexity**: the artifact is technically preserved but epistemically inaccessible. The enemy is disorganization, and the timescale is immediate.

Most data stores are good at one axis and terrible at the other. A box of prints is maximally durable across time (a child can still understand what they are in a hundred years) but minimally durable across complexity (you cannot query a box). A relational database is maximally durable across complexity (SQL is a precise query language) but minimally durable across time (the schema, the server, the driver, the language version, the cloud account all decay quickly).

arkiv and longecho together address both axes without collapsing them into each other.

---

## Two projects, two axes

### longecho: durability across time

[longecho](https://github.com/queelius/longecho) is a philosophy and a compliance checker. It does not define a schema. It does not require a specific format. Its central claim is this:

> A personal archive that is *self-describing*, stored in *durable formats*, and *locally accessible* will still be useful decades from now, even if every tool that currently reads it disappears.

The longecho criteria are minimal by design:

1. There is a README (plain text or markdown) that explains what the data is.
2. The data lives in formats that do not require proprietary software to read (`.txt`, `.md`, `.json`, `.jsonl`, `.db`, `.csv`, `.yaml`, `.jpg`, `.png`, ...).
3. Everything works offline.

Notice what longecho does *not* prescribe:
- No schema. Your README can be prose, a table, bullet points, whatever.
- No specific file structure. You can nest directories however you want.
- No versioning. There are no spec versions to track.
- No tooling lock-in. longecho itself is a validator, not a runtime.

This minimalism is the point. longecho optimizes for the distant future, where *the only things you can count on* are: a human who can read, a file browser, a text editor, and maybe an LLM. Anything more specific is a liability.

The payoff: a longecho-compliant archive degrades gracefully. You lose the fancy browser? You can still open the directory and read the README. You lose the text editor? You can still `cat` a JSONL file. You lose context entirely? The README tells you what you are looking at. Each level of tool loss reveals a simpler layer underneath that still works.

### arkiv: durability across complexity

arkiv is a format, a library, and an MCP server. Its central claim is this:

> A personal archive that preserves records as JSONL *and* makes them queryable through SQL and LLMs will let you actually *use* your data, today and for the foreseeable future, without sacrificing the underlying durability.

The arkiv format is also minimal, but along a different axis. A record is a JSON object with five optional conventional fields (`mimetype`, `uri`, `content`, `timestamp`, `metadata`). Unknown fields are absorbed into `metadata`. There is no required shape, no required validation, no enforced schema. If you can write it as JSON, it is a valid arkiv record.

On top of this format, arkiv provides:

1. **A SQLite query layer.** One command imports your JSONL files into a single-file database. SQLite gives you SQL plus the JSON1 extension, which means you can write queries like `SELECT content FROM records WHERE metadata->>'role' = 'user' AND content LIKE '%durability%'`. This is queryable the day you write it, and SQLite itself is a Library of Congress recommended archival format, so the query layer is almost as durable as the JSONL underneath it.

2. **A data dictionary.** arkiv auto-discovers the metadata keys that appear in your records and records them in `schema.yaml` as a human-readable data dictionary: what keys exist, how often, what types, what values. You can curate it by adding descriptions. This is *not* a validation schema; it is a map of what is actually in the data. An LLM reading this dictionary knows what fields are queryable and what they mean.

3. **An MCP server.** Three read-only tools (`get_manifest`, `get_schema`, `sql_query`) plus an optional append-only `write_record`. Any LLM with MCP support can load an arkiv archive, learn its structure, and query it in natural language. The server does not interpret the data; it exposes it.

The format is designed so that **the SQLite database is completely regenerable from the directory form**. If you delete the .db file, `arkiv import ./archive/` rebuilds it. This means the query layer never becomes the source of truth. The JSONL files plus the README plus the schema.yaml are enough to reconstruct everything.

---

## Why they compose

The two projects look superficially different. One is a philosophy, the other is a format with tooling. But they share a substrate: **the directory form**.

longecho looks at a directory and asks: does it have a README? Are the files in durable formats? If yes, it passes. longecho does not care what is inside the JSONL files.

arkiv produces directories that happen to be longecho-compliant for free:

- The exported README.md has a YAML frontmatter with `name`, `description`, `generator`, `contents`, and the body contains auto-generated data dictionary tables. longecho's compliance check finds the README.
- The JSONL files are durable-format text. longecho's compliance check finds them.
- The optional SQLite database is also durable-format. longecho's compliance check finds it too.
- The schema.yaml is durable-format YAML.

Dropped onto any filesystem, an arkiv archive is simultaneously:
- A longecho-compliant source (readable with a text editor or LLM in the future)
- A queryable arkiv database (usable with SQL or an LLM today)

**This is not a coincidence.** It is the result of a specific design choice: the archive directory is canonical for both projects, and neither project requires anything that would compromise the other. longecho would still work if arkiv vanished tomorrow, because longecho only needs the README and the plain-file data. arkiv would still work if longecho vanished tomorrow, because arkiv only needs the archive directory and its own library.

The relationship is composition without coupling: each project is independently useful, and their composition is more useful than either alone.

---

## The durability stack

With both projects in mind, the full durability picture looks like this:

```
┌───────────────────────────────────────────────────────────┐
│  LLM via MCP server (arkiv)                               │
│  "Show me conversations about durability from 2024"       │
├───────────────────────────────────────────────────────────┤
│  SQL query layer (arkiv SQLite + JSON1)                   │
│  SELECT content FROM records WHERE metadata->>...         │
├───────────────────────────────────────────────────────────┤
│  Data dictionary (arkiv schema.yaml)                      │
│  What keys exist, what they mean, what values they have   │
├───────────────────────────────────────────────────────────┤
│  Structured records (arkiv JSONL + records table)         │
│  One JSON object per line                                 │
├───────────────────────────────────────────────────────────┤
│  Self-describing directory (longecho README + durable     │
│  formats)                                                 │
│  Human can open it and understand what it is              │
├───────────────────────────────────────────────────────────┤
│  Plain text and file browsing (the substrate)             │
│  cat, grep, a file manager, eyes                          │
└───────────────────────────────────────────────────────────┘
```

Each layer is independently functional. If the top layer disappears (MCP goes away), the layer beneath still works (SQL query layer remains). If SQLite disappears, the JSONL files still work. If the JSONL format becomes obscure, the README still explains what the files are. If the README is the only thing left, a human or future LLM can read it and at least know what was once there.

**This is graceful degradation as a design principle**, not an afterthought. Each layer adds capability without removing what the layer below provided.

---

## Two forms, one archive

An arkiv archive has two interconvertible representations:

- **Directory form**: README.md + schema.yaml + *.jsonl files. Human-readable, git-diffable, appendable with `echo >>`, editable with a text editor.
- **Database form**: a single SQLite file containing `records`, `_schema`, and `_metadata` tables. Queryable, single-file-portable, LLM-accessible via MCP.

Both forms are **complete**. The directory form can regenerate the database (`arkiv import`). The database can regenerate the directory (`arkiv export`). The conversion is lossless in both directions. Neither form is a cache of the other; they are isomorphic representations optimized for different access patterns.

**Why the directory form is authoritative on divergence.** If the two forms get out of sync (someone edits a JSONL file after importing, or `insert_record` writes to the database without re-exporting), a conflict-resolution rule is needed. The directory form wins for three reasons:

1. **Accessibility under degraded conditions.** A plaintext JSONL file is readable with `cat` in any terminal, on any OS, in any era. A SQLite binary requires a specific parser. The accessibility gap is permanent. When you are trying to recover data from a failing disk, an old backup, or a format you barely remember, plaintext is the last thing to become unreadable.

2. **Human editability.** You can add a record by appending a line of JSON to a file. You can fix a typo by opening the file in a text editor. You can merge two archives by `cat`-ing their JSONL files together. These operations require no tooling beyond what every computer has. The database form requires the arkiv library (or at least an SQLite client) for any modification.

3. **Version control.** JSONL files diff meaningfully in git. SQLite binaries do not. For archives that evolve over time (and personal archives always do), the ability to see what changed, when, and why, is a form of durability that binary formats cannot provide.

These properties are why the spec says "if they diverge, the directory form is authoritative." It is not because the directory form is more complete (it is not; both forms contain the same data). It is because the directory form is more *survivable*.

**Detecting divergence.** When `arkiv import` loads a directory into SQLite, it MAY store a content fingerprint (hash of the JSONL and README files) in the `_metadata` table. When records are later added via `insert_record`, the implementation MAY track a count of records inserted since the last import. Together, these allow an `arkiv status` operation to report whether the two forms are in sync, whether the directory has been modified since import, or whether the database has new records not yet exported. This is optional but recommended for implementations that support the write path.

---

## Bundles are transport, not a third form

An arkiv archive may be packed into a `.zip` or `.tar.gz` for transport or storage. This is a serialization of the directory form, not a separate representation. There is no "bundle form" in the durability stack. A packed bundle is simply a directory form that has been compressed for shipping.

**Bundles are for transport. Directories are for working.** To operate on a bundle, you unpack it first. To share a directory, you pack it. This is how every other archive format works in computing (tar, deb, rpm, docker images): the archive is the shipping container, and work happens on the extracted contents.

This has concrete consequences for the arkiv CLI:

- `arkiv import bundle.zip --db archive.db` works, because import is an explicit conversion operation. The tool transparently unpacks to a temporary directory, imports, and discards the tempdir. The bundle is "consumed" into the database form.
- `arkiv export archive.db bundle.zip` works for the same reason. Export is explicit conversion; the tool exports to a tempdir, packs, and discards.
- `arkiv query bundle.zip "..."` does **not** work. Query asks the tool to *operate* on the archive, and operating on a packed bundle is not a thing. The user gets a clear error: "bundle.zip is a packed bundle, not a working archive. Unpack first."
- Same for `arkiv mcp bundle.zip` and any other read or write operation.

**Why not auto-extract for convenience?** Auto-extracting on every read would encode an implicit opinion about how bundles should be unpacked (sibling directory? tempdir? named what?) that belongs to the user, not the tool. It would also create lingering extracted directories the user didn't ask for and has to manage. The principle "bundles are for transport" is cleaner and more honest: the format has two forms (directory and database), plus a serialization (bundle). You opt into the serialization when you ship, and opt out of it when you work.

This also matches longecho's stance: longecho recognizes `.zip`, `.gz`, and `.tgz` as durable formats for compliance purposes, but does not extract, traverse, or inspect their contents. A bundle is an opaque durable artifact to longecho. The two projects agree: bundles are shipping containers, not working formats.

---

## Trust the future

longecho has an unusual design principle: "trust the future". The idea is that we should not over-engineer our archives because *future humans and future LLMs will be smarter than we are*. Writing a precise, rigid schema today is probably a mistake, because it encodes assumptions about how you (and others) will want to query the data, assumptions that will age poorly.

arkiv inherits this principle. The record format has no required fields. The `metadata` field is freeform JSON. The schema is auto-discovered and human-curatable, not enforced. The CLI accepts messy input (the `detect` and `fix` subcommands help you clean it up without gatekeeping). The MCP server exposes data to LLMs with essentially no interpretation layer, trusting that an LLM with a good prompt can figure out what to do with it.

The practical effect: an arkiv archive stays useful even as your own ideas about what to do with the data evolve. You can decide tomorrow that you want to extract reading-time estimates from your conversation data, and the answer is a SQL query, not a schema migration.

---

## What this means for the ecosystem

With this framing, the roles in the ecosystem become clearer:

**Source toolkits** (memex, mtk, btk, ptk, ebk, repoindex, chartfold) are producers. Their job is to extract data from some silo (ChatGPT, Gmail, browser bookmarks, camera roll, reading app, git repos, EHRs) and write it as JSONL records. Each toolkit knows the idiosyncrasies of its silo; none of them need to know about longecho or arkiv directly, as long as they produce valid JSONL and a README.

**arkiv** is an interchange format and query layer. It turns a collection of JSONL files into a queryable archive without imposing a schema. It does not *own* the data; it provides a structural layer over it.

**longecho** is a compliance philosophy and a tool for walking directories, building static sites, and checking graceful-degradation properties. It does not know or care that an archive happens to also be an arkiv archive; it simply recognizes it as self-describing and composed of durable files.

**Consumers** (longshade, analytics tools, any LLM via MCP) read arkiv archives and do something specific with them, usually oriented around a single use case like "be a conversable persona" or "generate a quarterly health summary".

**The archive directory** is the shared substrate. Every role in the ecosystem reads or writes it. The SQLite database is an isomorphic peer of the directory form, not a derivative. But the directory form is the one that toolkits produce, that longecho validates, that humans inspect, and that git can version-control. The database form is what the MCP server reads and what SQL queries target. Both are complete; each is optimized for a different surface.

---

## Why this matters

The temptation in personal data tooling is to pick one axis and commit to it completely. Build a slick queryable app and accept that it will die when the company dies. Or hoard plain-text files and accept that you cannot actually use them without writing scripts every time.

arkiv and longecho together let you refuse that trade-off. You get the modern queryable layer (SQL, LLM interface, structured metadata) *and* you get the distant-future survivability (plain files, self-describing, durable formats). Not as a compromise, but as consequences of a single design: **maintain two isomorphic representations of the same data, one optimized for humans and durability, the other optimized for machines and queries, with lossless conversion between them**.

This is the only design choice that really matters. Everything else in both specs follows from it.

---

## Further reading

- [arkiv SPEC.md](../SPEC.md) - the full arkiv format specification
- [longecho](https://github.com/queelius/longecho) - the longecho philosophy and validator
- [arkiv CLAUDE.md](../CLAUDE.md) - developer guide for the reference implementation
