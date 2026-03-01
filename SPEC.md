# arkiv: Universal Record Format

**Version:** 0.1 (Draft Specification)

---

## Purpose

arkiv is a universal personal data format. It provides:

1. **A record format** -- one JSON object per record, all fields optional, JSONL canonical storage
2. **An archive format** -- README.md + schema.yaml describe collections of JSONL files
3. **A SQLite query layer** -- import JSONL to SQLite for efficient querying
4. **An MCP server** -- 3 tools that let any LLM query the data

arkiv is not specific to any application. It is a general-purpose format for personal data sovereignty, archival, and interchange. Applications like persona generation (longshade), analytics, or knowledge management build on top of it.

---

## Design Principles

1. **Permissive input, best-effort processing.** Any valid JSON object is a valid record. Accept everything, preserve everything, process what you can.
2. **JSONL is canonical.** JSONL files are the durable, portable, human-readable source of truth. SQLite is a derived view for efficient querying.
3. **Standards over conventions.** MIME types (not custom type enums), URIs (not custom path formats), ISO 8601 (not custom date formats).
4. **Document-oriented, not relational.** Each record is a self-contained resource with context. Denormalize at export time from relational sources.
5. **No required fields.** The format imposes no schema. Metadata is freeform JSON. Applications decide what fields they need.

---

## Universal Record Format

Each line in a JSONL file is one record. A record is a JSON object with these conventional fields:

| Field | Type | Description |
|-------|------|-------------|
| `mimetype` | string | Standard MIME type (`text/plain`, `audio/wav`, `image/jpeg`, etc.) |
| `uri` | string | URI reference (`file://`, `http://`, `s3://`, `data:`, etc.) |
| `content` | string | Inline content (text for text types, base64 for binary) |
| `timestamp` | string | ISO 8601 datetime |
| `metadata` | object | Freeform JSON -- everything else |

**All fields are optional.** A record with only `metadata` is valid. A record with only `content` is valid. An empty object `{}` is valid (but useless).

### Invariant: One record = one resource = one mimetype

The `mimetype` field describes the resource. If both `content` and `uri` are present, they refer to the same resource -- `content` is the resource inlined, `uri` is where it lives. Derived representations (e.g., a transcript of an audio file) belong in `metadata`, not as a second mimetype.

### Examples

**Text (conversation message):**
```jsonl
{"mimetype": "text/plain", "uri": "https://chatgpt.com/c/abc123", "content": "I think the key insight is that category theory gives you a language for talking about structure without getting lost in details.", "timestamp": "2023-05-14T10:30:00Z", "metadata": {"conversation_id": "abc123", "role": "user", "source": "chatgpt"}}
```

**Text (blog post):**
```jsonl
{"mimetype": "text/markdown", "uri": "https://myblog.com/on-durability", "content": "# Why I Care About Durability\n\nWhen I think about what matters...", "timestamp": "2019-03-22", "metadata": {"title": "On Durability", "tags": ["philosophy", "archiving"]}}
```

**Audio (with transcript in metadata):**
```jsonl
{"mimetype": "audio/wav", "uri": "file://media/podcast-001.wav", "timestamp": "2024-01-15", "metadata": {"transcript": "Welcome to today's discussion about formal methods...", "duration": 45.2, "context": "podcast interview"}}
```

**Image:**
```jsonl
{"mimetype": "image/jpeg", "uri": "file://media/conference-talk.jpg", "timestamp": "2024-01-15", "metadata": {"caption": "Giving my talk on category theory at MIT", "location": "MIT", "people": ["self"]}}
```

**Video (remote URL):**
```jsonl
{"mimetype": "video/mp4", "uri": "https://youtube.com/watch?v=abc123", "timestamp": "2023-06-10", "metadata": {"title": "My conference talk on formal methods", "transcript": "Today I want to talk about..."}}
```

**Structured data (bookmark):**
```jsonl
{"mimetype": "application/json", "uri": "https://arxiv.org/abs/2301.00001", "timestamp": "2024-01-15", "metadata": {"annotation": "Great paper on type-theoretic approaches to databases", "tags": ["math", "databases"]}}
```

**Bare metadata (a fact about the person):**
```jsonl
{"metadata": {"relationship": "married to Sarah", "since": "2005"}}
```

**Minimal text:**
```jsonl
{"content": "Trust the future."}
```

---

## README.md (Archive Self-Description)

Every arkiv archive has a `README.md` with YAML frontmatter. This makes archives ECHO-compliant (self-describing) and human-readable.

```yaml
---
name: Alex's personal data archive
description: ChatGPT and Claude conversations, bookmarks, writings, and voice memos
datetime: 2026-02-16
generator: arkiv v0.1.0
contents:
  - path: conversations.jsonl
    description: ChatGPT and Claude conversations 2022-2025
  - path: writings.jsonl
    description: Blog posts and essays 2015-2025
  - path: voice.jsonl
    description: Podcast recordings and voice memos
---

# Alex's Personal Data Archive

This archive contains personal data from various AI assistants and tools...
```

### Frontmatter Fields (by convention)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable name of the archive |
| `description` | string | Brief description |
| `datetime` | string | ISO 8601 date of creation |
| `generator` | string | Tool that created this archive |
| `contents` | array | List of collection entries (path + optional description) |

All keys are optional. Unknown keys are preserved on roundtrip.

---

## schema.yaml (Metadata Schema)

A `schema.yaml` sits alongside the JSONL files and describes the metadata structure. It is auto-generated by `arkiv export` but can be hand-edited to add descriptions and curate values.

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
    source:
      description: "Which AI assistant"
      type: string
      count: 12847
      values: [chatgpt, claude]
writings:
  record_count: 134
  metadata_keys:
    title:
      type: string
      count: 134
    tags:
      type: array
      count: 120
```

### Merge-on-Import

When `arkiv import` processes a README.md with a sibling `schema.yaml`:

| Field | Behavior |
|-------|----------|
| `type` | Always recomputed from data (live) |
| `count` | Always recomputed from data (live) |
| `description` | Preserved from schema.yaml (stable) |
| `values` | From schema.yaml if curated, else auto-computed (stable) |

Keys in schema.yaml but not in data are preserved with `count=0`.

---

## Schema Discovery

Schema discovery scans a JSONL file's records and produces a summary of all metadata keys, their types, frequency, and example values.

```json
{
  "metadata_keys": {
    "role": {
      "type": "string",
      "count": 12847,
      "values": ["user", "assistant"]
    },
    "conversation_id": {
      "type": "string",
      "count": 12847,
      "example": "abc-123"
    },
    "topic": {
      "type": "string",
      "count": 8432,
      "example": "category theory"
    }
  }
}
```

### Schema Entry Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | JSON type: string, number, boolean, array, object |
| `count` | integer | How many records have this key |
| `values` | array | Enumerated values (if cardinality is low, e.g. < 20) |
| `example` | any | One example value (if cardinality is high) |
| `description` | string | Human-curated description (from schema.yaml) |

Schema is pre-computed during JSONL-to-SQLite import and stored in the `_schema` table. It is also written into `schema.yaml` on export.

---

## SQLite Query Layer

JSONL files can be imported into SQLite for efficient querying. The SQLite file is a derived view -- it can always be regenerated from the canonical JSONL.

### Schema

```sql
CREATE TABLE records (
    id INTEGER PRIMARY KEY,
    collection TEXT,        -- which JSONL file this came from
    mimetype TEXT,
    uri TEXT,
    content TEXT,
    timestamp TEXT,
    metadata JSON
);

CREATE TABLE _schema (
    collection TEXT,
    key_path TEXT,          -- metadata key name
    type TEXT,              -- string, number, boolean, array, object
    count INTEGER,
    sample_values TEXT,     -- JSON array of example or enumerated values
    description TEXT        -- human-curated description (from schema.yaml)
);

CREATE TABLE _metadata (
    key TEXT PRIMARY KEY,   -- readme_frontmatter, readme_body
    value TEXT
);

CREATE INDEX idx_records_collection ON records(collection);
CREATE INDEX idx_records_mimetype ON records(mimetype);
CREATE INDEX idx_records_timestamp ON records(timestamp);
```

### Querying Metadata

SQLite's JSON1 extension provides operators for querying JSON fields:

```sql
-- Find all user messages about math
SELECT content, timestamp
FROM records
WHERE collection = 'conversations'
  AND metadata->>'role' = 'user'
  AND metadata->>'topic' LIKE '%math%'
ORDER BY timestamp DESC
LIMIT 10;

-- Count records by source
SELECT metadata->>'source' AS source, COUNT(*) AS n
FROM records
WHERE collection = 'conversations'
GROUP BY source;

-- Find all audio with transcripts
SELECT uri, metadata->>'transcript' AS transcript, metadata->>'duration' AS duration
FROM records
WHERE mimetype LIKE 'audio/%'
  AND metadata->>'transcript' IS NOT NULL;

-- Full-text search across all content
SELECT content, mimetype, timestamp
FROM records
WHERE content LIKE '%category theory%';
```

### Import/Export Roundtrip

The import and export are lossless:

- **Import:** Each JSONL record becomes one row in `records`. The `collection` column records which file it came from. Schema is pre-computed into `_schema`. README metadata is stored in `_metadata`.
- **Export:** Each row becomes one JSONL record. Rows are grouped by `collection` into separate files. Schema is written to `schema.yaml`. README is written from `_metadata`.

---

## MCP Server

arkiv provides a generic MCP server with 3 tools that lets any LLM query the data.

### Tools

#### `get_manifest()`

Returns the archive overview with collection descriptions and pre-computed schemas. This is the LLM's first call -- it learns what data is available and what metadata keys can be queried.

**Parameters:** None

**Returns:** Archive overview derived from README.md metadata, record counts, and schemas.

#### `get_schema(collection?)`

Returns the pre-computed metadata schema for one or all collections. This tells the LLM what metadata keys exist, their types, and example values -- so it can write informed SQL queries.

**Parameters:**
- `collection` (optional, string): Filter to a specific collection. If omitted, returns schema for all collections.

**Returns:** Schema object with metadata keys, types, counts, and example values.

#### `sql_query(query)`

Runs a read-only SQL query against the SQLite database.

**Parameters:**
- `query` (string): SQL SELECT statement

**Returns:** Query results as JSON array of objects.

### Usage Pattern

```
LLM: get_manifest()
  → Learns: 3 collections (conversations, writings, voice), their descriptions, metadata keys

LLM: get_schema("conversations")
  → Learns: metadata has role (user/assistant), conversation_id, topic, source (chatgpt/claude)

LLM: sql_query("SELECT content FROM records WHERE collection='conversations' AND metadata->>'role'='user' AND content LIKE '%durability%' LIMIT 5")
  → Gets: actual conversation content about durability
```

---

## CLI

```bash
# Import a single JSONL file to SQLite
arkiv import conversations.jsonl --db archive.db

# Import via README.md (reads contents list, merges schema.yaml)
arkiv import README.md --db archive.db

# Import a directory (auto-detects README.md)
arkiv import ./archive/ --db archive.db

# Export SQLite back to JSONL files + README.md + schema.yaml
arkiv export archive.db --output ./exported/

# Discover/print schema of a JSONL file
arkiv schema conversations.jsonl

# Run a SQL query against a database
arkiv query archive.db "SELECT content FROM records WHERE metadata->>'role' = 'user' LIMIT 5"

# Validate a JSONL file (optionally against sibling schema.yaml)
arkiv detect conversations.jsonl

# Start MCP server
arkiv mcp archive.db

# Show database info (collections, record counts, etc.)
arkiv info archive.db
```

---

## Directory Structure

An arkiv archive on disk:

```
archive/
├── README.md               # ECHO self-description (YAML frontmatter + markdown)
├── schema.yaml             # Structured metadata schema (auto-generated, curatable)
├── conversations.jsonl     # One collection
├── writings.jsonl          # Another collection
├── bookmarks.jsonl         # Another collection
├── voice.jsonl             # Another collection
├── media/                  # Referenced files (audio, images, video)
│   ├── podcast-001.wav
│   ├── conference.jpg
│   └── ...
└── archive.db              # SQLite (derived, regenerable from JSONL)
```

The JSONL files, README.md, and schema.yaml are the source of truth. The SQLite file is derived and can be regenerated at any time via `arkiv import ./archive/ --db archive.db`.

---

## Design Decisions

### Why JSONL as canonical?

- Human-readable in a text editor
- `cat`, `grep`, `wc -l` just work
- Append-only: independent sources produce JSONL files, you `cat` them together
- Git-diffable
- Streaming-friendly (one record per line)
- No binary format to decode

### Why SQLite as query layer?

- Most deployed database engine in history
- Single file, no server
- Library of Congress recommends it as an archival format
- JSON1 extension provides native JSON querying
- Full-text search via FTS5
- Standard SQL interface

### Why all fields optional?

- Different sources produce different shapes of data
- Longshade shouldn't reject valid personal data because it doesn't fit a schema
- Processing is best-effort: use what's available, ignore what's missing
- The metadata field absorbs all domain-specific structure

### Why MIME types instead of custom types?

- Well-maintained standard covering every content type
- Already understood by every tool and system
- New content types get MIME types automatically
- More durable than any custom enum we'd define

### Why `uri`?

- `file://` for local files
- `http://`/`https://` for web resources
- `s3://` for cloud storage
- Any URI scheme works, current or future
- Provides provenance: where did this data originally live?

### Why document-oriented, not relational?

Personal data is naturally document-shaped. A conversation message, a photograph, a bookmark, a voice recording -- these are self-contained artifacts with context. Forcing them into normalized tables loses the natural structure. If importing from a relational database, denormalize at export time.

---

## Relationship to ECHO

ECHO is a philosophy and compliance standard for durable personal archives. Its core requirements: self-describing (README), durable formats, graceful degradation, local-first.

arkiv is independent of ECHO but naturally ECHO-compliant:

- **README.md** satisfies ECHO's self-description requirement
- **JSONL** is a durable format (plain text, human-readable, no special tools needed)
- **SQLite** is a durable format (Library of Congress recommended archival format)
- **Two degradation layers** built in: SQLite for rich queries, JSONL for `cat`/`grep`/text editors

arkiv does not claim to be ECHO's recommended format. ECHO is format-agnostic by design. But an arkiv archive with a README is automatically ECHO-compliant.

### Toolkit Output Convention

Source toolkits (memex, btk, ebk, ptk, mtk, repoindex, chartfold, etc.) can export as arkiv archives with ECHO compliance:

```
memex-export/
├── README.md              # ECHO compliant (self-describing, YAML frontmatter)
├── schema.yaml            # Structured metadata schema (curatable)
├── conversations.jsonl    # arkiv universal format (human-readable, durable)
└── conversations.db       # arkiv SQLite (queryable, durable)
```

This gives each export two degradation layers and full self-description, with no extra effort from the toolkit.

### Privacy and Encryption

arkiv archives contain personal data that may require access control. **pagevault** provides encrypted, password-protected viewing of static content with an embedded self-contained viewer.

For the raw data, standard encryption over a compressed archive is the most ECHO-compliant approach:

```bash
# Compress
tar czf archive.tar.gz README.md schema.yaml *.jsonl media/

# Encrypt with GPG (universally available, battle-tested)
gpg --symmetric --cipher-algo AES256 archive.tar.gz

# Or age (modern, simpler)
age -p archive.tar.gz > archive.tar.gz.age
```

This preserves the full degradation chain: decrypt → decompress → plaintext JSONL and SQLite. The encryption tool is separate from the data, widely available, and open-source.

For a *browsable* layer with authentication (e.g., sharing with family via a browser), **pagevault** provides encrypted viewing with an embedded self-contained viewer. Tradeoff: pagevault requires HTML + CSS + JavaScript, which is less ECHO-compliant than plaintext. But it's useful when you want access control without requiring recipients to use GPG.

The pragmatic choice: standard encryption (GPG/age) for the data archive, pagevault for the browsable interface when needed.

---

## Relationship to Other Projects

### Input Sources (Toolkit Ecosystem)

Source toolkits export data in arkiv's universal record format:

- **memex** -- Conversations (ChatGPT, Claude, etc.) → JSONL + SQLite
- **mtk** -- Email → JSONL + SQLite
- **btk** -- Bookmarks → JSONL + SQLite
- **ptk** -- Photos → JSONL + SQLite
- **ebk** -- Ebooks, reading notes → JSONL + SQLite
- **repoindex** -- Git repositories and code → JSONL + SQLite
- **chartfold** -- Health data → JSONL + SQLite
- **mf/Hugo** -- Blog posts, writings (mf is a Hugo tool; Markdown content is naturally compatible)

### Applications

- **longshade** -- Packages arkiv data as a conversable persona (system prompt + voice samples + data)
- **Any analytics/visualization tool** -- Query the SQLite directly
- **Any LLM** -- Via MCP server

### Privacy

- **pagevault** -- Encrypted viewing with embedded self-contained viewer. Wraps arkiv archives for password-protected access.

### Compliance

- **longecho** -- ECHO compliance validator. arkiv archives are naturally ECHO-compliant.

---

## Tech Stack

- Python 3.8+
- `sqlite3` (stdlib)
- `json` (stdlib)
- MCP Python SDK (for MCP server)
- No heavy dependencies

---

## Future Considerations

- **FTS5 full-text search index** -- Could be pre-built during import for faster text search
- **Embedding column** -- Optional vector embeddings in the SQLite for semantic search (if needed)
- **Watch mode** -- Monitor JSONL files for changes and auto-update SQLite
- **Streaming import** -- Handle very large JSONL files without loading into memory
