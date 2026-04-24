# arkiv

Universal personal data format. JSONL in, SQL out, MCP to LLMs.

## The Format

Every record is a JSON object. All fields optional.

```jsonl
{"mimetype": "text/plain", "content": "I think the key insight is...", "uri": "https://chatgpt.com/c/abc", "timestamp": "2023-05-14T10:30:00Z", "metadata": {"role": "user", "conversation_id": "abc"}}
{"mimetype": "audio/wav", "uri": "file://media/podcast.wav", "timestamp": "2024-01-15", "metadata": {"transcript": "Welcome to...", "duration": 45.2}}
{"mimetype": "image/jpeg", "uri": "file://media/photo.jpg", "metadata": {"caption": "My talk at MIT"}}
```

## The Stack

```
JSONL directory (human-readable, portable, durable)
       ⇅ arkiv convert
SQLite database (queryable, efficient, standard SQL)
       ↓ arkiv mcp
MCP server (tools → any LLM)
```

The two forms (directory and database) are isomorphic peers. `arkiv convert`
goes either direction, auto-detected from input type.

## Quick Start

```bash
pip install arkiv

# Point at a directory and query. arkiv.db is auto-created on demand.
arkiv query ./my-archive/ "SELECT content FROM records WHERE metadata->>'role' = 'user' LIMIT 5"

# Serve to any LLM via MCP
arkiv mcp ./my-archive/

# Explicit conversion (either direction)
arkiv convert conversations.jsonl archive.db              # JSONL → database
arkiv convert archive.db ./exported/                      # database → directory
arkiv convert archive.db 2024/ --since 2024-01-01         # temporal slice
arkiv convert archive.db archive.zip                      # pack for transport
```

## MCP Tools

Read-only by default. Start with `arkiv mcp --writable db` to enable the write tool.

| Tool | Description | Mode |
|------|-------------|------|
| `get_manifest()` | What collections exist, their descriptions and schemas | read-only |
| `get_schema(collection?)` | What metadata keys can be queried | read-only |
| `sql_query(query)` | Run read-only SQL | read-only |
| `write_record(...)` | Append a single record to a collection | writable |

## Why

- Your data lives in silos (ChatGPT, email, bookmarks, photos, voice memos)
- Source toolkits (memex, mtk, btk, ptk, ebk) export it as JSONL
- arkiv gives you one format, one database, one query interface
- Any LLM can query it via MCP
- JSONL is human-readable and durable. SQLite is the most deployed database in history.

## Spec and philosophy

- [SPEC.md](SPEC.md): full technical specification
- [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md): why arkiv exists and how it composes with [longecho](https://github.com/queelius/longecho)
