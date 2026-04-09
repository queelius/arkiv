# arkiv: Universal Record Format

**Format Version:** 0.2
**Specification Status:** Draft

---

## Purpose

arkiv is a universal personal data format. It defines:

1. **A record format** -- one JSON object per line, all fields optional, JSONL storage
2. **An archive format** -- a directory with README.md, schema.yaml, and JSONL files
3. **A schema convention** -- auto-discovered data dictionary with optional curation

arkiv also provides a reference implementation with a SQLite query layer, CLI, and MCP server. These are described separately in [Part 3](#part-3-reference-implementation) and are not required to produce or consume arkiv archives.

arkiv is not specific to any application. It is a general-purpose format for personal data sovereignty, archival, and interchange.

---

## Design Principles

1. **Permissive input, best-effort processing.** Any valid JSON object is a valid record. Accept everything, preserve everything, process what you can.
2. **The archive is the source of truth.** arkiv archives exist in two interconvertible forms -- a directory (README.md + schema.yaml + *.jsonl) and a database (single SQLite file). Both represent the same data. In normal use they stay in sync via import/export. If they diverge, the directory form is authoritative.
3. **Standards over conventions.** MIME types (not custom type enums), URIs (not custom path formats), ISO 8601 (not custom date formats), SQL (not a custom query language).
4. **Document-oriented, not relational.** Each record is a self-contained resource. Denormalize at export time from relational sources.
5. **No required fields.** The format imposes no schema. Metadata is freeform JSON. Applications decide what fields they need.

---

# Part 1: The Format

This section fully specifies the arkiv format. It is sufficient to produce and consume arkiv archives without the reference implementation or any specific programming language.

## 1.1 Record Format

Each line in a JSONL file is one record. A record is a JSON object with these conventional top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `mimetype` | string | Standard MIME type (`text/plain`, `audio/wav`, `image/jpeg`, etc.) |
| `uri` | string | URI reference (`file://`, `http://`, `s3://`, `data:`, etc.) |
| `content` | string | Inline text content |
| `timestamp` | string | ISO 8601 datetime |
| `metadata` | object | Freeform JSON -- everything domain-specific |

**All fields are optional.** A record with only `metadata` is valid. A record with only `content` is valid. An empty object `{}` is valid.

These five fields are the **known fields**. Any other top-level key is an **unknown field** -- implementations SHOULD merge unknown fields into `metadata` on import, preserving the original data while normalizing the structure.

### Content encoding

The `content` field holds inline text. It is always a UTF-8 string. arkiv does not specify a convention for binary content encoding; use `uri` to reference binary resources instead.

### Invariant: one record = one resource = one mimetype

If both `content` and `uri` are present, they refer to the same resource -- `content` is the resource inlined, `uri` is where it lives. Derived representations (e.g., a transcript of an audio file) belong in `metadata`, not as a second record or second mimetype.

### Error handling

Lines that are not valid JSON SHOULD be silently skipped. JSON values that are not objects (arrays, strings, numbers) SHOULD be silently skipped. Implementations MUST NOT fail on malformed input -- best-effort processing is a design principle.

### Examples

**Conversation message:**
```jsonl
{"mimetype": "text/plain", "uri": "https://chatgpt.com/c/abc123", "content": "I think the key insight is that category theory gives you a language for talking about structure.", "timestamp": "2023-05-14T10:30:00Z", "metadata": {"conversation_id": "abc123", "role": "user", "source": "chatgpt"}}
```

**Audio with transcript in metadata:**
```jsonl
{"mimetype": "audio/wav", "uri": "file://media/podcast-001.wav", "timestamp": "2024-01-15", "metadata": {"transcript": "Welcome to today's discussion...", "duration": 45.2}}
```

**Bare metadata (a fact):**
```jsonl
{"metadata": {"relationship": "married to Sarah", "since": "2005"}}
```

**Minimal text:**
```jsonl
{"content": "Trust the future."}
```

---

## 1.2 Archive Structure

An arkiv archive is a directory:

```
archive/
├── README.md           # Archive identity (YAML frontmatter + markdown body)
├── schema.yaml         # Data dictionary (auto-generated, hand-curatable)
├── conversations.jsonl # Collection: one JSONL file per logical group
├── bookmarks.jsonl     # Collection
├── media/              # Referenced files (audio, images, video)
│   ├── podcast-001.wav
│   └── photo.jpg
└── archive.db          # Optional: SQLite derived view (regenerable)
```

With `--nested` export, each collection gets its own subdirectory:

```
archive/
├── README.md           # Top-level archive identity
├── schema.yaml         # Full data dictionary (convenience copy; per-collection files are authoritative on reimport)
├── conversations/      # Per-collection subdirectory
│   ├── README.md
│   ├── schema.yaml
│   └── conversations.jsonl
└── bookmarks/
    ├── README.md
    ├── schema.yaml
    └── bookmarks.jsonl
```

In both layouts, the top-level README and schema.yaml cover the full archive. Nested collection READMEs contain per-collection metadata and a detailed schema table.

**The source of truth is the archive directory** -- specifically the JSONL files, README.md, and schema.yaml. The SQLite database is derived and can always be regenerated from these files.

Each `.jsonl` file is a **collection**. The collection name is the filename stem (e.g., `conversations.jsonl` → collection `conversations`).

---

## 1.3 README.md (Archive Identity)

Every arkiv archive SHOULD have a `README.md` with YAML frontmatter. This makes archives self-describing and human-readable.

```markdown
---
name: Alex's personal data archive
description: Conversations, bookmarks, and writings
datetime: 2026-02-16
generator: arkiv v0.1.1
arkiv_format: "0.2"
contents:
  - path: conversations.jsonl
    description: ChatGPT and Claude conversations 2022-2025
  - path: bookmarks.jsonl
    description: Browser bookmarks and annotations
---

# Alex's Personal Data Archive

This archive contains personal data exported from various tools...
```

Note: the `generator` field tracks the package version of the tool that created the archive, while `arkiv_format` tracks the format specification version. These may differ if the package is updated but the format version remains stable.

### Frontmatter fields (by convention)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable name of the archive |
| `description` | string | Brief description |
| `datetime` | string | ISO 8601 date of the most recent export (or the time preserved in stored frontmatter) |
| `generator` | string | Tool and version that created this archive |
| `arkiv_format` | string | Format version (e.g., `"0.2"`) |
| `contents` | array | List of `{path, description}` entries for each collection |

All keys are optional. Unknown keys MUST be preserved on roundtrip. The `contents` entries control which JSONL files are part of the archive and their ordering.

### Name resolution cascade

If `name` is not in frontmatter, implementations SHOULD fall back to the first `# Heading` in the body, then the directory name.

If `description` is not in frontmatter, implementations SHOULD fall back to the first paragraph of the body.

---

## 1.4 schema.yaml (Data Dictionary)

A `schema.yaml` sits alongside the JSONL files and describes the metadata structure of each collection. It is a **data dictionary** -- a summary of observed metadata keys, not a validation schema. It cannot enforce types or reject records.

```yaml
# Auto-generated by arkiv. Edit freely.
conversations:
  record_count: 12847
  metadata_keys:
    role:
      description: "Speaker identity"
      type: string
      count: 12847
      values: [user, assistant]
    conversation_id:
      type: string
      count: 12847
      example: "abc-123"
    source:
      description: "Which AI assistant"
      type: string
      count: 12847
      values: [chatgpt, claude]
```

### Schema entry fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | JSON type (see [type vocabulary](#type-vocabulary)) |
| `count` | integer | How many records have this metadata key |
| `values` | array | Enumerated values (for low-cardinality keys, threshold ≤ 20) |
| `example` | any | One example value (for high-cardinality keys, when `values` is absent) |
| `description` | string | Human-curated description |

The `values` and `example` fields are mutually exclusive in auto-generated schemas: low-cardinality keys get `values`, high-cardinality keys get `example`. Both may coexist in hand-edited schema.yaml.

### Type vocabulary

The `type` field uses standard JSON type names:

| Type | JSON values |
|------|-------------|
| `string` | `"hello"` |
| `number` | `42`, `3.14` |
| `boolean` | `true`, `false` |
| `array` | `[1, 2, 3]` |
| `object` | `{"key": "value"}` |
| `null` | `null` |

If a metadata key has mixed types across records, the type of the first occurrence is used.

### Merge-on-import semantics

When an implementation imports a README.md with a sibling `schema.yaml`, the two sources are merged:

| Field | Source | Behavior |
|-------|--------|----------|
| `type` | Data | Always recomputed from JSONL records |
| `count` | Data | Always recomputed from JSONL records |
| `description` | schema.yaml | Preserved across reimports |
| `values` | schema.yaml if present, else data | Curated values override auto-computed |
| `example` | Data | Recomputed from JSONL records |

Keys present in schema.yaml but not in the data are preserved with `count: 0`. This allows schema.yaml to document keys that may appear in future data.

---

## 1.5 Unknown Fields and Extensibility

arkiv is designed for forwards compatibility:

- **Records:** Unknown top-level keys are merged into `metadata`. No data is lost.
- **README frontmatter:** Unknown keys are preserved on roundtrip. Implementations MUST NOT strip unrecognized frontmatter.
- **schema.yaml:** Unknown fields within entries are ignored but preserved if possible.

### Format versioning

The `arkiv_format` field in README frontmatter identifies which version of this specification the archive conforms to. Implementations SHOULD include it on export. Implementations SHOULD accept archives without it (treating them as format version 0.1).

If the known fields set (`mimetype`, `uri`, `content`, `timestamp`, `metadata`) changes in a future version, the format version will increment.

---

# Part 2: Schema Discovery Algorithm

This section specifies the algorithm for auto-generating schema entries from JSONL data. Implementations that produce schema.yaml SHOULD follow this algorithm for interoperability.

## 2.1 Scanning

For each record in the JSONL file:
1. Extract the `metadata` object (skip records without metadata)
2. For each key-value pair in metadata:
   - Increment the count for this key
   - Record the JSON type of the value (using the [type vocabulary](#type-vocabulary))
   - Track unique values for enumeration (see below)

## 2.2 Value enumeration

For each metadata key, track its unique values:
- **Scalar values** (string, number, boolean): add to the set of unique values
- **Non-scalar values** (array, object, null): stop tracking values for this key; use `example` instead
- **Mixed types**: if a key has both scalar and non-scalar values across records, stop tracking

If the number of unique values exceeds **20** (the enumeration threshold), stop tracking and use `example` instead.

When values are tracked: if all values are strings, sort them lexicographically. Otherwise, list them in arbitrary order.

When values are not tracked: record the first observed value as `example`.

## 2.3 Result

For each metadata key, produce a `SchemaEntry`:
- `type`: the JSON type of the first observed value
- `count`: number of records containing this key
- `values`: sorted array of unique values (if cardinality ≤ 20 and all scalar), else absent
- `example`: first observed value (if `values` is absent), else absent

---

# Part 3: Reference Implementation

This section describes the arkiv Python reference implementation. It is informative, not normative -- other implementations may use different storage, query mechanisms, or interfaces.

## 3.1 SQLite Schema

The reference implementation imports archives into SQLite with three tables:

```sql
CREATE TABLE records (
    id INTEGER PRIMARY KEY,
    collection TEXT,        -- JSONL filename stem
    mimetype TEXT,
    uri TEXT,
    content TEXT,
    timestamp TEXT,
    metadata JSON           -- original metadata as JSON string
);

CREATE TABLE _schema (
    collection TEXT,
    key_path TEXT,           -- metadata key name
    type TEXT,               -- JSON type name
    count INTEGER,
    sample_values TEXT,      -- JSON array (values or [example])
    description TEXT         -- from schema.yaml
);

CREATE TABLE _metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX idx_records_collection ON records(collection);
CREATE INDEX idx_records_mimetype ON records(mimetype);
CREATE INDEX idx_records_timestamp ON records(timestamp);
```

The `_metadata` table stores README data as key-value pairs:
- `readme_frontmatter`: YAML-serialized frontmatter dict
- `readme_body`: markdown body text

The `_schema` table stores the merged schema (auto-discovered + curated). The `sample_values` column holds either the enumerated `values` array or a single-element array containing `example`.

### Import semantics

- `import_jsonl(path, collection)`: Deletes existing records for the collection (**replace semantics**), then inserts all records from the JSONL file. Pre-computes schema, preserving existing descriptions.
- `import_readme(path)`: Parses README frontmatter, imports each JSONL from `contents`, merges curated schema from sibling schema.yaml, stores README metadata. Handles nested archives: if a contents entry is a directory, the method recurses into its subdirectory, imports that subdirectory's README without storing its metadata in the top-level `_metadata` table.
- Unknown top-level fields in records are merged into the `metadata` JSON column.

### Export semantics

- Writes one JSONL file per collection
- Writes README.md from stored `_metadata`
- Writes schema.yaml from `_schema` table
- Roundtrip is lossless: import → export produces equivalent files
- Exported READMEs contain auto-generated schema summary tables wrapped in `<!-- arkiv:schema:begin -->` / `<!-- arkiv:schema:end -->` sentinel comments. On re-export, the region between sentinels is replaced; prose outside sentinels is preserved
- Optional parameters:
  - `nested`: If true, creates a subdirectory per collection, each with its own README.md and schema.yaml
  - `since` / `until`: Filter records by timestamp to temporal slices; uses a two-pass approach where JSONL is written first, then schema is recomputed from the filtered output
  - Empty collections (after filtering) are skipped and not written to output

### Query safety

The `query()` method enforces read-only access:
1. Prefix check: rejects queries not starting with `SELECT` or `WITH`
2. SQLite authorizer: allows only `SQLITE_SELECT`, `SQLITE_READ`, and `SQLITE_FUNCTION` operations at the engine level

Both layers are applied. The authorizer prevents bypass via SQL comments, semicolons, or CTEs containing write operations.

## 3.2 MCP Server

The reference implementation includes an MCP server (requires `pip install arkiv[mcp]`) that exposes tools over **stdio** transport. By default the server is read-only and exposes three tools: `get_manifest`, `get_schema`, and `sql_query`. When started with `--writable`, it additionally exposes `write_record` for append-only inserts.

#### `get_manifest()`

Returns the archive overview: name, description (from README), collection list with record counts, descriptions, and metadata schemas.

**Parameters:** None

**Returns:** JSON object with `name`, `description` (if present), and `collections` array. Each entry in the `collections` array is an object with:
- `file` (string): collection filename or path (e.g., "conversations.jsonl" or "conversations/")
- `record_count` (integer): number of records in the collection
- `description` (string, optional): human-readable description from README frontmatter
- `schema` (object, optional): object with `metadata_keys` mapping

#### `get_schema(collection?)`

Returns the data dictionary for one or all collections.

**Parameters:** `collection` (optional string)
**Returns:** JSON object with `record_count` and `metadata_keys` mapping.

#### `sql_query(query)`

Runs a read-only SQL query. Use `metadata->>'key'` or `json_extract(metadata, '$.key')` to query metadata fields.

**Parameters:** `query` (string, SELECT only)
**Returns:** JSON array of row objects.

#### `write_record(collection, content, mimetype?, timestamp?, metadata?)`

**Only available when the server was started with `--writable`.** Appends a single record to a collection. Append semantics: does not delete or modify existing records.

**Parameters:**
- `collection` (string, required): target collection name
- `content` (string, required): record content (text or JSON string)
- `mimetype` (string, optional, default `"text/plain"`): MIME type of the content
- `timestamp` (string, optional): ISO 8601 timestamp; defaults to current UTC
- `metadata` (string, optional): JSON string of metadata key-value pairs

**Returns:** JSON object with the inserted record's `id`, `collection`, and `timestamp`.

**Notes:**
- The schema (`_schema` table) is NOT recomputed per write. It reflects the state at last import/export. Use `arkiv import` to refresh the schema after bulk writes.
- Collection names are validated (no path separators, no leading dot, no OS-reserved names).
- Use `--writable` sparingly: the read-only default is the recommended deployment mode.

### Usage pattern

```
LLM: get_manifest()
  → Learns: 3 collections, their descriptions, metadata keys

LLM: get_schema("conversations")
  → Learns: metadata has role (user/assistant), conversation_id, source (chatgpt/claude)

LLM: sql_query("SELECT content FROM records WHERE collection='conversations' AND metadata->>'role'='user' LIMIT 5")
  → Gets: actual conversation content
```

## 3.3 CLI

```bash
pip install arkiv

# Import
arkiv import conversations.jsonl --db archive.db     # single JSONL file
arkiv import README.md --db archive.db               # via README (imports contents, merges schema)
arkiv import ./archive/ --db archive.db              # directory (auto-detects README.md)

# Export
arkiv export archive.db --output ./exported/         # JSONL + README.md + schema.yaml
arkiv export archive.db --output ./out/ --nested     # per-collection subdirectories
arkiv export archive.db --output 2024/ --since 2024-01-01 --until 2024-12-31  # temporal slice

# Query and inspect
arkiv query archive.db "SELECT ..."                  # SQL query
arkiv schema conversations.jsonl                     # print auto-discovered schema
arkiv info archive.db                                # collection counts and overview

# Validation and repair
arkiv detect conversations.jsonl                     # check arkiv format compliance
arkiv detect conversations.jsonl --strict            # exit 1 on any warnings
arkiv fix conversations.jsonl                        # fix known field misspellings (e.g., url → uri)

# MCP server
arkiv mcp archive.db                                 # start MCP server (read-only, stdio transport)
arkiv mcp --writable archive.db                      # enable write_record tool (append-only)
```

---

# Part 4: Ecosystem

arkiv does not stand alone. It is one layer in a broader model of durable personal data, alongside [longecho](https://github.com/queelius/longecho) and a collection of source toolkits and consumer applications. This section specifies how the pieces fit together. For the full rationale behind the model, see [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md).

## 4.1 Two Axes of Durability

Personal data fragility has two distinct dimensions:

- **Durability across time.** The archive must remain useful decades from now, even if every current tool disappears. This requires self-description, plain formats, local-first access, and graceful degradation. longecho addresses this axis.
- **Durability across complexity.** The archive must be usable *today*: queryable by SQL, navigable by LLMs, describable as a data dictionary. This requires structured metadata, a schema, and a query layer. arkiv addresses this axis.

The two axes are orthogonal. A solution that addresses only time (a box of plain files) is useless for complexity. A solution that addresses only complexity (a cloud-hosted relational database) is useless for time. arkiv and longecho together address both without compromising either.

## 4.2 The Durability Stack

An arkiv archive, viewed as a durability stack, has layers that can be peeled away as tooling disappears:

```
Layer 5: LLM interface      (arkiv MCP server + language model)
Layer 4: SQL query layer    (arkiv SQLite + JSON1 extension)
Layer 3: Data dictionary    (arkiv schema.yaml)
Layer 2: Structured records (arkiv JSONL files)
Layer 1: Self-description   (longecho README.md)
Layer 0: Plain files        (text editor, file browser, human eyes)
```

Each layer is independently functional and regenerable from the layer beneath. Losing the top layer does not compromise the ones below. Layer 0 is the substrate: if it survives, everything else can be rebuilt.

**Regenerability principle.** The directory form and the database form are isomorphic: each can regenerate the other losslessly via `arkiv import` and `arkiv export`. Neither is a cache of the other. However, the directory form is authoritative on divergence because it is human-inspectable, git-diffable, and editable without tooling. Every layer above the directory form MUST be regenerable from it. See [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) for the full rationale.

## 4.3 Ecosystem Roles

The arkiv ecosystem distributes responsibility across four role types:

### Source toolkits (producers)

Source toolkits extract data from application-specific silos and write arkiv-compliant directories. Each toolkit understands the idiosyncrasies of one silo; none of them need to know about longecho directly, as long as they produce valid JSONL, a README.md, and a schema.yaml.

Current producers:

| Toolkit | Source | Output |
|---------|--------|--------|
| `memex` | Conversations (ChatGPT, Claude, etc.) | arkiv directory |
| `mtk` | Email | arkiv directory |
| `btk` | Bookmarks | arkiv directory |
| `ptk` | Photos | arkiv directory |
| `ebk` | Ebooks, reading notes | arkiv directory |
| `repoindex` | Git repositories | arkiv directory |
| `chartfold` | Health data | arkiv directory |

A compliant producer SHOULD emit:

```
toolkit-export/
├── README.md           # Self-describing (YAML frontmatter with generator field)
├── schema.yaml         # Data dictionary (curatable)
├── collection.jsonl    # Records in arkiv format
└── collection.db       # Optional SQLite view (regenerable, convenience only)
```

### arkiv (interchange format and query layer)

arkiv defines the record format, the archive directory layout, and the schema discovery algorithm. The reference implementation provides import/export, a SQL query layer, and an MCP server. arkiv does not own the data; it provides structural access to it.

### Consumers

Consumers read arkiv archives and do something specific with them:

| Consumer | Role |
|----------|------|
| `longshade` | Package an arkiv archive as a conversable persona |
| Analytics / visualization tools | Query the SQLite database directly |
| Any LLM with MCP support | Query via the arkiv MCP server |

A consumer SHOULD depend on the arkiv format, not on the arkiv Python library. The format is the stable contract.

### longecho (compliance and navigation)

longecho treats the archive directory as its unit of work. It does not parse records or understand the schema. Its responsibilities:

1. **Validation.** `longecho check` verifies that a directory is self-describing (has a README) and composed of durable formats. An arkiv archive with a README passes this check automatically.
2. **Discovery.** `longecho query` walks a directory tree and finds all compliant sources. This lets a user navigate a whole collection of archives without centralized indexing.
3. **Static site generation.** `longecho build` generates a single-file HTML app (`site/index.html`) that presents the archive's structure and content for browser-based reading. This is a secondary degradation layer: if the arkiv Python library is unavailable but a browser is, the generated site still works.

longecho does not require arkiv, and arkiv does not require longecho. Their composition is structural: both read and write the same directory form.

## 4.4 Relationship to longecho

An arkiv archive is longecho-compliant by construction:

- The exported `README.md` satisfies longecho's self-description requirement.
- `schema.yaml`, the `*.jsonl` files, and the optional SQLite database are all in longecho's durable formats list (`.yaml`, `.jsonl`, `.db`).
- The rendered schema tables in the README body are plain markdown, readable without any tooling.
- Nested export (`--nested`) produces a fractal structure that longecho's recursive discovery handles natively.

The relationship is composition without coupling:

- arkiv does not depend on the longecho library or CLI.
- longecho does not depend on the arkiv library or CLI.
- Each project would continue to function if the other disappeared.
- Their output interoperates because both treat the archive directory as the canonical form.

## 4.5 Privacy and Encryption

arkiv archives contain personal data. Standard encryption over a compressed archive is the recommended approach:

```bash
tar czf archive.tar.gz README.md schema.yaml *.jsonl media/
gpg --symmetric --cipher-algo AES256 archive.tar.gz    # or: age -p archive.tar.gz > archive.tar.gz.age
```

This preserves the full degradation chain: decrypt, decompress, plaintext JSONL. The encryption step does not compromise any layer of the durability stack; it is a wrapper over the substrate (Layer 0).

Alternative approaches:

- **pagevault** wraps an arkiv archive in a password-protected static HTML viewer for browsable sharing. Less durable than GPG (requires a browser and JavaScript) but more convenient for sharing with people who will not run command-line tools.
- Filesystem-level encryption (LUKS, FileVault, BitLocker) covers the archive transparently without changing its structure.

The choice depends on who you are protecting the archive from and how it will be accessed.

---

## Design Decisions

### Why JSONL as the durable layer?

- Human-readable in a text editor
- `cat`, `grep`, `wc -l` just work
- Append-only: independent sources produce JSONL, you `cat` them together
- Git-diffable, streaming-friendly (one record per line)

### Why SQLite as derived layer?

- Most deployed database engine in history
- Single file, no server
- Library of Congress recommends it as an archival format
- JSON1 extension provides native JSON querying

### Why all fields optional?

- Different sources produce different shapes of data
- Processing is best-effort: use what's available, ignore what's missing
- The metadata field absorbs all domain-specific structure

### Why a data dictionary, not a validation schema?

The schema.yaml is a data dictionary -- it describes what has been observed, augmented with human-authored descriptions. It does not validate, enforce types, or reject records. This is deliberate:

- Personal data is messy; rigid schemas reject valid data
- The two-tier merge (auto + curated) keeps the dictionary fresh without losing human curation
- LLMs need to know what fields exist and what they mean, not enforce constraints
- JSON Schema-level complexity would be overkill for the use case

### Why README as identity?

A README.md with YAML frontmatter is simultaneously human-readable documentation, machine-parseable metadata, Git-friendly, and universally understood. Compared to a dedicated manifest.json or package.json, it degrades gracefully -- drop an arkiv directory on any file browser and the README explains what you're looking at.

---

## Future Considerations

- **FTS5 full-text search** -- Pre-built during import for faster text search
- **Vector embeddings** -- Optional embedding column for semantic search
- **Watch mode** -- Monitor JSONL files for changes, auto-update SQLite
