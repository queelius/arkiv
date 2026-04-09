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

## The regenerability principle

A consequence of the layered model: **every layer above the substrate must be regenerable from the substrate**.

The SQLite database is regenerable from the JSONL files plus README plus schema.yaml. The schema.yaml is partly regenerable from the JSONL (auto-discovered keys, types, counts, values) plus whatever human curation you added to it. The README can be partly regenerated too: `arkiv export` rebuilds it from stored metadata, though any free-form prose you wrote in the body is preserved across roundtrips.

**Nothing above the directory form is precious.** If you lose your .db file, you lose nothing; you rebuild it. This frees you to treat the query layer as a cache, the LLM interface as a tool, and the SQL as an ergonomic convenience. They are all recoverable.

The directory form itself is the thing you back up, version-control, archive, encrypt, share, and preserve. Everything else can be regenerated from it.

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

**The archive directory itself** is the shared substrate. Every role in the ecosystem reads or writes it. Everything else, including the SQLite database, the MCP server, the LLM conversation, the static website generated by longecho, is derived from that directory and regenerable from it.

---

## Why this matters

The temptation in personal data tooling is to pick one axis and commit to it completely. Build a slick queryable app and accept that it will die when the company dies. Or hoard plain-text files and accept that you cannot actually use them without writing scripts every time.

arkiv and longecho together let you refuse that trade-off. You get the modern queryable layer (SQL, LLM interface, structured metadata) *and* you get the distant-future survivability (plain files, self-describing, durable formats). Not as a compromise, but as consequences of a single design: **build the query layer as a derived view over a durable substrate**.

This is the only design choice that really matters. Everything else in both specs follows from it.

---

## Further reading

- [arkiv SPEC.md](../SPEC.md) - the full arkiv format specification
- [longecho](https://github.com/queelius/longecho) - the longecho philosophy and validator
- [arkiv CLAUDE.md](../CLAUDE.md) - developer guide for the reference implementation
